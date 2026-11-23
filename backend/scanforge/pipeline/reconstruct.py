"""Rebuild geometry: wall points -> wall centrelines with thickness.

Method
------
1. Project wall-labelled points to the floor plane.
2. Iteratively fit 2D lines with RANSAC (one line = one wall face).
3. Pair parallel faces 50-400 mm apart into one wall (thickness = gap).
   A face with no partner (the outer face wasn't scanned) gets the default
   thickness and is pushed outward by half of it.
4. Snap wall ends to each other so corners join.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..graph import Evidence, Source, Wall


@dataclass
class Face:
    p0: np.ndarray
    p1: np.ndarray
    normal: np.ndarray
    inliers: int
    rms: float

    @property
    def direction(self) -> np.ndarray:
        d = self.p1 - self.p0
        return d / np.linalg.norm(d)

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.p1 - self.p0))


def _fit_line(pts: np.ndarray):
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    d = vt[0]
    return c, d, np.array([-d[1], d[0]])


def ransac_faces(xy: np.ndarray, dist_mm: float = 15.0, min_inliers: int = 300,
                 min_length_mm: float = 500.0, iters: int = 400, max_faces: int = 60,
                 seed: int = 0) -> list[Face]:
    rng = np.random.default_rng(seed)
    remaining = xy.copy()
    faces: list[Face] = []
    while len(remaining) > min_inliers and len(faces) < max_faces:
        best = None
        for _ in range(iters):
            a, b = remaining[rng.choice(len(remaining), 2, replace=False)]
            d = b - a
            n = np.linalg.norm(d)
            if n < 100:
                continue
            normal = np.array([-d[1], d[0]]) / n
            mask = np.abs((remaining - a) @ normal) < dist_mm
            if best is None or mask.sum() > best.sum():
                best = mask
        if best is None or best.sum() < min_inliers:
            break
        pts = remaining[best]
        c, d, normal = _fit_line(pts)
        t = (pts - c) @ d
        # keep the largest continuous stretch (gaps > 1.5 m split separate walls)
        order = np.sort(t)
        gaps = np.where(np.diff(order) > 1500)[0]
        bounds = np.split(order, gaps + 1)
        seg = max(bounds, key=len)
        t0, t1 = seg[0], seg[-1]
        in_seg = (t >= t0) & (t <= t1)
        rms = float(np.sqrt(np.mean(((pts[in_seg] - c) @ normal) ** 2)))
        if t1 - t0 >= min_length_mm:
            faces.append(Face(c + d * t0, c + d * t1, normal, int(in_seg.sum()), rms))
        # remove the points used (whole line band) and continue
        idx = np.where(best)[0]
        remaining = np.delete(remaining, idx[in_seg] if t1 - t0 >= min_length_mm else idx, axis=0)
    return faces


def faces_to_walls(faces: list[Face], level_id: str, height: float,
                   default_thickness: float = 200.0, interior_point: np.ndarray | None = None,
                   min_t: float = 50.0, max_t: float = 400.0, prefix: str = "W") -> list[Wall]:
    used = set()
    walls: list[Wall] = []
    centre = interior_point
    for i, f in enumerate(faces):
        if i in used:
            continue
        partner = None
        for j, g in enumerate(faces):
            if j == i or j in used:
                continue
            if abs(abs(f.direction @ g.direction) - 1) > 0.01:
                continue
            gap = abs((g.p0 - f.p0) @ f.normal)
            # must overlap along the wall direction
            t = sorted([(g.p0 - f.p0) @ f.direction, (g.p1 - f.p0) @ f.direction])
            overlap = min(t[1], f.length) - max(t[0], 0)
            if min_t <= gap <= max_t and overlap > 0.5 * min(f.length, g.length):
                partner = (j, g, gap)
                break
        if partner:
            j, g, gap = partner
            used.update({i, j})
            side = np.sign((g.p0 - f.p0) @ f.normal)
            off = f.normal * side * gap / 2
            thickness, source, conf = gap, Source.observed, 0.95
        else:
            used.add(i)
            # push outward (away from the room interior) by half the default thickness
            outward = f.normal
            if centre is not None and ((centre - f.p0) @ outward) > 0:
                outward = -outward
            off = outward * default_thickness / 2
            thickness, source, conf = default_thickness, Source.inferred, 0.75
        p0, p1 = f.p0 + off, f.p1 + off
        walls.append(Wall(
            id=f"{prefix}{len(walls) + 1}", level_id=level_id,
            baseline=((round(p0[0], 1), round(p0[1], 1)), (round(p1[0], 1), round(p1[1], 1))),
            thickness=round(float(thickness), 1), height=height,
            source=Source.observed, confidence=conf,
            params={"thickness_source": source.value, "face_rms_mm": round(f.rms, 1)},
            evidence=Evidence(point_count=f.inliers),
        ))
    return join_corners(walls)


def _intersect(a0, a1, b0, b1):
    da, db = a1 - a0, b1 - b0
    m = np.array([da, -db]).T
    if abs(np.linalg.det(m)) < 1e-9:
        return None
    s, _ = np.linalg.solve(m, b0 - a0)
    return a0 + s * da


def join_corners(walls: list[Wall], snap_mm: float = 400.0) -> list[Wall]:
    """Extend/trim wall ends to meet neighbours whose ends are within `snap_mm`."""
    pts = {w.id: [np.array(w.baseline[0]), np.array(w.baseline[1])] for w in walls}
    for i, a in enumerate(walls):
        for b in walls[i + 1:]:
            x = _intersect(*pts[a.id], *pts[b.id])
            if x is None:
                continue
            for ea in (0, 1):
                for eb in (0, 1):
                    if (np.linalg.norm(pts[a.id][ea] - x) < snap_mm
                            and np.linalg.norm(pts[b.id][eb] - x) < snap_mm):
                        pts[a.id][ea] = x.copy()
                        pts[b.id][eb] = x.copy()
                        a.joined_to.append(b.id)
                        b.joined_to.append(a.id)
    # T-junctions: an end near the middle of another wall moves onto that wall's centreline
    for a in walls:
        for ea in (0, 1):
            pa = pts[a.id][ea]
            for b in walls:
                if b is a or b.id in a.joined_to:
                    continue
                b0, b1 = pts[b.id]
                d = b1 - b0
                L = np.linalg.norm(d)
                t = (pa - b0) @ d / L ** 2
                if not 0.05 < t < 0.95:
                    continue
                foot = b0 + t * d
                if np.linalg.norm(pa - foot) < snap_mm:
                    x = _intersect(*pts[a.id], b0, b1)
                    if x is not None:
                        pts[a.id][ea] = x
                        a.joined_to.append(b.id)
                        b.joined_to.append(a.id)
    for w in walls:
        p0, p1 = pts[w.id]
        w.baseline = ((round(p0[0], 1), round(p0[1], 1)), (round(p1[0], 1), round(p1[1], 1)))
    return walls
