"""Tests for Windows portable ZIP packaging; use synthetic files only."""

import hashlib
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_release import create_release_zip


def _test_release(tmp_path):
    app = tmp_path / "MicroPADImageAnalyzer_20261112_090422"
    (app / "_internal").mkdir(parents=True)
    (app / "results").mkdir()
    (app / "MicroPADImageAnalyzer.exe").write_bytes(b"synthetic dummy (not runnable)")
    (app / "_internal" / "base_library.zip").write_bytes(b"synthetic data")
    (app / "results" / "README.txt").write_text("Put local results here", encoding="utf-8")
    return app


def test_zip_is_complete_verified_and_relocatable(tmp_path):
    app = _test_release(tmp_path)
    zip_path, hash_value = create_release_zip(app, delays=(0,))
    assert zip_path.exists()
    assert (zip_path.with_name(zip_path.name + ".sha256.txt")).exists()
    assert hash_value == hashlib.sha256(zip_path.read_bytes()).hexdigest().upper()
    with zipfile.ZipFile(zip_path) as arc:
        assert arc.testzip() is None
        names = set(arc.namelist())
        assert app.name + "/MicroPADImageAnalyzer.exe" in names
        assert app.name + "/_internal/base_library.zip" in names
        assert app.name + "/results/README.txt" in names
        assert app.name + "/results/" in names
    assert not (app.parent / (app.name + ".zip.incomplete")).exists()


def test_refuse_to_include_measurement_results(tmp_path):
    app = _test_release(tmp_path)
    (app / "results" / "run123").mkdir()
    (app / "results" / "run123" / "measurements.csv").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="measurement data"):
        create_release_zip(app, delays=(0,))
    assert not (app.parent / (app.name + ".zip")).exists()


def test_reject_incomplete_application_directory(tmp_path):
    app = tmp_path / "MicroPADImageAnalyzer_20261112_090422"
    app.mkdir()
    (app / "MicroPADImageAnalyzer.exe").write_bytes(b"exe")
    with pytest.raises(ValueError, match="_internal"):
        create_release_zip(app, delays=(0,))
