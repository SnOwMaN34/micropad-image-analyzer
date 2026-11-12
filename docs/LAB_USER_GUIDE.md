# µPAD Image Analyzer — Laboratory Quick Start

**Research software, not a clinical diagnostic device.** The operator must review and approve all reaction-zone locations, concentration assignments, and calibration outcomes. Do not use calibration R² alone to decide whether a measurement is valid.

## 1. Starting the application

1. On a Windows PC, extract the complete distributed ZIP archive to a folder you can access (for example, `Documents\MicroPADImageAnalyzer`).
2. Keep **all files and the `_internal` folder together**. Do not copy the `.exe` away from its supporting files.
3. Double-click `MicroPADImageAnalyzer.exe`.
4. The application has two tabs at the top: **ROI Review** and **Calibration**. No Python installation or internet connection is required for normal operation.
5. Do not store the only copy of laboratory data inside the application folder. Choose source images from your own laboratory data location.

If Windows displays an unrecognized-app warning, stop and confirm the software's provenance and SHA-256 checksum with the distributor or your laboratory IT team. Do not bypass institution security policies.

## 2. ROI Review — process one image

1. Choose **ROI Review** and click **Browse...** to select a *single-frame RGB* JPG, PNG or TIFF image.
2. Select the **R**, **G** or **B** measurement channel appropriate for the color reaction and your laboratory method.
3. Adjust image orientation with 90° rotations or horizontal/vertical flips as needed. These operations rearrange original pixels without interpolation. The source image is never overwritten.
4. Click **Detect & Preview**. Automatic detection suggests candidate circular zones, but does not replace visual review.
5. Check every accepted (green) circle. Select the appropriate analytical **ROI Radius** (automatic or custom). The candidate-search radius and tolerance can be adjusted separately if the paper support has a larger radius than the colored reaction zone.
6. Correct the result: left-click an orange candidate to accept it; left-click empty space to request local center refinement; right-click a green ROI to exclude it; right-click an orange candidate to hide it. Use **Undo Edit** or **Reset Manual Edits** if needed.
7. Use **Fit Image**, **100%**, zoom and scroll controls to inspect placement at useful magnification. Display zoom does not change measurement pixels.
8. Check the **column-major numbering**: leftmost column top-to-bottom, then the next column from top to bottom. This sequence is used in saved ROI identifiers and CSV rows.
9. Click **Measure & Save CSV** only after reviewing all accepted ROIs.
10. Click **Open Latest Results** to inspect the saved folder.

The output includes the selected-channel intensity CSV, the colored and selected-channel overlays, ROI coordinates, a record of review decisions and measurement metadata. Preserve the whole run folder when archiving a measurement.

## 3. Calibration — one or multiple µPAD images

1. Switch to the **Calibration** tab.
2. Click **Add latest reviewed image** to import the run just saved. Alternatively use **Import reviewed CSV** and choose the `selected_channel_measurements.csv` in a previously reviewed run folder.
3. Repeat ROI review and import for every additional pad required by the same calibration. The app handles several reviewed image runs in one calibration project.
4. Inspect the imported **image/pad and ROI ID** for every row. Do not infer sample identities from spatial order alone.
5. Select one or more ROI rows and assign a **Role**:
   - **Blank**: enter a blank-group identifier, e.g. `B1`.
   - **Standard**: enter the known concentration, sample label and corresponding blank-group identifier.
   - **Ignore**: omit a ROI from calibration deliberately.
6. If two pads have independent blanks, use **B1** for the standards belonging to pad 1 and **B2** for those belonging to pad 2. Each standard must reference an existing blank group. A single calibration can still combine all its concentration levels.
7. Confirm the concentration **unit** (for example, `µM`) and ensure it is the same for all standards in the project. The software does **not** convert concentration units automatically.
8. Click **Calculate** and review the concentration-level data, linear fit, slope, intercept, R² and graph. Check that concentrations increase consistently with the expected analytical response, and confirm blank associations.
9. If desired, request the **outlier proposals**. Review each proposal against the original image and recorded QC. You can disable any proposal. A higher R² is *not* evidence that a point was analytically invalid.
10. Save the calibration project as JSON if you want to resume it later. Keep the reviewed run folders alongside the project when transferring it to another workstation; stored source paths may need attention after copying.
11. Choose **Export Excel**. Pick a location for the `.xlsx` file that your lab team can access and back up.

