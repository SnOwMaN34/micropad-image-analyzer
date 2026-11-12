"""Radius-aware candidate review and manual centre recovery.

Selection and manual corrections are distinct from the HSV contour detector and
from the analytical radius used for measuring original image pixels. All edits
are retained as auditable operations by the calling GUI.
"""

from dataclasses import dataclass
import math
from typing import Sequence

import cv2
import numpy as np

from .detection import Candidate
from .roi import ROI, roi_window, round_pixel


@dataclass(frozen=True)
class ReviewEntry:
    roi_id: str
    center_x: int
    center_y: int
    source: str
    candidate_id: str = ""
    candidate_radius: float | None = None
    qc_flags: str = ""

    def to_roi(self, radius: float) -> ROI:
        return ROI(self.roi_id, self.center_x, self.center_y, radius)


def candidate_radius_error(candidate: Candidate, target_radius: float) -> float:
    """Smallest relative mismatch using contour area or enclosing-circle radius.

    Both are geometrical candidates, not validated analytical ROI dimensions.
    """
    return min(abs(candidate.detector_radius - target_radius),
               abs(candidate.enclosing_radius - target_radius)) / target_radius


def radius_matches(candidate: Candidate, radius: float, tolerance_fraction: float) -> bool:
    """Use a user-chosen radius as a *candidate* search hint, not an exact fit."""
    return candidate_radius_error(candidate, radius) <= tolerance_fraction


def circle_is_plausible(candidate: Candidate) -> bool:
    """Avoid rescuing oblong handwriting merely because its radius matches.

    These deliberately permissive prototype cutoffs must be visually reviewed
    and validated on held-out images; they are not universal µPAD requirements.
    """
    return (candidate.circularity >= 0.45
            and candidate.axis_ratio >= 0.69
            and candidate.fill_ratio >= 0.55)


def select_candidates(
    candidates: Sequence[Candidate], radius: float, tolerance_fraction: float,
    image_shape: tuple[int, ...], baseline_ids: dict[str, str] | None = None,
    analytical_radius: float | None = None,
) -> tuple[list[ReviewEntry], int]:
    """Reconsider ALL contour candidates against a selected radius and tolerance.

    The original contour status is not final: previously rejected size outliers
    can be recovered if their shape is circular enough. No fixed grid or count.
    """
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("Target radius must be positive")
    if not math.isfinite(tolerance_fraction) or not 0.01 <= tolerance_fraction <= 1:
        raise ValueError("Candidate radius tolerance must be 1–100%")
    baseline_ids = baseline_ids or {}
    measurement_radius = radius if analytical_radius is None else analytical_radius
    if not math.isfinite(measurement_radius) or measurement_radius <= 0:
        raise ValueError("Analytical radius must be positive")
    viable = []
    size_matches = 0
    for candidate in candidates:
        if not radius_matches(candidate, radius, tolerance_fraction):
            continue
        size_matches += 1
        if not circle_is_plausible(candidate):
            continue
        x, y = round_pixel(candidate.center_x), round_pixel(candidate.center_y)
        try:
            roi_window(ROI("review_candidate", x, y, measurement_radius), image_shape)
        except ValueError:
            continue
        score = (candidate_radius_error(candidate, radius)
                 + 0.15 * max(0.0, 0.75 - candidate.circularity)
                 + 0.07 * max(0.0, 0.75 - candidate.fill_ratio))
        viable.append((score, candidate, x, y))

    # Avoid overlapping candidates for the same physical zone. This check is
    # deliberately conservative; visually inspect the overlay for omissions.
    selected: list[tuple[Candidate, int, int]] = []
    for _score, candidate, x, y in sorted(viable, key=lambda item: item[0]):
        if any(math.hypot(x - sx, y - sy) < radius * 0.85 for _, sx, sy in selected):
            continue
        selected.append((candidate, x, y))

    entries = []
    for candidate, x, y in sorted(selected, key=lambda item: (item[2], item[1])):
        prev_id = baseline_ids.get(candidate.candidate_id)
        entry_id = prev_id or f"ROI_{candidate.candidate_id}"
        recovered = prev_id is None
        entries.append(ReviewEntry(
            roi_id=entry_id, center_x=x, center_y=y,
            source="radius_recovered" if recovered else "radius_reselected",
            candidate_id=candidate.candidate_id,
            candidate_radius=candidate.detector_radius,
            qc_flags="recovered_by_radius_review" if recovered else "",
        ))
    return entries, size_matches


def baseline_entries(candidates: Sequence[Candidate]) -> list[ReviewEntry]:
    """Preserve original IDs and acceptances in automatic-radius mode."""
    return [ReviewEntry(
        roi_id=c.roi_id, center_x=round_pixel(c.center_x), center_y=round_pixel(c.center_y),
        source="original_detector", candidate_id=c.candidate_id,
        candidate_radius=c.detector_radius,
        qc_flags=";".join(c.flags),
    ) for c in candidates if c.roi_id]


def nearest_candidate(
    candidates: Sequence[Candidate], x: float, y: float,
    max_distance: float, excluded_ids: set[str] | None = None,
) -> Candidate | None:
    """Snap an approximate click to a measured candidate centroid when possible."""
    excluded_ids = excluded_ids or set()
    nearby = [c for c in candidates if c.candidate_id not in excluded_ids
              and math.hypot(c.center_x - x, c.center_y - y) <= max_distance]
    if not nearby:
        return None
    return min(nearby, key=lambda c: math.hypot(c.center_x - x, c.center_y - y))


def refine_click_hough(rgb: np.ndarray, x: int, y: int, radius: float) -> tuple[int, int] | None:
    """Find a nearby circular edge at the requested size, else return None.

    Grayscale edges are used ONLY for centre estimation; measurement stays on
    the original RGB data. A failure does not invent a 'detected' centre.
    """
    h, w = rgb.shape[:2]
    search = int(math.ceil(1.9 * radius))
    left, top = max(0, x - search), max(0, y - search)
    right, bottom = min(w, x + search + 1), min(h, y + search + 1)
    patch = rgb[top:bottom, left:right]
    if patch.shape[0] < 15 or patch.shape[1] < 15:
        return None
    gray = cv2.cvtColor(np.ascontiguousarray(patch), cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 1.5)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=max(12, int(radius * 0.65)), param1=95, param2=20,
        minRadius=max(4, int(radius * 0.65)), maxRadius=int(radius * 1.35),
    )
    if circles is None:
        return None
    options = []
    for cx, cy, cr in circles[0]:
        ox, oy = cx + left, cy + top
        distance = math.hypot(ox - x, oy - y)
        if distance > 0.70 * radius:
            continue
        options.append((distance / radius + abs(cr - radius) / radius * 0.65, ox, oy))
    if not options:
        return None
    _score, ox, oy = min(options)
    return int(round(ox)), int(round(oy))
