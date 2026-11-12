"""Regression checks for two-sheet lab-style workbook and multi-pad calibration."""
from __future__ import annotations
import csv, json, zipfile, re
from pathlib import Path
from xml.etree import ElementTree as ET
import math
import pytest
from micropad.calibration_core import CalibrationProject,Zone,analyze,propose_exclusions
from micropad.calibration_xlsx import create_calibration_workbook

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def project_fixture(*,shared_level=False):
    p=CalibrationProject('Synthetic two-pad nitrite','µM')
    for pad,blank,levels,baseline in [(1,'B1',[1,2,3],220),(2,'B2',[3,5,6] if shared_level else [4,5,6],232)]:
        for i in range(4):
            key=f'P{pad}-B{i}'
            p.zones.append(Zone(key,str(pad),f'IMG_000{pad}',f'ROI_{i+1:03d}',baseline+i*.15,'G',100,'local','hash',
                                role='Blank',sample=blank,blank_group=blank,source_image_path=f'C:/NO2_2/IMG_000{pad}.jpg'))
        for c in levels:
            for i in range(5):
                key=f'P{pad}-C{c}-R{i}'
                val=baseline/(10**(.002+.012*c+.0002*(i-2)))
                if pad==2 and c==5 and i==4:val=baseline/(10**(.002+.012*c+.029))
                p.zones.append(Zone(key,str(pad),f'IMG_000{pad}',f'ROI_{len(p.zones)+1:03d}',val,'G',100,'local','hash',
                                    role='Standard',sample=f'C{c}',concentration=c,blank_group=blank,
                                    source_image_path=f'C:/NO2_2/IMG_000{pad}.jpg'))
    return p


def xmltext(z,path):
    return z.read(path).decode('utf-8')


def test_all_data_baseline_is_reasonably_linear():
    p=project_fixture();r=analyze(p)['fit']
    assert r['r2']>.97
    assert len(r['points'])==6


def test_two_sheets_only_and_two_excel_charts(tmp_path):
    f=tmp_path/'lab.xlsx';p=project_fixture()
    create_calibration_workbook(p,f)
    with zipfile.ZipFile(f) as z:
        doc=ET.fromstring(z.read('xl/workbook.xml'))
        sheets=doc.find('m:sheets',NS)
        assert [x.attrib['name'] for x in sheets]==['All_Data','Optimized']
        assert 'xl/charts/chart1.xml' in z.namelist()
        assert 'xl/charts/chart2.xml' in z.namelist()
        assert '<c:dispRSqr val="1"/>' in xmltext(z,'xl/charts/chart1.xml')
        assert '<c:dispEq val="1"/>' in xmltext(z,'xl/charts/chart2.xml')
        assert 'majorGridlines' in xmltext(z,'xl/charts/chart1.xml')
        assert 'Concentration (' in xmltext(z,'xl/charts/chart1.xml')
        assert 'Mean pseudoabsorbance' in xmltext(z,'xl/charts/chart2.xml')


def test_blank_precedes_its_own_standards_and_second_blank_is_not_at_top(tmp_path):
    f=tmp_path/'lab.xlsx';create_calibration_workbook(project_fixture(),f)
    with zipfile.ZipFile(f) as z:
        s=xmltext(z,'xl/worksheets/sheet1.xml')
        pos_b1=s.index('PAD/BLOCK 1')
        pos_p1=re.search(r'<c r="A[0-9]+"[^>]*><v>1.0</v></c>',s).start()
        pos_b2=s.index('PAD/BLOCK 2')
        pos_p4=re.search(r'<c r="A[0-9]+"[^>]*><v>4.0</v></c>',s).start()
        assert pos_b1<pos_p1<pos_b2<pos_p4
        assert s.count('Blank — B1')==4
        assert s.count('Blank — B2')==4


