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


# ---- value redaction while a round is undecided but nothing is on the board


def give_up(client, task_id, n=3):
    """n fresh verifiers lease the blind task and release it with a counted reason (MAX_ATTEMPTS=3 → needs_steward)."""
    for i in range(n):
        h = register(client, f"quitter{task_id[-6:]}{i}", "gemini")
        r = claim(client, h, task_types=["verify.blind_extract"])
        assert r.status_code == 200 and r.json()["task"]["id"] == task_id, r.text
        assert client.post(f"/api/v1/leases/{r.json()['lease']['id']}/release", json={"reason": "gave_up"},
                           headers=h).status_code < 300


def value_shown(client, claim_id) -> bool:
    """Checks every public surface agrees on whether the claim's value is withheld; returns True if shown."""
    c = client.get(f"/api/v1/claims/{claim_id}").json()
    cell = next(cell for l in client.get("/api/v1/map").json()["layers"] for cell in l["cells"] if claim_id in cell["claim_ids"])
    awaiting = client.get("/api/v1/stats").json()["claims_awaiting_referee"]
    listed = next(x for x in client.get("/api/v1/claims").json()["items"] if x["id"] == claim_id)
    if c["value_hidden"]:
        assert c["value"] is None and c["quote"] is None and listed["value"] is None
        assert cell["value_hidden"] is True and cell["value_summary"].startswith("awaiting referee")
        assert awaiting == 1 and "72.4" not in client.get("/api/v1/map").text
        return False
    assert c["value"] == 72.4 and listed["value"] == 72.4 and cell["value_hidden"] is False and awaiting == 0
    return True


def test_value_hidden_while_tiebreak_stuck_in_needs_steward(client, conn):
    _, claim_id, _ = setup(client)
    _, _, out = blind(client, "victor", DISAGREE)
    tb = out["spawned_task_ids"][0]
    give_up(client, tb)
    assert task_status(conn, tb) == "needs_steward"
    assert not value_shown(client, claim_id)  # nothing pending, but the round (1 disagree) is undecided
    client.post(f"/api/v1/admin/claims/{claim_id}/resolve", json={"special_status": "none", "note": "ok"}, headers=STEWARD)
    assert task_status(conn, tb) == "closed"
    assert sub_status(conn, out["submission_id"]) == "rejected"  # claim kept: the disagree verdict loses
    assert value_shown(client, claim_id)


def test_value_hidden_while_first_blind_check_stuck(client, conn):
    _, claim_id, _ = setup(client)
    t1 = db.scalar(conn, "SELECT id FROM tasks WHERE type='verify.blind_extract' AND target_claim_id=?", (claim_id,))
    give_up(client, t1)
    assert task_status(conn, t1) == "needs_steward"
    assert not value_shown(client, claim_id)  # a steward could reopen it: keep it blind
    client.post(f"/api/v1/admin/claims/{claim_id}/resolve", json={"tier": "source-checked", "note": "ok"}, headers=STEWARD)
    assert task_status(conn, t1) == "closed"
    assert value_shown(client, claim_id)


def test_reopened_stuck_blind_task_stays_blind(client, conn):
    _, claim_id, _ = setup(client)
    t1 = db.scalar(conn, "SELECT id FROM tasks WHERE type='verify.blind_extract' AND target_claim_id=?", (claim_id,))
    give_up(client, t1)
    client.post(f"/api/v1/admin/tasks/{t1}/status", json={"status": "open"}, headers=STEWARD)
    assert not value_shown(client, claim_id)
    _, _, out = blind(client, "victor", AGREE)
    assert out["status"] == "verified" and value_shown(client, claim_id)


def test_round_handed_to_steward_stays_hidden_until_resolved(client, conn):
    _, claim_id, _ = setup(client)
    _, t1, out = blind(client, "victor", DISAGREE)
    client.post(f"/api/v1/admin/tasks/{out['spawned_task_ids'][0]}/status", json={"status": "closed"}, headers=STEWARD)
    assert sub_status(conn, out["submission_id"]) == "needs_steward"
    assert not value_shown(client, claim_id)
    client.post(f"/api/v1/admin/claims/{claim_id}/resolve", json={"tier": "reproduced", "note": "ok"}, headers=STEWARD)
    assert sub_status(conn, out["submission_id"]) == "rejected" and task_status(conn, t1) == "rejected"
    assert value_shown(client, claim_id)
