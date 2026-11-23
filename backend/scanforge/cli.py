"""Try the pipeline on your own scan:

    python -m scanforge.cli path/to/scan.e57 --name "My office"

Writes <scan>.graph.json and <scan>.ifc next to the input.
"""
import argparse
from pathlib import Path

from .export.ifc_export import export_ifc
from .pipeline.run import run_pointcloud


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--name", default="Untitled")
    ap.add_argument("--wall-thickness", type=float, default=200.0, help="mm, used when only one face is scanned")
    a = ap.parse_args()
    scan = Path(a.scan)
    g = run_pointcloud(scan, a.name, default_wall_thickness=a.wall_thickness)
    gj = scan.with_suffix(".graph.json")
    gj.write_text(g.model_dump_json(indent=2))
    ifc = export_ifc(g, scan.with_suffix(".ifc"))
    print(f"levels: {[(l.name, l.elevation, l.height) for l in g.levels]}")
    for cat, counts in g.summary().items():
        print(f"  {cat}: {counts}")
    print(f"wrote {gj}\nwrote {ifc}")


if __name__ == "__main__":
    main()
