"""Lossless right-angle orientation of the decoded RGB raster.

Each action is applied in the order entered by the user. No interpolation,
normalization, JPEG re-encoding, or modification of the source file occurs.
ROI coordinates after an action refer to the displayed (oriented) pixel grid.
"""

from __future__ import annotations

import numpy as np

ACTIONS = ("cw", "ccw", "flip_h", "flip_v")


def apply_orientation(rgb: np.ndarray, operations: list[str] | tuple[str, ...]) -> np.ndarray:
    """Apply exact 90-degree rotations and flips to an RGB image in memory."""
    oriented = rgb
    for operation in operations:
        if operation == "cw":
            oriented = np.rot90(oriented, -1)
        elif operation == "ccw":
            oriented = np.rot90(oriented, 1)
        elif operation == "flip_h":
            oriented = np.flip(oriented, axis=1)
        elif operation == "flip_v":
            oriented = np.flip(oriented, axis=0)
        else:
            raise ValueError(f"Unknown orientation operation: {operation}")
    oriented = np.ascontiguousarray(oriented)
    oriented.setflags(write=False)
    return oriented


def transformed_dimensions(width: int, height: int, operations: list[str] | tuple[str, ...]) -> tuple[int, int]:
    """Return width/height after the same orientation operations."""
    for operation in operations:
        if operation not in ACTIONS:
            raise ValueError(f"Unknown orientation operation: {operation}")
        if operation in ("cw", "ccw"):
            width, height = height, width
    return width, height


def to_original_point(x: int, y: int, source_width: int, source_height: int,
                      operations: list[str] | tuple[str, ...]) -> tuple[int, int]:
    """Invert the ordered transforms for an integer centre in oriented pixels."""
    shape_before = []
    width, height = source_width, source_height
    for operation in operations:
        if operation not in ACTIONS:
            raise ValueError(f"Unknown orientation operation: {operation}")
        shape_before.append((width, height))
        if operation in ("cw", "ccw"):
            width, height = height, width
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError("Transformed ROI centre lies outside the oriented image")
    for operation, (old_width, old_height) in reversed(list(zip(operations, shape_before))):
        if operation == "cw":
            x, y = y, old_height - 1 - x
        elif operation == "ccw":
            x, y = old_width - 1 - y, x
        elif operation == "flip_h":
            x = old_width - 1 - x
        elif operation == "flip_v":
            y = old_height - 1 - y
    return int(x), int(y)


def orientation_description(operations: list[str] | tuple[str, ...]) -> str:
    if not operations:
        return "Original orientation"
    labels = {"cw": "Rotate 90° Right", "ccw": "Rotate 90° Left",
              "flip_h": "Flip Horizontal", "flip_v": "Flip Vertical"}
    return " → ".join(labels[op] for op in operations)
