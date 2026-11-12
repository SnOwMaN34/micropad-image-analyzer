"""Deterministic circular masks in original, unrotated image coordinates."""

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray


MASK_RULE = "integer pixel centers; (x-cx)^2+(y-cy)^2 <= radius^2; inclusive boundary"


@dataclass(frozen=True)
class ROI:
    """A shared-radius measurement ROI. Coordinates index original pixels."""

    roi_id: str
    center_x: int
    center_y: int
    radius: float

    def __post_init__(self) -> None:
        if not self.roi_id or not isinstance(self.roi_id, str):
            raise ValueError("ROI ID must be a nonempty string")
        for coordinate in (self.center_x, self.center_y):
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, np.integer)):
                raise ValueError("ROI centers must be integer original-pixel coordinates")
        if not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("ROI radius must be positive and finite")


def round_pixel(value: float) -> int:
    """Snap a nonnegative detector coordinate to nearest integer, halves upward."""
    if not math.isfinite(value) or value < 0:
        raise ValueError("Detector coordinate must be nonnegative and finite")
    return math.floor(value + 0.5)


def circle_mask(radius: float, *, center_offset: float = 0.0) -> NDArray[np.bool_]:
    """Return a local mask; offset=0.5 is an area diagnostic, not measurement mode.

    With offset=0, the array center represents the integer ROI center. Floating
    point coordinates are used before squaring to avoid uint8 arithmetic overflow.
    """
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("Radius must be positive and finite")
    if center_offset not in (0.0, 0.5):
        raise ValueError("Only integer or half-pixel diagnostic centers are supported")
    extent = math.ceil(radius + center_offset)
    y, x = np.ogrid[-extent:extent + 1, -extent:extent + 1]
    return (x.astype(float) - center_offset) ** 2 + (y.astype(float) - center_offset) ** 2 <= radius ** 2


def roi_window(roi: ROI, image_shape: tuple[int, ...]) -> tuple[slice, slice]:
    """Return the full mask window; reject clipping rather than truncate a mask."""
    extent = math.ceil(roi.radius)
    left, top = roi.center_x - extent, roi.center_y - extent
    right, bottom = roi.center_x + extent + 1, roi.center_y + extent + 1
    if left < 0 or top < 0 or right > image_shape[1] or bottom > image_shape[0]:
        raise ValueError(f"ROI {roi.roi_id} crosses the image boundary")
    return slice(top, bottom), slice(left, right)


def overlapping_roi_ids(rois: list[ROI]) -> set[str]:
    """Flag touching/overlapping analytical circles without deleting measurements."""
    flagged: set[str] = set()
    for index, a in enumerate(rois):
        for b in rois[index + 1:]:
            if math.hypot(a.center_x - b.center_x, a.center_y - b.center_y) <= a.radius + b.radius:
                flagged.update((a.roi_id, b.roi_id))
    return flagged
