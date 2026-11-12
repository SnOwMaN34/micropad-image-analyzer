# Validation Guide

This guide covers scientific verification of the **human-reviewed** µPAD image-analysis workflow against historical ImageJ measurements and the resulting calibrations. It is a protocol, not a claim that the application is already analytically validated.

## 1. Define the comparison

The intended laboratory procedure is **semi-automatic**: automatic detection is followed by user inspection and correction before saving. Therefore, the primary comparison is between **manually approved Python ROIs** and the earlier manually placed ImageJ ROIs, using the **same source image, RGB channel, and nominal ROI radius**.

Two different properties must be distinguished:

1. **Measurement agreement of the workflows:** do corresponding physical reaction zones produce similar mean intensities, knowing the original ImageJ ROIs may not cover exactly the same pixels?
2. **Analytical calculation consistency:** given paired measurements, do the same blank/standard assignments and replicate inclusion rules yield similar pseudoabsorbances and calibration parameters?

The original exact ImageJ center/mask geometry may be unavailable. In that case do not call this a pixel-for-pixel verification; report it as a workflow comparison.

## 2. Preserve and document source inputs

For each experiment, retain the original RGB scans, ImageJ intensity export, processed laboratory workbook, and associated experimental notes/paper if available. Establish: image/export pairing, orientation, ROI mapping, channel, nominal ImageJ area/radius, standard concentrations and units, blank assignment, excluded historical observations, and exact prior Excel formulas. Do not overwrite originals.

Record the Git commit hash used for analysis:

```powershell
git rev-parse HEAD
```

A useful per-zone mapping has columns such as `experiment`, `image`, `python_roi_id`, `imagej_row`, `sample`, `concentration`, `blank_group`, `historically_included`, and a mapping confidence/status. **Pair measurements by their physical location and experimental labels, never by proximity of intensity values.**

## 3. Measure reviewed ROIs

For each original image:

1. Open it in **ROI Review**, orient it to the intended physical ordering, and choose the ImageJ RGB channel.
2. Set the nominal matching ROI radius and check the displayed pixel area (e.g. for nitrite, radius 100 px gives 31,417 pixels in the Python mask versus a historical ImageJ area of 31,428 pixels).
3. Run detection, review all reaction zones, and manually add/remove/reposition ROIs where needed. Preserve any QC notes.
4. Save the reviewed result and retain the **selected-channel CSV**, **review selection/log**, and **overlays**.
5. Confirm each Python ROI is paired to the corresponding ImageJ reaction zone.

Use all usable pairs when assessing **raw intensity agreement**, even when the historical lab calibration excluded those measurements. Record any physically invalid or unpairable zone as such rather than silently deleting it.

## 4. Compare individual intensities

For each paired zone \(i\), calculate:

\[
\Delta I_i = I_{\mathrm{Python},i} - I_{\mathrm{ImageJ},i}, \qquad
\Delta I_{\%,i} = 100\frac{I_{\mathrm{Python},i} - I_{\mathrm{ImageJ},i}}{I_{\mathrm{ImageJ},i}}.
\]

Summarize number of pairs, signed mean difference (**bias**), mean absolute error (**MAE**), root mean square error (**RMSE**), and maximum absolute deviation. Inspect scatter with the \(y=x\) line and a Bland–Altman-style difference-versus-mean plot. Check whether residuals vary by intensity, concentration, blank/standard group, or image.

**Caution:** repeated zones from the same pad are clustered observations. Treat simple agreement limits as descriptive unless a dependence-aware statistical plan is specified. A high correlation or \(R^2\) between intensity vectors does not establish agreement.

## 5. Compare blank and standard groups

For each blank group and concentration group, compute on **identical paired subsets**:

- The mean intensity.
- Sample standard deviation (SD).
- Relative SD (RSD), where defined.
- Difference and relative difference between the ImageJ and Python means.

Run two grouping schemes: **all usable pairs** and **historical inclusion selection**. If the lab excluded a particular replicate, select that same physical replicate in both ImageJ and Python historical calculations. Keep the excluded measurements visible in the raw comparison sheet.

If a laboratory workbook excluded a blank measurement, preserve that decision in the historical comparison as well. The reason must be documented where known; unknown historical reasons remain *unknown* and are not retroactively presented as verified QC failures.

## 6. Recreate the analytical calculations

Using each method's own applicable blank mean \(I_{0,g}\), compute individual standard pseudoabsorbance:

\[
A_i = \log_{10}(I_{0,g}/I_i).
\]

Then average the individual \(A_i\) within each concentration, and fit a line to the concentration-level means with the same concentration levels, regression approach, and replicate selection in both methods.

**Historical processing may be different:** some lab spreadsheets first averaged intensity and then applied the logarithm, which is generally not equal to averaging individual log values. Reproduce the **original** order of operations to compare published/historical results; report the program's current per-ROI-then-average method separately when they differ. Do not mislabel a different calculation as a failed intensity measurement.

Compare slope, intercept, \(R^2\), residuals, range, used concentration levels and number of replicates. A good calibration \(R^2\) does not demonstrate external predictive accuracy. Back-calculating standards already used in the fit is an **internal consistency check**; independent known-concentration quality-control samples are preferable for predictive accuracy.

## 7. Quantify historical-exclusion sensitivity

Produce matched ImageJ/Python calibrations under both inclusion schemes:

| Comparison | ImageJ | Python | Interpretation |
|---|---|---|---|
| Historical selection | Same historically retained zones | Same physical zones retained | Principal comparison controlling for previous decisions |
| All usable repeats | All usable zones | Corresponding usable zones | Sensitivity to replicate inclusion |

Compare how group mean, blank reference, regression slope/intercept, and residuals change. Do **not** choose historical or new exclusions solely to maximize \(R^2\). The application's statistical optimizer provides exploratory **standard-ROI** suggestions only; blank exclusions currently require manual review/editing in Excel. If reasons for historical exclusions are unknown, state that limitation plainly.

## 8. Extend to other pad types

After completing an example dataset end-to-end, apply the same protocol to other nitrite, ammonium, creatinine, and other colorimetric experiments for which source images, mapping and reference data are available. Verify channel and ROI geometry separately for each assay. Only attempt a calibration where standards, units and blank grouping can be reconstructed defensibly.

The software's ROI detection may need manual review for every assay; do not claim a 100% automatic detection rate from the human-reviewed final count. If automatic detection is assessed as a separate engineering outcome, record the number of correctly proposed, missed, and false candidates **before** manual editing.

## 9. Reporting and acceptance

A complete report should include: source/experiment inventory; mapping method; ROI pixel convention; any manual corrections; per-zone and group-level agreement; blank/standard processing; inclusion/exclusion log; paired calibration comparisons; editable graphs; and known limitations.

Avoid setting arbitrary universal acceptance thresholds for intensity error or calibration \(R^2\). Where formal acceptance criteria are needed, justify them from the assay's analytical objective, repeatability, concentration range, and any independent reference/quality-control data. The software should not be presented as validated on scanner configurations or analytes not actually tested.
