"""The render service of the video export (ADR-0017) and Observatory's passthrough to it, with a stand-in engine (no MuJoCo, no rendering):
`GET /engines`, `POST /jobs` (one at a time, 409 while one runs), `GET /jobs/{id}` and its file, a failing engine's error; then
Observatory's `/api/v1/render`, `/runs/{key}/video` and `/videos/{id}[/file]` with MINIVIEW_RENDER unset, dead and set.
Run: cd apps/observatory && uv run python tests/test_render_service.py"""

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from helpers import Checks, catalog, get, import_fixture, scene, serve, stub_engine, wait_until
from observatory.video import service

check = Checks("RENDER SERVICE")
K = "duck/apartment/explore9"


def tree(root: Path) -> list:
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*") if p.is_file())


def file_of(base: str, path: str):
    """(status, content type, bytes)."""
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.headers["Content-Type"], r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read()


def settled(base: str, jid: str, path: str = "/jobs/") -> dict:
    return wait_until(lambda: (j := get(base, path + jid)[1])["status"] in ("done", "failed") and j, 20, 0.05, "the job to finish")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    data, state = tmp / "data", tmp / "state"
    import_fixture(data)                                                       # explore9: a duck run with truth
    import_fixture(data, "explore9", robot="rover")                            # a robot with no engine model
    before = tree(data)
    os.environ.pop("MINIVIEW_RENDER", None)
    gate = stub_engine(tmp, "ok")
    httpd = service.make_server(data, state, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    R = f"http://127.0.0.1:{httpd.server_address[1]}"

    # ---- /engines
    code, body, _ = get(R, "/engines")
    eng = {e["name"]: e for e in body["engines"]}
    check("/engines lists mujoco as available for the duck, with no reason", code == 200 and eng["mujoco"] == {"name": "mujoco", "available": True, "why": None, "robots": ["duck"]}, body)
    os.environ["VIDEO_BLENDER"] = str(tmp / "nowhere" / "blender")
    bl = {e["name"]: e for e in get(R, "/engines")[1]["engines"]}["blender"]
    check("blender whose program (VIDEO_BLENDER, else robots.json's) does not exist: not available, and says which",
          bl["available"] is False and bl["robots"] == [] and "nowhere/blender does not exist" in bl["why"], bl)
    os.environ["VIDEO_BLENDER"] = sys.executable                                # a program that exists: the engine is listed as available
    bl = {e["name"]: e for e in get(R, "/engines")[1]["engines"]}["blender"]
    check("blender whose program exists: available for the duck (its URDF)", bl["available"] is True and bl["robots"] == ["duck"], bl)
    os.environ["VIDEO_BLENDER"] = str(tmp / "nowhere" / "blender")
    good_python = os.environ["VIDEO_MUJOCO_PYTHON"]
    os.environ["VIDEO_MUJOCO_PYTHON"] = str(tmp / "nowhere" / "python")
    mj = {e["name"]: e for e in get(R, "/engines")[1]["engines"]}["mujoco"]
    check("an engine whose python does not exist is not available, and says which", mj["available"] is False and "does not exist" in mj["why"] and mj["robots"] == [], mj)
    check("POST /jobs for it is a 503 with that reason", get(R, "/jobs", body={"run": K, "engine": "mujoco"})[:2] == (503, {"error": f"the mujoco engine is not available: {mj['why']}"}))
    os.environ["VIDEO_MUJOCO_PYTHON"] = good_python
    os.environ["VIDEO_MUJOCO_SCRIPT"] = str(tmp / "no-such-script.py")
    mj = {e["name"]: e for e in get(R, "/engines")[1]["engines"]}["mujoco"]
    check("an engine whose script does not exist is not available", mj["available"] is False and "script is not there" in mj["why"], mj)
    gate = stub_engine(tmp, "ok")

    # ---- bad requests
    for what, req, want in (("no run", {"engine": "mujoco"}, 400), ("a key that is not one", {"run": "../x", "engine": "mujoco"}, 400),
                            ("an engine there is not", {"run": K, "engine": "povray"}, 400), ("a robot the engine has no model for", {"run": "rover/apartment/explore9", "engine": "mujoco"}, 400),
                            ("a run that is not there", {"run": "duck/apartment/nope", "engine": "mujoco"}, 404), ("from after to", {"run": K, "engine": "mujoco", "from": 5, "to": 1}, 400),
                            ("a size that is not one", {"run": K, "engine": "mujoco", "size": "big"}, 400), ("from that is not a number", {"run": K, "engine": "mujoco", "from": "x"}, 400),
                            ("blender, whose program is not there", {"run": K, "engine": "blender"}, 503)):
        code, body, _ = get(R, "/jobs", body=req)
        check(f"POST /jobs with {what} is a {want} with a reason", code == want and isinstance(body, dict) and body.get("error"), (code, body))
    check("GET /jobs/{id} of no job is a 404", get(R, "/jobs/0000000000")[0] == 404)
    check("an unknown path is a 404", get(R, "/nothing")[0] == 404)

    # ---- one job: running, a second is a 409, then done and the file
    gate = stub_engine(tmp, "gated")
    code, body, _ = get(R, "/jobs", body={"run": K, "engine": "mujoco", "size": "960x540", "from": 33.0, "to": 34.0})
    jid = body.get("id")
    check("POST /jobs is a 202 with an id", code == 202 and isinstance(jid, str) and len(jid) >= 6, (code, body))
    j = wait_until(lambda: (j := get(R, "/jobs/" + jid)[1])["status"] == "running" and j, 10, 0.02, "the job to run")
    check("GET /jobs/{id} says running, with its run and engine, no file and no error", j == {"id": jid, "run": K, "engine": "mujoco", "status": "running", "error": None, "file": None}, j)
    code, body, _ = get(R, "/jobs", body={"run": K, "engine": "mujoco"})
    check("a second job while one runs is a 409 with the reason", code == 409 and "one at a time" in body["error"], (code, body))
    check("the file of a job that is not done is a 409", get(R, f"/jobs/{jid}/file")[0] == 409)
    gate.touch()
    j = settled(R, jid)
    check("the job is done, with the file's name <key with - for />-<engine>-<id>.mp4", j["status"] == "done" and j["error"] is None and j["file"] == f"duck-apartment-explore9-mujoco-{jid}.mp4", j)
    code, ctype, blob = file_of(R, f"/jobs/{jid}/file")
    info = json.loads(blob[blob.index(b"{"):]) if b"{" in blob else {}
    check("GET /jobs/{id}/file is the video, video/mp4", code == 200 and ctype == "video/mp4" and blob.startswith(b"\0\0\0\x18ftypmp42"), (code, ctype, blob[:24]))
    check("it is on disk in <state>/videos/, the bytes served", (state / "videos" / j["file"]).read_bytes() == blob)
    check("the engine was given the run, the robot, the size and the span asked (33 to 34 s at 30 fps)",
          info.get("run") == K and info.get("robot") == "duck" and info.get("size") == [960, 540] and info.get("frames") == 31
          and info.get("t0") == 33.0 and info.get("t1") == 34.0, info)
    stub_engine(tmp, "ok")
    code, body, _ = get(R, "/jobs", body={"run": K, "engine": "mujoco"})
    j2 = settled(R, body["id"])
    blob2 = file_of(R, f"/jobs/{body['id']}/file")[2]
    info2 = json.loads(blob2[blob2.index(b"{"):])
    check("after a job is done the next one starts (default: the whole run, 1280x720)", code == 202 and j2["status"] == "done" and info2["size"] == [1280, 720] and info2["frames"] > 31 and body["id"] != jid, (code, info2))

    # ---- a failing engine
    stub_engine(tmp, "fail")
    code, body, _ = get(R, "/jobs", body={"run": K, "engine": "mujoco"})
    j = settled(R, body["id"])
    check("an engine that exits 1 is a failed job with its error (exit 1), no file", code == 202 and j["status"] == "failed" and "exit 1" in j["error"] and j["file"] is None, j)
    check("... and its file is a 409", get(R, f"/jobs/{j['id']}/file")[0] == 409)
    check("the service did not write into the data folder", tree(data) == before)

    # ---- Observatory's passthrough
    cat = catalog(data)
    cat.put_scene(scene("apartment"))
    cat.scan()
    before = tree(data)                                                       # what the catalog itself wrote (the scene) is not the passthrough's
    mv, M = serve(cat, follow=False)
    code, body, _ = get(M, "/api/v1/render")
    check("MINIVIEW_RENDER unset: /api/v1/render says unavailable, no render service configured", (code, body) == (200, {"available": False, "why": "no render service configured"}), (code, body))
    code, body, _ = get(M, f"/api/v1/runs/{K}/video", body={"engine": "mujoco"})
    check("... and a video request is a 503 with the same reason", code == 503 and "no render service configured" in body["error"], (code, body))
    os.environ["MINIVIEW_RENDER"] = "http://127.0.0.1:1"
    code, body, _ = get(M, "/api/v1/render")
    check("MINIVIEW_RENDER at a port nothing listens on: unavailable, render service not answering: <why>", code == 200 and body["available"] is False and body["why"].startswith("render service not answering: "), body)
    check("... and a video request is a 503 saying so", get(M, f"/api/v1/runs/{K}/video", body={"engine": "mujoco"})[0] == 503)

    os.environ["MINIVIEW_RENDER"] = R + "/"
    stub_engine(tmp, "ok")
    code, body, _ = get(M, "/api/v1/render")
    check("MINIVIEW_RENDER set: /api/v1/render is the service's engines", code == 200 and {e["name"] for e in body["engines"]} >= {"mujoco", "blender"}
          and next(e for e in body["engines"] if e["name"] == "mujoco")["robots"] == ["duck"], body)
    check("a key that is not one is a 400", get(M, "/api/v1/runs/duck/apartment/UP/video", body={"engine": "mujoco"})[0] == 400)
    check("a body that is not JSON is a 400", get(M, f"/api/v1/runs/{K}/video", body="x")[0] == 400)
    check("the service's 404 (no such run) comes through with its reason", get(M, "/api/v1/runs/duck/apartment/nope/video", body={"engine": "mujoco"})[:2] == (404, {"error": "no run 'duck/apartment/nope'"}))
    check("the service's 400 (no model for that robot) comes through", get(M, "/api/v1/runs/rover/apartment/explore9/video", body={"engine": "mujoco"})[0] == 400)
    check("a POST anywhere else is still a 405", get(M, "/api/v1/runs", body={})[0] == 405)

    gate = stub_engine(tmp, "gated")
    code, body, _ = get(M, f"/api/v1/runs/{K}/video", body={"engine": "mujoco", "size": "960x540"})
    vid = body.get("id")
    check("POST /api/v1/runs/{key}/video is a 202 with the job's id", code == 202 and isinstance(vid, str), (code, body))
    j = wait_until(lambda: (j := get(M, "/api/v1/videos/" + vid)[1])["status"] == "running" and j, 10, 0.02, "the job to run")
    check("GET /api/v1/videos/{id} is the job, running", j["id"] == vid and j["run"] == K, j)
    code, body, _ = get(M, f"/api/v1/runs/{K}/video", body={"engine": "mujoco"})
    check("a second video while one renders is a 409 through miniview, with the reason", code == 409 and "one at a time" in body["error"], (code, body))
    check("the file of a job not done is a 409", get(M, f"/api/v1/videos/{vid}/file")[0] == 409)
    gate.touch()
    j = settled(M, vid, "/api/v1/videos/")
    code, ctype, blob = file_of(M, f"/api/v1/videos/{vid}/file")
    check("the job is done; its file streams through miniview, video/mp4, the very bytes", j["status"] == "done" and code == 200 and ctype == "video/mp4"
          and blob == (state / "videos" / j["file"]).read_bytes() and b'"size": [960, 540]' in blob, (j, code, ctype))
    check("a video id that is not one, or unknown, is a 404", get(M, "/api/v1/videos/..%2fx")[0] == 404 and get(M, "/api/v1/videos/abcdef0123")[0] == 404)
    stub_engine(tmp, "fail")
    vid = get(M, f"/api/v1/runs/{K}/video", body={"engine": "mujoco"})[1]["id"]
    j = settled(M, vid, "/api/v1/videos/")
    check("a failed job's error comes through", j["status"] == "failed" and "exit 1" in j["error"], j)
    check("miniview wrote nothing into the data folder", tree(data) == before)
    for h in (mv, httpd):
        h.shutdown()

check.done()
