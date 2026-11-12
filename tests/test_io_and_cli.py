"""Lossless fixtures exercise decoding, provenance and manual extraction end to end."""

import csv
import hashlib
import json

import cv2
import numpy as np
from PIL import Image
import pytest

from analyze_image import build_parser, run
from image_io import load_rgb, read_manual_centers
from reporting import create_output_directory


def test_opencv_bgr_conversion_and_immutable_source(tmp_path):
    path = tmp_path / "rgb_fixture.png"
    rgb = np.zeros((8, 9, 3), dtype=np.uint8)
    rgb[:] = (13, 97, 221)
    Image.fromarray(rgb).save(path)
    before = path.read_bytes()
    actual, metadata = load_rgb(path)
    np.testing.assert_array_equal(actual, rgb)
    assert not actual.flags.writeable
    assert metadata["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert path.read_bytes() == before


def test_uint16_decode_does_not_rescale(tmp_path):
    path = tmp_path / "native16.png"
    bgr = np.full((10, 10, 3), (60000, 20000, 1000), dtype=np.uint16)
    ok, encoded = cv2.imencode(".png", bgr)
    assert ok
    path.write_bytes(encoded.tobytes())
    rgb, metadata = load_rgb(path)
    assert rgb.dtype == np.uint16
    assert rgb[0, 0].tolist() == [1000, 20000, 60000]
    assert metadata["bits_per_channel"] == 16


@pytest.mark.parametrize("mode", ["L", "RGBA", "CMYK"])
def test_unsupported_image_modes_rejected(tmp_path, mode):
    path = tmp_path / ("unsupported.jpg" if mode == "CMYK" else "unsupported.png")
    Image.new(mode, (10, 10)).save(path)
    with pytest.raises(ValueError, match="RGB mode"):
        load_rgb(path)


def test_exif_orientation_is_not_applied(tmp_path):
    path = tmp_path / "orientation.jpg"
    rgb = np.zeros((8, 12, 3), dtype=np.uint8)
    rgb[:4] = (200, 20, 30)
    exif = Image.Exif()
    exif[274] = 3
    Image.fromarray(rgb).save(path, exif=exif)
    actual, metadata = load_rgb(path)
    assert actual.shape == (8, 12, 3)
    assert actual[0, 0, 0] > actual[-1, 0, 0]
    assert metadata["exif_orientation"] == 3


def test_output_path_is_confined_and_never_reused(tmp_path):
    results = tmp_path / "results"
    out = create_output_directory(results / "run", results)
    assert out.exists()
    with pytest.raises(FileExistsError):
        create_output_directory(out, results)
    for invalid in (results, tmp_path / "data", results / ".." / "data"):
        with pytest.raises(ValueError):
            create_output_directory(invalid, results)


@pytest.mark.parametrize("contents", [
    "roi_id,center_x,center_y\na,1.5,2\n",
    "roi_id,center_x,center_y\na,1,2\na,3,4\n",
    "roi_id,center_x,center_y\na,1,2\nb,1,2\n",
    "x,y\n1,2\n", "roi_id,center_x,center_y\n",
])
def test_bad_manual_center_files(tmp_path, contents):
    path = tmp_path / "centers.csv"
    path.write_text(contents)
    with pytest.raises(ValueError):
        read_manual_centers(path, 2)


def test_manual_cli_pipeline_and_reproducibility(tmp_path, monkeypatch):
    # Redirect the project root for synthetic outputs; experimental data are unnecessary.
    import analyze_image
    monkeypatch.setattr(analyze_image, "PROJECT_ROOT", tmp_path)
    image = tmp_path / "fixture.png"
    rgb = np.full((40, 60, 3), (19, 83, 211), dtype=np.uint8)
    Image.fromarray(rgb).save(image)
    centers = tmp_path / "manual.csv"
    centers.write_text("roi_id,center_x,center_y\nfixed_b,10,10\nfixed_a,40,25\n")
    args = build_parser().parse_args([str(image), "--centers-csv", str(centers), "--roi-radius", "5",
                                      "--reference-area", "31428", "--output", str(tmp_path / "results" / "one")])
    output, report = run(args)
    rows = list(csv.DictReader((output / "measurements.csv").open()))
    assert [r["roi_id"] for r in rows] == ["fixed_b", "fixed_a"]
    assert all(float(r["mean_R"]) == 19 and float(r["mean_G"]) == 83 and float(r["mean_B"]) == 211 for r in rows)
    assert report["roi_count"] == 2
    assert report["measurement"]["blank_correction"] is False
    assert report["area_comparison"]["actual_roi_pixel_count"] == 81
    assert (output / "roi_overlay.png").is_file()
    assert json.loads((output / "run.json").read_text())["source"]["source_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    args.output = tmp_path / "results" / "two"
    second, _ = run(args)
    assert (output / "measurements.csv").read_bytes() == (second / "measurements.csv").read_bytes()
    with pytest.raises(FileExistsError):
        run(args)
