"""Clean: downsample, drop noise, make Z point up, find floor levels.

Pure numpy/scipy so it runs on a small VPS. Swap in Open3D later for speed on
very large scans; the function signatures stay the same.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .ingest import Cloud


def voxel_downsample(c: Cloud, voxel_mm: float = 20.0) -> Cloud:
    keys = np.floor(c.xyz / voxel_mm).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    idx.sort()
    out = Cloud(c.xyz[idx], None if c.rgb is None else c.rgb[idx], dict(c.meta))
    out.meta["voxel_mm"] = voxel_mm
    return out


def remove_outliers(c: Cloud, k: int = 16, std_ratio: float = 2.5) -> Cloud:
    """Statistical outlier removal: drop points far from their neighbours."""
    tree = cKDTree(c.xyz)
    d, _ = tree.query(c.xyz, k=k + 1)
    mean_d = d[:, 1:].mean(axis=1)
    keep = mean_d < mean_d.mean() + std_ratio * mean_d.std()
    out = c.subset(keep)
    out.meta["outliers_removed"] = int((~keep).sum())
    return out


def _peakiness(values: np.ndarray, bin_mm: float = 50.0) -> float:
    """Floors and ceilings make huge spikes in the histogram of the up axis."""
    bins = max(int(np.ptp(values) / bin_mm), 1)
    h, _ = np.histogram(values, bins=bins)
    top = np.sort(h)[-2:].sum()
    return float(top) / max(len(values), 1)


def align_up(c: Cloud) -> Cloud:
    """Detect which axis is up (TLS: Z, ARKit/iPhone: usually Y) and rotate to Z-up."""
    scores = [_peakiness(c.xyz[:, i]) for i in range(3)]
    up = int(np.argmax(scores))
    xyz = c.xyz
    if up == 1:      # Y-up (right-handed): (x, y, z) -> (x, -z, y)
        xyz = np.column_stack([xyz[:, 0], -xyz[:, 2], xyz[:, 1]])
    elif up == 0:    # X-up: (x, y, z) -> (y, z, x)
        xyz = np.column_stack([xyz[:, 1], xyz[:, 2], xyz[:, 0]])
    xyz = xyz - np.array([0.0, 0.0, xyz[:, 2].min()])   # lowest point to z=0
    out = Cloud(xyz, c.rgb, dict(c.meta))
    out.meta["up_axis_detected"] = "xyz"[up]
    return out


def find_levels(c: Cloud, bin_mm: float = 50.0, min_share: float = 0.04,
                min_storey_mm: float = 2200.0) -> list[dict]:
    """Return storeys as {elevation, ceiling} pairs from horizontal-surface peaks."""
    z = c.xyz[:, 2]
    bins = max(int(np.ptp(z) / bin_mm), 1)
    h, edges = np.histogram(z, bins=bins)
    centres = (edges[:-1] + edges[1:]) / 2
    peaks = [centres[i] for i in range(len(h))
             if h[i] >= min_share * len(z)
             and h[i] == h[max(i - 2, 0): i + 3].max()]
    # merge peaks closer than one bin pair, then refine each to the median of its band
    merged: list[float] = []
    for p in sorted(peaks):
        if merged and p - merged[-1] < 3 * bin_mm:
            continue
        merged.append(p)
    merged = [float(np.median(z[np.abs(z - p) < bin_mm])) for p in merged]
    levels, i = [], 0
    while i < len(merged) - 1:
        floor, ceiling = merged[i], merged[i + 1]
        if ceiling - floor >= min_storey_mm:
            levels.append({"elevation": round(float(floor)), "ceiling": round(float(ceiling))})
        i += 1
    if not levels and len(merged) >= 2:
        levels.append({"elevation": round(float(merged[0])), "ceiling": round(float(merged[-1]))})
    return levels


def clean(c: Cloud, voxel_mm: float = 20.0) -> tuple[Cloud, list[dict]]:
    c = voxel_downsample(c, voxel_mm)
    c = remove_outliers(c)
    c = align_up(c)
    levels = find_levels(c)
    if levels:   # put the lowest finished floor at z = 0
        z0 = levels[0]["elevation"]
        c.xyz[:, 2] -= z0
        for lv in levels:
            lv["elevation"] -= z0
            lv["ceiling"] -= z0
    return c, levels
