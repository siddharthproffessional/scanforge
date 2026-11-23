"""Run the deterministic pipeline for one point cloud: file -> BuildingGraph.

The orchestrator agent calls this step by step (so it can retry a step with new
settings); `run_pointcloud` is the straight-through version used by tests and the CLI.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..graph import (BuildingGraph, Discipline, Level, Project, Slab, SourceFile)
from .clean import clean
from .ingest import classify_file, read_pointcloud
from .reconstruct import faces_to_walls, ransac_faces
from .segment import L, segment


MAX_POINTS = 20_000_000   # subsample above this so a small VPS doesn't run out of memory


def run_pointcloud(path: str | Path, project_name: str = "Untitled",
                   default_wall_thickness: float = 200.0,
                   preview_path: str | Path | None = None, preview_points: int = 80_000) -> BuildingGraph:
    info = classify_file(path)
    cloud = read_pointcloud(path)
    if len(cloud) > MAX_POINTS:
        keep = np.random.default_rng(0).choice(len(cloud), MAX_POINTS, replace=False)
        cloud = cloud.subset(np.sort(keep))
    cloud, levels = clean(cloud)
    if preview_path is not None:   # float32 xyz in mm, Z up, for the web viewer
        n = min(preview_points, len(cloud))
        idx = np.random.default_rng(0).choice(len(cloud), n, replace=False)
        cloud.xyz[idx].astype(np.float32).tofile(str(preview_path))

    g = BuildingGraph(project=Project(
        id="prj_" + Path(path).stem, name=project_name,
        disciplines=[Discipline.architecture],
        sources=[SourceFile(id="src_1", filename=Path(path).name, **{k: info[k] for k in ("kind", "device", "format")})],
    ))

    for i, lv in enumerate(levels):
        lid = f"L{i:02d}"
        height = lv["ceiling"] - lv["elevation"]
        g.levels.append(Level(id=lid, name=f"Level {i:02d}", elevation=lv["elevation"], height=height))
        mask = (cloud.xyz[:, 2] > lv["elevation"] - 200) & (cloud.xyz[:, 2] < lv["ceiling"] + 200)
        storey = cloud.subset(mask)
        labels, _ = segment(storey, lv)

        wall_xy = storey.xyz[labels == L["wall"], :2]
        floor_xy = storey.xyz[labels == L["floor"], :2]
        interior = floor_xy.mean(axis=0) if len(floor_xy) else None
        faces = ransac_faces(wall_xy)
        walls = faces_to_walls(faces, lid, height=height, interior_point=interior,
                               default_thickness=default_wall_thickness, prefix=f"{lid}-W")
        g.elements.extend(walls)

        if len(floor_xy) > 100:
            lo, hi = floor_xy.min(axis=0), floor_xy.max(axis=0)
            box = [(float(lo[0]), float(lo[1])), (float(hi[0]), float(lo[1])),
                   (float(hi[0]), float(hi[1])), (float(lo[0]), float(hi[1]))]
            g.elements.append(Slab(id=f"{lid}-S1", level_id=lid, kind="floor", boundary=box,
                                   thickness=150, confidence=0.6,
                                   params={"boundary_method": "bounding_box"}))
    return BuildingGraph.model_validate(g.model_dump())   # re-run reference checks
