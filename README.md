# ScanForge

LiDAR scans + 360 video → a building graph → **IFC** and a native **Revit** model, with AI agents handling judgement calls (unclear regions, family mapping, QA, Revit building).

> Working name. Status: **v0.1 skeleton**. The architecture pipeline runs end to end on point clouds (walls, floor slab, levels → IFC). Segmentation is a geometric baseline until the GPU model is plugged in.

## What works today

| Step | Status |
|---|---|
| Ingest E57, LAS/LAZ, PLY (scanner + iPhone), classify 360 video / phone images / drawings | ✅ |
| Clean: voxel downsample, outlier removal, auto up-axis (handles iPhone Y-up), level detection | ✅ |
| Segment | ⚙️ baseline (height bands). Plug in Point Transformer on GPU. |
| Rebuild walls: RANSAC faces → centrelines + thickness, corner and T-joins | ✅ |
| Building graph with provenance (observed / inferred / from drawings) | ✅ |
| IFC4 export: walls, slabs, ceilings, doors, windows, columns, rooms, lights, devices, pipes, ducts, conduit, systems | ✅ |
| API: create project, upload, process, graph, answer questions, export IFC | ✅ |
| Agents: orchestrator, vision reviewer, Revit builder (Claude API, tool use) | ⚙️ wired; vision frames + Revit MCP tools to connect |
| 360 frame registration (COLMAP), doors/windows from scans, MEP detection | ⏳ next |
| Web app (React + Three.js) | ⏳ see design canvas |

## Layout

```
backend/scanforge/
  graph.py              building graph (the neutral model)
  pipeline/ingest.py    readers + device/format detection + ffmpeg frame extraction
  pipeline/clean.py     downsample, outliers, up-axis, levels
  pipeline/segment.py   point labels (baseline now, ML model later)
  pipeline/reconstruct.py  walls from points
  pipeline/run.py       file -> graph
  export/ifc_export.py  graph -> IFC4
  agents/               Claude tool-use agents
  api.py                FastAPI
  cli.py                try it on a scan
schema/                 JSON Schema of the graph
samples/                example graph (arch + MEP)
docs/                   capture guide, graph conventions
revit/                  Revit builder plan (Revit API calls)
frontend/               web app plan
```

## Run it

```bash
cd backend
pip install -e ".[dev]"
pytest                                    # synthetic iPhone-style + scanner-style rooms
python -m scanforge.cli path/to/scan.e57 --name "My office"   # writes .graph.json + .ifc
uvicorn scanforge.api:app --reload        # API on :8000, docs at /docs
```

On the VPS: `cp .env.example .env`, add your Anthropic key (optional for the demo), then `SCANFORGE_PORT=32780 docker compose up -d --build`.

## Devices

Terrestrial scanner → E57. iPhone Pro → PLY/LAS/E57 from Polycam, 3D Scanner App or Dot3D. Samsung → photos/video only (no LiDAR on current Galaxy phones). 360 camera → equirectangular MP4. Details: [docs/capture-guide.md](docs/capture-guide.md).

## Live demo

**http://187.127.143.33:32780/** (Hostinger VPS, Docker). The API serves a demo page at `/`: run the sample scan or upload your own point cloud, watch the model rebuild over the scan in 3D, and download the IFC. Projects are deleted after 3 days (`SCANFORGE_KEEP_DAYS`).
