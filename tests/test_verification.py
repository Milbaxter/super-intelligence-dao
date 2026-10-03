"""Verification flow: quote check → T1 → blind agreement → T2 / disputed; reviews; credits."""

from agentdao import db
from conftest import (QUOTE, SOURCE, STEWARD, claim, create_task, do_extract, extract_payload, register, submit)


def _blind_payload(value=72.4, quote=QUOTE):
    return {"found": True, "value": value, "unit": "%", "quote": quote, "conditions": {}}


def test_extract_creates_t1_claim_and_spawns_blind_task(client):
    h = register(client, "alice")
    res = do_extract(client, h)
    assert res["status"] == "verifying"
    assert res["checks"][0]["passed"] and res["checks"][0]["tier"] == "source-checked"
    assert len(res["spawned_task_ids"]) == 1
    blind = client.get(f"/api/v1/tasks/{res['spawned_task_ids'][0]}").json()
    assert blind["type"] == "verify.blind_extract" and blind["status"] == "open"
    assert set(blind["inputs"]) == {"artifact_id", "artifact_name", "benchmark_id", "benchmark_name", "metric",
                                    "source_url", "conditions_hint"}
    assert blind["priority"] > client.get("/api/v1/tasks?type=map.extract").json()["items"][0]["priority"]


def test_failed_quote_is_dropped_and_submission_rejected(client):
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h).json()["lease"]
    bad = extract_payload(quote="This sentence is definitely not on the page: 72.4%")
    res = submit(client, h, lease["id"], bad).json()
    assert res["status"] == "rejected" and res["checks"][0]["detail"] == "quote_not_found"
    assert client.get("/api/v1/claims").json()["total"] == 0


def test_value_not_in_quote_fails(client):
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h).json()["lease"]
    res = submit(client, h, lease["id"], extract_payload(value=55.0)).json()
    assert res["checks"][0]["detail"] == "value_not_in_quote"


def test_invalid_payload_returns_field_errors(client):
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h).json()["lease"]
    r = submit(client, h, lease["id"], {"claims": [{"benchmark": "x"}]})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_payload" and any(f["field"] == "claims[0].value" for f in err["fields"])


def test_blind_value_never_leaked(client):
    h = register(client, "alice")
    res = do_extract(client, h)
    blind_id = res["spawned_task_ids"][0]
    v = register(client, "victor", family="gpt")
    leased = claim(client, v)
    assert leased.status_code == 200 and leased.json()["task"]["id"] == blind_id
    claim_id = res["checks"][0]["claim_id"]
    blobs = [
        leased.text,
        client.get(f"/api/v1/tasks/{blind_id}").text,
        client.get("/api/v1/tasks?limit=500").text,
        client.get(f"/api/v1/claims/{claim_id}").text,
        client.get("/api/v1/claims").text,
        client.get("/api/v1/artifacts/foo-agent").text,
        client.get("/api/v1/map").text,
        client.get("/api/v1/activity").text,
        client.get("/api/v1/me", headers=v).text,
    ]
    for b in blobs:
        assert "72.4" not in b and "0.724" not in b, b[:300]
    c = client.get(f"/api/v1/claims/{claim_id}").json()
    assert c["value"] is None and c["quote"] is None and c["value_hidden"] is True


def test_blind_agreement_promotes_to_t2_and_credits(client):
    h = register(client, "alice")
    res = do_extract(client, h)
    claim_id = res["checks"][0]["claim_id"]
    v = register(client, "victor", family="gpt")
    lease = claim(client, v).json()["lease"]
    blind = {"found": True, "value": 0.724, "unit": "fraction", "quote": QUOTE, "conditions": {}}  # % vs fraction
    out = submit(client, v, lease["id"], blind, tokens=500).json()
    assert out["status"] == "verified"
    c = client.get(f"/api/v1/claims/{claim_id}").json()
    assert c["tier"] == "reproduced" and c["display_status"] == "reproduced" and c["value"] == 72.4
    assert any(t["kind"] == "claim_reproduced" for t in c["trail"])
    people = {p["handle"]: p for p in client.get("/api/v1/contributors").json()}
    assert people["alice"]["credits"] == 10 and people["victor"]["credits"] == 4
    assert people["alice"]["verified_tokens"] == 1000 and people["victor"]["verified_tokens"] == 500
    stats = client.get("/api/v1/stats").json()
    assert stats["claims_by_tier"]["reproduced"] == 1 and stats["verified_tokens"] == 1500
    sub = client.get("/api/v1/me", headers=h).json()["recent_submissions"][0]
    assert sub["status"] == "verified"


def test_values_agree_tolerance():
    from agentdao.lifecycle import values_agree
    assert values_agree(72.4, "%", 72.49, "%") and values_agree(1000, "score", 1004, "score")
    assert not values_agree(72.4, "%", 73.0, "%") and values_agree(72.4, "%", 0.724, "")


