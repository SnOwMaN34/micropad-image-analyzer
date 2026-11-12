"""Human-reviewed calibration projects for colorimetric microPAD measurements.

Independent of the ROI detector and GUI. Raw measurements are never changed by
assignment, regression, or exploratory outlier proposals.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from collections import defaultdict
from statistics import mean, median, stdev
from typing import Any
import csv
import hashlib
import json
import math
from pathlib import Path


@dataclass
class Zone:
    key: str
    run_id: str
    image_id: str
    roi_id: str
    intensity: float
    channel: str
    radius: float
    source_csv: str
    source_sha256: str
    role: str = "Unassigned"           # Blank / Standard / Ignore / Unassigned
    sample: str = ""                 # human-assigned sample name
    concentration: float | None = None
    blank_group: str = ""            # Blank IDs shared across pads if desired
    note: str = ""
    qc_flags: str = ""
    source_image_path: str = ""


@dataclass
class CalibrationProject:
    name: str = "New calibration"
    concentration_unit: str = "µM"
    zones: list[Zone] = field(default_factory=list)
    approved_exclusions: list[str] = field(default_factory=list)
    optimizer_max_per_group: int = 1
    optimizer_min_keep: int = 3
    optimizer_max_total: int = 10
    optimizer_mad_factor: float = 3.5
    optimizer_min_abs_a: float = 0.005
    optimizer_min_group_size: int = 4

    def to_dict(self) -> dict[str, Any]:
        return {"format": "micropad-calibration-project", "version": 1, "name": self.name,
                "concentration_unit": self.concentration_unit,
                "zones": [asdict(z) for z in self.zones],
                "approved_exclusions": list(self.approved_exclusions),
                "optimizer_max_per_group": self.optimizer_max_per_group,
                "optimizer_min_keep": self.optimizer_min_keep,
                "optimizer_max_total": self.optimizer_max_total,
                "optimizer_mad_factor": self.optimizer_mad_factor,
                "optimizer_min_abs_a": self.optimizer_min_abs_a,
                "optimizer_min_group_size": self.optimizer_min_group_size}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'CalibrationProject':
        if data.get("format") != "micropad-calibration-project" or data.get("version") != 1:
            raise ValueError("Unsupported calibration project format")
        return cls(name=data.get("name", "New calibration"),
                   concentration_unit=data.get("concentration_unit", "µM"),
                   zones=[Zone(**v) for v in data.get("zones", [])],
                   approved_exclusions=list(data.get("approved_exclusions", [])),
                   optimizer_max_per_group=int(data.get("optimizer_max_per_group", 1)),
                   optimizer_min_keep=int(data.get("optimizer_min_keep", 3)),
                   optimizer_max_total=int(data.get("optimizer_max_total", 10)),
                   optimizer_mad_factor=float(data.get("optimizer_mad_factor", 3.5)),
                   optimizer_min_abs_a=float(data.get("optimizer_min_abs_a", 0.005)),
                   optimizer_min_group_size=int(data.get("optimizer_min_group_size", 4)))

    def save(self, filename: str | Path) -> None:
        Path(filename).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, filename: str | Path) -> 'CalibrationProject':
        return cls.from_dict(json.loads(Path(filename).read_text(encoding="utf-8")))

    def add_run(self, path: str | Path) -> int:
        """Import reviewed result CSV; same run ID may not be imported twice.

        CSV hash and relative result folder identity are retained for provenance.
        Only user-approved GUI runs should be imported. This function deliberately
        does not infer sample types or concentrations from spatial positions.
        """
        p = Path(path)
        csv_file = p / "selected_channel_measurements.csv" if p.is_dir() else p
        if csv_file.name != "selected_channel_measurements.csv":
            raise ValueError("Select a reviewed run's selected_channel_measurements.csv file")
        if not csv_file.is_file():
            raise FileNotFoundError(csv_file)
        review = csv_file.parent / "review_selection.csv"
        audit = csv_file.parent / "review_log.json"
        if not (review.is_file() and audit.is_file()):
            raise ValueError("This folder lacks review_selection.csv or review_log.json. Only reviewed runs are accepted.")
        audit_data = json.loads(audit.read_text(encoding="utf-8"))
        if not audit_data.get("review_required"):
            raise ValueError("The selected run does not contain a valid manual-review record")
        source_path = str(audit_data.get("image_path", "")).strip()
        if not source_path:
            raise ValueError("Review metadata does not identify the original image file")
        normalized_source = str(Path(source_path)).casefold()
        if any(z.source_image_path.casefold() == normalized_source for z in self.zones):
            raise ValueError("This source image was already imported. A duplicate scan must be handled explicitly, not counted twice")
        sha = hashlib.sha256(csv_file.read_bytes()).hexdigest()
        # A repeat of the same CSV in another location is treated as the same run.
        run_id = hashlib.sha256((sha+normalized_source).encode("utf-8")).hexdigest()[:16]
        if any(z.run_id == run_id for z in self.zones):
            raise ValueError("This reviewed run has already been added to the project")
        new_zones = []
        with csv_file.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            required = {"image_id", "roi_id", "mean_intensity", "channel", "radius"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError("Reviewed CSV is missing one or more required fields")
            for row in reader:
                intensity = float(row["mean_intensity"])
                if not math.isfinite(intensity) or not 0 < intensity <= 65535:
                    raise ValueError("Mean intensity must be finite and greater than zero")
                roi = row["roi_id"].strip()
                if not roi or any(z.roi_id == roi for z in new_zones):
                    raise ValueError("Each imported ROI ID must be unique within its run")
                new_zones.append(Zone(key=f"{run_id}:{roi}", run_id=run_id,
                                      image_id=row["image_id"], roi_id=roi, intensity=intensity,
                                      channel=row["channel"], radius=float(row["radius"]),
                                      source_csv=str(csv_file.resolve()), source_sha256=sha,
                                      qc_flags=row.get("qc_flags", ""),
                                      source_image_path=source_path))
        if not new_zones:
            raise ValueError("Reviewed run has no ROI measurements")
        self.zones.extend(new_zones)
        self.approved_exclusions = []
        return len(new_zones)

    def remove_run(self, run_id: str) -> int:
        before = len(self.zones)
        self.zones = [z for z in self.zones if z.run_id != run_id]
        keys = {z.key for z in self.zones}
        self.approved_exclusions = [k for k in self.approved_exclusions if k in keys]
        return before - len(self.zones)

    def validate(self) -> None:
        if not self.name.strip() or not self.concentration_unit.strip():
            raise ValueError("Calibration name and concentration unit are required")
        usable = [z for z in self.zones if z.role != "Ignore"]
        if not usable:
            raise ValueError("Add reviewed ROI measurements before calibration")
        if any(z.role not in {"Blank", "Standard", "Ignore", "Unassigned"} for z in usable):
            raise ValueError("Invalid ROI assignment type")
        if any(z.role == "Unassigned" for z in usable):
            raise ValueError("Assign every ROI as Blank, Standard, or Ignore before exporting")
        blank_groups: dict[str, list[Zone]] = defaultdict(list)
        for z in usable:
            if z.role == "Blank":
                if not z.blank_group.strip():
                    raise ValueError(f"Blank {z.key} requires a blank group name")
                blank_groups[z.blank_group].append(z)
        standard = [z for z in usable if z.role == "Standard"]
        if not standard:
            raise ValueError("No standards are assigned")
        for z in standard:
            if not z.blank_group or z.blank_group not in blank_groups:
                raise ValueError(f"Standard {z.key} has no existing blank group: {z.blank_group or '(empty)'}")
            if z.concentration is None or not math.isfinite(z.concentration) or z.concentration < 0:
                raise ValueError(f"Standard {z.key} requires a nonnegative finite concentration")
        if any(z.role == "Blank" and z.concentration is not None for z in usable):
            raise ValueError("Blank zones must not have standard concentrations")
        sample_concentrations = defaultdict(set)
        for z in standard:
            if z.sample.strip():
                sample_concentrations[z.sample.strip()].add(z.concentration)
        if any(len(values)>1 for values in sample_concentrations.values()):
            raise ValueError("One standard label is assigned to multiple concentrations; review assignments")
        if len({z.concentration for z in standard}) < 3:
            raise ValueError("At least three distinct standard concentrations are required")
        channels = {z.channel for z in usable}
        if len(channels) != 1:
            raise ValueError("All ROI measurements in one calibration must use the same RGB channel")
        if len(self.approved_exclusions) != len(set(self.approved_exclusions)):
            raise ValueError("Duplicate approved exclusion IDs")
        if any(k not in {z.key for z in standard} for k in self.approved_exclusions):
            raise ValueError("Approved exclusions must refer to standards in the current project")

    def computed_rows(self) -> list[dict[str, Any]]:
        self.validate()
        blank_groups: dict[str, list[Zone]] = defaultdict(list)
        for z in self.zones:
            if z.role == "Blank":
                blank_groups[z.blank_group].append(z)
        blank_means = {name: mean(z.intensity for z in group) for name, group in blank_groups.items()}
        rows=[]
        for z in self.zones:
            bm = blank_means.get(z.blank_group)
            a = math.log10(bm/z.intensity) if bm and z.role in {"Standard", "Blank"} else None
            rows.append({**asdict(z), "blank_mean": bm, "absorbance": a})
        return rows


def group_summary(rows: list[dict[str, Any]], *, excluded: set[str] | None = None) -> list[dict[str, Any]]:
    excluded=excluded or set()
    grouped=defaultdict(list)
    for r in rows:
        if r["role"] == "Standard" and r["key"] not in excluded:
            grouped[float(r["concentration"])].append(float(r["absorbance"]))
    output=[]
    for concentration, values in sorted(grouped.items()):
        output.append({"concentration": concentration, "n": len(values),
                       "mean_absorbance": mean(values),
                       "sd_absorbance": stdev(values) if len(values)>1 else 0.0,
                       "radii": "", "values": values})
    return output


def fit_calibration(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Ordinary least squares on concentration-level mean absorbances.

    No automatic blank-as-zero point, no forced intercept, no weighting.
    """
    if len(points)<3:
        raise ValueError("Calibration requires at least three concentration groups")
    xs=[float(p["concentration"]) for p in points]
    ys=[float(p["mean_absorbance"]) for p in points]
    mx,my=mean(xs),mean(ys)
    ssx=sum((x-mx)**2 for x in xs)
    if ssx<=0:
        raise ValueError("Concentrations must not all be the same")
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/ssx
    intercept=my-slope*mx
    predicted=[intercept+slope*x for x in xs]
    sse=sum((y-f)**2 for y,f in zip(ys,predicted))
    sst=sum((y-my)**2 for y in ys)
    if sst<=1e-24:
        raise ValueError("All response means are equal; calibration R² is undefined")
    r2=1-sse/sst
    rmse=math.sqrt(sse/len(xs))
    return {"slope": slope,"intercept": intercept,"r2":r2,"rmse":rmse,
            "n_concentration_groups":len(points), "n_replicates":sum(int(p["n"]) for p in points),
            "points":[{**p,"fitted_absorbance": yhat,"residual":y-yhat}
                      for p,y,yhat in zip(points,ys,predicted)]}


