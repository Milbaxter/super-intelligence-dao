"""Steward auth, error format, limits, static/protocol files."""

from conftest import STEWARD


def test_steward_endpoints_require_key(client):
    for method, path in [("post", "/api/v1/admin/invites"), ("get", "/api/v1/admin/queue"), ("post", "/api/v1/admin/generate")]:
        r = getattr(client, method)(path, headers={"Authorization": "Bearer dev-steward"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/admin/queue", headers=STEWARD).status_code == 200


def test_error_format_and_404(client):
    r = client.get("/api/v1/claims/cl_nope")
    assert r.status_code == 404 and set(r.json()["error"]) >= {"code", "message"}
    assert client.get("/api/v1/nothing-here").json()["error"]["code"] == "not_found"


def test_payload_size_limit(client):
    r = client.post("/api/v1/register", content=b"x" * (300 * 1024), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_public_endpoints_shape(client):
    s = client.get("/api/v1/stats").json()
    assert s["phase"] == "0" and s["artifacts_total"] == 1 and "stale" in s["claims_by_tier"]
    assert client.get("/api/v1/layers").json()[0]["artifact_count"] == 1
    m = client.get("/api/v1/map").json()
    assert m["layers"][0]["artifacts"][0]["id"] == "foo-agent"
    assert client.get("/api/v1/tracks").json()[0]["counts"] == {"open": 0, "in_progress": 0, "awaiting_verification": 0, "verified": 0}
    assert client.get("/api/v1/stats").headers.get("access-control-allow-origin") is None  # no Origin sent
    assert client.get("/api/v1/stats", headers={"Origin": "https://x.dev"}).headers["access-control-allow-origin"] == "*"


def test_join_md_templating_and_missing_files(client, app):
    assert client.get("/join.md").status_code == 404  # agent/ not written yet → helpful 404, not a crash
    assert client.get("/").status_code == 404
    agent = app.state.settings.agent_dir
    (agent / "task-types").mkdir(parents=True)
    (agent / "join.md").write_text("Base: {{BASE_URL}} v{{SKILL_VERSION}}")
    (agent / "task-types" / "map.extract.md").write_text("POST {{BASE_URL}}/api/v1/tasks/claim")
    r = client.get("/join.md")
    assert r.text == "Base: http://test v0.1.1" and r.headers["content-type"].startswith("text/markdown")
    assert client.get("/task-types/map.extract.md").text == "POST http://test/api/v1/tasks/claim"
    sv = client.get("/skill-version").json()
    assert sv["version"] == "0.1.1" and len(sv["sha256"]) == 64
    web = app.state.settings.web_dir
    web.mkdir()
    (web / "index.html").write_text("<h1>hi</h1>")
    (web / "map.html").write_text("<h1>map</h1>")
    assert client.get("/").text == "<h1>hi</h1>" and client.get("/map.html").text == "<h1>map</h1>"
    assert client.get("/../pyproject.toml").status_code == 404


def test_rate_limit(app):
    from fastapi.testclient import TestClient
    app.state.settings.rate_public_per_min = 3
    with TestClient(app) as c:
        codes = [c.get("/api/v1/stats").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_skill_version_alias(client):
    a = client.get("/skill-version").json()
    b = client.get("/api/v1/skill-version")
    assert b.status_code == 200 and b.json() == a and "version" in a


def test_local_sources_flag(tmp_path, monkeypatch):
    from agentdao import config
    from agentdao.app import create_app
    monkeypatch.delenv("AGENTDAO_ALLOW_LOCAL_SOURCES", raising=False)
    off = create_app(config.Settings(db_path=str(tmp_path / "a.db")))
    assert off.state.checker.fetcher.allow_http_localhost is False
    monkeypatch.setenv("AGENTDAO_ALLOW_LOCAL_SOURCES", "1")
    on = create_app(config.Settings(db_path=str(tmp_path / "b.db")))
    assert on.state.checker.fetcher.allow_http_localhost is True


def test_seed_tasks_resolve_artifacts_by_name(tmp_path, conn):
    import json
    from agentdao import db, seed
    d = tmp_path / "seedx"
    d.mkdir()
    (d / "tasks.json").write_text(json.dumps([
        {"type": "map.extract", "title": "by id", "inputs": {"artifact_id": "foo-agent"}},
        {"type": "map.extract", "title": "by name", "inputs": {"artifact_id": "wrong-guess", "artifact_name": "foo agent"}},
        {"type": "map.profile", "title": "unknown", "inputs": {"artifact_id": "nope", "artifact_name": "Nope"}},
        {"type": "map.gap_scan", "title": "scan", "inputs": {"layer": "harnesses"}},
    ]))
    report = seed.load_seed(conn, d)
    assert report["tasks"]["loaded"] == 3 and report["tasks"]["skipped"] == 1
    for t in db.all_(conn, "SELECT type, inputs FROM tasks WHERE type='map.extract'"):
        inp = json.loads(t["inputs"])
        assert (inp["artifact_id"], inp["artifact_name"], inp["layer"]) == ("foo-agent", "Foo-Agent", "harnesses")


def test_repo_seed_tasks_all_resolve():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "seed"
    arts = {a["id"]: a for a in json.loads((root / "artifacts.json").read_text())}
    for t in json.loads((root / "tasks.json").read_text()):
        if t["type"] in ("map.extract", "map.profile"):
            a = arts[t["inputs"]["artifact_id"]]
            assert t["inputs"]["artifact_name"] == a["name"] and t["inputs"]["layer"] == a["layer"]
        if t["type"] == "map.gap_scan":
            assert t["inputs"]["layer"]
