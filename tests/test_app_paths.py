"""Regression tests for results placement in source and portable builds."""

from pathlib import Path
import sys

from app_paths import working_root
import app_paths


def test_source_results_still_use_repository(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert working_root() == Path(app_paths.__file__).resolve().parents[1]


def test_frozen_results_resolve_beside_executable(monkeypatch, tmp_path):
    exe = tmp_path / "portable" / "MicroPADImageAnalyzer.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "other-profile"))
    monkeypatch.setenv("MICROPAD_DATA_DIR", str(tmp_path / "old-override"))
    assert working_root() == exe.parent.resolve()
    assert (working_root() / "results") == exe.parent / "results"


def test_frozen_path_does_not_depend_on_cwd(monkeypatch, tmp_path):
    exe = tmp_path / "dist" / "MicroPADImageAnalyzer.exe"
    other_dir = tmp_path / "unrelated"
    other_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.chdir(other_dir)
    assert working_root() == exe.parent.resolve()
