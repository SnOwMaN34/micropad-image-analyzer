"""Regression tests for right-click dismissal of unselected contour candidates."""

from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from roi_test_gui import RoiTestApp
from micropad.review import ReviewEntry
from micropad.detection import Candidate

def candidate(candidate_id, x, y, radius=30):
    return Candidate(candidate_id, float(x), float(y), radius, radius,
                     2500, .95, .8, .95, (), "")

def app_with_candidates(candidates, accepted=()):
    app = object.__new__(RoiTestApp)
    app.current_detection = SimpleNamespace(candidates=tuple(candidates))
    app.current_entries = list(accepted)
    app.manual_additions = {}
    app.manual_removed = set()
    app.dismissed_candidates = set()
    app.change_log = []
    app.undo_stack = []
    app.chosen_radius = lambda: 20
    app._image_pixel = lambda event: (event.x, event.y)
    app.refresh_preview = lambda: None
    return app

def test_dismiss_orange_candidate_without_accepted_rois():
    app = app_with_candidates([candidate("C001", 100, 100)])
    app.remove_at_click(SimpleNamespace(x=100, y=100))
    assert app.dismissed_candidates == {"C001"}
    assert app.change_log[-1]["action"] == "dismiss_candidate"
    app.undo_edit()
    assert not app.dismissed_candidates
    assert not app.change_log

def test_right_click_existing_green_roi_preserves_old_remove_behavior():
    green = ReviewEntry("ROI_001", 100, 100, "original_detector", "C001")
    app = app_with_candidates([candidate("C001", 100, 100)], [green])
    app.remove_at_click(SimpleNamespace(x=100, y=100))
    assert app.manual_removed == {"ROI_001"}
    assert not app.dismissed_candidates

def test_green_then_orange_can_be_removed_in_two_clicks():
    green = ReviewEntry("ROI_001", 100, 100, "original_detector", "C001")
    app = app_with_candidates([candidate("C001", 100, 100)], [green])
    def refresh():
        app.current_entries = [entry for entry in (green,) if entry.roi_id not in app.manual_removed]
    app.refresh_preview = refresh
    app.remove_at_click(SimpleNamespace(x=100, y=100))
    app.remove_at_click(SimpleNamespace(x=100, y=100))
    assert app.manual_removed == {"ROI_001"}
    assert app.dismissed_candidates == {"C001"}
    app.undo_edit()
    assert app.manual_removed == {"ROI_001"}
    assert not app.dismissed_candidates
    app.undo_edit()
    assert not app.manual_removed
    assert app.current_entries == [green]

def test_click_near_green_does_not_dismiss_distant_orange_candidate():
    green = ReviewEntry("ROI_001", 100, 100, "original_detector", "C001")
    app = app_with_candidates([candidate("C001", 100, 100),
                               candidate("C002", 130, 100, 30)], [green])
    app.remove_at_click(SimpleNamespace(x=102, y=100))
    assert app.manual_removed == {"ROI_001"}
    assert not app.dismissed_candidates

def test_reset_restores_dismissed_candidates():
    app = app_with_candidates([candidate("C002", 200, 200)])
    app.remove_at_click(SimpleNamespace(x=200, y=200))
    app.reset_edits()
    assert not app.dismissed_candidates
    app.undo_edit()
    assert app.dismissed_candidates == {"C002"}


def test_dismissed_candidate_is_not_snapped_on_left_click(monkeypatch):
    import numpy as np
    import roi_test_gui as gui
    app = app_with_candidates([candidate("C001", 100, 100)])
    app.rgb = np.zeros((400, 400, 3), dtype=np.uint8)
    app.detection = SimpleNamespace(candidates=tuple(app.current_detection.candidates))
    app.dismissed_candidates.add("C001")
    app._candidate_search_radius = lambda: 20
    app.manual_index = 0
    monkeypatch.setattr(gui, "refine_click_hough", lambda *args: (101, 102))
    app.add_at_click(SimpleNamespace(x=100, y=100))
    assert len(app.manual_additions) == 1
    new_entry = next(iter(app.manual_additions.values()))
    assert new_entry.source == "manual_hough"
    assert new_entry.candidate_id == ""
    assert app.dismissed_candidates == {"C001"}


def test_radius_refresh_does_not_reselect_dismissed_candidate(monkeypatch):
    import numpy as np
    import roi_test_gui as gui
    from types import SimpleNamespace as NS
    app = app_with_candidates([candidate("C001", 100, 100),
                               candidate("C002", 200, 200)])
    app.detection = NS(candidates=tuple(app.current_detection.candidates), roi_radius=20)
    app.rgb = np.zeros((400, 400, 3), dtype=np.uint8)
    app.dismissed_candidates.add("C001")
    app._candidate_search_radius = lambda: 20
    app._tolerance = lambda: 0.25
    app._refresh_area_comparison = lambda: None
    app._numbering_radius = lambda: 20
    app.radius_mode = NS(get=lambda: "manual")
    app.match_radius_follows_roi = NS(get=lambda: True)
    app.run_button = NS(config=lambda **kw: None)
    app.selection_info = NS(set=lambda value: None)
    app.status = NS(set=lambda value: None)
    app._draw_preview = lambda: None
    app.refresh_preview = gui.RoiTestApp.refresh_preview.__get__(app, gui.RoiTestApp)
    monkeypatch.setattr(gui, "detect_rois", lambda *args, **kwargs: app.current_detection)
    captured = []
    def fake_select(candidates, *args, **kwargs):
        captured.extend(c.candidate_id for c in candidates)
        return [], 0
    monkeypatch.setattr(gui, "select_candidates", fake_select)
    app.refresh_preview()
    assert captured == ["C002"]


def test_dismissed_candidate_is_not_drawn_on_saved_overlay(tmp_path):
    import numpy as np
    from PIL import Image
    app = app_with_candidates([candidate("C001", 100, 100, 30)])
    app.rgb = np.full((200, 200, 3), 180, dtype=np.uint8)
    app.dismissed_candidates.add("C001")
    app.channel = SimpleNamespace(get=lambda: "G")
    app._save_review_overlay(tmp_path, 20, [])
    saved = np.asarray(Image.open(tmp_path / "reviewed_candidate_overlay.png"))
    assert np.all(saved == 180)
    assert (tmp_path / "selected_channel_roi_overlay.png").exists()
