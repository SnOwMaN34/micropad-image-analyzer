"""OpenCV contour candidates and robust shared-radius estimation, without a grid."""

from dataclasses import dataclass, replace
import math

import cv2
import numpy as np
from numpy.typing import NDArray

from .measurement import validate_rgb
from .roi import ROI, roi_window, round_pixel


@dataclass(frozen=True)
class DetectionSettings:
    """Explicit initial settings for colored zones on near-neutral scanner backgrounds.

    HSV thresholds use OpenCV's 8-bit scales. Radius bounds are fractions of the
    shorter image dimension. Kernel sizes are native pixels; no resizing occurs.
    These are prototype settings, not validated for all analytes/scanners.
    """

    saturation_min: int = 10
    value_min: int = 100
    blur_size: int = 7
    close_size: int = 7
    min_radius_fraction: float = 0.01
    max_radius_fraction: float = 0.15
    min_circularity: float = 0.50
    min_fill_ratio: float = 0.70
    min_axis_ratio: float = 0.75
    cluster_relative_tolerance: float = 0.20
    mad_multiplier: float = 3.0
    min_relative_radius_tolerance: float = 0.15
    min_consistent: int = 3

    def __post_init__(self) -> None:
        for value in (self.saturation_min, self.value_min):
            if not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError("HSV thresholds must be integers between 0 and 255")
        for size in (self.blur_size, self.close_size):
            if not isinstance(size, int) or size < 1 or size % 2 != 1:
                raise ValueError("Kernel sizes must be positive odd integers")
        if not 0 < self.min_radius_fraction < self.max_radius_fraction < 0.5:
            raise ValueError("Require 0 < min radius fraction < max radius fraction < 0.5")
        for value in (self.min_circularity, self.min_fill_ratio, self.min_axis_ratio,
                      self.cluster_relative_tolerance, self.min_relative_radius_tolerance):
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError("Shape and radius tolerances must be in (0, 1]")
        if not math.isfinite(self.mad_multiplier) or self.mad_multiplier <= 0:
            raise ValueError("MAD multiplier must be positive and finite")
        if not isinstance(self.min_consistent, int) or self.min_consistent < 1:
            raise ValueError("min_consistent must be a positive integer")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    center_x: float
    center_y: float
    detector_radius: float
    enclosing_radius: float
    contour_area: float
    circularity: float
    fill_ratio: float
    axis_ratio: float
    flags: tuple[str, ...] = ()
    roi_id: str = ""


@dataclass(frozen=True)
class DetectionResult:
    candidates: tuple[Candidate, ...]
    rois: tuple[ROI, ...]
    radius_median: float | None
    radius_mad: float | None
    roi_radius: float | None
    warnings: tuple[str, ...]


def radius_consensus(radii: NDArray, settings: DetectionSettings) -> tuple[NDArray, float, float]:
    """Find the largest relative-radius neighborhood, then apply median/MAD QC.

    Radius outliers cannot set the median. Ties choose the narrowest cluster,
    then the larger median (favoring zones over similarly circular small ink).
    This only filters geometric candidates, never intensity observations.
    """
    values = np.asarray(radii, dtype=float)
    if values.ndim != 1 or not values.size or not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Candidate radii must be a nonempty positive finite vector")
    neighborhoods = [np.abs(values - seed) <= settings.cluster_relative_tolerance * seed for seed in values]
    def score(mask: NDArray) -> tuple:
        median = float(np.median(values[mask]))
        mad = float(np.median(np.abs(values[mask] - median)))
        return int(mask.sum()), -mad / median, median
    dominant = max(neighborhoods, key=score)
    median = float(np.median(values[dominant]))
    mad = float(np.median(np.abs(values[dominant] - median)))
    cutoff = max(settings.min_relative_radius_tolerance * median,
                 settings.mad_multiplier * 1.4826 * mad)
    accepted = dominant & (np.abs(values - median) <= cutoff)
    if accepted.sum() < settings.min_consistent:
        raise ValueError("Insufficient consistent circles to estimate a shared radius")
    median = float(np.median(values[accepted]))
    mad = float(np.median(np.abs(values[accepted] - median)))
    return accepted, median, mad


