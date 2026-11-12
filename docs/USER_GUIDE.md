# User Guide

This guide describes the **current integrated Tkinter application**, rather than a historical development milestone. All interface labels and exported field names are in English.

## 1. Start the application

Launch from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\micropad_app.py
```

Use the two top tabs, **ROI Review** and **Calibration**, to move between image measurement and calibration setup. The tabs are in the same main window. The standalone ROI tool (`scripts/roi_test_gui.py`) is also available, but it does not provide the integrated calibration workflow.

## 2. ROI Review: load, orient, and inspect an image

1. **Image**: select a discovered local image or click **Browse...** to open a JPEG, PNG, or TIFF in RGB mode. The current automatic detector requires an 8-bit RGB source. Other modes and multi-frame images are rejected instead of being silently converted.
2. **Measurement Channel**: choose **R**, **G**, or **B**. The channel affects measured intensities; circle detection is based on image color segmentation, not on this single channel.
3. **ROI Radius**: choose **Auto-detected** or **Custom (px)**. The displayed radius and actual discrete-pixel area are shown for the suggested and custom ROI; **Active ROI** indicates the applied setting.
4. **Image Orientation**: use **Rotate 90° Left/Right**, **Flip Horizontal/Vertical**, or **Reset Orientation** as needed. Actions apply in the order clicked. They rotate/reflect the in-memory raster without interpolation; the original file is untouched. An orientation change re-runs detection and prompts before clearing manual edits.
5. Click **1. Detect & Preview**, then review all overlaid circles visually.

**Analytical ROI radius** controls the pixels used in the intensity calculation. **Candidate search radius** is an independent hint for recognizing the colored zone or a larger backing-paper ring. Changing one does not imply they should be equal.

### Candidate Review Settings

- **Use analytical ROI radius**: the candidate search follows the measurement ROI radius.
- **Outer/backing-paper radius**: use an independently specified search radius when the physical disc is larger than the reaction zone.
- **Candidate radius tolerance (±%)**: selects acceptable contour sizes around that search radius.
- **Re-evaluate Candidates**: re-runs candidate selection with the current settings. Check the resulting green, orange, and manually created ROIs before proceeding.

The detector does not require a fixed matrix shape or target ROI count. The operator is responsible for confirming that every real reaction zone is included and no unwanted region remains.

## 3. ROI Preview: navigation and mouse actions

The main page and preview pane have independent scrollbars. Zooming or panning the preview **never changes measured ROI coordinates or source pixels**.

| Action | Effect |
|---|---|
| **Fit Image** | Show the entire raster within the preview |
| **100%** | Display one image pixel per display pixel |
| **Zoom + / Zoom −** | Magnify or reduce the preview |
| **Ctrl + mouse wheel** | Zoom around the pointer inside the preview |
| **Mouse wheel** | Scroll the enlarged image vertically; page scrolling applies outside the preview |
| **Shift + mouse wheel** | Scroll the enlarged image horizontally |
| **Left drag or middle drag** | Pan the preview |
| **Left click orange candidate** | Recover/accept a previously rejected candidate |
| **Left click empty area** | Try local circular refinement; if unsuccessful, offer a flagged manual center |
| **Right click accepted green/blue ROI** | Remove that ROI from the current measurement |
| **Right click orange candidate** | Hide it; prevent reselection/snapping at later candidate re-evaluations |
| **Undo Edit** | Restore the immediately previous edit, including a hidden candidate |
| **Reset Manual Edits** | Discard manual edits and hidden candidate states for the current image |

An accepted contour removed from measurement can remain orange. Right-click the orange candidate again to hide it, then left-click that location to search for a **new** circle instead of reaccepting the old candidate. Manually recovered circles must still be visually checked.

### ROI numbering

When reviewing and saving, accepted ROIs are numbered **first column top-to-bottom, then successive columns left-to-right**. Their IDs match the saved CSV rows and reviewed overlay labels. This is a grouping heuristic using x coordinates, not a grid constraint on detection; verify ordering on skewed or unusual layouts.

## 4. Save reviewed measurements

Click **2. Measure & Save CSV** only after inspecting the full image and confirming the ROI count, centers, radius, and channel.

Each save creates a new result folder under `results/`. Key outputs include:

| File | Meaning |
|---|---|
| `selected_channel_measurements.csv` | One selected-channel mean intensity per reviewed ROI, in approved ROI order |
| `measurements.csv` | Full RGB measurements and quality-control fields |
| `centers.csv` | Final ROI IDs and oriented-image pixel centers |
| `review_selection.csv` | Final and original IDs, matrix column/row, source/oriented centers, review provenance |
| `review_log.json` | Manual edits, hidden candidates, orientation, and review metadata |
| `run.json` | Original image/measurement parameters, provenance, and hashes |
| `reviewed_roi_overlay.png` | Final numbered ROIs on the RGB image |
| `reviewed_candidate_overlay.png` | RGB candidate review overlay, excluding manually hidden candidates |
| `selected_channel_roi_overlay.png` | Selected-channel grayscale with green accepted circles and matching labels; no candidate overlay for that channel |
| `candidate_overlay.png`, `roi_overlay.png` | Additional CLI-produced diagnostic overlays |
| `radius_comparison.csv` | Applied versus automatic radius and pixel area, when available |

**Do not measure pixel values from the overlays.** They contain annotations; the software measures the decoded source raster. The source image is not modified by any ROI editing or save operation.

## 5. Calibration: combine one or several µPADs

Switch to the **Calibration** tab.

1. Set the **project name** and **concentration unit** (e.g., `µM` or `ppm`); use the correct chemical definition of the unit for the specific assay.
2. Click **Add latest reviewed image**, or **Import reviewed CSV** and select a prior run's `selected_channel_measurements.csv` file. The `review_selection.csv` and `review_log.json` must be in the same run folder; unreviewed runs are rejected.
3. Repeat for each µPAD contributing to the **same calibration**. The application guards against importing the same original source image twice. Check the full image paths when scans have similar filenames.
4. Select one or multiple ROI rows (Ctrl/Shift), choose **Blank**, **Standard**, or **Ignore**, and click **Apply to selected**:
   - **Blank**: provide a blank-group ID such as `B1`; leave standard concentration empty.
   - **Standard**: provide a sample label, numerical concentration, and the **blank-group ID of the reference blank**.
   - **Ignore**: exclude the ROI from the calibration project.
5. Verify all assignments: **no sample role, concentration, or blank group is inferred from the ROI numbering**.
6. Click **Calculate**. Review the concentration-level calibration plot and results. Each concentration is one regression point even if the corresponding standard ROIs come from different images.
7. Optionally inspect **outlier proposals**. Toggle individual proposals off when unsupported; their purpose is to aid human review, not to erase laboratory observations.
8. **Save Project** to a calibration JSON if you need to resume later, then **Export Excel — 2 sheets**.

A calibration requires at least three distinct standard concentrations, a valid blank group for every standard, one shared RGB channel, and consistent concentration labels. A source image may have multiple roles/concentrations; assignment is per ROI. If you change assignments, recalculate and inspect the preview again.

## 6. Edit the exported Excel workbook

The export has **exactly two** sheets:

- **`All_Data`** — begins with all valid standard measurements included.
- **`Optimized`** — begins with statistically proposed standard exclusions, marked and requiring scientific review.

Both sheets are editable and contain independent scatter charts with axes, gridlines, a legend, a linear trendline, equation, and \(R^2\). Each blank block appears immediately before the standard groups that use it: **Blank B1 → its standards → Blank B2 → its standards**.

The left-hand measurement table has the following columns:

| Column | Heading | Notes |
|---|---|---|
| A | `Concentration` | Standard concentration or blank label |
| B | `Intensity` | Numerical input from the ROI measurement |
| C | `Absorbance` | Formula for individual blank-referenced signal; clearing this cell manually omits that measurement |
| D | `Mean intensity` | Formula-driven intensity mean for the corresponding group/blank |
| E | `Status` | `Included` / `Excluded` |
| F | `Blank group` | The operator-assigned blank reference |
| G–K | Source / ROI metadata | Image name/path, ROI ID, sample, measurement key |

The pooled regression summary is at the **right**, with concentration in **O**, count of included numeric absorbances in **P**, pooled mean pseudoabsorbance in **Q**, and regression outputs farther right. The per-concentration `Mean absorbance` and `SD absorbance` columns were intentionally removed from the detailed table; the pooled mean needed for regression remains in Q.

### Exclusions after export

A ROI contributes to its group only when **E is `Included` and C contains a numeric value**. To omit an ROI, set E to `Excluded` **or** delete that row's C formula/value. The count, pooled response, and regression are intended to update in Excel. This also works for blank rows. Blank D is a filtered mean of included blank intensities, and changing it affects all linked standard C formulas.

Blank C contains a *diagnostic* pseudoabsorbance relative to the **original all-blank intensity mean**, to prevent a circular reference. The standard's **actual** reference is the dynamically filtered blank D. Do not interpret the blank C values as the calibration baseline.

Invalid computed expressions show the text **`ERROR`**. A deliberately emptied C cell remains empty by design. If all blanks in a reference group are excluded, dependent standard calculations are invalid until an eligible blank is restored. If fewer than three usable standard concentration levels remain, do not interpret the fit as valid.

The source-code writer stores formulas with **English Excel function names** as required by the XLSX format. Excel localizes them when displayed in Hungarian, English, Portuguese, etc. The chart titles/axis labels stay in English. The exporter supplies cached initial values, but **Excel** is responsible for recalculation after manual cell edits. Check the charts and formulas with the laboratory's Excel version before relying on the edited file.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| Image not detected | RGB image format, weak/neutral spot contrast, candidate radius/tolerance; manual inspection and recovery |
| Extra orange circle blocks a smaller ROI | Right-click it to hide, then left-click the freed region for local refinement |
| IDs do not match intended sample order | Image orientation, physical layout, and column grouping; confirm every ROI assignment manually |
| Different pads produce an implausible calibration | Source image path, correct imported run, blank group, standard concentrations, measurement channel and units |
| Calibration refuses to calculate | Unassigned ROIs, missing blank reference, inconsistent sample/concentration mapping, too few distinct standards |
| Excel shows `ERROR` | Check positive intensities, valid included blank rows, and enough usable numeric standard means |
| Formula cell was deleted accidentally | Re-export from the saved calibration project or restore the intended formula from a comparable row |
| Zoomed ROI appears moved | Check image orientation versus display-only zoom; measurement coordinates are saved in the oriented raster |

See [Technical Reference](TECHNICAL_REFERENCE.md) for exact calculations, [Validation Guide](VALIDATION.md) for ImageJ comparison, and [Deployment Preparation](DEPLOYMENT.md) for current release restrictions.