def test_blind_disagreement_disputes_claim_and_steward_resolves(client):
    h = register(client, "alice")
    res = do_extract(client, h)
    claim_id = res["checks"][0]["claim_id"]
    v = register(client, "victor", family="gpt")
    lease = claim(client, v).json()["lease"]
    page_quote = "HumanEval pass@1 is 91.0 for the base model"
    out = submit(client, v, lease["id"], _blind_payload(91.0, page_quote)).json()
    assert out["status"] == "disputed"
    assert client.get(f"/api/v1/claims/{claim_id}").json()["display_status"] == "disputed"
    q = client.get("/api/v1/admin/queue", headers=STEWARD).json()
    assert [c["id"] for c in q["disputed_claims"]] == [claim_id]
    r = client.post(f"/api/v1/admin/claims/{claim_id}/resolve", json={"special_status": "retracted", "note": "wrong"}, headers=STEWARD)
    assert r.json()["display_status"] == "retracted"
    people = {p["handle"]: p for p in client.get("/api/v1/contributors").json()}
    assert people["victor"]["credits"] == 6 and people["alice"]["credits"] == 0


def test_blind_with_fabricated_quote_is_rejected_and_task_reopened(client):
    h = register(client, "alice")
    blind_id = do_extract(client, h)["spawned_task_ids"][0]
    v = register(client, "victor", family="gpt")
    lease = claim(client, v).json()["lease"]
    out = submit(client, v, lease["id"], _blind_payload(72.4, "Totally invented sentence with 72.4% inside")).json()
    assert out["status"] == "rejected"
    assert client.get(f"/api/v1/tasks/{blind_id}").json()["status"] == "open"


def test_cannot_verify_own_work_or_same_claim_twice(client, conn):
    h = register(client, "alice")
    blind_id = do_extract(client, h)["spawned_task_ids"][0]
    assert claim(client, h, task_types=["verify.blind_extract"]).status_code == 204  # own work
    v = register(client, "victor", family="gpt")
    lease = claim(client, v).json()["lease"]
    client.post(f"/api/v1/leases/{lease['id']}/release", json={"reason": "quota"}, headers=v)
    # a second blind task for the same claim (e.g. steward-spawned) must not go to victor
    with db.tx(conn):
        conn.execute("""INSERT INTO tasks (id,type,title,inputs,status,priority,created_at,updated_at,target_claim_id,parent_submission_id)
                        SELECT 't_second', type, title, inputs, 'open', 99, created_at, updated_at, target_claim_id, parent_submission_id
                        FROM tasks WHERE id=?""", (blind_id,))
    # not the twin (same claim), and not the released task either (24h release cooldown)
    assert claim(client, v).status_code == 204


def test_family_diversity_preferred(client):
    h = register(client, "alice", family="claude")
    do_extract(client, h)
    create_task(client, title="other map task", priority=7.6)  # slightly above blind (5*1.5=7.5)
    same = register(client, "sam", family="claude")
    assert claim(client, same).json()["task"]["type"] == "map.extract"
    diff = register(client, "gwen", family="gemini")
    assert claim(client, diff).json()["task"]["type"] == "verify.blind_extract"


def test_profile_review_accept_updates_artifact_and_credits_reviewer(client):
    h = register(client, "alice")
    create_task(client, "map.profile")
    lease = claim(client, h).json()["lease"]
    payload = {"fields": {"license": "Apache-2.0"},
               "sources": [{"field": "license", "url": SOURCE, "quote": "Licensed under the Apache-2.0 license"}]}
    res = submit(client, h, lease["id"], payload).json()
    assert res["status"] == "verifying" and len(res["spawned_task_ids"]) == 1
    r = register(client, "rita", family="gpt")
    rl = claim(client, r).json()
    assert rl["task"]["type"] == "verify.review" and rl["task"]["inputs"]["payload"] == payload
    out = submit(client, r, rl["lease"]["id"], {"verdict": "accept", "reasons": ["source matches"], "issues": []}).json()
    assert out["status"] == "verified"
    assert client.get("/api/v1/artifacts/foo-agent").json()["license"] == "Apache-2.0"
    people = {p["handle"]: p for p in client.get("/api/v1/contributors").json()}
    assert people["rita"]["credits"] == 2


def test_gap_scan_review_then_steward_accept(client):
    h = register(client, "alice")
    create_task(client, "map.gap_scan", inputs={"layer": "harnesses"})
    lease = claim(client, h).json()["lease"]
    payload = {"gaps": [{"title": "No cost-normalized harness results", "kind": "missing_evidence",
                         "description": "d", "evidence_urls": ["https://example.org/x"]}], "new_artifacts": []}
    submit(client, h, lease["id"], payload)
    r = register(client, "rita", family="gpt")
    rl = claim(client, r).json()["lease"]
    submit(client, r, rl["id"], {"verdict": "accept", "reasons": [], "issues": []})
    gaps = client.get("/api/v1/gaps?status=proposed").json()
    assert len(gaps) == 1
    client.post(f"/api/v1/admin/gaps/{gaps[0]['id']}/resolve", json={"status": "accepted", "note": "ok"}, headers=STEWARD)
    people = {p["handle"]: p for p in client.get("/api/v1/contributors").json()}
    assert people["alice"]["credits"] == 8


def test_taskgen_creates_extract_profile_gapscan_and_is_idempotent(client):
    created = client.post("/api/v1/admin/generate", headers=STEWARD).json()["created"]
    types = sorted(client.get(f"/api/v1/tasks/{t}").json()["type"] for t in created)
    assert types == ["map.extract", "map.gap_scan", "map.profile"]
    assert client.post("/api/v1/admin/generate", headers=STEWARD).json()["created"] == []