def analyze(project: CalibrationProject, excluded: set[str] | None = None) -> dict[str, Any]:
    rows=project.computed_rows()
    excluded=excluded or set()
    summary=group_summary(rows, excluded=excluded)
    if len(summary)<3:
        raise ValueError("At least three concentrations must remain after exclusions")
    return {"rows":rows,"groups":summary,"fit":fit_calibration(summary),"excluded":sorted(excluded)}


def propose_exclusions(project: CalibrationProject) -> dict[str, Any]:
    """Make *review-only* statistically screened calibration exclusion proposals.

    A candidate must pass the same strict screening logic as the earlier
    comparison/QC workbook: within-concentration modified MAD score >= 3.5 by
    default, absolute absorbance deviation >= 0.005, and group size >= 4.
    At most one candidate per concentration is proposed by default, and at
    least three replicates remain. Eligible candidates are ranked by their
    positive *incremental* R² gain. A better R² alone can never flag a zone.
    The full measurement dataset and calibration are never overwritten.
    """
    base = analyze(project)
    rows = base["rows"]
    standard = [r for r in rows if r["role"] == "Standard"]
    excluded: set[str] = set()
    proposals: list[dict[str, Any]] = []
    current = base
    max_per = max(0, int(project.optimizer_max_per_group))
    min_keep = max(3, int(project.optimizer_min_keep))
    max_total = max(0, int(project.optimizer_max_total))
    score_threshold = max(0.0, float(project.optimizer_mad_factor))
    abs_threshold = max(0.0, float(project.optimizer_min_abs_a))
    min_group = max(4, int(project.optimizer_min_group_size))

    while len(excluded) < max_total:
        current_r2 = current["fit"]["r2"]
        groups: dict[float, list[dict[str, Any]]] = defaultdict(list)
        for r in standard:
            if r["key"] not in excluded:
                groups[float(r["concentration"])].append(r)
        best_choice = None
        for concentration, group in groups.items():
            original_size = sum(float(z["concentration"]) == concentration for z in standard)
            already_removed = original_size - len(group)
            if (original_size < min_group or len(group) <= min_keep
                    or already_removed >= max_per):
                continue
            values = [float(r["absorbance"]) for r in group]
            center = median(values)
            mad = median(abs(v - center) for v in values)
            scaled_mad = 1.4826 * mad
            for r in group:
                deviation = abs(float(r["absorbance"]) - center)
                modified_score = deviation / scaled_mad if scaled_mad > 1e-14 else (float("inf") if deviation > 1e-14 else 0.0)
                if deviation < abs_threshold or modified_score < score_threshold:
                    continue
                try:
                    trial = analyze(project, excluded | {r["key"]})
                except ValueError:
                    continue
                delta = trial["fit"]["r2"] - current_r2
                if delta <= 1e-9:
                    continue
                rank = (-delta, -deviation, str(r["key"]))
                if best_choice is None or rank < best_choice[0]:
                    best_choice = (rank, r, trial, delta, deviation, mad, modified_score)
        if best_choice is None:
            break
        _rank, r, trial, delta, deviation, mad, score = best_choice
        excluded.add(r["key"])
        proposals.append({
            "key": r["key"], "roi_id": r["roi_id"], "image_id": r["image_id"],
            "concentration": r["concentration"], "absorbance": r["absorbance"],
            "deviation_from_group_median": deviation,
            "group_mad": mad,
            "modified_mad_score": score if math.isfinite(score) else None,
            "r2_before": current_r2, "r2_after": trial["fit"]["r2"],
            "delta_r2": delta,
            "reason": "Within-concentration modified MAD screen and absolute A deviation passed; R² improved. Human verification required.",
        })
        current = trial
    return {"baseline": base, "proposed": current, "proposals": proposals,
            "disclaimer": "EXPLORATORY ONLY: R² improvement is not evidence of an invalid measurement. Inspect raw image and documented QC before excluding."}
