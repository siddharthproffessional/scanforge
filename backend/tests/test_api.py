from fastapi.testclient import TestClient

from scanforge.demo import make_room_ply


def test_upload_process_export(tmp_path, monkeypatch):
    import scanforge.api as api
    monkeypatch.setattr(api, "DATA", tmp_path / "data")
    c = TestClient(api.app)

    pid = c.post("/projects", json={"name": "Test room"}).json()["id"]

    bad = c.post(f"/projects/{pid}/files", files={"file": ("scan.fls", b"x")})
    assert bad.status_code == 422 and "E57" in bad.json()["detail"]

    ply = tmp_path / "room.ply"
    make_room_ply(ply)
    up = c.post(f"/projects/{pid}/files", files={"file": ("room.ply", ply.read_bytes())}).json()
    assert up["kind"] == "pointcloud" and up["device"] == "iphone_lidar"

    assert c.post(f"/projects/{pid}/process").json()["status"] == "queued"
    p = c.get(f"/projects/{pid}").json()   # TestClient runs background tasks before returning
    assert p["state"] == "review", p
    assert p["summary"]["wall"]["observed"] == 5

    assert len(c.get(f"/projects/{pid}/points").content) % 12 == 0

    d = c.post("/demo").json()["id"]
    assert c.get(f"/projects/{d}").json()["state"] == "review"
    assert c.get("/").status_code == 200

    ifc = c.get(f"/projects/{pid}/export.ifc")
    assert ifc.status_code == 200 and ifc.content.startswith(b"ISO-10303-21")
