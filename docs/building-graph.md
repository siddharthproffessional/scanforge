# Building graph

The building graph is the one model every step reads and writes. IFC and Revit are both *exports* of it.

- Code: `backend/scanforge/graph.py` (Pydantic)
- JSON Schema: `schema/building_graph.schema.json` (regenerate with `python -m scanforge.schema`)
- Example: `samples/sample_room.graph.json`

## Conventions

- Millimetres, Z up, origin at the project base point.
- A wall's `baseline` is its **centreline**. Revit builds it with Location Line = Wall Centerline.
- Doors and windows are hosted: `host_id` = wall id, `offset_along` = distance from the wall's start to the opening's centre.
- Pipes, ducts, conduit and cable trays are polylines (`path`) with a section (`diameter`, or `width` + `height`) and a `system_id`.

## Provenance on every element

| Field | Meaning |
|---|---|
| `source` | `observed` (seen in scan/frames) · `inferred` (deduced) · `from_drawings` · `user` |
| `confidence` | 0–1. Below the threshold, the vision reviewer checks it. |
| `evidence` | Point count, frame ids, drawing refs, notes |
| `qa` | Deviation from the scan and pass/fail status |
| `exports` | IFC GUID and Revit element id after export |

`source` and `confidence` are written to IFC as the `ScanForge_Provenance` property set and to Revit as shared parameters `SF_GraphId` / `SF_Source`.

## Top-level sections

`project` · `levels` · `types` (graph type → Revit family/type, IFC class) · `systems` (circuits, pipe and duct systems) · `elements` · `questions` (agent → user) · `history` (every edit, by whom).
