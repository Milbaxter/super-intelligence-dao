"""Fixes from the first real-agent field test: same-IP verify block, release cooldown + `conflict`,
coarse blind hints, ambiguous table-row quotes, /stats in-progress count."""

from datetime import timedelta

from agentdao import db
from agentdao.verify import FetchResult, quote_ambiguity
from conftest import STEWARD, claim, create_task, do_extract, extract_payload, register, submit

TABLE_URL = "https://example.org/table"
TABLE_PAGE = "<table><tr><td>Foo-Agent</td><td>72.4</td><td>68.1</td><td>55.0</td></tr></table>"
ROW = "Foo-Agent 72.4 68.1 55.0"


def test_same_registered_ip_cannot_verify(app, client, conn):
    app.state.settings.dev_allow_same_ip = False  # TestClient: every request comes from the same host
    h = register(client, "alice")
    do_extract(client, h)
    v = register(client, "victor", family="gpt")
    hashes = [r[0] for r in conn.execute("SELECT registered_ip_hash FROM contributors")]
    assert len(set(hashes)) == 1 and hashes[0] and "testclient" not in hashes[0]
    assert claim(client, v, task_types=["verify.blind_extract"]).status_code == 204
    app.state.settings.dev_allow_same_ip = True  # dev bypass (AGENTDAO_DEV_ALLOW_SAME_IP=1)
    assert claim(client, v, task_types=["verify.blind_extract"]).status_code == 200


def test_released_task_not_reoffered_for_24h_and_conflict_is_free(client, monkeypatch):
    tid = create_task(client)
    a = register(client, "alice")
    lease = claim(client, a).json()["lease"]
    r = client.post(f"/api/v1/leases/{lease['id']}/release", json={"reason": "conflict"}, headers=a)
    assert r.status_code == 200
    t = client.get(f"/api/v1/tasks/{tid}").json()
    assert t["status"] == "open" and t["attempts"] == 0
    assert claim(client, a).status_code == 204
    real = db.utcnow
    monkeypatch.setattr(db, "utcnow", lambda: real() + timedelta(hours=25))
    assert claim(client, a).json()["task"]["id"] == tid


def test_blind_hint_is_coarse(client):
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h).json()["lease"]
    p = extract_payload()
    p["claims"][0]["conditions"] = {"model": "claude-x", "harness": "OpenHands", "attempts": 1, "date": "2026-08",
                                    "budget": "$5", "notes": "column 2"}
    blind_id = submit(client, h, lease["id"], p).json()["spawned_task_ids"][0]
    hint = client.get(f"/api/v1/tasks/{blind_id}").json()["inputs"]["conditions_hint"]
    assert hint == {"model": "claude-x", "harness": "OpenHands"}


def test_quote_ambiguity_detection():
    assert quote_ambiguity(ROW, 72.4)
    assert quote_ambiguity("A 72.4% B 68.1% C 55.0%", 0.724)
    assert not quote_ambiguity("On SWE-bench Verified, Foo-Agent resolves 72.4% of tasks", 72.4)
    assert not quote_ambiguity("Foo 72.4 vs 68 vs 55 in 2026", 72.4)  # different formats


def test_ambiguous_table_row_needs_notes_and_is_flagged(client, fetcher):
    fetcher.pages[TABLE_URL] = FetchResult(TABLE_URL, 200, "text/html", TABLE_PAGE.encode())
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h).json()["lease"]
    p = extract_payload(quote=ROW, source=TABLE_URL)
    p["claims"][0]["conditions"] = {"model": "claude-x"}
    res = submit(client, h, lease["id"], p).json()
    assert res["checks"][0]["detail"] == "ambiguous_quote_needs_notes" and res["status"] == "rejected"

    create_task(client)
    lease = claim(client, h).json()["lease"]
    p["claims"][0]["conditions"]["notes"] = "column: SWE-bench Verified"
    res = submit(client, h, lease["id"], p).json()
    chk = res["checks"][0]
    assert chk["passed"] and chk["tier"] == "source-checked" and chk["flag"] == "ambiguous_quote"
    q = client.get("/api/v1/admin/queue", headers=STEWARD).json()
    assert [c["id"] for c in q["flagged_claims"]] == [chk["claim_id"]] and q["flagged_claims"][0]["flag"] == "ambiguous_quote"
    r = client.post(f"/api/v1/admin/claims/{chk['claim_id']}/resolve", json={"tier": "source-checked", "note": "ok"},
                    headers=STEWARD)
    assert r.status_code == 200
    assert client.get("/api/v1/admin/queue", headers=STEWARD).json()["flagged_claims"] == []


def test_stats_in_progress_counts_only_active_leases(client, conn):
    h = register(client, "alice")
    do_extract(client, h)  # extract task → verifying; blind task open
    s = client.get("/api/v1/stats").json()
    assert s["tasks_in_progress"] == 0 and s["tasks_awaiting_verification"] == 1
    tid = create_task(client)
    with db.tx(conn):  # orphan: leased without an active lease (e.g. set by hand)
        conn.execute("UPDATE tasks SET status='leased' WHERE id=?", (tid,))
    s = client.get("/api/v1/stats").json()
    assert s["tasks_in_progress"] == 0
    assert client.get(f"/api/v1/tasks/{tid}").json()["status"] == "open"


def test_same_ip_bypass_refused_on_public_bind():
    from agentdao import config
    s = config.Settings(steward_key="x" * 32, allow_local_sources=False, dev_allow_same_ip=True)
    assert any("SAME_IP" in p for p in config.unsafe_for_public_bind(s, "0.0.0.0"))
    assert config.unsafe_for_public_bind(s, "127.0.0.1") == []
