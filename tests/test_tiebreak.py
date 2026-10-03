"""Blind tie-breaker: one disagreeing verdict never disputes a claim on its own; a side needs 2 votes (max 3)."""

from agentdao import db, lifecycle
from conftest import QUOTE, STEWARD, claim, do_extract, register, submit

OTHER_QUOTE = "HumanEval pass@1 is 91.0 for the base model"
AGREE = {"found": True, "value": 72.4, "unit": "%", "quote": QUOTE, "conditions": {}}
DISAGREE = {"found": True, "value": 91.0, "unit": "%", "quote": OTHER_QUOTE, "conditions": {}}
NOT_FOUND = {"found": False}


def blind(client, handle, payload, family="gpt"):
    """Register a fresh verifier, claim a blind task and submit; returns (headers, task_id, submit JSON)."""
    h = register(client, handle, family)
    r = claim(client, h, task_types=["verify.blind_extract"])
    assert r.status_code == 200, r.text
    out = submit(client, h, r.json()["lease"]["id"], payload)
    assert out.status_code == 200, out.text
    return h, r.json()["task"]["id"], out.json()


def setup(client):
    h = register(client, "alice")
    res = do_extract(client, h)
    return h, res["checks"][0]["claim_id"], res["submission_id"]


def credits(client):
    return {p["handle"]: p["credits"] for p in client.get("/api/v1/contributors").json()}


def sub_status(conn, sub_id):
    return db.scalar(conn, "SELECT status FROM submissions WHERE id=?", (sub_id,))


def task_status(conn, task_id):
    return db.scalar(conn, "SELECT status FROM tasks WHERE id=?", (task_id,))


def test_round_decision_rule():
    d = lifecycle.blind_round_decision
    assert d(["agree"]) == "reproduced"
    assert d(["disagree"]) is None
    assert d(["disagree", "disagree"]) == "disputed"
    assert d(["disagree", "agree"]) is None
    assert d(["disagree", "agree", "agree"]) == "reproduced"
    assert d(["disagree", "agree", "disagree"]) == "disputed"


def test_agree_first_reproduces_without_tiebreak(client, conn):
    _, claim_id, ext_sub = setup(client)
    _, _, out = blind(client, "victor", AGREE)
    assert out["status"] == "verified" and out["spawned_task_ids"] == []
    assert client.get(f"/api/v1/claims/{claim_id}").json()["tier"] == "reproduced"
    assert sub_status(conn, ext_sub) == "verified"
    assert credits(client) == {"alice": 10, "victor": 4}


def test_disagree_spawns_tiebreak_and_does_not_dispute(client, conn):
    _, claim_id, ext_sub = setup(client)
    _, first_task, out = blind(client, "victor", DISAGREE)
    assert out["status"] == "verifying" and len(out["spawned_task_ids"]) == 1
    tb = client.get(f"/api/v1/tasks/{out['spawned_task_ids'][0]}").json()
    assert tb["type"] == "verify.blind_extract" and tb["status"] == "open"
    assert db.scalar(conn, "SELECT target_claim_id FROM tasks WHERE id=?", (tb["id"],)) == claim_id
    c = client.get(f"/api/v1/claims/{claim_id}").json()
    assert c["special_status"] is None and c["display_status"] == "source-checked"
    assert task_status(conn, first_task) == "verifying" and sub_status(conn, ext_sub) == "verifying"
    assert credits(client) == {"alice": 0, "victor": 0}


def test_free_not_found_cannot_dispute_alone(client):
    _, claim_id, _ = setup(client)
    _, _, out = blind(client, "victor", NOT_FOUND)
    assert out["status"] == "verifying" and len(out["spawned_task_ids"]) == 1
    assert client.get(f"/api/v1/claims/{claim_id}").json()["special_status"] is None


def test_two_disagreements_dispute(client, conn):
    _, claim_id, ext_sub = setup(client)
    _, t1, first = blind(client, "victor", DISAGREE)
    _, t2, out = blind(client, "wendy", NOT_FOUND, "gemini")
    assert out["status"] == "disputed" and out["spawned_task_ids"] == []
    assert client.get(f"/api/v1/claims/{claim_id}").json()["display_status"] == "disputed"
    assert sub_status(conn, first["submission_id"]) == "disputed" and task_status(conn, t1) == "disputed"
    assert sub_status(conn, ext_sub) == "disputed"
    assert credits(client) == {"alice": 0, "victor": 0, "wendy": 0}  # no verify_agreed for a dispute
    # Steward sides with the extractor: alice +6, verifier submissions settle as rejected.
    client.post(f"/api/v1/admin/claims/{claim_id}/resolve", json={"special_status": "none", "note": "ok"}, headers=STEWARD)
    assert credits(client) == {"alice": 6, "victor": 0, "wendy": 0}
    assert {sub_status(conn, first["submission_id"]), sub_status(conn, out["submission_id"])} == {"rejected"}
    assert {task_status(conn, t1), task_status(conn, t2)} == {"rejected"}  # terminal, mirrors the submission


