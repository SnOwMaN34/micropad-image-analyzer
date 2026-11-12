"""Runtime file locations for µPAD Image Analyzer.

The source checkout uses its existing repository data/results directories.
The portable PyInstaller application stores results beside its executable,
not in the _internal bundle directory or the current working directory.
"""

from __future__ import annotations

from pathlib import Path
import sys


def working_root() -> Path:
    """Return the root containing the local ``results`` subdirectory.

    The caller creates ``results`` when saving. For portable distributions
    the directory containing the EXE must be writable by the user. This
    function deliberately does not silently redirect files to AppData.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