def test_dynamic_formulas_are_in_cells_not_fixed_values(tmp_path):
    f = tmp_path / 'lab.xlsx'
    create_calibration_workbook(project_fixture(), f)
    with zipfile.ZipFile(f) as z:
        s = xmltext(z, 'xl/worksheets/sheet1.xml')
        root = ET.fromstring(s)
        cells = {c.attrib['r']: c for c in root.findall('.//m:sheetData/m:row/m:c', NS)}

        def formula(cell):
            element = cells[cell].find('m:f', NS)
            assert element is not None, cell
            return element.text

        # Mean absorbance was removed from the detail table. The pooled mean
        # in Q remains necessary for the calibration regression.
        assert 'Mean absorbance' not in s
        assert 'Mean intensity' in s
        assert 'SD absorbance' not in s
        assert 'Status' in s
        assert 'Mean A (pooled)' in s
        # Both blank and standard intensities respond to manual C deletions and E statuses.
        assert 'ISNUMBER(C7:C10)' in formula('D7')
        assert 'E7:E10="Included"' in formula('D7')
        assert 'AVERAGE($B$7:$B$10)' in formula('C7')
        assert '$D$7/B12' in formula('C12')
        assert 'ISNUMBER(C12:C16)' in formula('D12')
        assert 'E12:E16="Included"' in formula('D12')
        assert 'ISNUMBER($C$6:$C$' in formula('P7')
        assert '($A$6:$A$' in formula('P7')
        assert '($E$6:$E$' in formula('P7')
        assert 'AVERAGEIFS(' in formula('Q7')
        assert 'SLOPE(' in formula('T7')
        assert 'RSQ(' in formula('T9')
        opt = xmltext(z, 'xl/worksheets/sheet2.xml')
        assert 'ISNUMBER($C$6:$C$' in opt
        assert 'AVERAGEIFS(' in opt


def test_blank_exclusions_and_standard_deletions_are_connected_by_formulas(tmp_path):
    f = tmp_path / 'lab.xlsx'
    create_calibration_workbook(project_fixture(), f)
    with zipfile.ZipFile(f) as z:
        root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cells = {c.attrib['r']: c for c in root.findall('.//m:sheetData/m:row/m:c', NS)}
        def formula(cell):
            return cells[cell].find('m:f', NS).text
        # A blank C deletion removes that blank's B intensity from the D7 reference.
        # Standard C12 refers to D7, so the calibration responds to the deletion.
        assert 'ISNUMBER(C7:C10)' in formula('D7')
        assert '$D$7/B12' in formula('C12')
        # A standard C deletion is also reflected by the n count, even though
        # its numeric concentration A12 remains populated.
        assert 'ISNUMBER($C$6:$C$' in formula('P7')
        # A blank C must not depend on D7 (would create a circular dependency).
        assert '$D$7' not in formula('C7')
        # Each pad's blank controls only its own standards.
        assert '$D$32' in formula('C37')


def test_larger_chart_and_right_legend_keep_labels_separate(tmp_path):
    f = tmp_path / 'lab.xlsx'
    create_calibration_workbook(project_fixture(), f)
    with zipfile.ZipFile(f) as z:
        for i in (1, 2):
            chart = xmltext(z, f'xl/charts/chart{i}.xml')
            drawing = xmltext(z, f'xl/drawings/drawing{i}.xml')
            assert '<c:legendPos val="r"/>' in chart
            assert '<c:overlay val="0"/>' in chart
            assert '<c:trendlineLbl>' in chart
            assert 'majorGridlines' in chart
            assert 'Concentration (' in chart
            assert 'Mean pseudoabsorbance' in chart
            assert '<xdr:ext cx="10600000" cy="6700000"/>' in drawing
            ET.fromstring(chart)
            ET.fromstring(drawing)


