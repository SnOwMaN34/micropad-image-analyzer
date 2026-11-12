"""Single-window calibration tab for the existing reviewed-ROI GUI.

All user-facing text is English.  There are no calibration pop-up windows:
Tkinter's existing application has exactly two top-level notebook tabs.
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import math
import sys

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from micropad.calibration_core import CalibrationProject, analyze, propose_exclusions
from micropad.calibration_xlsx import create_calibration_workbook


class CalibrationTab(ttk.Frame):
    def __init__(self, parent, roi_app):
        super().__init__(parent, padding=12)
        self.roi_app = roi_app
        self.project = CalibrationProject()
        self.name = tk.StringVar(value=self.project.name)
        self.unit = tk.StringVar(value=self.project.concentration_unit)
        self.role = tk.StringVar(value='Standard')
        self.sample = tk.StringVar()
        self.concentration = tk.StringVar()
        self.blank_group = tk.StringVar(value='B1')
        self.preview_mode = tk.StringVar(value='All measurements')
        self.status = tk.StringVar(value='Import a reviewed ROI measurement, then assign blanks and standards.')
        self.stats = tk.StringVar(value='No calibration calculated yet.')
        self.proposed: list[dict] = []
        self.optimization_computed = False
        self.enabled_proposals: set[str] = set()
        self._build()

    def _build(self):
        self.pack(fill='both', expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header=ttk.Frame(self)
        header.grid(row=0,column=0,sticky='ew',pady=(0,9))
        ttk.Label(header,text='Calibration',font=('Segoe UI',16,'bold')).pack(side='left',padx=(0,15))
        ttk.Label(header,text='Project').pack(side='left')
        ttk.Entry(header,textvariable=self.name,width=26).pack(side='left',padx=(6,14))
        ttk.Label(header,text='Concentration unit').pack(side='left')
        ttk.Entry(header,textvariable=self.unit,width=10).pack(side='left',padx=(6,18))
        ttk.Button(header,text='New',command=self.new_project).pack(side='right',padx=3)
        ttk.Button(header,text='Open project',command=self.load_project).pack(side='right',padx=3)
        ttk.Button(header,text='Save project',command=self.save_project).pack(side='right',padx=3)

        bar=ttk.Frame(self)
        bar.grid(row=1,column=0,sticky='ew',pady=(0,9))
        ttk.Button(bar,text='+ Add latest reviewed image',command=self.add_latest).pack(side='left')
        ttk.Button(bar,text='+ Import reviewed CSV',command=self.import_csv).pack(side='left',padx=5)
        ttk.Button(bar,text='Remove selected image',command=self.remove_selected_run).pack(side='left',padx=5)
        ttk.Separator(bar,orient='vertical').pack(side='left',fill='y',padx=12)
        ttk.Button(bar,text='Calculate',command=self.calculate).pack(side='left')
        ttk.Button(bar,text='Find outlier proposals',command=self.find_outliers).pack(side='left',padx=6)
        ttk.Button(bar,text='Export Excel — 2 sheets',command=self.export_excel).pack(side='right')

        panes=ttk.PanedWindow(self,orient='horizontal')
        panes.grid(row=2,column=0,sticky='nsew')
        left=ttk.Frame(panes,padding=(0,0,10,0));right=ttk.Frame(panes,padding=(10,0,0,0))
        panes.add(left,weight=7);panes.add(right,weight=5)
        left.columnconfigure(0,weight=1);left.rowconfigure(2,weight=1)
        right.columnconfigure(0,weight=1);right.rowconfigure(1,weight=1)

        runframe=ttk.LabelFrame(left,text='Imported µPAD images — verify source identity',padding=6)
        runframe.grid(row=0,column=0,sticky='ew',pady=(0,8))
        runframe.columnconfigure(0,weight=1)
        self.runs=ttk.Treeview(runframe,columns=('run','source','count'),show='headings',height=3,selectmode='browse')
        for k,label,width in [('run','Pad',50),('source','Original image (parent folder + filename)',360),('count','ROIs',50)]:
            self.runs.heading(k,text=label);self.runs.column(k,width=width,stretch=(k=='source'))
        self.runs.grid(row=0,column=0,sticky='ew')
        run_scroll=ttk.Scrollbar(runframe,orient='vertical',command=self.runs.yview)
        run_scroll.grid(row=0,column=1,sticky='ns')
        self.runs.configure(yscrollcommand=run_scroll.set)

        assign=ttk.LabelFrame(left,text='Assign selected ROI(s) — Ctrl/Shift for multiple',padding=8)
        assign.grid(row=1,column=0,sticky='ew',pady=(0,9))
        controls=ttk.Frame(assign); controls.pack(fill='x')
        for label,variable,width,choices in [
            ('Role',self.role,12,['Blank','Standard','Ignore']),
            ('Sample',self.sample,12,None),
            ('Concentration',self.concentration,13,None),
            ('Blank group',self.blank_group,12,None)]:
            field=ttk.Frame(controls);field.pack(side='left',padx=(0,12))
            ttk.Label(field,text=label).pack(anchor='w')
            if choices:
                ctl=ttk.Combobox(field,textvariable=variable,values=choices,state='readonly',width=width)
            else:
                ctl=ttk.Entry(field,textvariable=variable,width=width)
            ctl.pack()
        ttk.Button(controls,text='Apply to selected',command=self.apply_assignment).pack(side='left',padx=6,pady=(19,0))
        ttk.Label(assign,text='Blank: set group ID (e.g. B1). Standard: enter concentration and matching blank ID. '
                               'No values are assigned automatically.',foreground='#566477').pack(anchor='w',pady=(7,0))

        zonesframe=ttk.LabelFrame(left,text='Reviewed ROI measurements and assignments',padding=6)
        zonesframe.grid(row=2,column=0,sticky='nsew')
        zonesframe.rowconfigure(0,weight=1);zonesframe.columnconfigure(0,weight=1)
        self.zones=ttk.Treeview(zonesframe,columns=('pad','roi','intensity','role','sample','conc','blank','qc'),
                                show='headings',selectmode='extended',height=17)
        widths={'pad':130,'roi':85,'intensity':90,'role':85,'sample':80,'conc':90,'blank':78,'qc':140}
        for key,label in [('pad','Image / pad'),('roi','ROI'),('intensity','Intensity'),('role','Role'),
                          ('sample','Sample'),('conc','Concentration'),('blank','Blank ID'),('qc','QC flags')]:
            self.zones.heading(key,text=label);self.zones.column(key,width=widths[key],stretch=(key in ('pad','qc')))
        self.zones.grid(row=0,column=0,sticky='nsew')
        vbar=ttk.Scrollbar(zonesframe,command=self.zones.yview,orient='vertical')
        vbar.grid(row=0,column=1,sticky='ns')
        hbar=ttk.Scrollbar(zonesframe,command=self.zones.xview,orient='horizontal')
        hbar.grid(row=1,column=0,sticky='ew')
        self.zones.configure(xscrollcommand=hbar.set,yscrollcommand=vbar.set)
        self.zones.tag_configure('unassigned',background='#fff3d6')
        self.zones.tag_configure('blank',background='#e8f0fa')
        self.zones.tag_configure('ignored',foreground='#8b94a0')
        self.zones.bind('<<TreeviewSelect>>',self._populate_assignment)

        plot_header=ttk.Frame(right);plot_header.grid(row=0,column=0,sticky='ew')
        ttk.Label(plot_header,text='Calibration preview',font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Combobox(plot_header,textvariable=self.preview_mode,values=['All measurements','Outlier-screened'],
                     width=21,state='readonly').pack(side='right')
        self.preview_mode.trace_add('write',lambda *_:self._update_preview())
        plot_box=ttk.LabelFrame(right,text='Concentration-level mean pseudoabsorbance',padding=7)
        plot_box.grid(row=1,column=0,sticky='nsew',pady=(7,8))
        plot_box.rowconfigure(0,weight=1);plot_box.columnconfigure(0,weight=1)
        self.figure=Figure(figsize=(5.2,4.1),dpi=100)
        self.axes=self.figure.add_subplot(111)
        self.axes.set_xlabel('Concentration')
        self.axes.set_ylabel('Mean pseudoabsorbance')
        self.axes.grid(alpha=.25)
        self.canvas_plot=FigureCanvasTkAgg(self.figure,master=plot_box)
        self.canvas_plot.get_tk_widget().grid(row=0,column=0,sticky='nsew')
        ttk.Label(right,textvariable=self.stats,wraplength=520,justify='left').grid(row=2,column=0,sticky='ew',pady=(2,9))

        proposed=ttk.LabelFrame(right,text='Outlier proposals — review before export',padding=7)
        proposed.grid(row=3,column=0,sticky='ew')
        proposed.columnconfigure(0,weight=1)
        self.proposals=ttk.Treeview(proposed,columns=('enabled','source','roi','conc','score','delta'),
                                    show='headings',height=5,selectmode='browse')
        for k,t,w in [('enabled','Use?',55),('source','Image',120),('roi','ROI',76),
                      ('conc','Conc.',65),('score','MAD score',85),('delta','Δ R²',85)]:
            self.proposals.heading(k,text=t);self.proposals.column(k,width=w,stretch=(k=='source'))
        self.proposals.grid(row=0,column=0,sticky='ew')
        ttk.Button(proposed,text='Toggle selected proposal',command=self.toggle_proposal).grid(row=1,column=0,sticky='w',pady=(5,0))
        ttk.Label(proposed,text='R² improvement alone is not a valid reason to exclude data. '
                                 'Check the original scan and QC first.',wraplength=490,
                  foreground='#905b10').grid(row=2,column=0,sticky='w',pady=(5,0))
        ttk.Label(self,textvariable=self.status,wraplength=1200,foreground='#43556d').grid(
            row=3,column=0,sticky='ew',pady=(9,0))
        self._update_rows()

    def _sync(self):
        self.project.name=self.name.get().strip()
        self.project.concentration_unit=self.unit.get().strip()

    def _show_error(self,headline,error):
        self.status.set(f'{headline}: {error}')
        messagebox.showerror(headline,str(error))

    @staticmethod
    def _label(zone):
        parts=zone.source_image_path.replace('\\','/').split('/')
        return '/'.join(parts[-2:]) if len(parts)>1 else zone.image_id

    def _update_rows(self,selected=None):
        selected=set(selected or [])
        self.runs.delete(*self.runs.get_children())
        grouped={}
        for z in self.project.zones:grouped.setdefault(z.run_id,[]).append(z)
        for i,(run_id,zones) in enumerate(grouped.items(),1):
            self.runs.insert('', 'end', iid=run_id,values=(f'Pad {i}',self._label(zones[0]),len(zones)))
        self.zones.delete(*self.zones.get_children())
        index={run:i+1 for i,run in enumerate(grouped)}
        for z in self.project.zones:
            tag= 'unassigned' if z.role=='Unassigned' else 'blank' if z.role=='Blank' else 'ignored' if z.role=='Ignore' else ''
            self.zones.insert('','end',iid=z.key,tags=(tag,),values=(
                f'{index[z.run_id]}: {self._label(z)}',z.roi_id,f'{z.intensity:.5f}',z.role,z.sample,
                '' if z.concentration is None else f'{z.concentration:g}',z.blank_group,z.qc_flags))
        for key in selected:
            if self.zones.exists(key):self.zones.selection_add(key)
        counts=Counter(z.role for z in self.project.zones)
        self.status.set(f'Imported {len(grouped)} image(s), {len(self.project.zones)} ROI(s). '
                        f'Assigned: {counts["Blank"]} blank, {counts["Standard"]} standard; '
                        f'unassigned: {counts["Unassigned"]}.')

    def _populate_assignment(self,_event=None):
        selected=self.zones.selection()
        if len(selected)!=1:return
        z=next((x for x in self.project.zones if x.key==selected[0]),None)
        if z:
            self.role.set(z.role if z.role in ('Blank','Standard','Ignore') else 'Standard')
            self.sample.set(z.sample)
            self.concentration.set('' if z.concentration is None else f'{z.concentration:g}')
            if z.blank_group:self.blank_group.set(z.blank_group)

    def add_latest(self):
        folder=self.roi_app.last_output
        if folder is None:
            messagebox.showinfo('No reviewed run','Save reviewed ROI measurements on the ROI Review tab first.')
            return
        self._import(folder)

    def import_csv(self):
        f=filedialog.askopenfilename(title='Import reviewed selected-channel CSV',
             filetypes=[('Reviewed ROI measurements','selected_channel_measurements.csv'),('CSV','*.csv')],
             initialdir=str(self.roi_app.last_output or Path.cwd()))
        if f:self._import(Path(f))

    def _import(self,path):
        try:
            n=self.project.add_run(path)
            self.proposed=[];self.enabled_proposals=set();self.optimization_computed=False
            self._update_rows()
            self.stats.set('Import complete. Assign all ROIs before calculating.')
            self.status.set(f'Added {n} reviewed measurements from {path}. Confirm the original image name.')
        except Exception as exc:self._show_error('Unable to import reviewed image',exc)

    def remove_selected_run(self):
        runs=self.runs.selection()
        if not runs:return
        run_id=runs[0]
        n=self.project.remove_run(run_id)
        self.proposed=[];self.enabled_proposals=set();self.optimization_computed=False;self._update_rows()
        self.status.set(f'Removed {n} ROIs. Original review outputs remain untouched.')

    def apply_assignment(self):
        keys=set(self.zones.selection())
        if not keys:
            messagebox.showinfo('Select ROI(s)','Select one or more rows in the ROI table first.')
            return
        role=self.role.get()
        group=self.blank_group.get().strip()
        if role not in ('Blank','Standard','Ignore'):
            self._show_error('Invalid role','Choose Blank, Standard, or Ignore.');return
        if role!='Ignore' and not group:
            self._show_error('Missing blank ID','Enter a non-empty blank group (e.g. B1).');return
        concentration=None
        if role=='Standard':
            try:concentration=float(self.concentration.get().replace(',','.'))
            except ValueError:
                self._show_error('Invalid concentration','Enter a valid numeric concentration.');return
            if not math.isfinite(concentration) or concentration<0:
                self._show_error('Invalid concentration','Concentration must be finite and nonnegative.');return
        for z in self.project.zones:
            if z.key in keys:
                z.role=role
                z.sample=self.sample.get().strip() if role!='Ignore' else ''
                z.concentration=concentration
                z.blank_group=group if role!='Ignore' else ''
        self.proposed=[];self.enabled_proposals=set();self.optimization_computed=False
        self._update_rows(keys)
        self.stats.set('Assignments changed. Click Calculate to refresh the calibration.')

    def _run_analysis(self,notify=True):
        self._sync()
        full=analyze(self.project)
        if self.enabled_proposals:
            selected=analyze(self.project,self.enabled_proposals)
        else:
            selected=full
        return full,selected

    def calculate(self):
        try:
            full,selected=self._run_analysis()
            self._update_preview(full,selected)
        except Exception as exc:self._show_error('Calibration cannot be calculated',exc)

    def _update_preview(self,full=None,selected=None):
        if full is None:
            try:full,selected=self._run_analysis(notify=False)
            except Exception:return
        result=selected if self.preview_mode.get()=='Outlier-screened' else full
        fit=result['fit'];groups=result['groups']
        xs=[p['concentration'] for p in groups];ys=[p['mean_absorbance'] for p in groups]
        self.axes.clear()
        color='#d97732' if self.preview_mode.get()=='Outlier-screened' else '#7855a9'
        self.axes.scatter(xs,ys,color=color,label='Concentration mean',s=35,zorder=3)
        low,high=min(xs),max(xs)
        self.axes.plot([low,high],[fit['slope']*low+fit['intercept'],fit['slope']*high+fit['intercept']],
                       color='#334155',label='Linear fit',lw=1.6)
        self.axes.set_title(self.preview_mode.get()+' calibration',fontsize=11)
        self.axes.set_xlabel('Concentration ('+self.project.concentration_unit+')')
        self.axes.set_ylabel('Mean pseudoabsorbance (A)')
        self.axes.grid(True,alpha=.25)
        self.axes.legend(loc='best',fontsize=8)
        eq=f'A = {fit["slope"]:.6g} × c {fit["intercept"]:+.6g}\nR² = {fit["r2"]:.6f}'
        self.axes.text(.03,.96,eq,transform=self.axes.transAxes,verticalalignment='top',fontsize=9,
                       bbox={'boxstyle':'round','facecolor':'white','alpha':.85,'edgecolor':'#d3dce7'})
        self.figure.tight_layout(pad=1.1);self.canvas_plot.draw_idle()
        self.stats.set(f'Calibration levels: {len(xs)}  |  ROI measurements used: {fit["n_replicates"]}  |  '
                       f'Slope: {fit["slope"]:.7g}  |  Intercept: {fit["intercept"]:.7g}  |  R²: {fit["r2"]:.6f}')
        means=[p['mean_absorbance'] for p in sorted(full['groups'],key=lambda x:x['concentration'])]
        if any(b<a for a,b in zip(means,means[1:])):
            self.status.set('WARNING: Mean pseudoabsorbance decreases between some increasing concentrations. '
                            'Check the source images, blank assignments and concentration labels before trusting the fit.')

    def find_outliers(self):
        try:
            self._sync();opt=propose_exclusions(self.project)
            self.proposed=opt['proposals'];self.enabled_proposals={r['key'] for r in self.proposed}
            self.optimization_computed=True
            self._update_proposals()
            self.preview_mode.set('Outlier-screened')
            self._update_preview(opt['baseline'],opt['proposed'])
            self.status.set(f'{len(self.proposed)} statistically screened exclusion proposal(s). '
                            'Review each proposal; toggle off any you reject. Exclusions require independent QC justification.')
        except Exception as exc:self._show_error('Optimization failed',exc)

    def _update_proposals(self):
        self.proposals.delete(*self.proposals.get_children())
        for p in self.proposed:
            k=p['key'];score=p.get('modified_mad_score')
            self.proposals.insert('','end',iid=k,values=('Yes' if k in self.enabled_proposals else 'No',
                       p['image_id'],p['roi_id'],f'{p["concentration"]:g}',
                       f'{score:.2f}' if score is not None else '∞',f'{p["delta_r2"]:.5g}'))

    def toggle_proposal(self):
        selected=self.proposals.selection()
        if not selected:return
        k=selected[0]
        if k in self.enabled_proposals:self.enabled_proposals.remove(k)
        else:self.enabled_proposals.add(k)
        self._update_proposals()
        self.proposals.selection_set(k)
        self._update_preview()

    def save_project(self):
        self._sync()
        f=filedialog.asksaveasfilename(title='Save calibration project',defaultextension='.json',
                                       filetypes=[('Calibration project','*.json')],initialfile='calibration_project.json')
        if f:
            try:self.project.save(f);self.status.set(f'Saved project: {f}')
            except Exception as exc:self._show_error('Unable to save project',exc)

    def load_project(self):
        f=filedialog.askopenfilename(title='Open calibration project',filetypes=[('Calibration project','*.json')])
        if not f:return
        try:
            self.project=CalibrationProject.load(f)
            self.name.set(self.project.name);self.unit.set(self.project.concentration_unit)
            self.proposed=[];self.enabled_proposals=set();self.optimization_computed=False;self._update_rows()
            self.stats.set('Loaded project. Review image assignments, then Calculate.')
        except Exception as exc:self._show_error('Unable to load project',exc)

    def new_project(self):
        if self.project.zones and not messagebox.askyesno('Start new calibration','Clear current calibration assignments? Save first if needed.'):
            return
        self.project=CalibrationProject()
        self.name.set(self.project.name);self.unit.set(self.project.concentration_unit)
        self.proposed=[];self.enabled_proposals=set();self.optimization_computed=False;self._update_rows()
        self.stats.set('Start by importing a reviewed image.')

    def export_excel(self):
        try:
            self._sync()
            full,_=self._run_analysis()
        except Exception as exc:
            self._show_error('Cannot export — check assignments',exc);return
        # Always prepare the outlier-screened alternative before exporting.
        # Never silently treat proposals as scientifically approved exclusions.
        if not self.optimization_computed:
            self.find_outliers()
            if not self.optimization_computed:
                return
            if self.proposed:
                messagebox.showinfo('Review the outlier proposals',
                    f'{len(self.proposed)} candidate(s) passed the statistical screen. '
                    'Review the proposals in this tab, toggle any you reject, '
                    'and click Export Excel again. The optimized sheet is exploratory.')
                return
        path=filedialog.asksaveasfilename(title='Export formula-driven calibration',defaultextension='.xlsx',
                initialfile='micropad_calibration.xlsx',filetypes=[('Excel workbook','*.xlsx')])
        if not path:return
        try:
            # No UI-only approval is silently inferred. Optimization is explicitly
            # a proposal; users can toggle each screened candidate off before export.
            x=create_calibration_workbook(self.project,path,excluded_keys=self.enabled_proposals)
            self.status.set(f'Exported exactly two Excel sheets: All_Data and Optimized. '
                            f'Proposed exclusions: {len(x["excluded_keys"])}. Original ROI data unchanged.')
            messagebox.showinfo('Calibration exported',f'Workbook saved to:\n{path}\n\n'
               'Sheets: All_Data and Optimized\n'
               'Both contain formulas, editable native scatter charts, and original source references.\n'
               'Review proposed exclusions before interpreting the optimized calibration.')
        except Exception as exc:self._show_error('Unable to export Excel',exc)
