"""HTTP API for the web app. Storage is a local folder per project for now;
swap `DATA` for Supabase Storage + Postgres when deploying."""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents.registry import Workspace
from .demo import make_room_ply
from .export.ifc_export import export_ifc
from .graph import BuildingGraph
from .pipeline.ingest import UnsupportedInput, classify_file
from .pipeline.run import run_pointcloud

DATA = Path(os.getenv("SCANFORGE_DATA", "./data"))
WEB = Path(__file__).parent / "web"
app = FastAPI(title="ScanForge API", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return (WEB / "index.html").read_text()


@app.get("/health")
def health():
    return {"ok": True}


def _ws(pid: str) -> Workspace:
    root = DATA / pid
    if not root.exists():
        raise HTTPException(404, "project not found")
    return Workspace(root)


def _status(ws: Workspace) -> dict:
    f = ws.root / "status.json"
    return json.loads(f.read_text()) if f.exists() else {"state": "created"}


def _set_status(ws: Workspace, **kw) -> None:
    (ws.root / "status.json").write_text(json.dumps(kw))


class NewProject(BaseModel):
    name: str


KEEP_DAYS = float(os.getenv("SCANFORGE_KEEP_DAYS", "3"))


def _cleanup() -> None:
    """Demo server housekeeping: drop projects older than KEEP_DAYS."""
    if not DATA.exists():
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    for d in DATA.glob("prj_*"):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


@app.post("/projects")
def create_project(body: NewProject):
    _cleanup()
    pid = "prj_" + uuid.uuid4().hex[:10]
    (DATA / pid / "inputs").mkdir(parents=True)
    (DATA / pid / "name").write_text(body.name)
    return {"id": pid, "name": body.name}


@app.post("/demo")
def demo(bg: BackgroundTasks):
    """Create a project from the synthetic iPhone-style room scan and process it."""
    p = create_project(NewProject(name="Sample room"))
    ws = _ws(p["id"])
    make_room_ply(ws.root / "inputs" / "sample_room_iphone.ply")
    _set_status(ws, state="queued")
    bg.add_task(_process, ws, "Sample room")
    return p


@app.post("/projects/{pid}/files")
async def upload(pid: str, file: UploadFile):
    ws = _ws(pid)
    dest = ws.root / "inputs" / Path(file.filename).name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        info = classify_file(dest)
    except UnsupportedInput as e:
        dest.unlink()
        raise HTTPException(422, str(e))
    return {"file": dest.name, "bytes": dest.stat().st_size, **info}


def _process(ws: Workspace, name: str):
    t0 = time.time()
    try:
        _set_status(ws, state="processing")
        clouds = [p for p in (ws.root / "inputs").iterdir()
                  if p.suffix.lower() in {".e57", ".las", ".laz", ".ply"}]
        if not clouds:
            raise RuntimeError("no point cloud uploaded")
        g = run_pointcloud(max(clouds, key=lambda p: p.stat().st_size), name,
                           preview_path=ws.root / "preview.f32")
        ws.save(g)
        export_ifc(g, ws.root / "out" / "model.ifc")
        _set_status(ws, state="review", seconds=round(time.time() - t0, 1))
    except Exception as e:
        _set_status(ws, state="failed", error=str(e), seconds=round(time.time() - t0, 1))


@app.post("/projects/{pid}/process")
def process(pid: str, bg: BackgroundTasks):
    ws = _ws(pid)
    _set_status(ws, state="queued")
    bg.add_task(_process, ws, (ws.root / "name").read_text())
    return {"status": "queued"}


@app.get("/projects/{pid}")
def project(pid: str):
    ws = _ws(pid)
    out = {"id": pid, "name": (ws.root / "name").read_text(), **_status(ws),
           "inputs": [p.name for p in (ws.root / "inputs").iterdir()]}
    if ws.graph_path.exists():
        out["summary"] = ws.load().summary()
    return out


@app.get("/projects/{pid}/graph", response_model=BuildingGraph)
def graph(pid: str):
    ws = _ws(pid)
    if not ws.graph_path.exists():
        raise HTTPException(409, "not processed yet")
    return ws.load()


class Answer(BaseModel):
    answer: str


@app.post("/projects/{pid}/questions/{qid}")
def answer(pid: str, qid: str, body: Answer):
    from datetime import datetime, timezone
    ws = _ws(pid)
    g = ws.load()
    q = next((q for q in g.questions if q.id == qid), None)
    if q is None:
        raise HTTPException(404, "question not found")
    q.answer, q.answered_at = body.answer, datetime.now(timezone.utc)
    ws.save(g)
    return q


@app.get("/projects/{pid}/points", include_in_schema=False)
def points(pid: str):
    """Subsampled cleaned scan as raw float32 xyz (mm, Z up) for the viewer."""
    f = _ws(pid).root / "preview.f32"
    if not f.exists():
        raise HTTPException(409, "not processed yet")
    return FileResponse(f, media_type="application/octet-stream")


@app.get("/projects/{pid}/graph.json")
def graph_file(pid: str):
    ws = _ws(pid)
    return FileResponse(ws.graph_path, filename=f"{pid}.graph.json", media_type="application/json")


@app.get("/projects/{pid}/export.ifc")
def export(pid: str):
    ws = _ws(pid)
    path = export_ifc(ws.load(), ws.root / "out" / "model.ifc")
    return FileResponse(path, filename=f"{pid}.ifc", media_type="application/x-step")
