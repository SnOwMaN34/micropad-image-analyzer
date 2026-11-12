"""Raw RGB quantification only; no blanks, calibration, or intensity exclusions."""

import numpy as np
from numpy.typing import NDArray

from .roi import ROI, circle_mask, overlapping_roi_ids, roi_window


def validate_rgb(rgb: NDArray) -> None:
    """Reject conversions that could hide grayscale, alpha, or changed bit depth."""
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.shape[0] or not rgb.shape[1]:
        raise ValueError("Expected a nonempty H x W x 3 RGB array")
    if rgb.dtype not in (np.dtype("uint8"), np.dtype("uint16")):
        raise ValueError("Only original uint8/uint16 RGB values are supported")


def measure_rois(rgb: NDArray, rois: list[ROI], channel: str = "G") -> list[dict]:
    """Measure identical-radius integer-centered masks from the original RGB array.

    Invalid/clipped masks fail explicitly. Overlap is retained with a QC flag.
    The function neither changes input pixels nor normalizes intensities.
    """
    validate_rgb(rgb)
    if channel not in ("R", "G", "B"):
        raise ValueError("Channel must be R, G, or B")
    if not rois:
        raise ValueError("No ROIs to measure")
    if len({roi.roi_id for roi in rois}) != len(rois):
        raise ValueError("ROI IDs must be unique")
    radius = rois[0].radius
    if any(roi.radius != radius for roi in rois):
        raise ValueError("All ROIs must share one radius")
    mask = circle_mask(radius)
    pixel_count = int(mask.sum())
    overlapping = overlapping_roi_ids(rois)
    rows = []
    for roi in rois:
        ys, xs = roi_window(roi, rgb.shape)
        means = rgb[ys, xs][mask].mean(axis=0, dtype=np.float64)
        row = {
            "roi_id": roi.roi_id, "center_x": roi.center_x, "center_y": roi.center_y,
            "radius": radius, "pixel_count": pixel_count,
            "mean_R": float(means[0]), "mean_G": float(means[1]), "mean_B": float(means[2]),
            "selected_channel": channel, "selected_mean": float(means[("R", "G", "B").index(channel)]),
            "qc_flags": "overlapping_roi" if roi.roi_id in overlapping else "",
        }
        rows.append(row)
    return rows
