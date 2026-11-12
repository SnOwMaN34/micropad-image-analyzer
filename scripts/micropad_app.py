"""Two-tab µPAD image analysis app. Original ROI tools remain in the first tab."""
from __future__ import annotations
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk
SCRIPTS=Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS))
sys.path.insert(0,str(SCRIPTS.parent/'src'))
import roi_test_gui
from calibration_tab import CalibrationTab


def main():
    root=tk.Tk()
    root.title('µPAD Image Analyzer — ROI Review | Calibration')
    root.geometry('1440x920')
    root.minsize(1000,670)
    tabs=ttk.Notebook(root)
    review_tab=ttk.Frame(tabs)
    calibration_tab=ttk.Frame(tabs)
    tabs.add(review_tab,text='   ROI Review   ')
    tabs.add(calibration_tab,text='   Calibration   ')
    tabs.pack(fill='both',expand=True)
    reviewer=roi_test_gui.RoiTestApp(root,parent=review_tab)
    workspace=CalibrationTab(calibration_tab,reviewer)
    # RoiTestApp sets a test-runner title for standalone usage; this title is
    # the actual integrated application title and takes precedence.
    root.title('µPAD Image Analyzer — ROI Review | Calibration')
    root.mainloop()


if __name__=='__main__':
    main()
