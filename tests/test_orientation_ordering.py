"""Grid numbering and lossless orientation of analytical input pixels."""

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from micropad.orientation import apply_orientation, to_original_point, transformed_dimensions
from micropad.ordering import number_column_major


@dataclass(frozen=True)
class Entry:
    roi_id: str
    center_x: int
    center_y: int


def test_column_major_unsorted_3_by_2():
    entries = [Entry("B", 201, 111), Entry("C", 101, 10), Entry("A", 102, 110),
               Entry("D", 301, 10), Entry("E", 202, 10), Entry("F", 302, 112)]
    result = number_column_major(entries, 32)
    assert [item.previous_id for item in result] == ["C", "A", "E", "B", "D", "F"]
    assert [item.entry.roi_id for item in result] == [f"ROI_{i:03d}" for i in range(1, 7)]
    assert [(item.column, item.row) for item in result] == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)]


def test_nongrid_partial_column_is_not_dropped():
    result = number_column_major([Entry("x", 5, 8), Entry("y", 5, 40), Entry("z", 80, 20)], 10)
    assert len(result) == 3
    assert [v.previous_id for v in result] == ["x", "y", "z"]


def test_no_fixed_matrix_dimensions():
    entries = [Entry(str(y * 5 + x), x * 120 + (y % 2) * 7, y * 100)
               for y in range(4) for x in range(5)]
    numbered = number_column_major(entries[::-1], 45)
    assert len(numbered) == 20
    assert len({v.column for v in numbered}) == 5
    assert all(len([v for v in numbered if v.column == col]) == 4 for col in range(1, 6))


@pytest.mark.parametrize("ops", [[], ["cw"], ["ccw"], ["flip_h"], ["flip_v"],
                                    ["cw", "flip_h"], ["flip_h", "cw"],
                                    ["cw", "cw"], ["flip_v", "ccw", "flip_h"]])
def test_all_orientation_actions_exact_and_invertible(ops):
    source = np.arange(3 * 4 * 3, dtype=np.uint8).reshape((3, 4, 3))
    copy = source.copy()
    transformed = apply_orientation(source, ops)
    assert np.array_equal(source, copy)
    assert not transformed.flags.writeable
    width, height = transformed_dimensions(4, 3, ops)
    assert transformed.shape == (height, width, 3)
    for y in range(height):
        for x in range(width):
            ox, oy = to_original_point(x, y, 4, 3, ops)
            assert np.array_equal(transformed[y, x], source[oy, ox])


def test_order_after_rotation_changes_to_visible_columns():
    source = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    rotated = apply_orientation(source, ["cw"])
    assert np.array_equal(rotated[0, 0], source[1, 0])


def test_unknown_transform_fails():
    with pytest.raises(ValueError):
        apply_orientation(np.zeros((2, 2, 3), dtype=np.uint8), ["resize"])

@pytest.mark.parametrize("ops", [["cw"], ["ccw"], ["flip_h"], ["flip_v"],
                                    ["cw", "flip_h"], ["flip_v", "cw"]])
def test_circular_roi_mean_unchanged_by_lossless_orientation(ops):
    rng = np.random.default_rng(101)
    rgb = rng.integers(0, 256, size=(13, 17, 3), dtype=np.uint8)
    transformed = apply_orientation(rgb, ops)
    yy, xx = np.mgrid[-2:3, -2:3]
    mask = xx * xx + yy * yy <= 4
    ox, oy = 8, 6
    expected = rgb[oy-2:oy+3, ox-2:ox+3][mask].mean(axis=0)
    found = []
    for ty in range(2, transformed.shape[0] - 2):
        for tx in range(2, transformed.shape[1] - 2):
            if to_original_point(tx, ty, 17, 13, ops) == (ox, oy):
                found.append(transformed[ty-2:ty+3, tx-2:tx+3][mask].mean(axis=0))
    assert len(found) == 1
    np.testing.assert_array_equal(found[0], expected)
