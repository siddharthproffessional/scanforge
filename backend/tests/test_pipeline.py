"""End-to-end tests on the synthetic room in scanforge.demo."""
from pathlib import Path

import numpy as np
from plyfile import PlyData

from scanforge.demo import make_room_ply
from scanforge.export.ifc_export import export_ifc
from scanforge.graph import BuildingGraph
from scanforge.pipeline.run import run_pointcloud

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_sample_graph_validates():
    g = BuildingGraph.model_validate_json((SAMPLES / "sample_room.graph.json").read_text())
    assert len(g.by_category("wall")) == 4


def test_synthetic_room(tmp_path):
    ply = tmp_path / "room_iphone.ply"
    make_room_ply(ply)
    g = run_pointcloud(ply, "Synthetic room")

    assert len(g.levels) == 1
    lv = g.levels[0]
    assert abs(lv.elevation) < 10 and abs(lv.height - 3000) < 20

    walls = g.by_category("wall")
    lengths = sorted(round(np.hypot(*(np.subtract(*w.baseline)))) for w in walls)
    # 4 outer walls + 1 partition
    assert len(walls) == 5, lengths
    partition = [w for w in walls if w.params["thickness_source"] == "observed"]
    assert len(partition) == 1 and abs(partition[0].thickness - 100) < 15
    assert abs(np.mean([w.baseline[0][0] for w in partition] + [w.baseline[1][0] for w in partition]) - 3000) < 30

    assert len(partition[0].joined_to) == 1          # T-joined to the outer wall
    assert min(abs(partition[0].baseline[0][1]), abs(partition[0].baseline[1][1])) > 90  # reaches its centreline

    out = export_ifc(g, tmp_path / "room.ifc")
    import ifcopenshell
    assert len(ifcopenshell.open(str(out)).by_type("IfcWall")) == 5


def _zup_points(ply: Path) -> np.ndarray:
    v = PlyData.read(str(ply))["vertex"].data
    yup = np.column_stack([v["x"], v["y"], v["z"]]).astype(np.float64)
    return np.column_stack([yup[:, 0], -yup[:, 2], yup[:, 1]])   # back to Z-up, metres


def test_terrestrial_formats(tmp_path):
    """Same room as a scanner would export it: Z-up, metres, E57 and LAZ."""
    import laspy
    import pye57
    ply = tmp_path / "room.ply"
    make_room_ply(ply)
    xyz = _zup_points(ply) + np.array([500.0, 200.0, 12.0])  # survey-style offset origin

    laz = tmp_path / "room.laz"
    hdr = laspy.LasHeader(point_format=3, version="1.4")
    hdr.scales, hdr.offsets = [0.001] * 3, xyz.min(axis=0)
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.write(str(laz))

    e57 = tmp_path / "room.e57"
    w = pye57.E57(str(e57), mode="w")
    w.write_scan_raw({"cartesianX": xyz[:, 0], "cartesianY": xyz[:, 1], "cartesianZ": xyz[:, 2]})
    w.close()

    for f in (laz, e57):
        g = run_pointcloud(f)
        assert g.project.sources[0].device == "terrestrial_lidar"
        assert len(g.levels) == 1 and abs(g.levels[0].height - 3000) < 20, f.name
        assert len(g.by_category("wall")) == 5, f.name
