"""ROI numbering by spatial columns, independent of an expected grid size.

After the user has oriented an image, group nearby x-coordinates into columns,
then enumerate each column from top to bottom, proceeding left to right.
This function orders accepted/manual ROIs; it NEVER affects zone detection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import median
from typing import Generic, Protocol, Sequence, TypeVar
import math

class SpatialROI(Protocol):
    roi_id: str
    center_x: int
    center_y: int


T = TypeVar("T", bound=SpatialROI)


@dataclass(frozen=True)
class NumberedROI(Generic[T]):
    """A renumbered dataclass entry and its original review identity."""
    entry: T
    previous_id: str
    column: int  # 1-based, left to right
    row: int  # 1-based, top to bottom within a column


def number_column_major(entries: Sequence[T], roi_radius: float) -> list[NumberedROI[T]]:
    """Enumerate arbitrary X by Y layouts without requiring X or Y up front.

    X centres within 0.9 times the analytical radius form a column. This is a
    documented heuristic (not a validation of true grid identity) and requires
    visual review on skewed or irregularly spaced images. Empty input is valid.
    """
    if not math.isfinite(roi_radius) or roi_radius <= 0:
        raise ValueError("Analytical ROI radius must be positive")
    threshold = max(2.0, 0.90 * roi_radius)
    groups: list[list[T]] = []
    for entry in sorted(entries, key=lambda e: (e.center_x, e.center_y, e.roi_id)):
        if not groups or abs(entry.center_x - median(e.center_x for e in groups[-1])) > threshold:
            groups.append([entry])
        else:
            groups[-1].append(entry)
    output = []
    index = 0
    for col, group in enumerate(groups, start=1):
        for row, entry in enumerate(sorted(group, key=lambda e: (e.center_y, e.center_x, e.roi_id)), start=1):
            index += 1
            output.append(NumberedROI(
                entry=replace(entry, roi_id=f"ROI_{index:03d}"),
                previous_id=entry.roi_id,
                column=col,
                row=row,
            ))
    return output
