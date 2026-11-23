"""Write the JSON Schema for the building graph: python -m scanforge.schema"""
import json
from pathlib import Path

from .graph import BuildingGraph

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[2] / "schema" / "building_graph.schema.json"
    out.write_text(json.dumps(BuildingGraph.model_json_schema(), indent=2))
    print(f"wrote {out}")
