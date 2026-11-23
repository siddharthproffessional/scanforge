"""Segment: give every point a label.

`segment()` is the interface the rest of the pipeline uses. The default
implementation is a geometric baseline (height bands) so the pipeline runs end to
end today. Replace `_model_segment` with a trained point-cloud model
(e.g. Point Transformer via Pointcept) on the GPU worker, then fuse 2D labels
projected from the registered 360 frames.
"""
from __future__ import annotations

import numpy as np

from .ingest import Cloud

LABELS = ["unlabelled", "floor", "ceiling", "wall", "door", "window", "column",
          "light_fixture", "pipe", "duct", "clutter"]
L = {name: i for i, name in enumerate(LABELS)}


def segment(c: Cloud, level: dict, band_mm: float = 80.0, use_model: bool = False):
    """Return (labels, confidence) arrays for the points of one storey."""
    if use_model:
        return _model_segment(c, level)
    z = c.xyz[:, 2]
    labels = np.full(len(c), L["clutter"], dtype=np.int16)
    conf = np.full(len(c), 0.3, dtype=np.float32)
    floor = np.abs(z - level["elevation"]) < band_mm
    ceil = np.abs(z - level["ceiling"]) < band_mm
    # wall candidates: tall band between floor and ceiling, refined later by plane fitting
    mid = (z > level["elevation"] + 300) & (z < level["ceiling"] - 300)
    labels[floor], conf[floor] = L["floor"], 0.9
    labels[ceil], conf[ceil] = L["ceiling"], 0.85
    labels[mid] = L["wall"]
    conf[mid] = 0.5
    return labels, conf


def _model_segment(c: Cloud, level: dict):
    raise NotImplementedError("Plug in the GPU segmentation model here")
