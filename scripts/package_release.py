"""Create and verify a portable Windows release ZIP from an existing EXE folder.

This is a packaging utility, not a scientific analysis module.
Usage: .\\.venv\\Scripts\\python.exe scripts\\package_release.py .\\release\\MicroPADImageAnalyzer_YYYYMMDD_HHMMSS

The archive is built outside the release folder and published atomically only
when completed and CRC-verified. It retries temporary Windows file locks.
Research data under results/ are NEVER included (README.txt is allowed).
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import time
import zipfile


RETRY_DELAYS_SECONDS = (0, 2, 4, 7, 10, 15)


def release_files(folder: Path) -> list[Path]:
    """Select release files, refusing to accidentally include raw measurements."""
    if not folder.is_dir():
        raise ValueError(f"Release folder does not exist: {folder}")
    if not (folder / "MicroPADImageAnalyzer.exe").is_file():
        raise ValueError("Missing MicroPADImageAnalyzer.exe in the release folder")
    if not (folder / "_internal").is_dir():
        raise ValueError("Missing _internal folder; the whole one-directory build is required")
    files = sorted((p for p in folder.rglob("*") if p.is_file()), key=lambda p: str(p).casefold())
    for file in files:
        relative = file.relative_to(folder)
        if relative.parts and relative.parts[0].casefold() == "results":
            if relative.as_posix().casefold() != "results/readme.txt":
                raise ValueError(
                    f"The release folder contains measurement data: {relative}. "
                    "Do not distribute laboratory results. Create a clean release folder or move results "
                    "out of this folder before packaging."
                )
    return files


def create_release_zip(folder: Path, *, delays: tuple[int, ...] = RETRY_DELAYS_SECONDS) -> tuple[Path, str]:
    """Write ZIP+SHA256 after successful read and full archive integrity check."""
    folder = Path(folder).resolve()
    files = release_files(folder)
    output_zip = folder.with_name(folder.name + ".zip")
    partial_zip = output_zip.with_name(output_zip.name + ".incomplete")
    checksum_path = output_zip.with_name(output_zip.name + ".sha256.txt")

    if not files:
        raise ValueError("Release folder does not contain any files")

    last_error: OSError | None = None
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            print(f"Retry {attempt}/{len(delays)} after {delay}s (temporary file lock)...", flush=True)
            time.sleep(delay)
        try:
            partial_zip.unlink(missing_ok=True)
            with zipfile.ZipFile(partial_zip, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as archive:
                # Keep the visible results folder even if nothing has been saved yet.
                archive.writestr(f"{folder.name}/results/", b"")
                for file in files:
                    relative = file.relative_to(folder).as_posix()
                    archive.write(file, arcname=f"{folder.name}/{relative}")

            with zipfile.ZipFile(partial_zip, "r") as archive:
                failing_member = archive.testzip()
                if failing_member is not None:
                    raise ValueError(f"CRC validation failed for ZIP member {failing_member}")
                archive_files = [name for name in archive.namelist() if not name.endswith("/")]
                if len(archive_files) != len(files):
                    raise ValueError("ZIP validation found an unexpected file count")
                if f"{folder.name}/MicroPADImageAnalyzer.exe" not in archive.namelist():
                    raise ValueError("ZIP validation failed: EXE missing")

            digest = hashlib.sha256()
            with partial_zip.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            checksum = digest.hexdigest().upper()
            os.replace(partial_zip, output_zip)
            checksum_path.write_text(f"{checksum}  {output_zip.name}\n", encoding="ascii")
            print(f"ZIP OK: {output_zip}")
            print(f"Files archived (excluding directory markers): {len(files)}")
            print(f"SHA-256: {checksum}")
            return output_zip, checksum
        except (PermissionError, OSError) as exc:
            last_error = exc
            print(f"Attempt {attempt}/{len(delays)}: file unavailable: {exc}", flush=True)
            try:
                partial_zip.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt == len(delays):
                break
        except Exception:
            try:
                partial_zip.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    raise OSError(
        f"Could not package the release folder because a file remained locked: {last_error}. "
        "Close MicroPADImageAnalyzer.exe, wait for antivirus/indexing to release the file, "
        "then rerun package_release.py. The EXE folder is unchanged."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Zip and verify an already-built portable application")
    parser.add_argument("release_folder", type=Path, help="Existing release folder containing EXE and _internal")
    args = parser.parse_args()
    try:
        create_release_zip(args.release_folder)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Packaging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
