"""Ingest: read any supported capture into one internal form.

Supported capture devices (first release)
-----------------------------------------
- Terrestrial LiDAR scanner (Leica, Faro, Trimble, NavVis...): export E57 from the
  scanner's own software. LAS/LAZ also accepted. Native formats (.fls, .lgs, .rcp)
  are not read directly; ask the user to export E57.
- iPhone / iPad Pro with LiDAR: PLY, LAS/LAZ or E57 from apps such as Polycam,
  3D Scanner App or Dot3D. ARKit exports are usually Y-up, so the up axis is
  detected rather than assumed.
- Samsung / Android phones: current Galaxy phones have no LiDAR, so they give
  photos or video only. These go through photogrammetry (COLMAP) and are mainly
  used as extra imagery for the vision reviewer.
- 360 camera: equirectangular MP4. Insta360 .insv must be exported to MP4 first.

Internal form: `Cloud` = float64 XYZ in millimetres, Z up, optional uint8 RGB.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

POINTCLOUD_EXT = {".e57", ".las", ".laz", ".ply"}
VIDEO_EXT = {".mp4", ".mov"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic"}
DRAWING_EXT = {".pdf", ".dwg", ".dxf"}
NEEDS_EXPORT = {
    ".fls": "Faro native scan: export E57 from SCENE",
    ".lgs": "Leica native scan: export E57 from Cyclone / Register 360",
    ".rcp": "ReCap project: export E57 from ReCap",
    ".rcs": "ReCap scan: export E57 from ReCap",
    ".insv": "Insta360 file: export an equirectangular MP4 from Insta360 Studio",
}


class UnsupportedInput(ValueError):
    pass


@dataclass
class Cloud:
    xyz: np.ndarray                      # (N, 3) float64, millimetres
    rgb: Optional[np.ndarray] = None     # (N, 3) uint8
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.xyz)

    def subset(self, mask: np.ndarray) -> "Cloud":
        return Cloud(self.xyz[mask], None if self.rgb is None else self.rgb[mask], dict(self.meta))


def classify_file(path: str | Path) -> dict:
    """Decide what a file is and which device probably made it."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in NEEDS_EXPORT:
        raise UnsupportedInput(f"{p.name}: {NEEDS_EXPORT[ext]}")
    if ext in POINTCLOUD_EXT:
        device = "iphone_lidar" if ext == ".ply" else "terrestrial_lidar"
        return {"kind": "pointcloud", "format": ext[1:], "device": device}
    if ext in VIDEO_EXT:
        info = probe_video(p) if p.exists() else {}
        w, h = info.get("width", 0), info.get("height", 0)
        is_360 = bool(w and h and abs(w / h - 2.0) < 0.05)   # equirectangular is 2:1
        return {"kind": "video360" if is_360 else "images",
                "format": ext[1:],
                "device": "camera_360" if is_360 else "android_camera",
                **info}
    if ext in IMAGE_EXT:
        return {"kind": "images", "format": ext[1:], "device": "android_camera"}
    if ext in DRAWING_EXT:
        return {"kind": "drawing", "format": ext[1:], "device": "other"}
    raise UnsupportedInput(f"{p.name}: unsupported file type {ext or '(none)'}")


# ---------------------------------------------------------------- readers
def _to_mm(xyz: np.ndarray, unit_hint: Optional[str]) -> tuple[np.ndarray, str]:
    """Scans are almost always in metres. Use the extent to catch the odd mm file."""
    if unit_hint == "mm":
        return xyz, "mm"
    extent = float(np.ptp(xyz, axis=0).max()) if len(xyz) else 0.0
    if extent > 2000:          # >2 km in metres is implausible for a building scan
        return xyz, "mm"
    return xyz * 1000.0, "m"


def read_pointcloud(path: str | Path, unit_hint: Optional[str] = None) -> Cloud:
    p = Path(path)
    ext = p.suffix.lower()
    rgb = None
    if ext == ".e57":
        import pye57
        e57 = pye57.E57(str(p))
        parts, colours = [], []
        for i in range(e57.scan_count):
            d = e57.read_scan(i, ignore_missing_fields=True, colors=True, transform=True)
            parts.append(np.column_stack([d["cartesianX"], d["cartesianY"], d["cartesianZ"]]))
            if "colorRed" in d:
                colours.append(np.column_stack([d["colorRed"], d["colorGreen"], d["colorBlue"]]))
        xyz = np.vstack(parts).astype(np.float64)
        if colours and len(colours) == len(parts):
            rgb = np.vstack(colours).astype(np.uint8)
    elif ext in {".las", ".laz"}:
        import laspy
        las = laspy.read(str(p))
        xyz = np.column_stack([las.x, las.y, las.z]).astype(np.float64)
        if {"red", "green", "blue"} <= set(las.point_format.dimension_names):
            c = np.column_stack([las.red, las.green, las.blue])
            rgb = (c >> 8).astype(np.uint8) if c.max() > 255 else c.astype(np.uint8)
    elif ext == ".ply":
        from plyfile import PlyData
        v = PlyData.read(str(p))["vertex"].data
        xyz = np.column_stack([v["x"], v["y"], v["z"]]).astype(np.float64)
        if {"red", "green", "blue"} <= set(v.dtype.names):
            rgb = np.column_stack([v["red"], v["green"], v["blue"]]).astype(np.uint8)
    else:
        raise UnsupportedInput(f"{p.name}: not a point cloud")
    xyz, unit = _to_mm(xyz, unit_hint)
    return Cloud(xyz, rgb, {"source": p.name, "input_unit": unit, "points_in": len(xyz)})


# ---------------------------------------------------------------- video / images
def probe_video(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    j = json.loads(out.stdout)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": float(num) / float(den), "duration_s": float(j["format"]["duration"])}


def extract_frames(video: str | Path, out_dir: str | Path, every_s: float = 1.0) -> list[Path]:
    """Pull one frame every `every_s` seconds. The orchestrator lowers this where
    scan overlap is weak; pose estimation (COLMAP) then registers them to the cloud."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video),
         "-vf", f"fps=1/{every_s}", "-q:v", "2", str(out / "f_%05d.jpg")],
        check=True)
    return sorted(out.glob("f_*.jpg"))
