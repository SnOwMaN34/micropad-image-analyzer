"""One-time, idempotent migration of result paths for frozen Windows builds.

Run from repository root:
    .\\.venv\\Scripts\\python.exe scripts\\apply_packaging_changes.py

It changes only runtime paths and the default file-dialog directory, not ROI
selection, calibration calculations, or image processing.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

REPLACEMENTS: dict[str, list[tuple[str, str]]] = {
    "scripts/roi_test_gui.py": [
        (
            'PROJECT_ROOT = Path(__file__).resolve().parents[1]\n'
            'sys.path.insert(0, str(PROJECT_ROOT / "src"))\n'
            'sys.path.insert(0, str(PROJECT_ROOT / "scripts"))',
            'SOURCE_ROOT = Path(__file__).resolve().parents[1]\n'
            'sys.path.insert(0, str(SOURCE_ROOT / "src"))\n'
            'sys.path.insert(0, str(SOURCE_ROOT / "scripts"))\n'
            'from app_paths import working_root\n'
            'PROJECT_ROOT = working_root()',
        ),
        (
            '        initial = DATA_ROOT if DATA_ROOT.is_dir() else PROJECT_ROOT',
            '        documents = Path.home() / "Documents"\n'
            '        initial = (DATA_ROOT if DATA_ROOT.is_dir() else\n'
            '                   documents if documents.is_dir() else Path.home())',
        ),
        (
            '            self.status.set("No images found in data/lab_validated/. Use Browse... to select an image elsewhere.")',
            '            self.status.set(\n'
            '                "No images are bundled. Use Browse... to select a laboratory scan."\n'
            '                if getattr(sys, "frozen", False) else\n'
            '                "No images found in data/lab_validated/. Use Browse... to select an image elsewhere."\n'
            '            )',
        ),
    ],
    "scripts/analyze_image.py": [
        (
            'PROJECT_ROOT = Path(__file__).resolve().parents[1]\n'
            'sys.path.insert(0, str(PROJECT_ROOT / "src"))',
            'SOURCE_ROOT = Path(__file__).resolve().parents[1]\n'
            'sys.path.insert(0, str(SOURCE_ROOT / "src"))\n'
            'from app_paths import working_root\n'
            'PROJECT_ROOT = working_root()',
        ),
    ],
}


def main() -> int:
    if not (ROOT / "scripts" / "app_paths.py").is_file():
        print("Missing scripts/app_paths.py. Copy the complete packaging toolkit first.")
        return 2
    plans = {}
    for name, replacements in REPLACEMENTS.items():
        path = ROOT / name
        if not path.is_file():
            print(f"Missing source file: {name}")
            return 2
        content = path.read_text(encoding="utf-8")
        original = content
        for old, new in replacements:
            if new in content:
                continue
            if content.count(old) != 1:
                print(f"Cannot safely patch {name}: expected source fragment missing or ambiguous. No files changed.")
                print("Check that this is the current GitHub version and that no other patch already changed it.")
                return 2
            content = content.replace(old, new, 1)
        plans[path] = (original, content)
    for path, (before, after) in plans.items():
        if before != after:
            path.write_text(after, encoding="utf-8")
            print(f"Updated: {path.relative_to(ROOT)}")
        else:
            print(f"Already updated: {path.relative_to(ROOT)}")
    print("Done. Original image processing and calibration logic are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
