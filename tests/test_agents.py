"""Registration, claiming, heartbeat, release, lease expiry."""

from datetime import timedelta

from agentdao import db
from conftest import STEWARD, claim, create_task, register


def test_register_requires_valid_unused_invite(client):
    r = client.post("/api/v1/register", json={"invite_code": "nope", "handle": "alice", "model_family": "claude"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_invite"
    code = client.post("/api/v1/admin/invites", json={"count": 1}, headers=STEWARD).json()["codes"][0]
    r = client.post("/api/v1/register", json={"invite_code": code, "handle": "alice", "model_family": "claude"})
    assert r.status_code == 201
    assert r.json()["api_key"].startswith("adk_")
    again = client.post("/api/v1/register", json={"invite_code": code, "handle": "bob", "model_family": "gpt"})
    assert again.status_code == 403


def test_register_validates_handle_and_stores_only_hash(client, conn):
    code = client.post("/api/v1/admin/invites", json={"count": 1}, headers=STEWARD).json()["codes"][0]
    bad = client.post("/api/v1/register", json={"invite_code": code, "handle": "No Spaces!", "model_family": "claude"})
    assert bad.status_code == 422
    key = client.post("/api/v1/register", json={"invite_code": code, "handle": "carol", "model_family": "gemini"}).json()["api_key"]
    stored = db.scalar(conn, "SELECT api_key_hash FROM contributors WHERE handle='carol'")
    assert key not in stored and len(stored) == 64
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {key}"}).json()
    assert me["handle"] == "carol" and me["credits"] == 0


def test_agent_endpoints_require_auth(client):
    assert client.get("/api/v1/me").status_code == 401
    r = client.post("/api/v1/tasks/claim", json={}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_claim_heartbeat_release(client):
    h = register(client, "alice")
    assert claim(client, h).status_code == 204  # nothing open yet
    tid = create_task(client)
    r = claim(client, h, model="claude-x")
    assert r.status_code == 200
    lease = r.json()["lease"]
    assert lease["task_id"] == tid and lease["heartbeat_every_s"] == 600
    assert r.json()["instructions_url"] == "http://test/task-types/map.extract.md"
    assert client.get(f"/api/v1/tasks/{tid}").json()["status"] == "leased"
    hb = client.post(f"/api/v1/leases/{lease['id']}/heartbeat", json={"progress_note": "reading"}, headers=h)
    assert hb.status_code == 200 and hb.json()["expires_at"] >= lease["expires_at"]
    rel = client.post(f"/api/v1/leases/{lease['id']}/release", json={"reason": "quota"}, headers=h)
    assert rel.json() == {"ok": True}
    t = client.get(f"/api/v1/tasks/{tid}").json()
    assert t["status"] == "open" and t["attempts"] == 0  # quota release is free
    assert client.post(f"/api/v1/leases/{lease['id']}/heartbeat", json={}, headers=h).status_code == 409


def test_release_gave_up_counts_attempt_and_max_attempts_goes_to_steward(client):
    tid = create_task(client)
    for i in range(3):  # different contributors: a released task is not re-offered to the releaser for 24h
        h = register(client, f"agent{i}")
        lease = claim(client, h).json()["lease"]
        client.post(f"/api/v1/leases/{lease['id']}/release", json={"reason": "gave_up"}, headers=h)
    t = client.get(f"/api/v1/tasks/{tid}").json()
    assert t["attempts"] == 3 and t["status"] == "needs_steward"


def test_max_two_active_leases(client):
    h = register(client, "alice")
    for _ in range(3):
        create_task(client)
    assert claim(client, h).status_code == 200
    assert claim(client, h).status_code == 200
    r = claim(client, h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "lease_limit"


def test_lease_expiry_returns_task_to_open(client, monkeypatch):
    h = register(client, "alice")
    tid = create_task(client)
    lease = claim(client, h).json()["lease"]
    real = db.utcnow
    monkeypatch.setattr(db, "utcnow", lambda: real() + timedelta(minutes=31))
    t = client.get(f"/api/v1/tasks/{tid}").json()  # any request sweeps
    assert t["status"] == "open" and t["attempts"] == 1
    r = client.post(f"/api/v1/leases/{lease['id']}/submit", json={"payload": {}}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "lease_not_active"


def test_model_family_and_type_filters(client):
    h = register(client, "alice", family="claude")
    create_task(client, allowed_model_families=["open-weight"])
    assert claim(client, h).status_code == 204
    assert claim(client, h, task_types=["map.profile"]).status_code == 204
    ow = register(client, "olmo-fan", family="open-weight")
    assert claim(client, ow).status_code == 200
