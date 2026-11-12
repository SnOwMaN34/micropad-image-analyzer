"""Read-only source decoding and manual-center CSV input for the CLI."""

import csv
import hashlib
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from micropad.measurement import validate_rgb
from micropad.roi import ROI


def load_rgb(path: Path) -> tuple[np.ndarray, dict]:
    """Decode native RGB without EXIF transforms, ICC conversion, or enhancement.

    OpenCV IMREAD_UNCHANGED preserves depth and ignores EXIF orientation. Pillow
    reads metadata only. Unsupported modes fail rather than silently convert.
    """
    data = path.read_bytes()
    with Image.open(BytesIO(data)) as header:
        if header.format not in ("JPEG", "PNG", "TIFF") or header.mode != "RGB":
            raise ValueError("Source must be a JPEG/PNG/TIFF with RGB mode; grayscale/alpha/CMYK are unsupported")
        if getattr(header, "n_frames", 1) != 1:
            raise ValueError("Multi-frame images are unsupported; provide a single-frame RGB image")
        exif = header.getexif()
        metadata = {
            "format": header.format, "width": header.width, "height": header.height,
            "source_mode": header.mode, "exif_orientation": exif.get(274),
            "dpi": [float(v) for v in header.info["dpi"]] if "dpi" in header.info else None,
            "embedded_icc_profile": bool(header.info.get("icc_profile")),
        }
    bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if bgr is None:
        raise ValueError(f"OpenCV could not decode {path}")
    validate_rgb(bgr)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if rgb.shape[:2] != (metadata["height"], metadata["width"]):
        raise ValueError("Decoder dimensions differ from native stored dimensions")
    rgb.setflags(write=False)
    metadata.update({
        "source_path": str(path.resolve()), "source_sha256": hashlib.sha256(data).hexdigest(),
        "dtype": str(rgb.dtype), "bits_per_channel": rgb.dtype.itemsize * 8,
        "decoded_rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
        "decoder": "OpenCV IMREAD_UNCHANGED followed by COLOR_BGR2RGB",
        "orientation_policy": "stored raster; no EXIF rotation or mirroring",
        "color_policy": "no ICC/gamma conversion, enhancement, rescaling, or normalization",
    })
    return rgb, metadata


def read_manual_centers(path: Path, radius: float) -> list[ROI]:
    """Read roi_id,center_x,center_y; preserve IDs/order and require integer centers.

    The measurement CSV itself can be reused as this input. Additional columns
    are ignored; radius is always explicitly supplied once for the entire image.
    """
    rois = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"roi_id", "center_x", "center_y"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Manual CSV needs roi_id,center_x,center_y columns")
        for line, row in enumerate(reader, 2):
            x, y = float(row["center_x"]), float(row["center_y"])
            if not x.is_integer() or not y.is_integer():
                raise ValueError(f"Manual CSV line {line}: centers must be integer native-pixel coordinates")
            rois.append(ROI(row["roi_id"].strip(), int(x), int(y), radius))
    if not rois or len({r.roi_id for r in rois}) != len(rois):
        raise ValueError("Manual centers must be nonempty with unique ROI IDs")
    if len({(r.center_x, r.center_y) for r in rois}) != len(rois):
        raise ValueError("Manual ROI centers must be unique")
    return rois
