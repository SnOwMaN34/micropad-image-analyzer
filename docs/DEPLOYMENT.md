# Deployment Preparation

This document records the **current release readiness and packaging prerequisites**. It is not a statement that a Windows executable has already been built, tested, signed, or deployed.

## Current state

- **GUI framework:** Tkinter / `ttk` (standard CPython Windows installation), two tabs in the same main window.
- **Desktop entry point:** `scripts/micropad_app.py`.
- **Main application features:** human-reviewed ROI detection/measurement; multi-image blank/standard assignments; Excel calibration export.
- **Data processing:** NumPy, OpenCV, Pillow and other dependencies listed in `requirements-core.txt`; Matplotlib is used for the live calibration preview.
- **Excel export:** the current writer produces an Office Open XML workbook with formula strings and native Excel chart definitions. It does not calculate Excel cells itself.
- **Development tooling:** `pytest` tests exist; `requirements-gui.txt` includes `PySide6` and `pyinstaller` from an earlier packaging plan. **PySide6 is not used by the currently running Tkinter app.** Rationalize packaging dependencies before releasing an installer.

## Packaging decisions that must be made

1. **Framework:** retain Tkinter for the first distributable build, or deliberately migrate to PySide6 in a separate scoped change. Do not accidentally ship both as runtime requirements.
2. **Distribution:** choose a folder-based executable versus one-file packaging; the folder-based option is often easier to inspect and debug for scientific desktop software.
3. **File locations:** ensure installed applications can find bundled `src/micropad` and `scripts` modules, and save user results/projects to a **user-writable location**. Today's source-tree assumptions (`PROJECT_ROOT`, `results/`) must be checked in a frozen application.
4. **Original-data safety:** verify the distributed program never modifies the source image or original ImageJ files, including after rotation, measurement, or saving.
5. **Optional libraries:** audit and remove unused runtime packages before freezing, particularly PySide6 if Tkinter is retained.
6. **Metadata and privacy:** keep CSVs, JSONs, charts and lab images out of the distributable unless they are cleared example fixtures; avoid including personal filesystem paths in shared demo projects.
7. **Licensing:** check redistribution requirements for Python, OpenCV, Pillow, Matplotlib, NumPy, PyInstaller, and any other bundled dependencies.
8. **Version and reproducibility:** record source commit, runtime package versions, installation instructions, checksum of the release archive, and known limitations. Preserve algorithm identifiers and project-data format version independently of the GUI's presentation.

## Functional smoke-test checklist

Before publishing an executable, test on a Windows computer that **does not have the development virtual environment**:

- Start the app from the packaged executable; check both top tabs and resizing/scrolling.
- Import a representative RGB image; confirm orientation controls and preview zoom/pan do not change source intensities.
- Detect and review circles, including custom radius, search-radius tolerance, manual addition/removal, orange candidate hiding, undo/reset and final column-major numbering.
- Save ROI results. Compare source-image hash before and after; open every CSV, JSON and overlay from the output folder.
- Combine at least two reviewed pad images with independent blank groups; check sample assignments and channel/unit validation.
- Calculate calibration and inspect the proposed-standard-exclusion list; confirm no suggestion is silently accepted as a scientifically justified outlier.
- Export Excel, verify exactly `All_Data` and `Optimized`, editable chart elements, correct headings, included-row counts, dynamic blank means, and formula-error behavior.
- In **Hungarian Excel** and (if possible) **Portuguese/English Excel**, verify formulas calculate, updates after manual deletion of a standard/blank signal propagate, and chart labels/legend/trendline remain legible.
- Confirm the application handles missing files, malformed CSV, duplicate source image, missing blank assignment, excessive ROI radius and insufficient concentration levels without overwriting data.
- Test a clean restart and import an existing calibration project JSON.

## Test command during development

```powershell
$tmp = Join-Path $env:TEMP ("micropad_test_" + [guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe -m pytest -q -o "addopts=" --basetemp "$tmp" -p no:cacheprovider
```

Tests use synthetic or controlled fixtures; passing does not establish analytical validity on laboratory data. See [Validation Guide](VALIDATION.md) for that process.

## Release documentation set

At release time, include only the relevant, current documentation:

- [README](../README.md) for installation and first use.
- [User Guide](USER_GUIDE.md) for lab workflow.
- [Technical Reference](TECHNICAL_REFERENCE.md) for algorithm and output reproducibility.
- [Validation Guide](VALIDATION.md) for scientific evidence and limits.
- This deployment/release checklist.

Do **not** include local `.venv`, unapproved laboratory images, historical exports, temporary `results/`, internal project planning files or AI-assistant logs in the distributed application.
