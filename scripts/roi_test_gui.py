r"""Human-reviewed ROI interface for the integrated ?PAD Image Analyzer.

This reviewer can run standalone or as the ROI Review tab of the desktop app.
It never overwrites original source images or historical reference data.
All user-facing interface labels and exports are in English.
"""

from __future__ import annotations

import csv
import json
import copy
import uuid
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageDraw, ImageTk

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))
from app_paths import working_root
PROJECT_ROOT = working_root()

from micropad.detection import DetectionSettings, detect_rois
from micropad.roi import ROI, circle_mask, roi_window
from micropad.review import (ReviewEntry, select_candidates, baseline_entries,
                             nearest_candidate, refine_click_hough)
from micropad.orientation import apply_orientation, orientation_description, to_original_point
from micropad.ordering import number_column_major
from image_io import load_rgb
from analyze_image import build_parser, run

DATA_ROOT = PROJECT_ROOT / "data" / "lab_validated"
RESULTS_ROOT = PROJECT_ROOT / "results"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def roi_pixel_area(radius: float) -> int:
    """Count pixels in the SAME inclusive integer-centered mask as measurement.

    This is deliberately not pi*r*r: ImageJ comparisons require the actual
    discrete-pixel area used by the existing measurement module.
    """
    return int(circle_mask(radius).sum())


def format_area(area: int) -> str:
    return f"{area:,}"


def write_radius_comparison(
    result_dir: Path, *, auto_radius: float, applied_radius: float,
    mode: str, channel: str,
) -> None:
    """Save the proposed and applied circle sizes alongside a measurement run."""
    auto_area, applied_area = roi_pixel_area(auto_radius), roi_pixel_area(applied_radius)
    with (result_dir / "radius_comparison.csv").open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "radius_mode", "selected_channel", "detected_radius_px", "detected_area_pixels",
            "applied_radius_px", "applied_area_pixels", "area_difference_pixels",
            "area_difference_percent_vs_detected",
        ])
        writer.writeheader()
        writer.writerow({
            "radius_mode": mode,
            "selected_channel": channel,
            "detected_radius_px": auto_radius,
            "detected_area_pixels": auto_area,
            "applied_radius_px": applied_radius,
            "applied_area_pixels": applied_area,
            "area_difference_pixels": applied_area - auto_area,
            "area_difference_percent_vs_detected": 100 * (applied_area - auto_area) / auto_area,
        })


