# Technical Reference

This is the current technical description of the image-processing, review, calibration, and export pipeline. It consolidates the previous prototype, viewport, orientation, candidate-dismissal, and Excel implementation notes. Algorithm/version identifiers in `src/micropad/__init__.py` and calibration project JSON are **data/provenance fields** and are intentionally not renamed during documentation cleanup.

## Architecture

| Component | Responsibility |
|---|---|
| `scripts/micropad_app.py` | Tkinter desktop entry point; hosts **ROI Review** and **Calibration** in one `ttk.Notebook` |
| `scripts/roi_test_gui.py` | User-driven image review, candidate selection, manual edits, orientation, preview and save |
| `scripts/calibration_tab.py` | Multiple-run import, manual ROI/sample/blank assignments, live plot, outlier proposal review, XLSX export |
| `scripts/analyze_image.py` | Reproducible single-image CLI measurement and result provenance |
| `scripts/image_io.py` | Source decoding and manual-center CSV parsing |
| `scripts/reporting.py` | CSV, JSON, and diagnostic overlay outputs |
| `src/micropad/detection.py` | HSV segmentation, contour candidates, radius consensus |
| `src/micropad/review.py` | Candidate filtering/recovery and local Hough refinement |
| `src/micropad/roi.py` | Circular mask and boundary rules |
| `src/micropad/measurement.py` | Per-ROI RGB and selected-channel intensity means |
| `src/micropad/ordering.py` | Approved ROI column-major numbering |
| `src/micropad/orientation.py` | Lossless 90° rotation/axis reflection; coordinate inversion |
| `src/micropad/calibration_core.py` | Calibration projects, assignments, blank means, OLS fitting, statistical exclusion proposals |
| `src/micropad/calibration_xlsx.py` | Two-sheet, formula-backed XLSX and native Excel charts |

The image-measurement and calibration cores are separate from the Tkinter widgets. The GUI does not change source images or overwrite previous saved runs. Image review is mandatory for the intended workflow: automatic candidates are suggestions.

## Image input and pixel measurement

The image loader accepts single-frame RGB JPEG, PNG, and TIFF. It decodes with OpenCV `IMREAD_UNCHANGED`, converts BGR to RGB, and retains original pixel values; EXIF rotation, ICC/gamma conversion, contrast changes, resizing, and smoothing are not applied to measurement data. The automatic detector currently requires 8-bit RGB even though the low-level measurement machinery can handle wider integer depths. Unsupported modes/depths are rejected explicitly.

Pixel coordinates are native image pixels with `x` rightward and `y` downward. Orientation transformations operate on the array in memory without interpolation, and are recorded in order. The saved reviewed ROI coordinates refer to the **oriented raster**; `review_selection.csv` additionally contains mapped original-source coordinates. Preview-only interpolation/zoom/pan never affects measurement pixels.

A circular ROI with integer center \((c_x,c_y)\) and radius \(r\) uses the inclusive mask:

```text
(x - c_x)^2 + (y - c_y)^2 <= r^2
```

Centers are snapped to integers using half-up rounding. NumPy computes raw mean intensities from the selected source RGB channel, not from an annotated preview. A radius of 100 px produces **31,417** pixels with the current integer-centered mask; an ImageJ reference circle may contain **31,428** pixels, so identical nominal radii do not prove identical pixel membership. No historical ImageJ mask is reconstructed unless its exact original geometry is available.

## Automatic circular-zone detection

