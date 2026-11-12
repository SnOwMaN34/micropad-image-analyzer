"""Command-line image measurement and reviewed-center replay; see docs/TECHNICAL_REFERENCE.md."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))
from app_paths import working_root
PROJECT_ROOT = working_root()

import cv2
import numpy as np
from PIL import __version__ as pillow_version

from micropad import ALGORITHM_VERSION, SETTINGS_VERSION, __version__
from micropad.detection import DetectionSettings, detect_rois
from micropad.measurement import measure_rois
from micropad.roi import MASK_RULE, circle_mask
from micropad.orientation import ACTIONS, apply_orientation
from micropad.ordering import number_column_major
from image_io import load_rgb, read_manual_centers
from reporting import create_output_directory, write_csv, write_json, write_overlay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect circular colored zones and measure original RGB; no blank correction.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, help="New directory under project results/; never overwritten")
    parser.add_argument("--channel", choices=("R", "G", "B"), default="G")
    parser.add_argument("--transform", action="append", choices=ACTIONS, default=[],
                        help="Apply a rotation/flip action in order; repeatable, no interpolation")
    parser.add_argument("--image-id", help="Technical image identifier; no pad/sample mapping is inferred")
    parser.add_argument("--reference-area", type=int, help="Optional comparison only; never controls detection or radius")
    parser.add_argument("--centers-csv", type=Path, help="Bypass detection with roi_id,center_x,center_y in original pixels")
    radii = parser.add_mutually_exclusive_group()
    radii.add_argument("--roi-radius", type=float, help="Explicit shared analytical radius in original pixels")
    radii.add_argument("--radius-factor", type=float, default=1.0, help="Interior factor of detected median radius, in (0,1]; default 1")
    parser.add_argument("--saturation-min", type=int, default=10)
    parser.add_argument("--value-min", type=int, default=100)
    parser.add_argument("--min-radius-fraction", type=float, default=0.01)
    parser.add_argument("--max-radius-fraction", type=float, default=0.15)
    parser.add_argument("--min-consistent", type=int, default=3)
    return parser


def run(args: argparse.Namespace) -> tuple[Path, dict]:
    """Analyze one source image and publish a fresh, auditable results directory."""
    if args.reference_area is not None and args.reference_area <= 0:
        raise ValueError("Reference area must be positive")
    if args.centers_csv and args.roi_radius is None:
        raise ValueError("Manual centers require --roi-radius")
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    rgb, source = load_rgb(args.image)
    original_width, original_height = rgb.shape[1], rgb.shape[0]
    transform_operations = list(getattr(args, "transform", []) or [])
    rgb = apply_orientation(rgb, transform_operations)
    settings = DetectionSettings(
        saturation_min=args.saturation_min, value_min=args.value_min,
        min_radius_fraction=args.min_radius_fraction, max_radius_fraction=args.max_radius_fraction,
        min_consistent=args.min_consistent,
    )
    warnings = ["Physical ROI-to-ImageJ mapping is unconfirmed; no reference intensity values were compared.",
                "Pad, blank, concentration and sample labels are unassigned.",
                "Detector settings have not been validated on held-out images."]
    if source["format"] == "JPEG":
        warnings.append("Input is JPEG-compressed; no source image was resaved for measurement.")
    if not source["embedded_icc_profile"]:
        warnings.append("No embedded ICC profile; precise source color characterization is unknown.")
    if source["exif_orientation"] not in (None, 1):
        warnings.append("EXIF orientation was not applied; all coordinates refer to the stored raster.")
    candidates = ()
    if args.centers_csv:
        rois = read_manual_centers(args.centers_csv, args.roi_radius)
        detection_metadata = {
            "mode": "manual_centers", "settings": None,
            "centers_path": str(args.centers_csv.resolve()),
            "centers_sha256": hashlib.sha256(args.centers_csv.read_bytes()).hexdigest(),
            "radius_median": None, "radius_mad": None,
            "ordering": "preserve supplied ROI IDs and CSV row order",
        }
    else:
        detection = detect_rois(rgb, settings, radius_factor=args.radius_factor, roi_radius=args.roi_radius)
        rois, candidates = list(detection.rois), detection.candidates
        # Column-major numbering is a presentation/export policy, not a
        # constraint on detection and not a fixed X-by-Y template.
        if rois:
            numbered = number_column_major(rois, rois[0].radius)
            id_map = {item.previous_id: item.entry.roi_id for item in numbered}
            rois = [item.entry for item in numbered]
            candidates = tuple(replace(c, roi_id=id_map.get(c.roi_id, c.roi_id))
                               for c in candidates)
        warnings.extend(detection.warnings)
        detection_metadata = {
            "mode": "automatic", "settings": asdict(settings),
            "radius_median": detection.radius_median, "radius_mad": detection.radius_mad,
            "candidate_count_above_area_floor": len(candidates),
            "rejected_candidate_count": sum(not c.roi_id for c in candidates),
            "accepted_with_qc_count": sum(bool(c.roi_id) and bool(c.flags) for c in candidates),
            "radius_definition": "sqrt(segmented contour area / pi); colored interior, not outer rim",
            "center_rule": "contour moments; nearest integer pixel, ties upward",
            "ordering": "column-major in oriented raster: left-to-right columns, top-to-bottom each column",
        }
    measurements = measure_rois(rgb, rois, args.channel) if rois else []
    if any(row["qc_flags"] for row in measurements):
        warnings.append("Some analytical ROIs overlap; retained with QC flags for review.")
    candidate_by_roi = {c.roi_id: c for c in candidates if c.roi_id}
    for row in measurements:
        candidate = candidate_by_roi.get(row["roi_id"])
        if candidate and candidate.flags:
            row["qc_flags"] = ";".join(filter(None, (row["qc_flags"], *candidate.flags)))
    if any(c.roi_id and c.flags for c in candidates):
        warnings.append("Some uniform ROIs exceed their segmented interior's enclosing radius; inspect or explicitly choose an inner margin.")
    radius = rois[0].radius if rois else None
    area = measurements[0]["pixel_count"] if measurements else None
    comparison = {
        "imagej_reference_area": args.reference_area,
        "actual_roi_pixel_count": area,
        "difference_pixels": area - args.reference_area if area is not None and args.reference_area is not None else None,
        "relative_difference_percent": 100 * (area - args.reference_area) / args.reference_area if area is not None and args.reference_area is not None else None,
        "radius_100_integer_center_area": int(circle_mask(100).sum()),
        "radius_100_half_pixel_center_area": int(circle_mask(100, center_offset=0.5).sum()),
        "interpretation": "Radius-100 areas are diagnostics only. Equal area does not prove identical ImageJ placement or mask membership.",
    }
    report = {
        "software_version": __version__, "algorithm_version": ALGORITHM_VERSION,
        "settings_version": SETTINGS_VERSION,
        "environment": {"python": sys.version, "opencv": cv2.__version__, "numpy": np.__version__, "pillow": pillow_version,
                        "opencv_threads": cv2.getNumThreads(), "opencl_enabled": cv2.ocl.useOpenCL()},
        "source": source, "image_id": args.image_id or args.image.stem,
        "orientation": {"operations": transform_operations,
                        "coordinate_space": "oriented_raster",
                        "original_dimensions": [original_width, original_height],
                        "oriented_dimensions": [rgb.shape[1], rgb.shape[0]],
                        "resampling": "none; lossless integer-pixel permutation"},
        "status": "needs_visual_review" if rois else "detection_failed",
        "detection": detection_metadata, "roi_count": len(rois),
        "measurement": {"selected_channel": args.channel, "mask_rule": MASK_RULE,
                        "shared_radius": radius, "radius_factor": args.radius_factor,
                        "radius_mode": "explicit_override" if args.roi_radius is not None else "rounded_detected_median_times_factor",
                        "inner_margin_fraction": 1 - args.radius_factor if args.roi_radius is None else None,
                        "explicit_roi_radius": args.roi_radius, "blank_correction": False},
        "area_comparison": comparison, "warnings": warnings,
    }
    image_id = report["image_id"]
    for row in measurements:
        row.update({"image_id": image_id, "source_sha256": source["source_sha256"],
                    "measurement_version": __version__, "algorithm_version": ALGORITHM_VERSION,
                    "settings_version": SETTINGS_VERSION, "reference_area": args.reference_area,
                    "area_difference_pixels": comparison["difference_pixels"]})
    # A final source hash guards against an external change during analysis.
    if hashlib.sha256(args.image.read_bytes()).hexdigest() != source["source_sha256"]:
        raise RuntimeError("Source changed during analysis; outputs were not written")
    requested = args.output or PROJECT_ROOT / "results" / datetime.now(timezone.utc).strftime("prototype_%Y%m%d_%H%M%S_%f")
    output = create_output_directory(requested, PROJECT_ROOT / "results")
    fields = ["image_id", "roi_id", "center_x", "center_y", "radius", "pixel_count", "mean_R", "mean_G", "mean_B",
              "selected_channel", "selected_mean", "qc_flags", "source_sha256", "measurement_version", "algorithm_version",
              "settings_version", "reference_area", "area_difference_pixels"]
    write_csv(output / "measurements.csv", measurements, fields)
    write_csv(output / "centers.csv", [{"roi_id": r.roi_id, "center_x": r.center_x, "center_y": r.center_y} for r in rois],
              ["roi_id", "center_x", "center_y"])
    candidate_rows = []
    for c in candidates:
        row = asdict(c)
        row["flags"] = ";".join(c.flags)
        candidate_rows.append(row)
    write_csv(output / "candidates.csv", candidate_rows, list(CANDIDATE_FIELDS))
    write_json(output / "run.json", report)
    write_overlay(output / "roi_overlay.png", rgb, rois, title=f"{len(rois)} ROIs; radius={radius}px; channel={args.channel}; review required")
    write_overlay(output / "candidate_overlay.png", rgb, rois, candidates=candidates,
                  title="Green: accepted ROIs. Orange: flagged contour candidates; see candidates.csv")
    # Raw selected channel displayed as grayscale, without normalization.
    # The mask outlines/labels are drawn on a separate RGB copy.
    chosen = rgb[:, :, ("R", "G", "B").index(args.channel)]
    channel_rgb = np.repeat(chosen[:, :, None], 3, axis=2)
    write_overlay(output / "selected_channel_roi_overlay.png", channel_rgb, rois,
                  title=f"{args.channel} channel (grayscale); {len(rois)} ROIs; radius={radius}px")
    return output, report


CANDIDATE_FIELDS = ("candidate_id", "center_x", "center_y", "detector_radius", "enclosing_radius",
                    "contour_area", "circularity", "fill_ratio", "axis_ratio", "flags", "roi_id")


def main() -> int:
    args = build_parser().parse_args()
    try:
        output, report = run(args)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Analysis failed: {error}", file=sys.stderr)
        return 2
    print(f"Results: {output}")
    print(f"ROI count: {report['roi_count']}; shared radius: {report['measurement']['shared_radius']} px")
    print(f"Area comparison: {report['area_comparison']}")
    print("Visual review required. ImageJ intensity mapping has not been assumed.")
    return 0 if report["roi_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
