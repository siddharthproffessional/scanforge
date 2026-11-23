# Frontend (to build next)

React + Three.js, following the four screens on the design canvas: Upload, Processing, Review, Export.

Planned pieces:
- **Point cloud view**: Three.js `Points` with an octree (or Potree) for large scans
- **Model view**: draw the building graph directly (walls as boxes from `baseline` + `thickness`), coloured by QA deviation; IFC view with That Open Components
- **Agent chat and questions**: `GET /projects/{id}/graph` → `questions`; answer with `POST /projects/{id}/questions/{qid}`
- **Uploads**: chunked uploads for multi-GB scans (direct to Supabase Storage)