1. Blur a **separate detector copy** with a 7-pixel Gaussian kernel.
2. Segment the blurred RGB image in HSV (default saturation \(\ge 10\), value \(\ge 100\) on OpenCV's 8-bit scales).
3. Apply 7-pixel elliptical morphological closing and find external contours.
4. Ignore contours below a minimum area based on 1% of the shorter source-image dimension; retain larger candidates with geometric metrics and QC flags.
5. Evaluate radius, circularity, fill ratio, and axis ratio. Common defaults are 0.50 minimum circularity, 0.70 minimum fill ratio, and 0.75 minimum axis ratio.
6. Derive candidate center from contour moments; candidate equivalent radius from \(\sqrt{\mathrm{area}/\pi}\).
7. Identify a dominant radius neighborhood within \(\pm20\%\) and apply a robust median/MAD consensus, with at least three consistent circles by default.
8. Propose a common analytical radius. For unusual layouts, the operator can set a custom analytical radius and independently tune the candidate-search radius and tolerance.

These parameters are current implementation defaults and are **not** universal validated thresholds for all analytes, scans, or scanners. Detection never requires a specified grid size, concentration list, target number of ROIs, or intensity-based ranking.

The live overlay distinguishes accepted ROIs from rejected/orange candidates. Manual review allows an orange candidate to be accepted, an accepted ROI to be removed, or an orange candidate to be hidden with right-click so it cannot snap back during subsequent re-evaluations. Manual local refinement can propose a new center after hiding a contour. Undo and reset can restore prior selections; manual actions are recorded in `review_log.json`.

## Orientation, numbering, and preview

- Orientation controls: clockwise/counterclockwise 90° rotation; horizontal and vertical reflection; reset. Operations are applied in the order selected, with no color interpolation.
- Orientation changes re-run detection and require confirmation before clearing manual edits.
- Approved ROIs are numbered **leftmost column top-to-bottom**, then the next column to the right. The implementation uses x-coordinate grouping and a radius-derived tolerance (currently 0.90 times a detected-radius hint). This is only a **post-detection ordering heuristic**; skewed matrices still require human review.
- `review_selection.csv` preserves `original_review_id`, final ID, 1-based column/row, oriented and source centers, radius, candidate/source/QC information.
- Large scans are previewed with viewport-only Pillow resampling; canvas vector overlays are redrawn on zoom/pan; no high-resolution zoomed source is created for measuring.

## Reviewed measurement outputs

Saving via the ROI GUI uses the CLI's manual-center execution path to ensure the intensity CSV reflects the **final approved ROIs**, not a different automatic re-detection. It checks that saved ROI IDs and centers match the reviewed set. A new output directory is used rather than overwriting experimental files.

| Output | Notes |
|---|---|
| `measurements.csv` | Full RGB means, chosen channel mean, pixel count, geometry and QC |
| `selected_channel_measurements.csv` | Selected-channel-only mean values and review metadata for calibration |
| `centers.csv` | ROI IDs, center_x, center_y; preserved row order |
| `candidates.csv` | Contour geometry and QC decisions (pre-review detector context) |
| `review_selection.csv` | Canonical ROI numbering, mapped coordinates, review provenance |
| `review_log.json` | Manual changes, dismissed candidates, orientation, selection settings |
| `run.json` | Input/decoder metadata, file hashes, settings, software/algorithm identifiers |
| `roi_overlay.png`, `candidate_overlay.png` | CLI diagnostics |
| `reviewed_roi_overlay.png`, `reviewed_candidate_overlay.png` | Human-reviewed RGB overlays |
| `selected_channel_roi_overlay.png` | Selected-channel grayscale, with **green** approved outlines and final labels only |
| `radius_comparison.csv` | Pixel-count comparison for suggested and applied radii (when an automatic radius exists) |

`reviewed_candidate_overlay.png` omits candidates manually hidden by the operator. The selected-channel overlay does **not** have a separate candidate image. Source-image files and historical ImageJ exports remain untouched.

## CLI and fixed-center replay

From the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\analyze_image.py "data/lab_validated/NO2_1/IMG_0002_CurvadoDia_20min (2) (1).jpg" --channel G --roi-radius 100
```

A saved `centers.csv` can be used to measure the same approved coordinates at a fixed radius:

```powershell
.\.venv\Scripts\python.exe scripts\analyze_image.py "data/lab_validated/NO2_1/IMG_0002_CurvadoDia_20min (2) (1).jpg" `
  --centers-csv "results/REVIEWED_RUN/centers.csv" --roi-radius 100 --channel G
```

If the original run was rotated or mirrored, supply the **same ordered `--transform` arguments** (e.g. `--transform cw --transform flip_h`), since saved centers refer to the oriented raster. Manual-center replay requires an explicit radius and preserves supplied IDs and order. The CLI does **not** assign standards or perform calibration; use the Calibration tab for that. The CLI's default output-folder prefix contains the historical word `prototype` for compatibility; this does not change the current application capability.

## Calibration project and calculations

The calibration project stores imported reviewed intensity values and manual assignments. It requires:

- Every non-ignored ROI assigned **Blank** or **Standard**, with a usable blank-group ID.
- At least three distinct standard concentrations with finite, nonnegative concentration values.
- A matching blank group for each standard, one RGB channel for the complete calibration, and consistent standard labels.
- Positive, finite source intensities and no duplicate import of the same original source image.

A standard \(i\) uses the average intensity \(I_{0,g}\) of its assigned blank group \(g\):

\[
A_i = \log_{10}\left(\frac{I_{0,g}}{I_i}\right),\qquad
I_{0,g} = \operatorname{mean}\{I_j: j\in g\}.
\]

The application **first** computes an absorbance for every standard ROI, **then** pools absorbances for the same concentration across the selected pads, and averages them. Linear ordinary least squares is applied to **one mean per distinct concentration**, with a **free intercept**, no forced zero point, and no weighting:

\[
\overline A_c = mc+b.
\]

The fit includes slope, intercept, \(R^2\), and RMSE. The separate worksheet containing all input standard measurements remains the primary reproducibility reference. The fitted calibration is a descriptive regression until appropriate analytical validation is completed.

### Outlier proposals

The automatic proposal function currently considers **standard ROIs only**. Default screening requirements include:

- At least **four** starting replicate measurements in that concentration group.
- Modified MAD score \(\ge 3.5\) within the concentration group.
- Absolute pseudoabsorbance deviation from group median \(\ge 0.005\).
- At least **three** measurements retained in that group.
- At most **one** proposed exclusion per concentration, at most **ten** total by default.
- A **positive incremental improvement** in \(R^2\) after excluding the candidate.

The algorithm is a constrained greedy search and **does not guarantee a global best \(R^2\)**. Higher \(R^2\) alone is never evidence of invalid data; candidate exclusions must be inspected using the scan, assay conditions, and a documented scientific reason. The tool does not automatically propose blank exclusions, but blank measurements can be excluded **manually in Excel**.

## XLSX generation and editing semantics

The writer in `calibration_xlsx.py` produces exactly `All_Data` and `Optimized`, with native chart objects and Office Open XML formulas. It does not calculate Excel formulas itself; it supplies initial numerical caches and requests Excel recalculation.

The detailed table contains **A** concentration, **B** intensity, **C** individual pseudoabsorbance, **D** mean intensity, **E** Included/Excluded status, **F** blank group, and **G–K** provenance fields. The regression input table uses **O** concentration, **P** number of included numerical signals, and **Q** pooled mean pseudoabsorbance, with fit statistics to its right. The chart uses pooled mean values, not all raw replicate points.

A ROI is included in Excel only when its **C** cell holds a numeric value and **E** is `Included`. Clearing C or changing E to `Excluded` omits that measurement from relevant averages and counts. The blank reference **D** is similarly filtered, so a blank exclusion can change all linked standard absorbances. The blank C diagnostic uses the **original unfiltered blank mean** to avoid a circular formula reference. Formula failures display the literal `ERROR`; intentional deletion of a C formula remains blank. Chart source and regression should be rechecked after any manual edits.

Formula names are stored in **English OOXML convention**, regardless of the user's Excel UI language. Chart labels are English strings. Blank-group and measurement identifiers remain traceable, including when the calibration spans several pad images.

## Limits to keep visible during validation and release

- The automatic HSV detector can miss pale/neutral or overlapping zones, and its fixed pixel kernels can behave differently at another scanner resolution.
- Column grouping can be unstable on strongly skewed pads; check the displayed order.
- ImageJ intensity matching cannot be concluded solely from nominal ROI radius; original centers and mask membership may differ.
- A high \(R^2\) cannot prove valid outlier exclusion or reliable concentration estimation on independent samples.
- Excel dynamic editing depends on the target Excel application recalculating and updating the native chart correctly.
- The current application uses Tkinter, not PySide6; packaged Windows delivery is a separate qualification task.