def test_split_needs_third_verdict_then_agree_reproduces(client, conn):
    _, claim_id, ext_sub = setup(client)
    _, _, d1 = blind(client, "victor", DISAGREE)
    _, _, a1 = blind(client, "wendy", AGREE, "gemini")
    assert a1["status"] == "verifying" and len(a1["spawned_task_ids"]) == 1  # 1–1: third check
    assert client.get(f"/api/v1/claims/{claim_id}").json()["value_hidden"] is True
    _, _, a2 = blind(client, "xavi", AGREE, "open-weight")
    assert a2["status"] == "verified" and a2["spawned_task_ids"] == []
    c = client.get(f"/api/v1/claims/{claim_id}").json()
    assert c["tier"] == "reproduced" and c["special_status"] is None and c["value"] == 72.4
    assert credits(client) == {"alice": 10, "victor": 0, "wendy": 4, "xavi": 4}
    assert sub_status(conn, d1["submission_id"]) == "rejected" and sub_status(conn, a1["submission_id"]) == "verified"
    assert sub_status(conn, ext_sub) == "verified"
    assert not db.scalar(conn, f"""SELECT COUNT(*) FROM tasks WHERE type='verify.blind_extract'
                                   AND status IN {lifecycle.PENDING_TASK_STATUSES}""")


def test_split_then_disagree_disputes(client):
    _, claim_id, _ = setup(client)
    blind(client, "victor", AGREE | {"value": 91.0, "quote": OTHER_QUOTE})
    blind(client, "wendy", AGREE, "gemini")
    _, _, out = blind(client, "xavi", NOT_FOUND, "open-weight")
    assert out["status"] == "disputed"
    assert client.get(f"/api/v1/claims/{claim_id}").json()["display_status"] == "disputed"
    assert credits(client) == {"alice": 0, "victor": 0, "wendy": 0, "xavi": 0}


def test_first_verifier_and_author_cannot_take_tiebreak(client):
    alice, _, _ = setup(client)
    v, _, out = blind(client, "victor", DISAGREE)
    tb = out["spawned_task_ids"][0]
    assert claim(client, v, task_types=["verify.blind_extract"]).status_code == 204
    assert claim(client, alice, task_types=["verify.blind_extract"]).status_code == 204
    w = register(client, "wendy", "gemini")
    assert claim(client, w, task_types=["verify.blind_extract"]).json()["task"]["id"] == tb


def test_value_hidden_during_tiebreak(client):
    _, claim_id, _ = setup(client)
    _, _, out = blind(client, "victor", DISAGREE)
    tb = out["spawned_task_ids"][0]
    w = register(client, "wendy", "gemini")
    leased = claim(client, w, task_types=["verify.blind_extract"])
    c = client.get(f"/api/v1/claims/{claim_id}").json()
    assert c["value"] is None and c["quote"] is None and c["value_hidden"] is True
    assert all(t["detail"] is None for t in c["trail"])
    assert any(t["kind"] == "claim_blind_split" for t in c["trail"])
    blobs = [leased.text, client.get(f"/api/v1/tasks/{tb}").text, client.get(f"/api/v1/claims/{claim_id}").text,
             client.get("/api/v1/claims").text, client.get("/api/v1/map").text, client.get("/api/v1/activity").text,
             client.get("/api/v1/artifacts/foo-agent").text, client.get("/api/v1/me", headers=w).text]
    for b in blobs:  # neither the original value nor the first verifier's blind value
        for needle in ("72.4", "0.724", "91.0", OTHER_QUOTE):
            assert needle not in b, (needle, b[:300])


def test_stale_round_ignores_earlier_verdicts(client, conn):
    _, claim_id, _ = setup(client)
    blind(client, "victor", AGREE)  # round 1: reproduced
    with db.tx(conn):
        conn.execute("UPDATE claims SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (claim_id,))
    assert client.post("/api/v1/admin/generate", headers=STEWARD).status_code == 200
    _, _, out = blind(client, "wendy", DISAGREE, "gemini")  # round 2: the old agree must not count
    assert out["status"] == "verifying" and len(out["spawned_task_ids"]) == 1
    _, _, out = blind(client, "xavi", DISAGREE, "open-weight")
    assert out["status"] == "disputed"
    assert credits(client) == {"alice": 10, "victor": 4, "wendy": 0, "xavi": 0}


def test_steward_resolution_mid_tiebreak_settles_round(client, conn):
    _, claim_id, ext_sub = setup(client)
    _, _, out = blind(client, "victor", DISAGREE)
    tb = out["spawned_task_ids"][0]
    client.post(f"/api/v1/admin/claims/{claim_id}/resolve", json={"special_status": "retracted", "note": "x"}, headers=STEWARD)
    assert task_status(conn, tb) == "closed"
    assert sub_status(conn, out["submission_id"]) == "verified"
    assert sub_status(conn, ext_sub) == "rejected"


def test_steward_closing_tiebreak_hands_round_to_steward(client, conn):
    _, claim_id, ext_sub = setup(client)
    _, _, out = blind(client, "victor", DISAGREE)
    r = client.post(f"/api/v1/admin/tasks/{out['spawned_task_ids'][0]}/status", json={"status": "closed"}, headers=STEWARD)
    assert r.status_code < 300, r.text
    assert sub_status(conn, out["submission_id"]) == "needs_steward"
    assert sub_status(conn, ext_sub) == "needs_steward"