def detect_rois(rgb: NDArray, settings: DetectionSettings | None = None, *,
                radius_factor: float = 1.0, roi_radius: float | None = None) -> DetectionResult:
    """Find colored, compact contour candidates and make equal-radius ROIs.

    Contour moments estimate centers; sqrt(area/pi) estimates colored-interior
    radii rather than tape/outer rims. Measurement centers are snapped once with
    half-up rounding. ROI IDs sort by (original y, original x), not grid rows.
    A supplied roi_radius overrides only analytical size, never candidate QC.
    """
    settings = settings or DetectionSettings()
    validate_rgb(rgb)
    if rgb.dtype != np.uint8:
        raise ValueError("This detector currently requires uint8 RGB; no silent bit-depth conversion")
    if not math.isfinite(radius_factor) or not 0 < radius_factor <= 1:
        raise ValueError("radius_factor must be in (0, 1]")
    if roi_radius is not None and (not math.isfinite(roi_radius) or roi_radius <= 0):
        raise ValueError("Explicit ROI radius must be positive and finite")
    if roi_radius is not None and radius_factor != 1:
        raise ValueError("Use either an explicit ROI radius or an interior factor")
    blurred = cv2.GaussianBlur(rgb, (settings.blur_size, settings.blur_size), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_RGB2HSV)
    mask = np.where((hsv[:, :, 1] >= settings.saturation_min) &
                    (hsv[:, :, 2] >= settings.value_min), 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (settings.close_size, settings.close_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    minimum = min(rgb.shape[:2]) * settings.min_radius_fraction
    maximum = min(rgb.shape[:2]) * settings.max_radius_fraction
    candidates = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < math.pi * minimum ** 2:
            continue  # A documented area floor suppresses tiny specks; larger failures are audited.
        moments = cv2.moments(contour)
        perimeter = cv2.arcLength(contour, True)
        (_, _), enclosing = cv2.minEnclosingCircle(contour)
        _, _, width, height = cv2.boundingRect(contour)
        radius = math.sqrt(area / math.pi)
        circularity = 4 * math.pi * area / perimeter ** 2 if perimeter else 0.0
        fill = area / (math.pi * enclosing ** 2)
        axis_ratio = min(width, height) / max(width, height)
        flags = []
        if radius > maximum:
            flags.append("radius_above_search_range")
        if circularity < settings.min_circularity:
            flags.append("low_circularity")
        if fill < settings.min_fill_ratio:
            flags.append("low_fill_ratio")
        if axis_ratio < settings.min_axis_ratio:
            flags.append("low_axis_ratio")
        candidates.append(Candidate("", moments["m10"] / moments["m00"], moments["m01"] / moments["m00"],
                                    radius, float(enclosing), area, circularity, fill, axis_ratio, tuple(flags)))
    candidates.sort(key=lambda c: (c.center_y, c.center_x))
    candidates = [replace(c, candidate_id=f"C{i:03d}") for i, c in enumerate(candidates, 1)]
    indices = [i for i, c in enumerate(candidates) if not c.flags]
    try:
        keep, median, mad = radius_consensus(np.array([candidates[i].detector_radius for i in indices]), settings)
    except ValueError as error:
        candidates = [replace(c, flags=c.flags or ("insufficient_radius_consensus",)) for c in candidates]
        return DetectionResult(tuple(candidates), (), None, None, None, (str(error),))
    radius = roi_radius if roi_radius is not None else float(round_pixel(median * radius_factor))
    if radius <= 0:
        raise ValueError("Analytical radius rounds to zero; increase the radius factor")
    rois = []
    warnings = []
    for index, accepted in zip(indices, keep, strict=True):
        c = candidates[index]
        if not accepted:
            candidates[index] = replace(c, flags=("radius_outlier",))
            continue
        roi = ROI(f"ROI_{len(rois) + 1:03d}", round_pixel(c.center_x), round_pixel(c.center_y), radius)
        try:
            roi_window(roi, rgb.shape)
        except ValueError:
            candidates[index] = replace(c, flags=("clipped_roi",))
            warnings.append(f"{c.candidate_id}: analytical ROI crosses the image boundary")
            continue
        if any((r.center_x, r.center_y) == (roi.center_x, roi.center_y) for r in rois):
            candidates[index] = replace(c, flags=("duplicate_center",))
            continue
        rois.append(roi)
        # Uniform analytical circles can extend outside weakly segmented pale
        # interiors. Retain the measurement and expose this geometry for review.
        qc = ("roi_larger_than_detected_enclosing_circle",) if radius > c.enclosing_radius else ()
        candidates[index] = replace(c, roi_id=roi.roi_id, flags=qc)
    return DetectionResult(tuple(candidates), tuple(rois), median, mad, radius, tuple(warnings))
