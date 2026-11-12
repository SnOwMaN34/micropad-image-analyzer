"""Export two lab-style, formula-driven calibration worksheets as native XLSX.

No dependencies beyond the Python standard library. The workbook contains
native scatter charts and OOXML formulas, not rendered plots. Images, ROI masks,
and historical measurements are not modified. All calculations are recalculated
by Excel on opening and include numeric formula caches for initial previews.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from statistics import mean
from xml.sax.saxutils import escape
import math
import zipfile
from .calibration_core import CalibrationProject, analyze, propose_exclusions

SX = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
XDR = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'


def column(number: int) -> str:
    out = ''
    while number:
        number, rem = divmod(number - 1, 26)
        out = chr(65 + rem) + out
    return out


def xml_cell(address, value=None, *, formula=None, style=0) -> str:
    attributes = f' r="{address}"' + (f' s="{style}"' if style else '')
    if formula is not None:
        cached = (str(float(value)) if isinstance(value, (int, float)) and
                  math.isfinite(float(value)) else '')
        return f'<c{attributes}><f>{escape(formula.lstrip("="))}</f><v>{cached}</v></c>'
    if value is None or value == '':
        return f'<c{attributes}/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return f'<c{attributes}/>'
        return f'<c{attributes}><v>{value}</v></c>'
    return f'<c{attributes} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


class Worksheet:
    def __init__(self, name: str):
        self.name = name
        self.cells: dict[int, dict[int, str]] = defaultdict(dict)
        self.merges: list[str] = []
        self.maxrow = 1

    def put(self, row, col, value=None, *, formula=None, style=0):
        self.cells[row][col] = xml_cell(f'{column(col)}{row}', value, formula=formula, style=style)
        self.maxrow = max(row, self.maxrow)

    def labels(self, row, names, style=1):
        for i, name in enumerate(names, 1):
            self.put(row, i, name, style=style)

    def merge(self, address):
        self.merges.append(address)

    def as_xml(self):
        widths = [19, 17, 19, 20, 14, 15, 31, 13, 34, 19, 32, 3, 3, 3,
                  19, 13, 22, 3, 23, 28, 14, 14, 14, 14]
        cols = '<cols>' + ''.join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                  for i, w in enumerate(widths, 1)) + '</cols>'
        data = ''.join(f'<row r="{index}">' + ''.join(items[c] for c in sorted(items)) + '</row>'
                       for index, items in sorted(self.cells.items()))
        merges = f'<mergeCells count="{len(self.merges)}">' + ''.join(
            f'<mergeCell ref="{addr}"/>' for addr in self.merges) + '</mergeCells>' if self.merges else ''
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<worksheet xmlns="{SX}" xmlns:r="{REL}">'
                '<sheetViews><sheetView workbookViewId="0"><pane ySplit="4" topLeftCell="A5" '
                'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                '<sheetFormatPr defaultRowHeight="18"/>' + cols + '<sheetData>' + data + '</sheetData>'
                + merges + '<drawing r:id="rId1"/></worksheet>')


def chart_xml(sheet_name, xs, ys, *, unit, color):
    """Editable Excel XY scatter chart, with a non-overlapping external legend.

    Text is deliberately smaller, and the chart has a larger drawing canvas.
    The equation/R² label is positioned in the free upper-left of the chart,
    away from the rising fitted line and the right-side legend.
    """
    def title(value, font_size=1050):
        return ('<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p>'
                f'<a:r><a:rPr lang="en-US" sz="{font_size}"/><a:t>{escape(value)}</a:t></a:r>'
                '<a:endParaRPr lang="en-US"/></a:p></c:rich></c:tx>'
                '<c:overlay val="0"/></c:title>')

    def number_cache(values):
        return ('<c:numCache><c:formatCode>General</c:formatCode>'
                f'<c:ptCount val="{len(values)}"/>' + ''.join(
                    f'<c:pt idx="{i}"><c:v>{v:.15g}</c:v></c:pt>' for i, v in enumerate(values))
                + '</c:numCache>')

    quoted = "'" + sheet_name.replace("'", "''") + "'!"
    xref = f'{quoted}$O$7:$O${6+len(xs)}'
    yref = f'{quoted}$Q$7:$Q${6+len(ys)}'
    grid = ('<c:majorGridlines><c:spPr><a:ln w="6350">'
            '<a:solidFill><a:srgbClr val="D8E1E9"/></a:solidFill>'
            '</a:ln></c:spPr></c:majorGridlines>')
    series = (
        '<c:ser><c:idx val="0"/><c:order val="0"/>'
        '<c:tx><c:v>Mean pseudoabsorbance</c:v></c:tx>'
        '<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>'
        '<c:marker><c:symbol val="circle"/><c:size val="7"/>'
        f'<c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f'<a:ln><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        '</a:ln></c:spPr></c:marker>'
        '<c:trendline><c:name>Linear calibration fit</c:name>'
        '<c:spPr><a:ln w="25400"><a:solidFill><a:srgbClr val="263748"/>'
        '</a:solidFill></a:ln></c:spPr>'
        '<c:trendlineType val="linear"/><c:dispRSqr val="1"/><c:dispEq val="1"/>'
        '<c:trendlineLbl><c:layout><c:manualLayout>'
        '<c:xMode val="factor"/><c:yMode val="factor"/>'
        '<c:x val="0.19"/><c:y val="0.12"/>'
        '</c:manualLayout></c:layout></c:trendlineLbl>'
        '</c:trendline>'
        f'<c:xVal><c:numRef><c:f>{escape(xref)}</c:f>{number_cache(xs)}</c:numRef></c:xVal>'
        f'<c:yVal><c:numRef><c:f>{escape(yref)}</c:f>{number_cache(ys)}</c:numRef></c:yVal>'
        '</c:ser>')
    x_axis = ('<c:valAx><c:axId val="101"/><c:scaling><c:orientation val="minMax"/>'
              '</c:scaling><c:axPos val="b"/>' + title(f'Concentration ({unit})') + grid +
              '<c:tickLblPos val="nextTo"/><c:crossAx val="201"/><c:crosses val="autoZero"/></c:valAx>')
    y_axis = ('<c:valAx><c:axId val="201"/><c:scaling><c:orientation val="minMax"/>'
              '</c:scaling><c:axPos val="l"/>' + title('Mean pseudoabsorbance (A)') + grid +
              '<c:tickLblPos val="nextTo"/><c:crossAx val="101"/><c:crosses val="autoZero"/></c:valAx>')
    heading = 'All measurements calibration' if sheet_name == 'All_Data' else 'Outlier-screened calibration'
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart>'
            + title(heading, 1300)
            + '<c:plotArea><c:layout/><c:scatterChart><c:scatterStyle val="marker"/>'
            + series + '<c:axId val="101"/><c:axId val="201"/></c:scatterChart>'
            + x_axis + y_axis + '</c:plotArea>'
            '<c:legend><c:legendPos val="r"/><c:layout/><c:overlay val="0"/></c:legend>'
            '<c:plotVisOnly val="1"/></c:chart></c:chartSpace>')


def drawing_xml():
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}" xmlns:r="{REL}">'
            '<xdr:oneCellAnchor><xdr:from><xdr:col>14</xdr:col><xdr:colOff>0</xdr:colOff>'
            '<xdr:row>16</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
            '<xdr:ext cx="10600000" cy="6700000"/>'
            '<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>'
            '<xdr:cNvPr id="2" name="Editable calibration chart"/><xdr:cNvGraphicFramePr/>'
            '</xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/>'
            '<a:ext cx="10600000" cy="6700000"/></xdr:xfrm>'
            f'<a:graphic><a:graphicData uri="{C}">'
            f'<c:chart xmlns:c="{C}" xmlns:r="{REL}" r:id="rId1"/>'
            '</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>'
            '</xdr:oneCellAnchor></xdr:wsDr>')


def styles_xml():
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{SX}">
<numFmts count="1"><numFmt numFmtId="164" formatCode="0.000000"/></numFmts>
<fonts count="3"><font><sz val="10"/><name val="Aptos"/><color rgb="FF253647"/></font>
<font><b/><sz val="10"/><name val="Aptos"/><color rgb="FFFFFFFF"/></font>
<font><b/><sz val="11"/><name val="Aptos"/><color rgb="FF253647"/></font></fonts>
<fills count="5"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF263748"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE7EDF3"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFDFDF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top/><bottom style="thin"><color rgb="FFCAD4DF"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="0" fillId="4" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>
<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyNumberFormat="1"/>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _safe_image_name(row):
    from pathlib import PurePath
    p = str(row.get('source_image_path', ''))
    parts = p.replace('\\', '/').split('/')
    if len(parts) > 1:
        return '/'.join(parts[-2:])
    return row['image_id']


def _numeric_included_count(start: int, end: int, *, concentration_cell: str | None = None) -> str:
    """Count actual numeric absorbances, not merely populated concentration rows.

    Both a manually cleared absorbance and an Excluded status remove the ROI.
    SUMPRODUCT/ISNUMBER also ignores formulas whose result is empty text.
    """
    col_a = f'$A${start}:$A${end}'
    col_c = f'$C${start}:$C${end}'
    col_e = f'$E${start}:$E${end}'
    terms = [f'--ISNUMBER({col_c})', f'--({col_e}="Included")']
    if concentration_cell is not None:
        terms.append(f'--({col_a}={concentration_cell})')
    return f'SUMPRODUCT({",".join(terms)})'


def _sheet(project, name, result, proposed_ids, base_rows):
    optimized = name == 'Optimized'
    sheet = Worksheet(name)
    sheet.put(1, 1, f'{project.name} — {"OUTLIER-SCREENED" if optimized else "ALL MEASUREMENTS"}', style=2)
    sheet.merge('A1:K1')
    sheet.put(2, 1, f'Concentration unit: {project.concentration_unit} | Selected RGB channel: '
                         f'{next((r["channel"] for r in base_rows if r["role"] != "Ignore"), "?")} | '
                         'Each standard uses its assigned blank group')
    sheet.merge('A2:K2')
    sheet.put(3, 1, ('EXPLORATORY: review proposed exclusions. E=Included/Excluded; clearing C also omits that ROI.'
                     if optimized else
                     'ALL DATA: edit E status or clear C absorbance to omit a measurement; all calculations update.'))
    sheet.merge('A3:K3')
    sheet.labels(4, ['Concentration', 'Intensity', 'Absorbance', 'Mean intensity',
                     'Status', 'Blank group', 'Source image', 'ROI ID',
                     'Original image path', 'Sample', 'Measurement key'], style=1)
    sheet.put(4, 15, 'Concentration', style=1)
    sheet.put(4, 16, 'n included', style=1)
    sheet.put(4, 17, 'Mean A (pooled)', style=1)
    sheet.put(4, 19, 'Metric', style=1)
    sheet.put(4, 20, 'Formula-driven result', style=1)
    sheet.put(5, 15, 'One pooled point per concentration, including replicates from separate pads.')
    sheet.merge('O5:Q5')

    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in base_rows:
        if entry['role'] in ('Blank', 'Standard'):
            grouped[entry['blank_group']].append(entry)
    row = 6
    for index, (blank_id, group) in enumerate(grouped.items(), start=1):
        blanks = [entry for entry in group if entry['role'] == 'Blank']
        stds = [entry for entry in group if entry['role'] == 'Standard']
        if not stds:
            continue
        path_labels = list(dict.fromkeys(_safe_image_name(entry) for entry in group))
        sheet.put(row, 1, f'PAD/BLOCK {index}  •  Blank {blank_id}  •  ' + ', '.join(path_labels), style=3)
        sheet.merge(f'A{row}:K{row}')
        row += 1
        blank_start = row
        blank_end = row + len(blanks) - 1
        blank_mean = mean(entry['intensity'] for entry in blanks)
        for entry in blanks:
            rr = row
            sheet.put(rr, 1, f'Blank — {blank_id}')
            sheet.put(rr, 2, entry['intensity'], style=4)
            # For blank rows, C is a diagnostic relative to the INITIAL full-
            # blank mean, so C never depends on the filtered reference D.
            # This avoids a circular Excel reference, while allowing users to
            # remove any blank by clearing C or changing its E status.
            sheet.put(rr, 3, math.log10(blank_mean / entry['intensity']),
                      formula=f'IFERROR(LOG10(AVERAGE($B${blank_start}:$B${blank_end})/B{rr}),"ERROR")', style=4)
            sheet.put(rr, 5, 'Included')
            sheet.put(rr, 6, blank_id)
            sheet.put(rr, 7, _safe_image_name(entry))
            sheet.put(rr, 8, entry['roi_id'])
            sheet.put(rr, 9, entry['source_image_path'])
            sheet.put(rr, 10, entry['sample'])
            sheet.put(rr, 11, entry['key'])
            row += 1
        count_blanks = _numeric_included_count(blank_start, blank_end)
        # The blank reference changes when a blank's C cell is deleted or
        # when E is set to Excluded; all standard C formulas refer to D here.
        mean_blank_formula = (
            f'IFERROR(SUMPRODUCT(--ISNUMBER(C{blank_start}:C{blank_end}),'
            f'--(E{blank_start}:E{blank_end}="Included"),'
            f'B{blank_start}:B{blank_end})/({count_blanks}),"ERROR")'
        )
        sheet.put(blank_start, 4, blank_mean, formula=mean_blank_formula, style=7)
        row += 1
        concentration_groups = defaultdict(list)
        for entry in stds:
            concentration_groups[float(entry['concentration'])].append(entry)
        for concentration, entries in sorted(concentration_groups.items()):
            start = row
            end = row + len(entries) - 1
            local_included = [entry for entry in entries if entry['key'] not in proposed_ids]
            for entry in entries:
                rr = row
                excluded = optimized and entry['key'] in proposed_ids
                style = 5 if excluded else 4
                sheet.put(rr, 1, concentration, style=style)
                sheet.put(rr, 2, entry['intensity'], style=style)
                sheet.put(rr, 3, entry['absorbance'],
                          formula=f'IFERROR(LOG10($D${blank_start}/B{rr}),"ERROR")', style=style)
                sheet.put(rr, 5, 'Excluded' if excluded else 'Included', style=5 if excluded else 0)
                sheet.put(rr, 6, blank_id)
                sheet.put(rr, 7, _safe_image_name(entry))
                sheet.put(rr, 8, entry['roi_id'])
                sheet.put(rr, 9, entry['source_image_path'])
                sheet.put(rr, 10, entry['sample'])
                sheet.put(rr, 11, entry['key'])
                row += 1
            selected_i = [entry['intensity'] for entry in local_included]
            count = _numeric_included_count(start, end)
            # A mean uses only rows with a numeric C absorbance and E=Included.
            # Removing a C formula or excluding a row updates the aggregate.
            int_avg_form = (f'IFERROR(SUMPRODUCT(--ISNUMBER(C{start}:C{end}),'
                            f'--(E{start}:E{end}="Included"),B{start}:B{end})/'
                            f'({count}),"ERROR")')
            sheet.put(start, 4, mean(selected_i), formula=int_avg_form, style=7)
            row += 1
        row += 1
    end_all = row - 1
    # One point per distinct concentration, even when there are repeats across
    # multiple pads. Display *actual* numeric and Included C values only.
    concentration_groups: dict[float, list[dict]] = defaultdict(list)
    for entry in base_rows:
        if entry['role'] == 'Standard' and entry['key'] not in proposed_ids:
            concentration_groups[float(entry['concentration'])].append(entry)
    xs, ys = [], []
    for idx, (concentration, standards) in enumerate(sorted(concentration_groups.items()), start=7):
        xs.append(concentration)
        y_mean = mean(entry['absorbance'] for entry in standards)
        ys.append(y_mean)
        sheet.put(idx, 15, concentration, style=4)
        count_expr = _numeric_included_count(6, end_all, concentration_cell=f'O{idx}')
        mean_expr = (f'IFERROR(AVERAGEIFS($C$6:$C${end_all},'
                     f'$A$6:$A${end_all},O{idx},$E$6:$E${end_all},"Included"),"ERROR")')
        sheet.put(idx, 16, len(standards), formula=count_expr)
        sheet.put(idx, 17, y_mean, formula=mean_expr, style=7)
    last = 6 + len(xs)
    fit = result['fit']
    sheet.put(7, 19, 'Slope')
    sheet.put(7, 20, fit['slope'], formula=f'IFERROR(SLOPE(Q7:Q{last},O7:O{last}),"ERROR")', style=7)
    sheet.put(8, 19, 'Intercept')
    sheet.put(8, 20, fit['intercept'], formula=f'IFERROR(INTERCEPT(Q7:Q{last},O7:O{last}),"ERROR")', style=7)
    sheet.put(9, 19, 'R²')
    sheet.put(9, 20, fit['r2'], formula=f'IFERROR(RSQ(Q7:Q{last},O7:O{last}),"ERROR")', style=7)
    sheet.put(10, 19, 'Number of levels')
    sheet.put(10, 20, len(xs), formula=f'COUNT(O7:O{last})')
    sheet.put(11, 19, 'Number of standard ROIs')
    sheet.put(11, 20, sum(len(v) for v in concentration_groups.values()),
              formula=f'SUM(P7:P{last})')
    sheet.put(12, 19, 'Blank rule')
    sheet.put(12, 20, 'Blank reference D excludes rows with E=Excluded or manually cleared C.')
    sheet.put(13, 19, 'Equation')
    sheet.put(13, 20, 'Slope/intercept/R² above update when standard C or E changes.')
    sheet.put(14, 19, 'Blank A note')
    sheet.put(14, 20, 'Blank C diagnostic uses initial all-blank mean; filtered blank D feeds standard C.')
    sheet.put(15, 19, 'QC')
    sheet.put(15, 20, ('Review red excluded rows. Clear C or edit E to adjust.' if optimized else
                       'All ROIs initially included. Clear C or edit E to adjust.'))
    return sheet, xs, ys


def create_calibration_workbook(project: CalibrationProject, filename: str|Path, *,
                                excluded_keys: set[str]|None = None) -> dict:
    """Write exactly two sheets. The optimization remains a reviewable proposal."""
    project.validate()
    all_data=analyze(project)
    automatic=propose_exclusions(project)
    exclusions = set(p['key'] for p in automatic['proposals']) if excluded_keys is None else set(excluded_keys)
    if any(k not in {z.key for z in project.zones if z.role=='Standard'} for k in exclusions):
        raise ValueError('Exclusions must refer to current standard ROI IDs')
    optimized_data=analyze(project,excluded=exclusions)
    raw_rows=all_data['rows']
    sheets=[_sheet(project,'All_Data',all_data,set(),raw_rows),
            _sheet(project,'Optimized',optimized_data,exclusions,raw_rows)]
    dst=Path(filename)
    dst.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED) as z:
        contenttypes=(f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<Types xmlns="{CT}">'
           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
           '<Default Extension="xml" ContentType="application/xml"/>'
           '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
           '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
           +''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in (1,2))
           +''.join(f'<Override PartName="/xl/drawings/drawing{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>' for i in (1,2))
           +''.join(f'<Override PartName="/xl/charts/chart{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>' for i in (1,2))
           +'</Types>')
        z.writestr('[Content_Types].xml',contenttypes)
        z.writestr('_rels/.rels',f'<?xml version="1.0"?><Relationships xmlns="{PKG}">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<?xml version="1.0"?>'
                   f'<workbook xmlns="{SX}" xmlns:r="{REL}"><sheets>'
                   '<sheet name="All_Data" sheetId="1" r:id="rId1"/>'
                   '<sheet name="Optimized" sheetId="2" r:id="rId2"/>'
                   '</sheets><calcPr calcId="191029" calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
                   '</workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',f'<?xml version="1.0"?><Relationships xmlns="{PKG}">'
                   +''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in (1,2))
                   +'<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',styles_xml())
        for i,(sh,x,y) in enumerate(sheets,1):
            z.writestr(f'xl/worksheets/sheet{i}.xml',sh.as_xml())
            z.writestr(f'xl/worksheets/_rels/sheet{i}.xml.rels',f'<?xml version="1.0"?>'
                       f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
                       f'Type="{REL}/drawing" Target="../drawings/drawing{i}.xml"/></Relationships>')
            z.writestr(f'xl/drawings/drawing{i}.xml',drawing_xml())
            z.writestr(f'xl/drawings/_rels/drawing{i}.xml.rels',f'<?xml version="1.0"?>'
                       f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
                       f'Type="{REL}/chart" Target="../charts/chart{i}.xml"/></Relationships>')
            z.writestr(f'xl/charts/chart{i}.xml',chart_xml(sh.name,x,y,unit=project.concentration_unit,
                       color='8051AB' if i==1 else 'E08438'))
    return {'filename':str(dst),'sheets':['All_Data','Optimized'],
            'all_fit':all_data['fit'],'optimized_fit':optimized_data['fit'],
            'excluded_keys':sorted(exclusions),'proposals':automatic['proposals']}
