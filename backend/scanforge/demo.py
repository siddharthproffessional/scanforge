"""Synthetic test scan: an iPhone-style PLY (metres, Y-up, noisy) of one room.

Room: 6 m x 4 m x 3 m, interior faces of the four outer walls, plus a 100 mm
partition at x = 3 m (both faces scanned) running from y = 0 to y = 2.5 m.
Used by the tests and by the "Try the sample scan" button.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement


def _plane(rng, n, x, y, z):
    return np.column_stack([rng.uniform(*x, n) if isinstance(x, tuple) else np.full(n, x),
                            rng.uniform(*y, n) if isinstance(y, tuple) else np.full(n, y),
                            rng.uniform(*z, n) if isinstance(z, tuple) else np.full(n, z)])


def make_room_ply(path: str | Path, seed: int = 1) -> Path:
    rng = np.random.default_rng(seed)
    W, D, H = 6.0, 4.0, 3.0
    parts = [
        _plane(rng, 60000, (0, W), (0, D), 0.0),          # floor
        _plane(rng, 60000, (0, W), (0, D), H),            # ceiling
        _plane(rng, 30000, (0, W), 0.0, (0, H)),          # outer walls, interior faces
        _plane(rng, 30000, (0, W), D, (0, H)),
        _plane(rng, 20000, 0.0, (0, D), (0, H)),
        _plane(rng, 20000, W, (0, D), (0, H)),
        _plane(rng, 12000, 2.95, (0, 2.5), (0, H)),       # partition, two faces
        _plane(rng, 12000, 3.05, (0, 2.5), (0, H)),
    ]
    pts = np.vstack(parts) + rng.normal(0, 0.004, (sum(len(p) for p in parts), 3))
    pts = np.vstack([pts, rng.uniform(-2, 8, (300, 3))])  # stray outliers
    # ARKit style: Y up. (x, y, z)_zup -> (x, z, -y)_yup
    yup = np.column_stack([pts[:, 0], pts[:, 2], -pts[:, 1]]).astype(np.float32)
    v = np.empty(len(yup), dtype=[("x", "f4"), ("y", "f4"), ("z", "f4")])
    v["x"], v["y"], v["z"] = yup[:, 0], yup[:, 1], yup[:, 2]
    path = Path(path)
    PlyData([PlyElement.describe(v, "vertex")]).write(str(path))
    return path
