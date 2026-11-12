"""Synthetic irregular layouts test centers and resistance to ink/size artifacts."""

import cv2
import numpy as np
import pytest

from micropad.detection import DetectionSettings, detect_rois, radius_consensus


@pytest.mark.parametrize("centers", [
    [(80, 100), (220, 130), (370, 90)],
    [(90, 90), (280, 150), (140, 330), (390, 350)],
    [(70, 80), (220, 110), (390, 70), (100, 260), (310, 240), (70, 420), (390, 410)],
])
def test_arbitrary_layouts_and_false_candidates(centers):
    rgb = np.full((500, 720, 3), 245, dtype=np.uint8)
    for center in centers:
        cv2.circle(rgb, center, 30, (240, 150, 200), -1)
    cv2.circle(rgb, (600, 320), 65, (240, 150, 200), -1)  # round size outlier
    cv2.circle(rgb, (550, 60), 8, (240, 150, 200), -1)   # small round ink-like artifact
    cv2.putText(rgb, "P4 20", (470, 175), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 40, 110), 3)
    before = rgb.copy()
    result = detect_rois(rgb)
    assert len(result.rois) == len(centers)
    assert {(r.center_x, r.center_y) for r in result.rois} == set(centers)
    assert abs(result.radius_median - 30) < 3
    assert len({r.radius for r in result.rois}) == 1
    assert any("radius_outlier" in c.flags for c in result.candidates)
    assert any("low_circularity" in c.flags for c in result.candidates)
    assert list(result.rois) == sorted(result.rois, key=lambda r: (r.center_y, r.center_x))
    np.testing.assert_array_equal(rgb, before)
    assert result == detect_rois(rgb)  # stable centers, IDs, flags and radius


def test_radius_cluster_cannot_be_set_by_large_and_small_artifacts():
    radii = np.array([100, 101, 99, 100, 98, 12, 14, 260])
    keep, median, _ = radius_consensus(radii, DetectionSettings())
    assert keep.tolist() == [True] * 5 + [False] * 3
    assert median == 100


def test_pale_contour_size_variation_is_within_explicit_tolerance():
    radii = np.array([105, 109, 113, 117, 119, 120, 121, 123, 124])
    keep, median, _ = radius_consensus(radii, DetectionSettings())
    assert keep.all()
    assert median == 119


def test_no_circles_returns_auditable_failure():
    result = detect_rois(np.full((300, 400, 3), 255, dtype=np.uint8))
    assert result.rois == ()
    assert result.roi_radius is None
    assert result.warnings


def test_margin_and_radius_override_do_not_change_detection_centers():
    rgb = np.full((200, 400, 3), 245, dtype=np.uint8)
    for center in [(70, 80), (190, 100), (310, 80)]:
        cv2.circle(rgb, center, 23, (240, 150, 200), -1)
    full, inner, fixed = detect_rois(rgb), detect_rois(rgb, radius_factor=0.8), detect_rois(rgb, roi_radius=15)
    assert [(r.center_x, r.center_y) for r in full.rois] == [(r.center_x, r.center_y) for r in inner.rois]
    assert len(full.rois) == len(inner.rois) == len(fixed.rois) == 3
    assert inner.roi_radius < full.roi_radius
    assert fixed.roi_radius == 15


@pytest.mark.parametrize("settings", [{"blur_size": 4}, {"saturation_min": -1},
                                      {"min_radius_fraction": 0.3, "max_radius_fraction": 0.1},
                                      {"min_consistent": 0}])
def test_invalid_settings(settings):
    with pytest.raises(ValueError):
        DetectionSettings(**settings)
