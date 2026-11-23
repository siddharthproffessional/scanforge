# Capture guide: which device gives what

| Device | What it gives | Accuracy | Export from | Role in the pipeline |
|---|---|---|---|---|
| Terrestrial LiDAR scanner (Leica, Faro, Trimble, NavVis…) | Dense point cloud, often with colour | Millimetres | Scanner software → **E57** (or LAS/LAZ). Native `.fls` / `.lgs` / `.rcp` are not read: export E57. | Main geometry source. Walls, slabs, columns, exposed MEP. |
| iPhone / iPad Pro (LiDAR) | Point cloud or mesh plus posed photos | Roughly centimetres; drifts over large areas | Polycam (point-cloud export needs a paid plan), 3D Scanner App or Dot3D → **PLY / LAS / E57** | Small spaces, quick surveys, filling gaps the big scanner missed. |
| Samsung / Android phone | Photos and video only (current Galaxy phones have no LiDAR) | Lower; needs photogrammetry | Camera roll → JPG / MP4 | Extra imagery for the vision reviewer (fixtures, labels, glass vs opening). Optional photogrammetry point cloud later. |
| 360 camera (Insta360, Ricoh Theta…) | Equirectangular video | No depth on its own | Export **equirectangular MP4** (Insta360 `.insv` → Insta360 Studio) | Meaning, not geometry: door vs opening, glass, light types, signage, MEP labels. |

## Capture rules that matter for BIM quality

1. **Overlap scans by about 30%** so they register to each other.
2. **Walk the 360 camera slowly (around 1 m/s)** and keep it above head height so it sees ceilings.
3. **Lift ceiling tiles** in corridors and plant rooms and scan above them, or the pipes and ducts there will only be *inferred*.
4. **Scan plant rooms and risers**: they hold most of the visible MEP.
5. **Best case: scan during construction**, before walls are closed. All wiring and pipes are visible then.
6. Upload any **old drawings** (PDF/DWG). The drawing reader uses them for what the scan can't see.

## Units and axes

The ingest step converts everything to millimetres with Z up. iPhone (ARKit) exports are usually Y-up; the up axis is detected automatically from where the floor and ceiling are.
