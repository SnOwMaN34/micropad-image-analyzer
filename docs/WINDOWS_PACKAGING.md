# Windows Packaging — Developer / Distributor Guide

These steps apply to the current **Tkinter** desktop application. No PySide6 migration or installer is required for the first portable release. Build on a **Windows x64 PC** for Windows x64 users.

## Inputs

- A clean, up-to-date local clone of `SnOwMaN34/micropad`.
- Python 3.12 x64 in `.venv`, with dependencies from `requirements-core.txt`.
- This toolkit's two new scripts plus the updated runtime paths in `roi_test_gui.py` and `analyze_image.py`.
- PyInstaller installed into the same virtual environment.

## Install this toolkit into the repository

Copy `scripts/app_paths.py`, `scripts/apply_packaging_changes.py`, `scripts/build_windows.ps1`, and `docs/LAB_USER_GUIDE.md` into their matching locations in the repository. This developer guide is optional in the repository.

From the project-root PowerShell terminal, run:

```powershell
.\.venv\Scripts\python.exe scripts\apply_packaging_changes.py
.\.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
```

The path-patch step is **idempotent**. It carefully modifies only the locations used for results and the initial Browse dialog. It does not touch algorithms or calibration logic.

## Build the portable application

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The build script checks the path patch, runs `pytest`, invokes PyInstaller with `--onedir --windowed`, assembles a clean release folder, and creates a ZIP and checksum. No data from `data/`, `results/` or `.venv/` is copied into the release.

Output:

```text
release/
  MicroPADImageAnalyzer_YYYYMMDD_HHMMSS/
    MicroPADImageAnalyzer.exe
    _internal/
    LAB_USER_GUIDE.md
    BUILD_INFO.txt
    results/
      README.txt
  MicroPADImageAnalyzer_YYYYMMDD_HHMMSS.zip
  MicroPADImageAnalyzer_YYYYMMDD_HHMMSS.zip.sha256.txt
```

Always distribute the **entire ZIP**, not only the EXE.

## Debug build

For a build that displays diagnostic console messages, use:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Console
```

The default GUI build does not show a console window. If it fails to start on the receiving PC, reproduce the failure with the console build and capture the error details.

## Runtime data placement

- Running from source: existing repository `results/` and `data/lab_validated/` paths are preserved.
- Running a PyInstaller build: reviewed runs are written to **`results/` alongside `MicroPADImageAnalyzer.exe`** (not inside the bundled `_internal` folder or `%LOCALAPPDATA%`). The build creates `results/README.txt` so the ZIP always includes this folder. The application folder must be extracted to a user-writable location such as `Documents` and must not be run from inside a ZIP or a protected folder.
- The **Browse...** file picker starts in the user's Documents folder when no lab dataset is bundled.
- The original input image is never overwritten; it is read from the chosen location.
- Calibration `.xlsx` and project `.json` use explicit save dialogs.
- The packaged application intentionally does **not** redirect silently to another directory if the executable folder is read-only. Give the application folder write permission or extract it to a different location before measuring.

## Acceptance test before distribution

1. Confirm the full `pytest` suite passes.
2. Launch the EXE, verify both **ROI Review** and **Calibration** tabs and the app layout/scrolling.
3. Import an *authorized test image*, detect circles, verify manual add/remove/hide/undo and correct column-major numbering.
4. Save a reviewed run. Confirm it appears in the `results/` folder **beside the EXE**, including `review_inputs/` and a fresh per-measurement directory. Verify all CSV/JSON and overlay files; confirm the original image hash did not change.
5. Import two different approved runs into the calibration tab, assign **B1** and **B2**, concentrations and labels, calculate a plausible calibration and verify source/run/ROI mapping.
6. Save and reopen a calibration project. Export Excel and check `All_Data` and `Optimized`, editing included standard and blank rows, regression recalculation and chart readability in Microsoft Excel.
7. Test from a *separate Windows user account* or clean Windows PC without Python installed, and with no access to the development repository.
8. Confirm the bundle contains no local data, internal development notes, credentials or unpublished measurements.
9. Record test date, tester, OS architecture, representative sample IDs and outcomes. Verify license and institutional software-distribution requirements before sharing.

**Release status:** a successful build is only a **release candidate**. This toolkit was prepared without running the resulting Windows executable in this environment; do not claim that the lab-ready EXE has already been tested.