def test_optimizer_removes_screened_outlier_and_does_not_modify_raw_source(tmp_path):
    p=project_fixture();copy=[z.intensity for z in p.zones]
    opt=propose_exclusions(p)
    assert opt['proposed']['fit']['r2']>opt['baseline']['fit']['r2']
    assert opt['proposals']
    f=tmp_path/'lab.xlsx';result=create_calibration_workbook(p,f)
    assert result['excluded_keys']
    with zipfile.ZipFile(f) as z:
        assert 'Excluded' in xmltext(z,'xl/worksheets/sheet2.xml')
        root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cells={c.attrib['r']:c for c in root.findall('.//m:sheetData/m:row/m:c',NS)}
        # Input rows remain Included on the primary full-data sheet.
        for c in cells.values():
            if c.attrib['r'].startswith('E') and c.find('m:is',NS) is not None:
                assert ''.join(c.itertext()) != 'Excluded'
    assert [z.intensity for z in p.zones]==copy


def test_same_concentration_across_pads_pooled_into_one_calibration_level():
    p=project_fixture(shared_level=True)
    result=analyze(p)
    assert len(result['groups'])==5
    group=next(g for g in result['groups'] if g['concentration']==3)
    assert group['n']==10


def test_invalid_blank_reference_fails_before_export(tmp_path):
    p=project_fixture();stand=next(z for z in p.zones if z.role=='Standard')
    stand.blank_group='NO_BLANK'
    with pytest.raises(ValueError,match='blank group'):
        create_calibration_workbook(p,tmp_path/'a.xlsx')


def test_duplicate_import_same_original_source_rejected(tmp_path):
    folder=tmp_path/'one';folder.mkdir()
    with (folder/'selected_channel_measurements.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['image_id','roi_id','mean_intensity','channel','radius'])
        writer.writeheader();writer.writerow({'image_id':'IMG_0001','roi_id':'ROI_001','mean_intensity':220,
                                               'channel':'G','radius':100})
    (folder/'review_selection.csv').write_text('roi_id\nROI_001\n')
    (folder/'review_log.json').write_text(json.dumps({'review_required':True,'image_path':'C:/NO2_1/IMG_0001.jpg'}))
    p=CalibrationProject()
    assert p.add_run(folder)==1
    with pytest.raises(ValueError, match='already been added'):
        p.add_run(folder)


def test_all_data_is_unchanged_if_optimized_candidates_toggled_off(tmp_path):
    p=project_fixture();f=tmp_path/'lab.xlsx'
    r=create_calibration_workbook(p,f,excluded_keys=set())
    assert r['all_fit']['r2']==pytest.approx(r['optimized_fit']['r2'])
    assert not r['excluded_keys']


def test_formula_errors_are_visible_and_unrelated_manual_deletions_remain_possible(tmp_path):
    f = tmp_path / 'error_formula.xlsx'
    create_calibration_workbook(project_fixture(), f)
    with zipfile.ZipFile(f) as z:
        for i in (1, 2):
            root = ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml'))
            cells = {c.attrib['r']: c for c in root.findall('.//m:sheetData/m:row/m:c', NS)}
            formulas = {address: cell.find('m:f', NS).text for address, cell in cells.items()
                        if cell.find('m:f', NS) is not None}
            # No function should silently replace a computation error with an empty string.
            assert not any(',""' in expression for expression in formulas.values())
            assert '"ERROR"' in formulas['D7']  # no eligible blanks -> ERROR
            assert '"ERROR"' in formulas['C12']  # invalid blank -> ERROR
            assert '"ERROR"' in formulas['Q7']  # missing concentration mean -> ERROR
            for address in ('T7', 'T8', 'T9'):
                assert formulas[address].startswith('IFERROR(')
                assert '"ERROR"' in formulas[address]
            assert cells['E7'].find('m:is', NS) is not None  # status moved E
            assert cells['F7'].find('m:is', NS) is not None  # blank group moved F
            assert 'SD absorbance' not in z.read(f'xl/worksheets/sheet{i}.xml').decode('utf-8')