## 4. Excel workbook — review and edit

The export contains **exactly two sheets**:

- **All_Data**: calibration with all initially included measurements.
- **Optimized**: a separate, exploratory calibration using the enabled statistical-exclusion proposals.

Each blank block appears **immediately before its associated standards**: Blank B1, its standards, Blank B2, its standards, and so on. The detail table starts with **Concentration**, **Intensity**, **Absorbance**, **Mean intensity**, **Status**, and **Blank group**. Native, editable Excel charts show the regression with equation, R², axes, gridlines and legend.

- The source **Intensity** values are measurements. Dependent values (blank reference means, pseudoabsorbance, concentration-level averages, slope, intercept and R²) are represented by Excel formulas.
- To omit a measurement in Excel, set its **Status** to `Excluded`, or clear that ROI's **Absorbance** cell. Both methods can affect standards **and blanks**.
- A deleted blank absorbance or excluded blank removes that blank intensity from the reference mean for its group. That may change *all* associated standard absorbances. Keep a record of why you excluded it.
- The count of included observations is based on the **actually numeric absorbances** marked `Included`, not just the number of concentration labels.
- If a formula cannot be evaluated, `ERROR` should be shown. Do not report a calibration until errors, missing blank groups and inconsistent concentrations have been resolved.
- After manual edits, confirm the chart and regression have recalculated in Excel. Native Excel translations of functions are handled by the installed Office locale; headings remain in English.

**Calculation convention:** for each standard ROI, `A = log10(blank group's mean intensity / ROI intensity)`. Individual pseudoabsorbances are then averaged within each concentration; an unweighted straight line with an intercept is fitted to the mean response at each concentration level. This may differ from historical laboratory worksheets that first averaged intensities and only then applied the logarithm.

## 5. Where the measurement results are saved

The portable Windows application saves each reviewed measurement in the **`results` folder beside `MicroPADImageAnalyzer.exe`**. For example:

```text
MicroPADImageAnalyzer_YYYYMMDD_HHMMSS/
  MicroPADImageAnalyzer.exe
  _internal/
  results/
    README.txt
    review_inputs/
    prototype_.../              (one folder per measurement)
```

Use **Open Latest Results** after a measurement, or open the application's folder in Windows Explorer and then open `results`. The app creates additional run subfolders automatically. The folder must be **writable**; extract the entire ZIP to a normal folder such as `Documents`, rather than opening the EXE directly inside the ZIP, or placing it in a protected/read-only location such as `C:\Program Files`.

The Excel workbook and calibration-project JSON are saved wherever you choose in their save dialogs; they are **not** automatically saved to `results`. Results are local; the application does not upload images to a cloud service. Moving the application folder moves the results with it, but saved calibration projects may contain absolute paths to source images and reviewed CSV files; check these after moving or copying the folder.

## 6. Common problems

| Symptom | What to check |
|---|---|
| No image is listed in the dropdown | This is normal in the distributed app; click **Browse...** and choose a laboratory image. |
| Orange rings are visible but excluded | Review them manually; add a legitimate candidate or hide a false detection. |
| A large white backing disc is selected | Adjust candidate-search radius independently from analytical ROI radius. |
| Saved result count is wrong | Inspect accepted circles and column numbering before clicking **Measure & Save CSV**. |
| Imported run rejected | Import `selected_channel_measurements.csv` from a reviewed folder containing `review_selection.csv` and `review_log.json`; avoid importing the same source image twice. |
| Calibration cannot be computed | Check that all ROIs have roles, each standard has a concentration and an existing blank group, all channels agree, and at least three concentration levels exist. |
| Excel displays `ERROR` | Check that enough blank measurements remain included, concentrations are valid and formulas have not been inadvertently deleted. |
| Application does not start | Keep the whole extracted folder together. Contact the distributor with the Windows version and error message; do not delete `_internal`. |

## 7. Recommended recordkeeping

For each calibration retain: the original images, reviewed run folders, original instrument/protocol metadata, the calibration project JSON, the exported Excel file, details of exclusions and the application build identifier in `BUILD_INFO.txt`.

**Important:** The application helps standardize image measurements but has not been certified for clinical diagnostics. Scientific review and suitability for each assay are the laboratory's responsibility.