def discover_images() -> list[Path]:
    """Return the available local images; no lab data are copied or uploaded."""
    if not DATA_ROOT.is_dir():
        return []
    return sorted(
        (p for p in DATA_ROOT.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda p: str(p).casefold(),
    )


def write_selected_channel_csv(result_dir: Path, entries: list[ReviewEntry] | None = None) -> Path:
    """Export ONLY the user-selected intensity column for spreadsheet work.

    The existing full measurements.csv is deliberately retained for QA and
    compatibility with the original pipeline/tests.
    """
    source = result_dir / "measurements.csv"
    destination = result_dir / "selected_channel_measurements.csv"
    columns = [
        "image_id", "roi_id", "center_x", "center_y", "radius",
        "pixel_count", "channel", "mean_intensity", "qc_flags",
        "roi_source", "candidate_id",
    ]
    review_by_id = {entry.roi_id: entry for entry in (entries or [])}
    with source.open("r", newline="", encoding="utf-8-sig") as input_stream:
        original = csv.DictReader(input_stream)
        required = {
            "image_id", "roi_id", "center_x", "center_y", "radius",
            "pixel_count", "selected_channel", "selected_mean", "qc_flags",
        }
        if not required.issubset(set(original.fieldnames or [])):
            raise ValueError("measurements.csv is missing one or more required columns.")
        # x means the file cannot be overwritten by accident.
        with destination.open("x", newline="", encoding="utf-8-sig") as output_stream:
            writer = csv.DictWriter(output_stream, fieldnames=columns)
            writer.writeheader()
            for row in original:
                review = review_by_id.get(row["roi_id"])
                combined_flags = ";".join(flag for flag in (
                    row["qc_flags"], review.qc_flags if review else "",
                ) if flag)
                writer.writerow({
                    "image_id": row["image_id"],
                    "roi_id": row["roi_id"],
                    "center_x": row["center_x"],
                    "center_y": row["center_y"],
                    "radius": row["radius"],
                    "pixel_count": row["pixel_count"],
                    "channel": row["selected_channel"],
                    "mean_intensity": row["selected_mean"],
                    "qc_flags": combined_flags,
                    "roi_source": review.source if review else "",
                    "candidate_id": review.candidate_id if review else "",
                })
    return destination


def append_run_history(
    *, image: Path, channel: str, detected_radius: float,
    applied_radius: float, roi_count: int, qc_count: int, result_dir: Path,
) -> None:
    """Keep a local index of all runs under the Git-ignored results folder."""
    RESULTS_ROOT.mkdir(exist_ok=True)
    path = RESULTS_ROOT / "test_history.csv"
    columns = [
        "run_time_utc", "image_path", "selected_channel", "detected_radius_px",
        "applied_radius_px", "roi_count", "flagged_roi_count", "result_directory",
    ]
    row = {
        "run_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "image_path": str(image.resolve()),
        "selected_channel": channel,
        "detected_radius_px": detected_radius,
        "applied_radius_px": applied_radius,
        "roi_count": roi_count,
        "flagged_roi_count": qc_count,
        "result_directory": str(result_dir.resolve()),
    }
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig" if needs_header else "utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def fit_zoom_for_viewport(image_width: int, image_height: int,
                          viewport_width: int, viewport_height: int) -> float:
    """Scale to show the entire image without upscaling above native resolution."""
    if min(image_width, image_height, viewport_width, viewport_height) <= 0:
        raise ValueError("Image and viewport dimensions must be positive.")
    return min(1.0, max(0.01, min((viewport_width - 12) / image_width,
                                    (viewport_height - 12) / image_height)))


def source_pixel_from_world(world_x: float, world_y: float, *, zoom: float,
                            offset_x: float, offset_y: float,
                            image_width: int, image_height: int) -> tuple[int, int] | None:
    """Map a SCROLLED canvas world-coordinate to oriented source pixels.

    Display zoom, page scrolling and canvas panning never change ROI coordinates.
    """
    if zoom <= 0:
        raise ValueError("Zoom must be positive.")
    x, y = (world_x - offset_x) / zoom, (world_y - offset_y) / zoom
    if not (0 <= x < image_width and 0 <= y < image_height):
        return None
    return (min(image_width - 1, max(0, math.floor(x + 0.5))),
            min(image_height - 1, max(0, math.floor(y + 0.5))))


class RoiTestApp:
    def __init__(self, root: tk.Tk, *, parent: tk.Widget | None = None) -> None:
        self.root = root
        self.parent = parent if parent is not None else root
        if parent is None:  # Preserve the original standalone ROI test tool.
            root.title("µPAD ROI Test Tool – ROI Review")
            root.geometry("1330x900")
            root.minsize(840, 620)
        cv2.setNumThreads(1)
        cv2.ocl.setUseOpenCL(False)

        self.paths = discover_images()
        self.path_by_label = {
            str(path.relative_to(DATA_ROOT)): path for path in self.paths
        }
        self.image_choice = tk.StringVar()
        self.channel = tk.StringVar(value="G")
        self.radius_mode = tk.StringVar(value="auto")
        self.manual_radius = tk.StringVar(value="100")
        self.auto_area_info = tk.StringVar(value="Radius: —    Area: —")
        self.manual_area_info = tk.StringVar(value="Radius: 100 px    Area: —")
        self.applied_area_info = tk.StringVar(value="Active ROI: —")
        self.info = tk.StringVar(value="Select an image, then click Detect & Preview.")
        self.status = tk.StringVar(value="The selected channel is used for intensity measurement; detection is based on HSV color segmentation.")
        self.image_path: Path | None = None
        self.rgb = None
        self.detection = None
        self.last_output: Path | None = None
        self._preview_photo = None
        self.tolerance_percent = tk.StringVar(value="30")
        self.match_radius_follows_roi = tk.BooleanVar(value=True)
        self.match_radius = tk.StringVar(value="100")
        self.selection_info = tk.StringVar(value="Candidate review: no image loaded")
        self.current_detection = None
        self.current_entries: list[ReviewEntry] = []
        self.manual_additions: dict[str, ReviewEntry] = {}
        self.manual_removed: set[str] = set()
        # Suppressed orange candidates remain unavailable until Undo/Reset/Image load.
        # This is an interactive review choice, not a change to the detector.
        self.dismissed_candidates: set[str] = set()
        self.change_log: list[dict] = []
        self.undo_stack: list[tuple[dict, set, set, list]] = []
        self.preview_geometry = None  # Deprecated; use zoom + canvas world coordinates.
        self.manual_index = 0
        self.orientation_ops: list[str] = []
        self.orientation_label = tk.StringVar(value="Original orientation")
        self.source_dimensions = (0, 0)  # width, height before rotation or mirroring

        # Viewport state affects ONLY the on-screen preview, never the saved ROI
        # coordinates, source pixels, measured areas, or reviewed selections.
        self.source_image: Image.Image | None = None
        self.zoom_mode = "fit"
        self.zoom_scale = 1.0
        self.zoom_label = tk.StringVar(value="Zoom: Fit")
        self.image_offset_x = 0.0
        self.image_offset_y = 0.0
        self.world_width = 1.0
        self.world_height = 1.0
        self._click_start: tuple[int, int] | None = None
        self._left_dragged = False

        # Scrollable application page. The preview has its OWN independent
        # scrollbars for image navigation; scrolling the page changes neither
        # image coordinates nor ROI positions.
        self.page_canvas = tk.Canvas(self.parent, borderwidth=0, highlightthickness=0)
        self.page_scrollbar = ttk.Scrollbar(self.parent, orient="vertical", command=self.page_canvas.yview)
        self.page_scrollbar.pack(side="right", fill="y")
        self.page_canvas.pack(side="left", fill="both", expand=True)
        self.page_canvas.configure(yscrollcommand=self.page_scrollbar.set)
        page = ttk.Frame(self.page_canvas)
        self.page_window = self.page_canvas.create_window((0, 0), window=page, anchor="nw")
        page.bind("<Configure>", self._on_page_content_resize)
        self.page_canvas.bind("<Configure>", self._on_page_resize)

        content = ttk.Frame(page, padding=12)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)

        settings = ttk.LabelFrame(content, text="Measurement Settings", padding=12)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Image:").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        self.image_combo = ttk.Combobox(
            settings, textvariable=self.image_choice,
            values=list(self.path_by_label), state="readonly", width=67,
        )
        self.image_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.image_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_image())
        ttk.Button(settings, text="Browse...", command=self.browse_image).grid(
            row=0, column=2, sticky="ew", padx=(10, 0), pady=4,
        )

        ttk.Label(settings, text="Measurement Channel:").grid(
            row=1, column=0, sticky="w", pady=6
        )
        channel_box = ttk.Frame(settings)
        channel_box.grid(row=1, column=1, columnspan=2, sticky="w")
        for c, label in (("R", "R — Red"), ("G", "G — Green"), ("B", "B — Blue")):
            ttk.Radiobutton(channel_box, text=label, value=c, variable=self.channel,
                            command=self.refresh_preview).pack(side="left", padx=(0, 24))

        ttk.Label(settings, text="ROI Radius:").grid(row=2, column=0, sticky="w", pady=6)
        radius_box = ttk.Frame(settings)
        radius_box.grid(row=2, column=1, columnspan=2, sticky="w", pady=6)
        ttk.Radiobutton(
            radius_box, text="Auto-detected", variable=self.radius_mode,
            value="auto", command=self.refresh_preview,
        ).pack(side="left", padx=(0, 24))
        ttk.Radiobutton(
            radius_box, text="Custom (px):", variable=self.radius_mode,
            value="manual", command=self.refresh_preview,
        ).pack(side="left")
        self.radius_spin = ttk.Spinbox(
            radius_box, from_=1, to=5000, increment=1, width=8,
            textvariable=self.manual_radius,
        )
        self.radius_spin.pack(side="left", padx=7)
        self.radius_spin.bind("<Return>", lambda _event: self.refresh_preview())
        self.radius_spin.bind("<FocusOut>", lambda _event: self.refresh_preview())
        ttk.Button(radius_box, text="Refresh Preview", command=self.refresh_preview).pack(
            side="left", padx=(16, 0),
        )

        comparison = ttk.Frame(settings)
        comparison.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        comparison.columnconfigure(0, weight=1)
        comparison.columnconfigure(1, weight=1)

        detected_panel = ttk.LabelFrame(comparison, text="Suggested ROI (Automatic)", padding=(12, 10))
        detected_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(detected_panel, textvariable=self.auto_area_info, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        manual_panel = ttk.LabelFrame(comparison, text="Custom Radius and Area", padding=(12, 10))
        manual_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(manual_panel, textvariable=self.manual_area_info, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        ttk.Label(settings, textvariable=self.applied_area_info, font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 0),
        )

        workflow = ttk.LabelFrame(content, text="ROI Workflow", padding=12)
        workflow.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        actions = ttk.Frame(workflow)
        actions.pack(fill="x")
        ttk.Button(actions, text="1. Detect & Preview", command=self.load_image).pack(side="left")
        ttk.Button(actions, text="Re-evaluate Candidates", command=self.refresh_preview).pack(
            side="left", padx=(10, 0))
        ttk.Button(actions, text="Undo Edit", command=self.undo_edit).pack(side="left", padx=(18, 0))
        ttk.Button(actions, text="Reset Manual Edits", command=self.reset_edits).pack(side="left", padx=(10, 0))
        self.run_button = ttk.Button(
            actions, text="2. Measure & Save CSV", command=self.save_run, state="disabled",
        )
        self.run_button.pack(side="left", padx=(18, 0))
        self.open_button = ttk.Button(
            actions, text="Open Latest Results", command=self.open_last_output, state="disabled",
        )
        self.open_button.pack(side="left", padx=(10, 0))

        candidate_frame = ttk.LabelFrame(content, text="Candidate Review Settings", padding=12)
        candidate_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        candidate_row1 = ttk.Frame(candidate_frame)
        candidate_row1.pack(fill="x", pady=(0, 6))
        ttk.Label(candidate_row1, text="Candidate search radius:").pack(side="left")
        ttk.Checkbutton(
            candidate_row1, text="Use analytical ROI radius", variable=self.match_radius_follows_roi,
            command=self.refresh_preview,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(candidate_row1, text="or use outer/backing-paper radius (px):").pack(
            side="left", padx=(18, 5))
        self.match_radius_spin = ttk.Spinbox(
            candidate_row1, from_=1, to=5000, increment=1, width=8,
            textvariable=self.match_radius,
        )
        self.match_radius_spin.pack(side="left")
        self.match_radius_spin.bind("<Return>", lambda _event: self.refresh_preview())
        self.match_radius_spin.bind("<FocusOut>", lambda _event: self.refresh_preview())

        candidate_row2 = ttk.Frame(candidate_frame)
        candidate_row2.pack(fill="x", pady=(0, 6))
        ttk.Label(candidate_row2, text="Candidate radius tolerance (±%):").pack(side="left")
        self.tolerance_spin = ttk.Spinbox(
            candidate_row2, from_=1, to=100, increment=5, width=7,
            textvariable=self.tolerance_percent,
        )
        self.tolerance_spin.pack(side="left", padx=(10, 0))
        self.tolerance_spin.bind("<Return>", lambda _event: self.refresh_preview())
        self.tolerance_spin.bind("<FocusOut>", lambda _event: self.refresh_preview())
        ttk.Label(candidate_row2, text="Re-checks ALL contour candidates, including originally rejected ones.").pack(
            side="left", padx=(18, 0))

        info_bar = ttk.Frame(candidate_frame)
        info_bar.pack(fill="x", pady=(4, 0))
        ttk.Label(info_bar, text="ℹ", font=("Segoe UI Symbol", 13, "bold"), foreground="#1e6fd9").pack(side="left")
        ttk.Label(
            info_bar,
            text="Workflow: Select an image, set options, then click 1. Detect & Preview to find ROI candidates.",
            wraplength=1100,
        ).pack(side="left", padx=(8, 0))
        # Live detection / selection status is essential during manual review.
        # Keep both existing StringVars visible; do not replace their logic.
        ttk.Label(candidate_frame, textvariable=self.info, wraplength=1150).pack(
            fill="x", anchor="w", pady=(7, 1))
        ttk.Label(candidate_frame, textvariable=self.selection_info, wraplength=1150).pack(
            fill="x", anchor="w", pady=(1, 0))

        orientation_bar = ttk.LabelFrame(content, text="Image Orientation", padding=12)
        orientation_bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for label, operation in (("Rotate 90° Left", "ccw"), ("Rotate 90° Right", "cw"),
                                 ("Flip Horizontal", "flip_h"), ("Flip Vertical", "flip_v")):
            ttk.Button(orientation_bar, text=label,
                       command=lambda op=operation: self.apply_orientation_action(op)).pack(
                side="left", padx=(0, 10))
        ttk.Button(orientation_bar, text="Reset Orientation", command=self.reset_orientation).pack(
            side="left", padx=(0, 14))
        ttk.Separator(orientation_bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(orientation_bar, text="Current orientation:", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(orientation_bar, textvariable=self.orientation_label, wraplength=320).pack(side="left", padx=(8, 0))

        preview_frame = ttk.LabelFrame(content, text="ROI Preview — Original Pixels, Display Orientation Applied", padding=8)
        preview_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        toolbar = ttk.Frame(preview_frame)
        toolbar.pack(fill="x", pady=(0, 7))
        ttk.Button(toolbar, text="Fit Image", command=self.zoom_fit).pack(side="left")
        ttk.Button(toolbar, text="100%", command=self.zoom_actual).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Zoom −", command=lambda: self.zoom_by(1 / 1.25)).pack(side="left", padx=(12, 0))
        ttk.Button(toolbar, text="Zoom +", command=lambda: self.zoom_by(1.25)).pack(side="left", padx=(6, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=14)
        ttk.Label(toolbar, textvariable=self.zoom_label, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=14)
        ttk.Label(toolbar, text="Ctrl + wheel: zoom  |  Wheel: scroll  |  Left drag: pan  |  "
                 "Left click: add ROI  |  Right click green: exclude ROI  |  "
                 "Right click orange: hide candidate",
                  wraplength=760).pack(side="left")

        viewer = ttk.Frame(preview_frame)
        viewer.pack(fill="x", expand=False)
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewer, bg="#eeeeee", height=600,
                                highlightthickness=1, highlightbackground="#c2c2c2",
                                xscrollincrement=20, yscrollincrement=20)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_ybar = ttk.Scrollbar(viewer, orient="vertical", command=self._preview_yview)
        self.preview_ybar.grid(row=0, column=1, sticky="ns")
        self.preview_xbar = ttk.Scrollbar(viewer, orient="horizontal", command=self._preview_xview)
        self.preview_xbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.preview_xbar.set,
                              yscrollcommand=self.preview_ybar.set)
        self.canvas.bind("<Configure>", self._on_preview_resize)
        self.canvas.bind("<ButtonPress-1>", self._left_press)
        self.canvas.bind("<B1-Motion>", self._left_motion)
        self.canvas.bind("<ButtonRelease-1>", self._left_release)
        self.canvas.bind("<Button-2>", self._middle_press)
        self.canvas.bind("<B2-Motion>", self._middle_motion)
        self.canvas.bind("<Button-3>", self.remove_at_click)
        self.root.bind_all("<MouseWheel>", self._on_global_wheel, add="+")
        self.root.bind_all("<Button-4>", self._on_global_wheel, add="+")
        self.root.bind_all("<Button-5>", self._on_global_wheel, add="+")

        # Update the true pixel area while the user types, not only after Enter.
        self.manual_radius.trace_add("write", self._manual_radius_edited)

        footer = ttk.Label(page, textvariable=self.status, wraplength=1120, padding=(12, 6))
        footer.pack(fill="x")
        if not self.paths:
            self.status.set(
                "No images are bundled. Use Browse... to select a laboratory scan."
                if getattr(sys, "frozen", False) else
                "No images found in data/lab_validated/. Use Browse... to select an image elsewhere."
            )

    def browse_image(self) -> None:
        documents = Path.home() / "Documents"
        initial = (DATA_ROOT if DATA_ROOT.is_dir() else
                   documents if documents.is_dir() else Path.home())
        chosen = filedialog.askopenfilename(
            title="Select a µPAD Image", initialdir=initial,
            filetypes=[("µPAD images", "*.jpg *.jpeg *.png *.tif *.tiff"), ("All files", "*.*")],
        )
        if chosen:
            self.image_path = Path(chosen)
            self.image_choice.set(str(chosen))
            self.load_image()

    def _chosen_path(self) -> Path | None:
        label = self.image_choice.get().strip()
        return self.path_by_label.get(label) or (Path(label) if label else None)

    def apply_orientation_action(self, operation: str) -> None:
        """Apply user action to the source raster and re-run all detection."""
        if self.image_path is None:
            messagebox.showinfo("Image Orientation", "Please select an image first.")
            return
        if (self.manual_additions or self.manual_removed or self.dismissed_candidates) and not messagebox.askyesno(
                "Reset ROI Edits?",
                "Changing image orientation re-detects zones and clears manual ROI edits. Continue?"):
            return
        self.orientation_ops.append(operation)
        self.load_image(preserve_orientation=True)

    def reset_orientation(self) -> None:
        if self.image_path is None or not self.orientation_ops:
            return
        if (self.manual_additions or self.manual_removed or self.dismissed_candidates) and not messagebox.askyesno(
                "Reset ROI Edits?",
                "Resetting orientation re-detects zones and clears manual ROI edits. Continue?"):
            return
        self.orientation_ops = []
        self.load_image(preserve_orientation=True)

    def load_image(self, *, preserve_orientation: bool = False) -> None:
        path = self._chosen_path()
        if not path:
            messagebox.showinfo("Image Selection", "Please select an image first.")
            return
        preserved_mode = self.radius_mode.get() if preserve_orientation else None
        preserved_manual_radius = self.manual_radius.get() if preserve_orientation else None
        if not preserve_orientation:
            self.orientation_ops = []
        self.orientation_label.set(orientation_description(self.orientation_ops))
        self.run_button.config(state="disabled")
        self.detection = None
        self.current_detection = None
        self.current_entries = []
        self.manual_additions.clear()
        self.manual_removed.clear()
        self.dismissed_candidates.clear()
        self.change_log.clear()
        self.undo_stack.clear()
        self.manual_index = 0
        self.rgb = None
        self.source_image = None
        self.image_path = None
        self.zoom_mode = "fit"
        self.zoom_scale = 1.0
        self._refresh_area_comparison()
        self.canvas.delete("all")
        self.info.set("Detecting reaction zones...")
        self.root.update_idletasks()
        try:
            original_rgb, _source = load_rgb(path)
            self.source_dimensions = (original_rgb.shape[1], original_rgb.shape[0])
            rgb = apply_orientation(original_rgb, self.orientation_ops)
            result = detect_rois(rgb, DetectionSettings())
            if not result.candidates:
                raise ValueError("No circle candidates were detected. Adjust detector thresholds in the scientific code.")
            self.rgb = rgb
            self.source_image = Image.fromarray(rgb)
            self.detection = result
            self.image_path = path
            self.radius_mode.set("auto")
            if result.roi_radius is None:
                if not result.candidates:
                    raise ValueError("No usable circle radius could be estimated.")
                self.radius_mode.set("manual")
                self.manual_radius.set(str(round(sorted(c.detector_radius for c in result.candidates)[len(result.candidates)//2])))
            else:
                self.manual_radius.set(str(result.roi_radius))
            qc = sum(bool(c.flags) for c in result.candidates if c.roi_id)
            self.info.set(
                f"{len(result.rois)} initially accepted ROI • suggested radius: {result.roi_radius} px • "
                f"geometry QC flags: {qc} • image: {path.name}"
            )
            if preserve_orientation and preserved_mode is not None:
                self.radius_mode.set(preserved_mode if result.roi_radius is not None else "manual")
                if preserved_manual_radius is not None:
                    self.manual_radius.set(preserved_manual_radius)
            self.match_radius.set(str(round(result.roi_radius or 100)))
            self.status.set("Left-click a missing zone to recover/refine its center. Right-click a green ROI to remove it.")
            self.run_button.config(state="normal")
            self.refresh_preview()
        except (ValueError, OSError, RuntimeError, cv2.error) as exc:
            self.info.set("Detection failed.")
            messagebox.showerror("Detection Error", str(exc))

    def chosen_radius(self) -> float:
        if not self.detection:
            raise ValueError("Run detection first.")
        if self.radius_mode.get() == "auto":
            if self.detection.roi_radius is None:
                raise ValueError("Automatic radius unavailable. Select a custom radius.")
            return float(self.detection.roi_radius)
        return self._parse_custom_radius()

    def _parse_custom_radius(self) -> float:
        try:
            radius = float(self.manual_radius.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Enter a positive number for the custom radius.") from exc
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError("The custom radius must be a positive, finite number.")
        return radius

    def _manual_radius_edited(self, *_args: object) -> None:
        """Keep the comparison visible and live as an entered radius changes."""
        if self.detection is not None and self.rgb is not None:
            # Typing updates the area immediately, without expensive repeated
            # segmentation for each keystroke. Enter/FocusOut re-runs selection.
            self._refresh_area_comparison()
            self.status.set("Radius edited: press Enter or Re-evaluate Candidates to update the ROI selection.")

    def _refresh_area_comparison(self) -> None:
        """Show both areas using the measurement's actual discrete ROI mask."""
        if self.detection is None or self.rgb is None:
            self.auto_area_info.set("Radius: —    Area: —")
            self.manual_area_info.set("Radius: —    Area: —")
            self.applied_area_info.set("Active ROI: —")
            return

        if self.detection.roi_radius is None:
            proposed_area = None
            self.auto_area_info.set("No reliable automatic radius available")
        else:
            proposed = float(self.detection.roi_radius)
            proposed_area = roi_pixel_area(proposed)
            self.auto_area_info.set(
                f"Radius: {proposed:g} px    Area: {format_area(proposed_area)} pixels"
            )

        # An impossible oversized circle is not rasterized into a huge array.
        max_possible_radius = min(self.rgb.shape[:2]) / 2
        try:
            custom = self._parse_custom_radius()
            if custom >= max_possible_radius:
                self.manual_area_info.set(f"Radius: {custom:g} px    Area: too large for the image")
            else:
                custom_area = roi_pixel_area(custom)
                self.manual_area_info.set(
                    f"Radius: {custom:g} px    Area: {format_area(custom_area)} pixels"
                )
        except ValueError:
            self.manual_area_info.set("Custom radius: invalid value")

        try:
            active = self.chosen_radius()
            if active >= max_possible_radius:
                self.applied_area_info.set("Active ROI: selected radius is too large for the image")
                return
            active_area = roi_pixel_area(active)
            delta = active_area - proposed_area if proposed_area is not None else None
            percent = 100 * delta / proposed_area if proposed_area else None
            label = "automatic" if self.radius_mode.get() == "auto" else "custom"
            self.applied_area_info.set(
                f"Currently applied ({label}): {active:g} px / {format_area(active_area)} pixels    "
                + (f"|    Difference from automatic: {delta:+,} pixels ({percent:+.2f}%)"
                   if delta is not None else "|    Automatic reference unavailable")
            )
        except ValueError:
            self.applied_area_info.set("Active ROI: invalid radius")

    def _candidate_search_radius(self) -> float:
        if self.match_radius_follows_roi.get():
            return self.chosen_radius()
        try:
            value = float(self.match_radius.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Enter a positive candidate search radius.") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Candidate search radius must be positive and finite.")
        return value

    def _tolerance(self) -> float:
        try:
            value = float(self.tolerance_percent.get().strip().replace(",", ".")) / 100
        except ValueError as exc:
            raise ValueError("Enter a percentage from 1 to 100 for radius tolerance.") from exc
        if not math.isfinite(value) or not 0.01 <= value <= 1.0:
            raise ValueError("Radius tolerance must be between 1 and 100%.")
        return value

    def _numbering_radius(self) -> float:
        """Use a fixed detected geometry hint so radius adjustments cannot renumber ROIs."""
        if self.detection is not None and self.detection.roi_radius is not None:
            return float(self.detection.roi_radius)
        if self.detection is not None and self.detection.candidates:
            values = sorted(float(c.detector_radius) for c in self.detection.candidates)
            return values[len(values) // 2]
        return self.chosen_radius()

    def _available_entries(self, computed: list[ReviewEntry]) -> list[ReviewEntry]:
        # Manual forced recoveries survive a change in measurement radius;
        # manually removed IDs stay removed until Undo/Reset.
        combined = {e.roi_id: e for e in computed}
        combined.update(self.manual_additions)
        for key in self.manual_removed:
            combined.pop(key, None)
        return sorted(combined.values(), key=lambda e: (e.center_y, e.center_x, e.roi_id))

    def refresh_preview(self) -> None:
        """Re-run candidate detection and radius-aware acceptance (not just redraw)."""
        if self.detection is None or self.rgb is None:
            self._refresh_area_comparison()
            return
        self._refresh_area_comparison()
        try:
            radius = self.chosen_radius()
            search_radius = self._candidate_search_radius()
            tolerance = self._tolerance()
            if radius >= min(self.rgb.shape[:2]) / 2:
                raise ValueError("The chosen analytical radius is too large for this image.")
            if search_radius >= min(self.rgb.shape[:2]) / 2:
                raise ValueError("The chosen candidate search radius is too large for this image.")
            # Re-run the HSV detector on every explicit apply. In manual mode
            # its original radius consensus is superseded by re-evaluating the
            # complete candidate pool against the user target and tolerance.
            self.current_detection = detect_rois(
                self.rgb, DetectionSettings(), roi_radius=radius,
            )
            # A dismissed contour must not be auto-selected on later radius changes.
            candidates = tuple(c for c in self.current_detection.candidates
                               if c.candidate_id not in self.dismissed_candidates)
            previous_ids = {c.candidate_id: c.roi_id for c in self.detection.candidates if c.roi_id}
            if self.radius_mode.get() == "auto" and self.match_radius_follows_roi.get():
                computed = baseline_entries(candidates)
                count_matching = len(computed)
            else:
                computed, count_matching = select_candidates(
                    candidates, search_radius, tolerance, self.rgb.shape,
                    previous_ids, analytical_radius=radius,
                )
            entries = self._available_entries(computed)
            valid_entries, clipped = [], 0
            for e in entries:
                try:
                    roi_window(e.to_roi(radius), self.rgb.shape)
                except ValueError:
                    clipped += 1
                    continue
                valid_entries.append(e)
            self.current_entries = valid_entries
            self.run_button.config(state="normal" if valid_entries and not clipped else "disabled")
            recovered = sum(e.source in ("radius_recovered", "manual_candidate", "manual_hough", "manual_click")
                            for e in valid_entries)
            self.selection_info.set(
                f"Candidate review: {len(candidates)} contours | "
                f"search radius {search_radius:g} px (±{tolerance*100:g}%) | "
                f"{count_matching} matches | {len(valid_entries)} accepted ROIs | "
                f"{recovered} recovered/manually placed | "
                f"{len(self.dismissed_candidates)} hidden candidates | "
                f"{clipped} clipped"
            )
            self.status.set(
                "ROI numbers: first column top-to-bottom, then columns left-to-right. "
                "Left-click to recover zones; right-click a green ROI to exclude it, "
                "or an orange candidate to hide it. Undo restores hidden candidates."
            )
            self._draw_preview()
        except (ValueError, RuntimeError, cv2.error) as exc:
            self.status.set(str(exc))
            self.run_button.config(state="disabled")

    def _on_page_resize(self, event: tk.Event) -> None:
        self.page_canvas.itemconfigure(self.page_window, width=event.width)

    def _on_page_content_resize(self, _event: tk.Event) -> None:
        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))

    def _on_preview_resize(self, _event: tk.Event) -> None:
        if self.source_image is None:
            return
        if self.zoom_mode == "fit":
            self.zoom_scale = fit_zoom_for_viewport(
                self.source_image.width, self.source_image.height,
                self.canvas.winfo_width(), self.canvas.winfo_height())
        self._draw_preview()

    def _update_scrollregion(self) -> None:
        if self.source_image is None:
            return
        vw, vh = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        image_w = self.source_image.width * self.zoom_scale
        image_h = self.source_image.height * self.zoom_scale
        self.image_offset_x = max(0.0, (vw - image_w) / 2)
        self.image_offset_y = max(0.0, (vh - image_h) / 2)
        self.world_width = max(float(vw), self.image_offset_x + image_w)
        self.world_height = max(float(vh), self.image_offset_y + image_h)
        self.canvas.configure(scrollregion=(0, 0, self.world_width, self.world_height))

    def _native_under_widget(self, x: float, y: float) -> tuple[float, float] | None:
        if self.source_image is None or self.zoom_scale <= 0:
            return None
        sx = (self.canvas.canvasx(x) - self.image_offset_x) / self.zoom_scale
        sy = (self.canvas.canvasy(y) - self.image_offset_y) / self.zoom_scale
        return (sx, sy)

    def _scroll_to_native(self, x: float, y: float, at_x: float, at_y: float) -> None:
        """Keep a chosen source-image pixel at the same screen position after zoom."""
        self._update_scrollregion()
        target_x = self.image_offset_x + x * self.zoom_scale - at_x
        target_y = self.image_offset_y + y * self.zoom_scale - at_y
        self.canvas.xview_moveto(max(0.0, target_x) / self.world_width)
        self.canvas.yview_moveto(max(0.0, target_y) / self.world_height)

    def _set_zoom(self, scale: float, *, anchor_x: float | None = None,
                  anchor_y: float | None = None) -> None:
        if self.source_image is None:
            return
        vw, vh = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        at_x = vw / 2 if anchor_x is None else anchor_x
        at_y = vh / 2 if anchor_y is None else anchor_y
        native = self._native_under_widget(at_x, at_y)
        if native is None:
            native = (self.source_image.width / 2, self.source_image.height / 2)
        self.zoom_scale = min(8.0, max(0.05, scale))
        self.zoom_mode = "manual"
        self._scroll_to_native(native[0], native[1], at_x, at_y)
        self._draw_preview()

    def zoom_by(self, factor: float, *, anchor_x: float | None = None,
                anchor_y: float | None = None) -> None:
        if factor <= 0:
            raise ValueError("Zoom factor must be positive.")
        self._set_zoom(self.zoom_scale * factor, anchor_x=anchor_x, anchor_y=anchor_y)

    def zoom_actual(self) -> None:
        self._set_zoom(1.0)

    def zoom_fit(self) -> None:
        if self.source_image is None:
            return
        self.zoom_mode = "fit"
        self.zoom_scale = fit_zoom_for_viewport(
            self.source_image.width, self.source_image.height,
            max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._draw_preview()

    def _preview_xview(self, *args: str) -> None:
        self.canvas.xview(*args)
        self._draw_preview()

    def _preview_yview(self, *args: str) -> None:
        self.canvas.yview(*args)
        self._draw_preview()

    def _on_global_wheel(self, event: tk.Event) -> str | None:
        if not self.page_canvas.winfo_ismapped():
            return None
        """Scroll page over settings; scroll/zoom image over the preview."""
        # MouseWheel delta uses multiples of 120 on Windows, while X11
        # traditionally dispatches Button-4/5. Handle both.
        num = getattr(event, "num", None)
        delta = getattr(event, "delta", 0)
        if num == 4:
            steps = 1
        elif num == 5:
            steps = -1
        elif delta:
            steps = (1 if delta > 0 else -1) * max(1, abs(int(delta)) // 120)
        else:
            return None
        if event.widget is self.canvas:
            if getattr(event, "state", 0) & 0x0004:  # Ctrl + wheel
                self.zoom_by(1.25 ** steps, anchor_x=event.x, anchor_y=event.y)
            elif getattr(event, "state", 0) & 0x0001:  # Shift + wheel
                self.canvas.xview_scroll(-steps * 2, "units")
                self._draw_preview()
            elif self.world_height > self.canvas.winfo_height() + 2:
                self.canvas.yview_scroll(-steps * 2, "units")
                self._draw_preview()
            else:
                self.page_canvas.yview_scroll(-steps * 3, "units")
            return "break"
        # Allow native widget wheel behavior in selectors and spinboxes.
        if isinstance(event.widget, (ttk.Combobox, ttk.Spinbox, tk.Spinbox)):
            return None
        self.page_canvas.yview_scroll(-steps * 3, "units")
        return None

    def _left_press(self, event: tk.Event) -> None:
        self._click_start = (event.x, event.y)
        self._left_dragged = False
        self.canvas.scan_mark(event.x, event.y)

    def _left_motion(self, event: tk.Event) -> None:
        if self._click_start is None:
            return
        start_x, start_y = self._click_start
        if abs(event.x - start_x) + abs(event.y - start_y) >= 6:
            self._left_dragged = True
        if self._left_dragged:
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            self._draw_preview()

    def _left_release(self, event: tk.Event) -> None:
        should_add = self._click_start is not None and not self._left_dragged
        self._click_start = None
        self._left_dragged = False
        if should_add:
            self.add_at_click(event)

    def _middle_press(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def _middle_motion(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._draw_preview()

    def _draw_preview(self) -> None:
        """Render only visible pixels for memory-safe zoom, plus vector ROI lines.

        All coordinates used for ROI editing and saving remain in the ORIENTED
        image pixel space. The original source file is never changed. Nothing from the zoomed preview is measured.
        """
        if self.source_image is None or self.detection is None:
            return
        try:
            radius = self.chosen_radius()
        except ValueError:
            return
        self._update_scrollregion()
        vw, vh = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        left, top = self.canvas.canvasx(0), self.canvas.canvasy(0)
        z = self.zoom_scale
        # Viewport-only resampling: even at 800% zoom no full-resolution
        # multi-hundred-megapixel scaled copy is ever allocated.
        affine = (1 / z, 0, (left - self.image_offset_x) / z,
                  0, 1 / z, (top - self.image_offset_y) / z)
        visible = self.source_image.transform(
            (vw, vh), Image.Transform.AFFINE, affine,
            resample=Image.Resampling.BILINEAR, fillcolor=(240, 240, 240))
        self._preview_photo = ImageTk.PhotoImage(visible)
        self.canvas.delete("preview_layer")
        self.canvas.create_image(left, top, anchor="nw", image=self._preview_photo,
                                 tags=("preview_layer",))
        right, bottom = left + vw, top + vh
        candidates = self.current_detection.candidates if self.current_detection is not None else ()
        accepted_candidates = {e.candidate_id for e in self.current_entries if e.candidate_id}

        def intersects(x: float, y: float, r: float) -> bool:
            return (x+r >= left and x-r <= right and y+r >= top and y-r <= bottom)

        for c in candidates:
            if (c.candidate_id in accepted_candidates
                    or c.candidate_id in self.dismissed_candidates):
                continue
            x = self.image_offset_x + c.center_x * z
            y = self.image_offset_y + c.center_y * z
            cr = c.enclosing_radius * z
            if not intersects(x, y, cr):
                continue
            self.canvas.create_oval(x-cr, y-cr, x+cr, y+cr,
                                    outline="#ef7d00", width=2, tags=("preview_layer",))
            self.canvas.create_text(x, y, text=c.candidate_id,
                                    fill="#be4d00", font=("Segoe UI", 9, "bold"),
                                    tags=("preview_layer",))
        # Labels are derived from the FINAL reviewed layout, not the detector's
        # temporary ID order. They always match the saved CSV and overlay.
        for numbered in number_column_major(self.current_entries, self._numbering_radius()):
            entry = numbered.entry
            x = self.image_offset_x + entry.center_x * z
            y = self.image_offset_y + entry.center_y * z
            rr = radius * z
            if not intersects(x, y, rr):
                continue
            color = "#008fe6" if entry.roi_id in self.manual_additions else "#06b52d"
            self.canvas.create_oval(x-rr, y-rr, x+rr, y+rr,
                                    outline=color, width=3, tags=("preview_layer",))
            self.canvas.create_text(x-rr, y-rr-10, anchor="sw",
                                    text=entry.roi_id.replace("ROI_", ""), fill="#163c93",
                                    font=("Segoe UI", 9, "bold"), tags=("preview_layer",))
        self.zoom_label.set(f"Zoom: {z*100:.0f}%" + (" (Fit)" if self.zoom_mode == "fit" else ""))

    def _image_pixel(self, event: tk.Event) -> tuple[int, int] | None:
        if self.source_image is None:
            return None
        return source_pixel_from_world(
            self.canvas.canvasx(event.x), self.canvas.canvasy(event.y),
            zoom=self.zoom_scale, offset_x=self.image_offset_x,
            offset_y=self.image_offset_y, image_width=self.source_image.width,
            image_height=self.source_image.height)

    def _checkpoint(self) -> None:
        self.undo_stack.append((copy.copy(self.manual_additions), set(self.manual_removed),
                                set(self.dismissed_candidates), list(self.change_log)))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def add_at_click(self, event: tk.Event) -> None:
        """Snap to a rejected candidate, else refine locally with Hough circles."""
        if self.rgb is None or self.current_detection is None:
            return
        position = self._image_pixel(event)
        if position is None:
            return
        try:
            radius = self.chosen_radius()
            x, y = position
            used = {e.candidate_id for e in self.current_entries if e.candidate_id}
            candidate = nearest_candidate(
                self.current_detection.candidates, x, y,
                max(radius, self._candidate_search_radius()) * 1.0,
                used | self.dismissed_candidates,
            )
            if candidate is not None:
                cx, cy = round(candidate.center_x), round(candidate.center_y)
                roi_id = next((c.roi_id for c in self.detection.candidates
                               if c.candidate_id == candidate.candidate_id and c.roi_id),
                              f"ROI_{candidate.candidate_id}")
                source = "manual_candidate"
                flags = "manual_recovery;review_center_and_radius"
                candid = candidate.candidate_id
                cand_rad = candidate.detector_radius
            else:
                refined = refine_click_hough(self.rgb, x, y, self._candidate_search_radius())
                if refined is not None:
                    cx, cy = refined
                    source = "manual_hough"
                    flags = "manual_hough_refinement;review_center_and_radius"
                else:
                    confirmed = messagebox.askyesno(
                        "Approximate Center Only",
                        "No reliable candidate or local circle was found near the click. "
                        "Use the approximate clicked position anyway? It will be FLAGGED for review.",
                    )
                    if not confirmed:
                        return
                    cx, cy = x, y
                    source = "manual_click"
                    flags = "unverified_click_center;manual_review_required"
                self.manual_index += 1
                roi_id = f"ROI_M{self.manual_index:03d}"
                candid = ""
                cand_rad = None
            if any(math.hypot(e.center_x - cx, e.center_y - cy) < radius * 0.70
                   for e in self.current_entries):
                self.status.set("This location is already covered by an accepted ROI. Right-click it to remove first.")
                return
            roi_window(ROI(roi_id, cx, cy, radius), self.rgb.shape)
            self._checkpoint()
            entry = ReviewEntry(roi_id, cx, cy, source, candid, cand_rad, flags)
            self.manual_additions[roi_id] = entry
            self.manual_removed.discard(roi_id)
            self.change_log.append({"action": "add_or_recover", "roi_id": roi_id,
                                    "origin": source, "click_x": x, "click_y": y,
                                    "refined_x": cx, "refined_y": cy,
                                    "candidate_id": candid, "qc_flags": flags})
            self.refresh_preview()
        except (ValueError, cv2.error) as exc:
            messagebox.showwarning("Unable to Add ROI", str(exc))

    def remove_at_click(self, event: tk.Event) -> None:
        """Right-click a green ROI to exclude, or an orange candidate to hide.

        Hidden candidates cannot be clicked or automatically reselected by
        future radius changes. The user may still place a NEW ROI through local
        Hough refinement at the same position. Undo and Reset restore candidates.
        """
        if self.current_detection is None:
            return
        pos = self._image_pixel(event)
        if pos is None:
            return
        x, y = pos
        radius = self.chosen_radius()
        accepted = min(self.current_entries,
                       key=lambda e: math.hypot(e.center_x-x, e.center_y-y),
                       default=None)
        accepted_distance = (math.hypot(accepted.center_x-x, accepted.center_y-y)
                             if accepted is not None else math.inf)
        accepted_hit = accepted is not None and accepted_distance <= radius * 1.1

        used = {e.candidate_id for e in self.current_entries if e.candidate_id}
        rejected_hits = []
        for candidate in self.current_detection.candidates:
            if candidate.candidate_id in used or candidate.candidate_id in self.dismissed_candidates:
                continue
            distance = math.hypot(candidate.center_x-x, candidate.center_y-y)
            if distance <= candidate.enclosing_radius * 1.1:
                rejected_hits.append((distance, candidate.candidate_id, candidate))
        rejected = min(rejected_hits, default=None)

        # If both overlays are near the click, use the closer center. This
        # preserves the original behavior when the green ROI is the target.
        if rejected is not None and (not accepted_hit or rejected[0] < accepted_distance):
            candidate = rejected[2]
            self._checkpoint()
            self.dismissed_candidates.add(candidate.candidate_id)
            self.change_log.append({"action": "dismiss_candidate",
                                    "candidate_id": candidate.candidate_id,
                                    "candidate_center_x": candidate.center_x,
                                    "candidate_center_y": candidate.center_y,
                                    "click_x": x, "click_y": y})
            self.refresh_preview()
            return
        if not accepted_hit:
            return
        self._checkpoint()
        self.manual_additions.pop(accepted.roi_id, None)
        self.manual_removed.add(accepted.roi_id)
        self.change_log.append({"action": "remove", "roi_id": accepted.roi_id,
                                "click_x": x, "click_y": y})
        self.refresh_preview()

    def undo_edit(self) -> None:
        if self.undo_stack:
            additions, removed, dismissed, changes = self.undo_stack.pop()
            self.manual_additions = additions
            self.manual_removed = removed
            self.dismissed_candidates = dismissed
            self.change_log = changes
            self.refresh_preview()

    def reset_edits(self) -> None:
        if not (self.manual_additions or self.manual_removed or self.dismissed_candidates):
            return
        self._checkpoint()
        self.manual_additions.clear()
        self.manual_removed.clear()
        self.dismissed_candidates.clear()
        self.change_log.append({"action": "reset_edits"})
        self.refresh_preview()

    def save_run(self) -> None:
        if self.image_path is None or self.detection is None or not self.current_entries:
            messagebox.showinfo("Measurement", "Load an image and accept at least one ROI first.")
            return
        try:
            radius = self.chosen_radius()
            channel = self.channel.get()
            numbered = number_column_major(self.current_entries, self._numbering_radius())
            reviewed_entries = [item.entry for item in numbered]
            for entry in reviewed_entries:
                roi_window(entry.to_roi(radius), self.rgb.shape)
            # The original CLI's verified manual-center measurement mode
            # guarantees that saved measurements use EXACTLY the reviewed ROIs.
            # Input CSV remains on disk for provenance and reruns.
            inputs_dir = RESULTS_ROOT / "review_inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            centers_path = inputs_dir / f"centers_{uuid.uuid4().hex}.csv"
            with centers_path.open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["roi_id", "center_x", "center_y"])
                writer.writeheader()
                writer.writerows([{"roi_id": e.roi_id, "center_x": e.center_x,
                                  "center_y": e.center_y} for e in reviewed_entries])
            parser = build_parser()
            cli_args = [
                str(self.image_path), "--channel", channel,
                "--centers-csv", str(centers_path), "--roi-radius", str(radius),
            ]
            for operation in self.orientation_ops:
                cli_args.extend(["--transform", operation])
            args = parser.parse_args(cli_args)
            self.info.set("Measuring reviewed ROIs and saving auditable results...")
            self.root.update_idletasks()
            result_dir, report = run(args)
            # Enforce that the CLI uses identical transformed coordinates and IDs.
            with (result_dir / "centers.csv").open(newline="", encoding="utf-8-sig") as stream:
                saved_centers = [(r["roi_id"], int(r["center_x"]), int(r["center_y"]))
                                 for r in csv.DictReader(stream)]
            expected_centers = [(e.roi_id, e.center_x, e.center_y) for e in reviewed_entries]
            if saved_centers != expected_centers:
                raise RuntimeError("Saved ROI IDs/centres do not match the reviewed preview")
            simple_csv = write_selected_channel_csv(result_dir, reviewed_entries)
            if self.detection.roi_radius is not None:
                write_radius_comparison(
                    result_dir, auto_radius=float(self.detection.roi_radius),
                    applied_radius=radius, mode=self.radius_mode.get(), channel=channel,
                )
            with (result_dir / "review_selection.csv").open("x", newline="", encoding="utf-8-sig") as stream:
                columns = ["roi_id", "original_review_id", "column", "row", "center_x", "center_y",
                           "source_center_x", "source_center_y", "analytical_radius", "source",
                           "candidate_id", "candidate_radius", "qc_flags"]
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows([{
                    "roi_id": item.entry.roi_id,
                    "original_review_id": item.previous_id,
                    "column": item.column, "row": item.row,
                    "center_x": item.entry.center_x, "center_y": item.entry.center_y,
                    "source_center_x": to_original_point(
                        item.entry.center_x, item.entry.center_y,
                        *self.source_dimensions, self.orientation_ops)[0],
                    "source_center_y": to_original_point(
                        item.entry.center_x, item.entry.center_y,
                        *self.source_dimensions, self.orientation_ops)[1],
                    "analytical_radius": radius, "source": item.entry.source,
                    "candidate_id": item.entry.candidate_id,
                    "candidate_radius": item.entry.candidate_radius,
                    "qc_flags": item.entry.qc_flags,
                } for item in numbered])
            with (result_dir / "review_log.json").open("x", encoding="utf-8") as stream:
                json.dump({
                    "image_path": str(self.image_path),
                    "channel": channel, "radius_mode": self.radius_mode.get(),
                    "initial_automatic_radius": self.detection.roi_radius,
                    "analytical_radius": radius,
                    "candidate_search_radius": self._candidate_search_radius(),
                    "candidate_search_follows_analytical_radius": self.match_radius_follows_roi.get(),
                    "candidate_radius_tolerance_fraction": self._tolerance(),
                    "accepted_roi_count": len(reviewed_entries),
                    "image_orientation_operations": self.orientation_ops,
                    "orientation_description": orientation_description(self.orientation_ops),
                    "coordinates": "ROI/CSV coordinates are in the losslessly oriented raster",
                    "numbering_rule": "column-major, left-to-right; top-to-bottom within columns",
                    "ordering_column_tolerance_px": max(2.0, 0.90 * self._numbering_radius()),
                    "numbering_map": [
                        {"roi_id": item.entry.roi_id, "original_review_id": item.previous_id,
                         "column": item.column, "row": item.row} for item in numbered],
                    "operations": self.change_log,
                    "removed_ids": sorted(self.manual_removed),
                    "dismissed_candidate_ids": sorted(self.dismissed_candidates),
                    "review_required": True,
                }, stream, indent=2, ensure_ascii=True)
            # An extra reviewed overlay is saved; CLI overlays are not altered.
            self._save_review_overlay(result_dir, radius, numbered)
            if report["roi_count"] != len(reviewed_entries):
                raise RuntimeError("Saved ROI count differs from reviewed selection")
            flagged = sum(bool(e.qc_flags) for e in reviewed_entries)
            try:
                append_run_history(
                    image=self.image_path, channel=channel,
                    detected_radius=float(self.detection.roi_radius or radius),
                    applied_radius=radius, roi_count=report["roi_count"],
                    qc_count=flagged, result_dir=result_dir,
                )
            except OSError as exc:
                messagebox.showwarning("History Save Warning", f"Measurement completed but history not updated: {exc}")
            self.last_output = result_dir
            self.open_button.config(state="normal")
            self.info.set(f"SAVED: {report['roi_count']} reviewed ROIs • {channel} channel • "
                          f"{radius:g} px / {format_area(roi_pixel_area(radius))} pixels • {simple_csv.name}")
            self.status.set(f"Results folder: {result_dir}. Review flags in review_selection.csv.")
            messagebox.showinfo(
                "Measurement Completed",
                f"Saved to:\n{result_dir}\n\n"
                "Selected channel: selected_channel_measurements.csv\n"
                "Review decisions: review_selection.csv and review_log.json\n"
                "Overlays: reviewed_roi_overlay.png, reviewed_candidate_overlay.png, "
                "selected_channel_roi_overlay.png",
            )
        except (ValueError, OSError, RuntimeError, cv2.error) as exc:
            self.info.set("Measurement failed; the original image was not modified.")
            messagebox.showerror("Measurement Error", str(exc))

    def _save_review_overlay(self, folder: Path, radius: float, numbered: list) -> None:
        image = Image.fromarray(self.rgb.copy())
        draw = ImageDraw.Draw(image)
        for item in numbered:
            entry = item.entry
            x, y = entry.center_x, entry.center_y
            color = (0, 130, 230) if item.previous_id in self.manual_additions else (0, 180, 20)
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=color, width=4)
            draw.text((x-radius, y-radius-18), entry.roi_id, fill=(20, 20, 160),
                      stroke_width=2, stroke_fill=(255, 255, 255))
        image.save(folder / "reviewed_roi_overlay.png", format="PNG")
        # Preserve the full candidate review context, not only the chosen masks.
        candidate_image = Image.fromarray(self.rgb.copy())
        candidate_draw = ImageDraw.Draw(candidate_image)
        included = {item.entry.candidate_id for item in numbered if item.entry.candidate_id}
        if self.current_detection is not None:
            for c in self.current_detection.candidates:
                if (c.candidate_id in included
                        or c.candidate_id in self.dismissed_candidates):
                    continue
                x, y, cr = c.center_x, c.center_y, c.enclosing_radius
                candidate_draw.ellipse((x-cr, y-cr, x+cr, y+cr),
                                       outline=(250, 140, 0), width=3)
                candidate_draw.text((x-18, y), c.candidate_id, fill=(180, 40, 0),
                                    stroke_width=2, stroke_fill=(255, 255, 255))
        for item in numbered:
            e = item.entry
            x, y = e.center_x, e.center_y
            color = (0, 130, 230) if item.previous_id in self.manual_additions else (0, 180, 20)
            candidate_draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                                   outline=color, width=4)
            candidate_draw.text((x-radius, y-radius-18), e.roi_id,
                                fill=(20, 20, 160), stroke_width=2,
                                stroke_fill=(255, 255, 255))
        candidate_image.save(folder / "reviewed_candidate_overlay.png", format="PNG")
        # Export only ONE selected-channel view, with matching ROI IDs.
        # Grayscale values are the original selected 8-bit channel; drawing
        # annotations happens on a copy and never changes measured values.
        channel_index = {"R": 0, "G": 1, "B": 2}[self.channel.get()]
        channel_image = Image.fromarray(self.rgb[:, :, channel_index].copy()).convert("RGB")
        channel_draw = ImageDraw.Draw(channel_image)
        # Match the accepted-ROI styling of the candidate overlay: every
        # reviewed ROI is green, including manually recovered or moved ROIs.
        # Use the final column-major IDs (not the original candidate IDs).
        # No rejected/orange candidates are shown on the channel image.
        for item in numbered:
            e = item.entry
            x, y = e.center_x, e.center_y
            channel_draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                                 outline=(0, 200, 0), width=4)
            channel_draw.text((x-radius, y-radius-18), e.roi_id,
                              fill=(255, 255, 0), stroke_width=2,
                              stroke_fill=(0, 0, 0))
        channel_image.save(folder / "selected_channel_roi_overlay.png", format="PNG")

    def open_last_output(self) -> None:
        if self.last_output is None:
            return
        if sys.platform == "win32":
            os.startfile(str(self.last_output))  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("Results Folder", str(self.last_output))


def main() -> None:
    root = tk.Tk()
    RoiTestApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
