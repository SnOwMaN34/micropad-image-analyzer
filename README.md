# µPAD Image Analyzer

**µPAD Image Analyzer** is a desktop research application for reviewing and measuring colorimetric reaction zones on microfluidic paper-based analytical devices (µPADs), and preparing blank-referenced calibration curves from one or more scanned images.

The workflow is **human-reviewed**, not fully autonomous. The software proposes circular regions of interest (ROIs); the operator checks their location and radius, corrects them when needed, assigns blank/standard identities and concentrations, and reviews the calibration before using its results.

> **Status:** working research software under validation. A distributable Windows executable and an installer have **not** yet been verified for laboratory release. The current desktop interface uses **Tkinter**, with two tabs: **ROI Review** and **Calibration**.

## What it does

- Finds circular color-reaction candidates without requiring a preset number of rows or columns.
- Supports manual ROI additions, removals, rejected-candidate hiding, undo/reset, and independent control of analytical radius versus candidate-search radius.
- Rotates images by 90° and flips horizontally/vertically without interpolating the measurement pixels; zoom and pan affect only the preview.
- Numbers approved ROIs **by column**, top to bottom, progressing from left to right; the saved ROI identifiers and CSV order match the reviewed overlay.
- Measures mean intensity of the selected **R**, **G**, or **B** channel in the approved ROIs, and saves measurements, overlays, and an audit record.
- Combines reviewed measurements from multiple µPAD images in one calibration project; blank groups, standard identities, and concentrations are assigned **manually**.
- Calculates individual blank-referenced pseudoabsorbance, concentration-level averages, and an unweighted linear fit with free intercept.
- Exports an editable Excel workbook containing exactly **`All_Data`** and **`Optimized`** sheets with formulas and native scatter charts. Statistical outlier suggestions are for review, not automatic scientific approval.

## Run on Windows (from source)

Requirements: Python 3.12 with Tkinter support (included with the standard Windows Python installer), VS Code or a terminal, and the dependencies in `requirements-core.txt`.

From the **repository root**, in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-core.txt
.\.venv\Scripts\python.exe scripts\micropad_app.py
```

If the virtual environment already exists, skip its creation and reinstalling requirements unless needed. The application does **not** require PySide6 to run in its current Tkinter form. `requirements-gui.txt` currently also lists optional packaging/UI-development dependencies; see [Deployment Preparation](docs/DEPLOYMENT.md) before building an executable.

The standalone ROI reviewer and command-line measurement program remain available:

```powershell
.\.venv\Scripts\python.exe scripts\roi_test_gui.py
.\.venv\Scripts\python.exe scripts\analyze_image.py --help
```

## Typical workflow

1. Open **ROI Review** and load or browse to a supported image.
2. Choose the RGB measurement channel, image orientation, and analytical ROI radius.
3. Detect and inspect the proposed ROIs; adjust candidates and manually correct any missed or unwanted zones.
4. Click **Measure & Save CSV**. The original image remains unchanged; reviewed measurements and audit files are saved under `results/`.
5. Switch to **Calibration** and import that reviewed run. Import additional reviewed images if the calibration spans several pads.
6. Assign each ROI a **Blank**, **Standard**, or **Ignore** role. Supply the blank-group IDs, concentrations, units, and standard labels; never rely on the image position to infer these.
7. Calculate and review the calibration. Optionally inspect statistical outlier proposals and disable any that are not scientifically justified.
8. Export the **two-sheet Excel workbook**; examine all formula results, blank references, sample assignments, and the editable charts.

For exact button behavior and Excel editing, see the [User Guide](docs/USER_GUIDE.md).

## Project layout

| Path | Purpose |
|---|---|
| `scripts/micropad_app.py` | Integrated two-tab desktop entry point |
| `scripts/roi_test_gui.py` | ROI review interface; also supports standalone use |
| `scripts/calibration_tab.py` | Calibration assignment and preview interface |
| `scripts/analyze_image.py` | Image measurement command-line entry point |
| `src/micropad/` | Reusable detection, ROI, measurement, orientation, calibration, and Excel-export logic |
| `tests/` | Automated tests using synthetic/controlled data |
| `docs/` | Current user, technical, validation, and deployment documentation |
| `data/` | Local experimental and reference data; see privacy note below |
| `results/` | Local measurement results and audit files; excluded from Git |

## Tests

For Windows, use an isolated temporary directory to avoid known permissions issues with the default pytest temporary path:

```powershell
$tmp = Join-Path $env:TEMP ("micropad_test_" + [guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe -m pytest -q -o "addopts=" --basetemp "$tmp" -p no:cacheprovider
```

Passing software tests does **not** by itself establish analytical validity. Real-image comparisons and laboratory verification are addressed in the [Validation Guide](docs/VALIDATION.md).

## Data protection and provenance

Keep unpublished laboratory images, ImageJ reference measurements, calibration inputs, generated outputs, and identifiable metadata **outside Git** unless sharing has been expressly authorized. The `.gitignore` already excludes the corresponding `data/` locations and `results/`; verify `git status` before each commit. Calibration project JSON files contain source paths and measurement values, so they may also be sensitive.

Source images are decoded for measurement and are **not overwritten**. Each reviewed run records ROI geometry, channel, image orientation, manual interventions, and reference information required to trace the analysis.

## Documentation

- [User Guide](docs/USER_GUIDE.md) — step-by-step ROI review, multiple pads, calibration assignments, and Excel editing.
- [Technical Reference](docs/TECHNICAL_REFERENCE.md) — algorithm, pixel conventions, output contracts, calibration calculations, and optimizer limits.
- [Validation Guide](docs/VALIDATION.md) — reproducible ImageJ comparisons, grouping, exclusions, and interpretation.
- [Deployment Preparation](docs/DEPLOYMENT.md) — architecture, quality checks, packaging prerequisites, and known release limitations.

## Scope and limitations

The image detector was developed on a limited set of scans and can miss weak/neutral spots or produce extra candidates. The final ROI selection must be verified by a human. The current software is not a certified diagnostic device, and high calibration \(R^2\) alone does not establish assay accuracy or justify excluding measurements. Scientific interpretation and suitability for use remain the operator's responsibility.
