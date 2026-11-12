"""CSV/JSON/PNG reporting on copies; experimental sources are never output targets."""

import csv
import json
from pathlib import Path

import cv2
import numpy as np

from micropad.detection import Candidate
from micropad.roi import ROI, circle_mask


def create_output_directory(path: Path, results_root: Path) -> Path:
    """Require a new directory strictly inside project results/, resolving links."""
    resolved, root = path.resolve(), results_root.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("Output directory must be a new subdirectory inside project results/")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    """Write a new CSV; existing files are never replaced."""
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, document: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def write_overlay(path: Path, rgb: np.ndarray, rois: list[ROI], *,
                  candidates: tuple[Candidate, ...] = (), title: str = "") -> None:
    """Draw exact measurement-mask outlines on a copy, then save lossless PNG.

    Green = accepted analytical ROIs; orange = flagged detector candidates when
    requested. Numbering matches CSV IDs and has no experimental meaning.
    """
    overlay = rgb.copy()
    for candidate in candidates:
        if not candidate.roi_id:
            center = (round(candidate.center_x), round(candidate.center_y))
            cv2.circle(overlay, center, round(candidate.enclosing_radius), (255, 140, 0), 2, cv2.LINE_AA)
            cv2.putText(overlay, candidate.candidate_id, center, cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 140, 0), 2, cv2.LINE_AA)
    for roi in rois:
        mask = circle_mask(roi.radius).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        extent = mask.shape[0] // 2
        offset = np.array([[[roi.center_x - extent, roi.center_y - extent]]])
        outlines = [(contour + offset).astype(np.int32) for contour in contours]
        cv2.drawContours(overlay, outlines, -1, (0, 200, 0), 3, cv2.LINE_AA)
        label = roi.roi_id
        point = (roi.center_x - 55, roi.center_y + 8)
        cv2.putText(overlay, label, point, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(overlay, label, point, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2, cv2.LINE_AA)
    if title:
        cv2.rectangle(overlay, (0, 0), (overlay.shape[1] - 1, 42), (0, 0, 0), -1)
        cv2.putText(overlay, title, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
    encoded_ok, encoded = cv2.imencode(".png", cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    if not encoded_ok:
        raise OSError("Failed to encode overlay PNG")
    with path.open("xb") as stream:
        stream.write(encoded.tobytes())
