"""Coordinate mapping must be invariant under preview zoom and scrolling."""

from pathlib import Path
import sys

# The standalone GUI is a launcher script, not an installed Python package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from roi_test_gui import fit_zoom_for_viewport, source_pixel_from_world


def test_fit_zoom_never_upscales_and_fits_rectangular_images():
    zoom = fit_zoom_for_viewport(2560, 1752, 1000, 600)
    assert zoom <= (600 - 12) / 1752
    assert zoom * 2560 <= 1000
    assert fit_zoom_for_viewport(80, 80, 1000, 600) == 1.0


def test_mapping_at_native_zoom_with_canvas_scroll():
    # Suppose the canvas has been scrolled by x=700, y=400 virtual pixels.
    scroll_x, scroll_y = 700, 400
    px, py = 950, 780
    screen_x = px - scroll_x
    screen_y = py - scroll_y
    assert source_pixel_from_world(screen_x + scroll_x, screen_y + scroll_y,
                                   zoom=1, offset_x=0, offset_y=0,
                                   image_width=2568, image_height=1744) == (px, py)


def test_mapping_after_zoom_with_centered_fit_offsets():
    # A centered fitted image has blank space at the left/top, which must not
    # distort native ROI coordinates.
    x, y = 433, 950
    zoom = 0.4
    offset_x, offset_y = 80, 30
    wx, wy = offset_x + x * zoom, offset_y + y * zoom
    assert source_pixel_from_world(wx, wy, zoom=zoom,
                                   offset_x=offset_x, offset_y=offset_y,
                                   image_width=1728, image_height=2456) == (x, y)


def test_mapping_high_zoom_preserves_correct_pixel():
    for z in (0.21, 1, 1.25, 4, 8):
        x, y = 1245, 986
        assert source_pixel_from_world(x*z, y*z, zoom=z, offset_x=0, offset_y=0,
                                       image_width=3656, image_height=2528) == (x, y)


def test_mapping_outside_image_returns_none():
    params = dict(zoom=0.5, offset_x=100, offset_y=70,
                  image_width=1728, image_height=2456)
    assert source_pixel_from_world(99, 100, **params) is None
    assert source_pixel_from_world(100, 69, **params) is None
    assert source_pixel_from_world(100 + 1728*.5, 200, **params) is None
    assert source_pixel_from_world(110, 70 + 2456*.5, **params) is None
