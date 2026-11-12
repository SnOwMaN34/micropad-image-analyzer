"""Tests for radius-based candidate recovery and manual-review helpers."""

import numpy as np
import pytest

from micropad.detection import Candidate
from micropad.review import (
    candidate_radius_error, circle_is_plausible, nearest_candidate,
    radius_matches, select_candidates,
)


def make_candidate(candidate_id="C001", x=200, y=200, area_radius=112.0,
                   enclosing_radius=121.0, circularity=.92, fill_ratio=.83,
                   axis_ratio=.96, flags=("radius_outlier",), roi_id=""):
    return Candidate(candidate_id, float(x), float(y), float(area_radius),
                     float(enclosing_radius), 3.14159 * area_radius ** 2,
                     circularity, fill_ratio, axis_ratio, flags, roi_id)


def test_size_outliers_can_be_recovered_without_a_grid():
    cands = [make_candidate("C001", x=120, y=150),
             make_candidate("C002", x=500, y=150, area_radius=118),
             make_candidate("C003", x=880, y=150, area_radius=24, enclosing_radius=35)]
    selected, matches = select_candidates(cands, 100, .25, (1200, 1200, 3))
    assert matches == 2
    assert [e.candidate_id for e in selected] == ["C001", "C002"]
    assert all(e.source == "radius_recovered" for e in selected)


def test_handwriting_like_shapes_are_not_auto_accepted():
    cands = [make_candidate("C001", x=300, y=350, circularity=.18,
                            fill_ratio=.29, axis_ratio=.20)]
    selected, matches = select_candidates(cands, 100, .30, (1000, 1000, 3))
    assert matches == 1
    assert selected == []


def test_overlapping_duplicate_candidates_not_counted_twice():
    candidates = [make_candidate("C001", 250, 250),
                  make_candidate("C002", 258, 255)]
    selected, _ = select_candidates(candidates, 110, .25, (1000, 1000, 3))
    assert len(selected) == 1


def test_original_roi_id_stays_the_same_if_candidate_is_reselected():
    selected, _ = select_candidates([make_candidate("C008")], 100, .25,
                                    (1000, 1000, 3), {"C008": "ROI_004"})
    assert selected[0].roi_id == "ROI_004"


def test_nearest_candidate_snaps_rough_click_to_candidate_centroid():
    candidates = [make_candidate("C001", x=200, y=200),
                  make_candidate("C002", x=500, y=400)]
    assert nearest_candidate(candidates, 225, 210, 50).candidate_id == "C001"
    assert nearest_candidate(candidates, 225, 210, 50, {"C001"}) is None


def test_out_of_bounds_roi_is_excluded():
    selected, _ = select_candidates([make_candidate("C001", x=30, y=30)],
                                    100, .25, (1000, 1000, 3))
    assert selected == []


def test_invalid_radius_tolerance_is_rejected():
    with pytest.raises(ValueError):
        select_candidates([], 100, 0, (1000, 1000, 3))
    with pytest.raises(ValueError):
        select_candidates([], -20, .25, (1000, 1000, 3))


def test_candidate_search_and_analytical_radius_can_differ():
    # Outer backing-paper radius may be ~140 px while the coloured inner region
    # must still be measured with a 100-px analytical ROI.
    candidate = make_candidate("C099", 300, 300, area_radius=139, enclosing_radius=149)
    selected, matches = select_candidates([candidate], 140, .12, (1000, 1000, 3),
                                          analytical_radius=100)
    assert matches == 1
    assert len(selected) == 1
    assert selected[0].to_roi(100).radius == 100
