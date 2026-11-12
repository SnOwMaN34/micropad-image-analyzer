"""Regression checks for RGB ordering, deterministic masks and invalid ROIs."""

import numpy as np
import pytest

from micropad.measurement import measure_rois
from micropad.roi import ROI, circle_mask, round_pixel


def test_mask_boundary_and_imagej_area_diagnostic():
    assert circle_mask(2).sum() == 13  # origin, eight adjacent pixels, four axial boundary pixels
    assert circle_mask(100).sum() == 31417
    assert circle_mask(100, center_offset=0.5).sum() == 31428
    assert round_pixel(10.5) == 11


@pytest.mark.parametrize("color,channel,expected", [
    ((255, 0, 0), "R", 255), ((0, 255, 0), "G", 255), ((0, 0, 255), "B", 255),
    ((17, 83, 211), "G", 83),
])
def test_rgb_means_and_channel_selection(color, channel, expected):
    rgb = np.full((15, 20, 3), color, dtype=np.uint8)
    before = rgb.copy()
    rgb.setflags(write=False)
    rows = measure_rois(rgb, [ROI("a", 4, 5, 2), ROI("b", 14, 9, 2)], channel)
    assert all([r["mean_R"], r["mean_G"], r["mean_B"]] == list(color) for r in rows)
    assert all(r["selected_mean"] == expected for r in rows)
    assert {r["pixel_count"] for r in rows} == {13}
    np.testing.assert_array_equal(rgb, before)


def test_only_mask_pixels_are_measured():
    rgb = np.zeros((9, 9, 3), dtype=np.uint8)
    rgb[2:7, 2:7] = (200, 100, 50)
    rgb[2, 2] = (255, 255, 255)  # square corner outside radius-2 circle
    row = measure_rois(rgb, [ROI("a", 4, 4, 2)])[0]
    assert (row["mean_R"], row["mean_G"], row["mean_B"]) == (200, 100, 50)


def test_uint16_measurement_preserves_values():
    rgb = np.full((9, 9, 3), (1000, 20000, 60000), dtype=np.uint16)
    assert measure_rois(rgb, [ROI("a", 4, 4, 2)])[0]["mean_B"] == 60000


@pytest.mark.parametrize("radius", [0, -1, float("nan"), float("inf")])
def test_invalid_radius(radius):
    with pytest.raises(ValueError):
        circle_mask(radius)
    with pytest.raises(ValueError):
        ROI("a", 5, 5, radius)


def test_subpixel_measurement_centers_rejected_explicitly():
    with pytest.raises(ValueError, match="integer"):
        ROI("a", 5.5, 5, 2)


def test_clipped_duplicate_empty_and_unequal_rois_fail():
    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    for rois in ([], [ROI("a", 0, 0, 2)],
                 [ROI("a", 3, 3, 1), ROI("a", 7, 7, 1)],
                 [ROI("a", 3, 3, 1), ROI("b", 7, 7, 2)]):
        with pytest.raises(ValueError):
            measure_rois(rgb, rois)


def test_overlap_is_flagged_and_preserved():
    rgb = np.ones((20, 20, 3), dtype=np.uint8)
    rows = measure_rois(rgb, [ROI("a", 5, 5, 3), ROI("b", 7, 5, 3)])
    assert len(rows) == 2
    assert all(r["qc_flags"] == "overlapping_roi" for r in rows)


@pytest.mark.parametrize("array", [np.zeros((4, 4)), np.zeros((4, 4, 4), dtype=np.uint8),
                                  np.zeros((4, 4, 3), dtype=float)])
def test_invalid_rgb_arrays(array):
    with pytest.raises(ValueError):
        measure_rois(array, [ROI("a", 2, 2, 1)])
