"""The Council: cycle, sealing, eligibility, Method of Equal Shares, applicability rules, paused tracks, review."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from agentdao import config, council, db, taskgen
from conftest import STEWARD, claim, create_task, register, submit

API = "/api/v1"


# ------------------------------------------------------------------ helpers


def make_verified(conn, handle, n=1, track=None):
    """Give `handle` n verified research submissions (council eligibility)."""
    cid = db.scalar(conn, "SELECT id FROM contributors WHERE handle=?", (handle,))
    with db.tx(conn):
        for _ in range(n):
            tid, now = db.new_id("t"), db.now_ts()
            conn.execute("INSERT INTO tasks (id,type,title,status,track_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                         (tid, "map.gap_scan", "done", "verified", track, now, now))
            conn.execute("""INSERT INTO submissions (id,task_id,contributor_id,model_family,payload,status,tokens_estimate,created_at)
                            VALUES (?,?,?,?,?,?,?,?)""", (db.new_id("s"), tid, cid, "claude", "{}", "verified", 1000, now))


def verify_task(conn, handle, task_id):
    """A verified submission by `handle` on an existing task (resolved now)."""
    cid = db.scalar(conn, "SELECT id FROM contributors WHERE handle=?", (handle,))
    now = db.now_ts()
    with db.tx(conn):
        conn.execute("""INSERT INTO submissions (id,task_id,contributor_id,model_family,payload,status,tokens_estimate,created_at,resolved_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""", (db.new_id("s"), task_id, cid, "claude", "{}", "verified", 1000, now, now))
        conn.execute("UPDATE tasks SET status='verified' WHERE id=?", (task_id,))


def member(client, conn, handle, family="claude", verified=1):
    h = register(client, handle, family)
    if verified:
        make_verified(conn, handle, verified)
    return h


def proposal(title, kind, effect, metric="verified_outputs", target=1, forecast=0.7, track_id="map-harnesses", **success):
    return {"title": title, "kind": kind, "problem": "Answers which harnesses are best; used by map readers.",
            "evidence": "The evidence brief shows few verified outputs here.", "evidence_urls": ["https://example.org/e"],
            "non_goals": "No new benchmarks.", "risks": "Agents could pad with weak claims.",
            "success": {"metric": metric, "target": target, "deadline_days": 7, "track_id": track_id, **success},
            "forecast": forecast, "success_text": "At least one verified output in the track.", "effect": effect}


def extract_tasks(n):
    return [{"type": "map.extract", "title": f"Extract Foo-Agent results #{i}", "inputs": {"artifact_id": "foo-agent"}}
            for i in range(n)]


CRITIQUE = {"strongest_objection": "Little evidence it changes a decision.", "missing_evidence": "No usage data.",
            "gaming_risk": "Padding.", "amendment": "Halve the tasks.", "forecast": 0.4, "recommend": "amend"}


def claim_ok(client, h, **body):
    r = claim(client, h, **body)
    assert r.status_code == 200, (r.status_code, r.text, r.headers.get("x-no-task-reason"))
    return r.json()


def submit_ok(client, h, lease_id, payload):
    r = submit(client, h, lease_id, payload)
    assert r.status_code == 200, r.text
    return r.json()


def propose(client, h, payload):
    c = claim_ok(client, h)
    assert c["task"]["type"] == "steer.propose"
    out = submit_ok(client, h, c["lease"]["id"], payload)
    assert out["status"] == "accepted"
    return out["checks"][0]["item_id"]


def advance(client, reason="test: close the stage now"):
    r = client.post(f"{API}/admin/council/advance", json={"reason": reason}, headers=STEWARD)
    assert r.status_code == 200, r.text
    return r.json()


def open_cycle(client, **body):
    r = client.post(f"{API}/admin/council/open", json=body, headers=STEWARD)
    assert r.status_code == 201, r.text
    return r.json()


def public_dump(client):
    """Everything an outsider can read about the council and its tasks."""
    parts = [client.get(f"{API}/council").text, client.get(f"{API}/council/cycles").text,
             client.get(f"{API}/activity?limit=200").text, client.get(f"{API}/council/track-record").text,
             client.get(f"{API}/council/evidence").text]
    for t in client.get(f"{API}/tasks?limit=500").json()["items"]:
        parts.append(client.get(f"{API}/tasks/{t['id']}").text)
    return "\n".join(parts)


def credits(client):
    return {p["handle"]: p["credits"] for p in client.get(f"{API}/contributors").json()}


# ------------------------------------------------------------------ Method of Equal Shares (pure)


def test_mes_majority_bloc_cannot_take_everything():
    """10 voters, budget 10 (share 1). A 6-voter bloc approves A1–A3, a 4-voter minority B1–B2, all cost 3.
    Approval-count greedy would fund A1, A2, A3. MES: A1 (ρ .5), A2 (ρ .5, the bloc is now spent), B1 (ρ .75)."""
    bloc, minority = [f"a{i}" for i in range(6)], [f"b{i}" for i in range(4)]
    items = [{"id": x, "cost": 3, "approvers": bloc} for x in ("A1", "A2", "A3")]
    items += [{"id": x, "cost": 3, "approvers": minority} for x in ("B1", "B2")]
    r = council.equal_shares(bloc + minority, items, 10)
    assert {k for k, v in r.items() if v["funded"]} == {"A1", "A2", "B1"}
    assert r["A1"]["rho"] == 0.5 and r["A2"]["rho"] == 0.5 and r["B1"]["rho"] == 0.75
    assert r["B1"]["why"] == "Funded: 4 of 10 voters approved; each paid 0.75 slots"
    # A3: 60% approval but only 1 slot left (cost 3); B2: the minority had 1 slot left and 40% < 50%.
    assert r["A3"]["why"] == ("Not funded: its 6 approvers had spent their shares on items they also approved "
                              "(0 slots left, cost 3); completion step: cost 3 > remaining budget 1")
    assert r["B2"]["why"].startswith("Not funded: its 4 approvers had spent their shares")
    assert r["B2"]["why"].endswith("the completion step needs ≥ 50% approval, it had 40%")


def test_mes_uneven_payments():
    """3 voters, budget 30 (share 10). X(12, abc) ρ=4 → 6 each; Y(4, a) ρ=4 → a has 2; Z(13, abc): a pays 2,
    b and c pay 5.5 (Σ = 13)."""
    items = [{"id": "X", "cost": 12, "approvers": ["a", "b", "c"]}, {"id": "Y", "cost": 4, "approvers": ["a"]},
             {"id": "Z", "cost": 13, "approvers": ["a", "b", "c"]}]
    r = council.equal_shares(["a", "b", "c"], items, 30)
    assert all(r[i]["funded"] and r[i]["step"] == "equal_shares" for i in "XYZ")
    assert (r["X"]["rho"], r["Y"]["rho"], r["Z"]["rho"]) == (4, 4, 5.5)
    assert r["Z"]["paid"] == 13
    assert "up to 5.5 slots" in r["Z"]["why"]
    assert council._rho([2, 6, 6], 13) == 5.5 and council._rho([1, 1], 3) == float("inf")


def test_mes_tie_breaks_on_approvers_then_cost_then_order():
    # X and Y both ρ = 1; Y has more approvers → funded first; then only 1 slot is left for X (cost 2).
    items = [{"id": "X", "cost": 2, "approvers": ["a", "b"]}, {"id": "Y", "cost": 3, "approvers": ["a", "b", "c"]}]
    r = council.equal_shares(["a", "b", "c"], items, 4.5)
    assert r["Y"]["funded"] and not r["X"]["funded"]
    # Same ρ, approvers and cost → earlier submission wins.
    items = [{"id": "P", "cost": 2, "approvers": ["a", "b"]}, {"id": "Q", "cost": 2, "approvers": ["a", "b"]}]
    r = council.equal_shares(["a", "b"], items, 2)
    assert r["P"]["funded"] and not r["Q"]["funded"]


def test_mes_completion_step_and_reasons():
    """4 voters, budget 8 (share 2). P(5, ab) is never affordable under MES (shares 4 < 5); Q(2, c) is.
    Completion: P has 50% approval and 6 slots remain → funded."""
    items = [{"id": "P", "cost": 5, "approvers": ["a", "b"]}, {"id": "Q", "cost": 2, "approvers": ["c"]},
             {"id": "R", "cost": 30, "approvers": ["a"]}, {"id": "S", "cost": 1, "approvers": []}]
    r = council.equal_shares(["a", "b", "c", "d"], items, 8)
    assert r["Q"]["step"] == "equal_shares" and r["P"]["step"] == "completion"
    assert r["P"]["why"] == "Funded in the completion step: 2 of 4 voters (50%) approved and its cost 5 fit the 6 slots left"
    assert r["R"]["why"] == "Not funded: cost 30 > total budget 8"
    assert r["S"]["why"] == "Not funded: no voter approved it"
    assert not council.equal_shares([], items, 8)["Q"]["funded"]


def test_mes_too_few_approvers_reason():
    items = [{"id": "T", "cost": 6, "approvers": ["a"]}]
    r = council.equal_shares(["a", "b", "c", "d"], items, 8)
    assert r["T"]["why"].startswith("Not funded: its 1 approver together held 2 slots, less than its cost 6")


def test_shrunk_forecast_and_family_split():
    assert council.shrunk_forecast([], 0.5) == 0.5
    assert council.shrunk_forecast([0.9, 0.8, 0.7], 0.5) == 0.65  # (3·0.8 + 3·0.5) / 6
    assert council.families_disagree({"claude": {"voters": 2, "approval_pct": 100.0},
                                      "gpt": {"voters": 2, "approval_pct": 0.0}})
    assert not council.families_disagree({"claude": {"voters": 2, "approval_pct": 100.0},
                                          "gpt": {"voters": 1, "approval_pct": 0.0}})


def test_proposal_validation():
    bad = council.validate_payload("steer.propose", {"title": "x" * 200, "kind": "nope", "forecast": 1.0})
    fields = {e["field"] for e in bad}
    assert {"title", "kind", "forecast", "problem", "success", "effect"} <= fields
    ok = proposal("t", "tasks", {"track_id": "map-harnesses", "tasks": extract_tasks(2)})
    assert council.validate_payload("steer.propose", ok) == []
    assert council.proposal_cost(ok) == 2
    nt = proposal("t", "new_track", {"id": "map-x", "name": "X", "workstream": "map", "summary": "s", "why": "w",
                                     "weight": 2, "tasks": extract_tasks(3)})
    assert council.validate_payload("steer.propose", nt) == [] and council.proposal_cost(nt) == 4
    app = proposal("t", "applicability", {"task_type": "map.extract", "exclude_artifact_kinds": ["dataset"],
                                           "include_artifact_kinds": ["model"]})
    assert any(e["field"] == "effect" for e in council.validate_payload("steer.propose", app))


# ------------------------------------------------------------------ full cycle


def test_full_cycle(client, conn, monkeypatch):
    alice = member(client, conn, "alice", "claude")
    bob = member(client, conn, "bob", "gpt")
    carol = member(client, conn, "carol", "gemini")
    dave = member(client, conn, "dave", "open-weight")
    cyc = open_cycle(client, budget_slots=10)
    assert cyc["status"] == "propose" and cyc["items"] == []

    a = propose(client, alice, proposal("Extract Foo-Agent twice", "tasks",
                                        {"track_id": "map-harnesses", "tasks": extract_tasks(2)}, forecast=0.7))
    b = propose(client, bob, proposal("Lower harness weight", "reweight", {"track_id": "map-harnesses", "weight": 3}))
    c = propose(client, carol, proposal("Skip datasets", "applicability",
                                        {"task_type": "map.extract", "exclude_artifact_kinds": ["dataset"]},
                                        metric="no_results_rate", target=0.2, track_id=None, forecast=0.6))
    d = propose(client, alice, proposal("Extract a lot", "tasks", {"track_id": "map-harnesses", "tasks": extract_tasks(11)}))
    # alice's person has 2 proposals: no third propose slot for her
    r = claim(client, alice)
    assert r.status_code == 204

    # Sealing during PROPOSE: only a count; nothing of the content anywhere public.
    pub = client.get(f"{API}/council").json()["cycle"]
    assert pub["counts"]["sealed"] == 4 and pub["items"] == []
    dump = public_dump(client)
    for secret in ("Extract Foo-Agent twice", "Lower harness weight", "Skip datasets", "Extract a lot", a, b, c, d):
        assert secret not in dump
    propose_task = client.get(f"{API}/tasks?type=steer.propose&limit=50").json()["items"][0]["id"]
    assert all(s["contributor"] is None for s in client.get(f"{API}/tasks/{propose_task}").json()["submissions"])

    cyc = advance(client)
    assert cyc["status"] == "critique" and cyc["counts"]["on_ballot"] == 4
    assert {i["id"] for i in cyc["items"]} == {a, b, c, d}
    assert all(i["author"] is None and i["proposer_forecast"] is None for i in cyc["items"])
    assert credits(client)["alice"] == 4 and credits(client)["bob"] == 2  # +2 per balloted proposal

    # Critiques: nobody gets their own proposal; each person critiques a proposal at most once.
    authors = {a: "alice", b: "bob", c: "carol", d: "alice"}
    seen: dict[str, list[str]] = {}
    for handle, h in (("alice", alice), ("bob", bob), ("carol", carol), ("dave", dave)):
        while True:
            r = claim(client, h)
            if r.status_code == 204:
                break
            task = r.json()["task"]
            assert task["type"] == "steer.critique"
            item_id = task["inputs"]["item_id"]
            assert authors[item_id] != handle and handle not in seen.get(item_id, [])
            assert "forecast" not in task["inputs"]["proposal"] and "author" not in json.dumps(task["inputs"])
            seen.setdefault(item_id, []).append(handle)
            submit_ok(client, h, r.json()["lease"]["id"], CRITIQUE)
    assert all(len(v) == 2 for v in seen.values()) and set(seen) == {a, b, c, d}
    pub = client.get(f"{API}/council").json()["cycle"]
    assert all(i["critiques"] == [] and i["critique_count"] == 2 for i in pub["items"])  # sealed until VOTE
    assert "Little evidence it changes a decision." not in public_dump(client)

    cyc = advance(client)
    assert cyc["status"] == "vote"
    assert all(len(i["critiques"]) == 2 and i["critiques"][0]["forecast"] is None and i["critiques"][0]["critic"] is None
               for i in cyc["items"])

    def vote(h, approve, **body):
        cl = claim_ok(client, h, **body)
        assert cl["task"]["type"] == "steer.vote"
        inputs = cl["task"]["inputs"]
        assert {x["item_id"] for x in inputs["items"]} == {a, b, c, d}
        assert all("forecast" not in x["proposal"] for x in inputs["items"])
        return submit_ok(client, h, cl["lease"]["id"],
                         {"approve": approve, "forecasts": {a: 0.8, b: 0.5, c: 0.4, d: 0.2}, "comment": "ok"})

    # a ballot must forecast every item
    cl = claim_ok(client, alice)
    r = submit(client, alice, cl["lease"]["id"], {"approve": [a], "forecasts": {a: 0.5}})
    assert r.status_code == 422 and "missing a forecast" in r.text
    submit_ok(client, alice, cl["lease"]["id"], {"approve": [a, b], "forecasts": {a: 0.8, b: 0.5, c: 0.4, d: 0.2}})
    vote(bob, [b, c])
    vote(carol, [c, a, d])
    vote(dave, [b])
    assert claim(client, dave).status_code == 204  # already voted: not offered again by default
    out = vote(dave, [b, c], task_types=["steer.vote"])  # explicit: replaces the earlier ballot
    assert out["checks"][0]["replaced_earlier"] is True
    pub = client.get(f"{API}/council").json()["cycle"]
    assert pub["ballots"] is None and pub["counts"]["ballots"] == 4 and pub["counts"]["ballots_replaced"] == 1

    cyc = advance(client)
    assert cyc["status"] == "ratify" and cyc["results"]["voters"] == 4
    items = {i["id"]: i for i in cyc["items"]}
    # shares 2.5: B (ρ 1/3, 3 approvers) and C (ρ 1/3) first, then A (ρ 1); D costs 11 > 10.
    assert {i for i, x in items.items() if x["tally"]["funded"]} == {a, b, c}
    assert items[d]["tally"]["why"] == "Not funded: cost 11 > total budget 10" and items[d]["status"] == "not_funded"
    assert items[a]["tally"]["why"] == "Funded: 2 of 4 voters approved; each paid 1 slot"
    assert items[a]["author"] == "alice" and items[a]["proposer_forecast"] == 0.7
    # agg forecast for A: 4 voters (0.8) + 2 critics (0.4) → median 0.8 → (6·0.8 + 3·0.5)/9 = 0.7
    assert items[a]["agg_forecast"] == 0.7 and items[a]["tally"]["n_forecasts"] == 6
    ballots = {tuple(x["handles"]): x for x in cyc["ballots"]}
    assert ballots[("dave",)]["approve"] == [b, c] and len(cyc["ballots"]) == 4
    assert items[a]["critiques"][0]["critic"] in ("bob", "carol", "dave")

    # Ratify: veto needs a reason; approve applies the effect.
    r = client.post(f"{API}/admin/council/items/{b}/ratify", json={"decision": "veto"}, headers=STEWARD)
    assert r.status_code == 422
    r = client.post(f"{API}/admin/council/items/{b}/ratify", json={"decision": "veto", "reason": "keep weight 5"}, headers=STEWARD)
    assert r.status_code == 200 and r.json()["steward"] == {"decision": "veto", "reason": "keep weight 5", "by": "steward"}
    r = client.post(f"{API}/admin/council/items/{a}/ratify", json={"decision": "approve", "reason": ""}, headers=STEWARD)
    assert r.status_code == 200 and r.json()["status"] == "applied"
    created = r.json()["tally"]["applied_effect"]["created_task_ids"]
    assert len(created) == 2
    assert db.scalar(conn, "SELECT COUNT(*) FROM tasks WHERE created_by=? AND track_id='map-harnesses' AND status='open'",
                     (f"council:{cyc['id']}",)) == 2
    assert client.get(f"{API}/council").json()["cycle"]["status"] == "ratify"
    r = client.post(f"{API}/admin/council/items/{c}/ratify", json={"decision": "approve"}, headers=STEWARD)
    assert r.status_code == 200
    rules = client.get(f"{API}/council/rules").json()
    assert [(x["task_type"], x["mode"], x["artifact_kinds"]) for x in rules["active"]] == [("map.extract", "exclude", ["dataset"])]
    assert rules["inactive"][0]["artifact_kinds"] == ["dataset", "library", "tool"]
    assert db.scalar(conn, "SELECT weight FROM tracks WHERE id='map-harnesses'") == 5  # vetoed reweight not applied
    ov = client.get(f"{API}/council").json()
    assert ov["cycle"]["status"] == "closed" and ov["veto_rate"] == {"approved": 2, "vetoed": 1, "rate": 0.333}

    # Review at the deadline (lazy): A (scope proposal_tasks by default) gets a verified output on one of its own
    # tasks → met; other work in the track doesn't count; C has < 5 resolved → missed.
    assert all(json.loads(t["inputs"])["council_item"] == a for t in
               db.all_(conn, "SELECT inputs FROM tasks WHERE id IN (?, ?)", created))
    verify_task(conn, "bob", created[0])
    make_verified(conn, "bob", track="map-harnesses")  # same track, not a proposal task: out of scope
    real = db.utcnow
    monkeypatch.setattr(db, "utcnow", lambda: real() + timedelta(days=8))
    make_verified(conn, "bob", track="map-harnesses")  # after the deadline: out of the window
    ov = client.get(f"{API}/council").json()["cycle"]
    st = {i["id"]: i for i in ov["items"]}
    assert st[a]["status"] == "met" and st[a]["measured_value"] == 1
    assert st[c]["status"] == "missed" and st[c]["measured_value"] is None
    briers = {(r["person"], r["role"]): r["brier"] for r in db.all_(conn, "SELECT * FROM council_scores WHERE item_id=?", (a,))}
    alice_person = db.scalar(conn, "SELECT person FROM contributors WHERE handle='alice'")
    assert briers[(alice_person, "proposer")] == 0.09 and briers[(alice_person, "voter")] == 0.04
    tr = {tuple(p["handles"]): p for p in client.get(f"{API}/council/track-record").json()["people"]}
    assert tr[("alice",)]["proposals"] == 2 and tr[("alice",)]["funded"] == 1 and tr[("alice",)]["met"] == 1
    assert tr[("alice",)]["brier_proposer"] == 0.09
    cr = credits(client)
    n_crit = {h: sum(h in v for v in seen.values()) for h in ("alice", "dave")}
    assert cr["alice"] == 2 * 2 + 2 * n_crit["alice"] + 1 + 6  # balloted ×2, critiques, vote, met
    assert cr["dave"] == 2 * n_crit["dave"] + 1  # critiques + one counted ballot (replacing earns nothing extra)


def test_lazy_stage_advance_by_time(client, conn, monkeypatch):
    alice = member(client, conn, "alice")
    open_cycle(client, propose_days=1, critique_days=1, vote_days=1)
    propose(client, alice, proposal("p", "reweight", {"track_id": "map-harnesses", "weight": 2}))
    real = db.utcnow
    monkeypatch.setattr(db, "utcnow", lambda: real() + timedelta(days=1, minutes=1))
    cyc = client.get(f"{API}/council").json()["cycle"]
    assert cyc["status"] == "critique"
    # the next stage keeps its full length from the moment the previous one closed
    assert db.parse_ts(cyc["deadlines"]["critique_until"]) - db.parse_ts(cyc["deadlines"]["propose_until"]) == timedelta(days=1)
    monkeypatch.setattr(db, "utcnow", lambda: real() + timedelta(days=2, minutes=2))
    assert client.get(f"{API}/council").json()["cycle"]["status"] == "vote"
    monkeypatch.setattr(db, "utcnow", lambda: real() + timedelta(days=3, minutes=3))
    cyc = client.get(f"{API}/council").json()["cycle"]
    assert cyc["status"] == "closed" and cyc["results"]["voters"] == 0  # nobody voted: nothing funded
    assert client.get(f"{API}/tasks?status=open").json()["total"] == 0  # stage tasks closed


def test_one_cycle_at_a_time_and_empty_cycle(client):
    open_cycle(client)
    assert client.post(f"{API}/admin/council/open", json={}, headers=STEWARD).status_code == 409
    cyc = advance(client)
    assert cyc["status"] == "closed" and "no proposals" in cyc["note"]
    assert client.post(f"{API}/admin/council/advance", json={"reason": "x"}, headers=STEWARD).status_code == 409
    open_cycle(client)  # a new one may open now


def test_eligibility_rules(client, conn):
    newbie = register(client, "newbie")  # no verified work
    code = client.post(f"{API}/admin/invites", json={"count": 2, "person": "pat"}, headers=STEWARD).json()["codes"]
    pats = []
    for i, cd in enumerate(code):
        r = client.post(f"{API}/register", json={"invite_code": cd, "handle": f"pat{i}", "model_family": "gpt"})
        pats.append({"Authorization": f"Bearer {r.json()['api_key']}"})
        make_verified(conn, f"pat{i}")
    other = member(client, conn, "other", "gemini")
    open_cycle(client)
    assert claim(client, newbie).status_code == 204  # non-verified: can't propose
    p1 = propose(client, pats[0], proposal("one", "reweight", {"track_id": "map-harnesses", "weight": 2}))
    propose(client, pats[1], proposal("two", "reweight", {"track_id": "map-harnesses", "weight": 4}))
    assert claim(client, pats[0]).status_code == 204  # the person "pat" has 2 proposals (across both agents)
    assert claim(client, pats[1]).status_code == 204
    advance(client)
    # pat's agents can't critique pat's proposals; newbie can't critique at all; other critiques each once.
    assert claim(client, pats[0]).status_code == 204 and claim(client, pats[1]).status_code == 204
    assert claim(client, newbie).status_code == 204
    got = []
    for _ in range(2):
        cl = claim_ok(client, other)
        got.append(cl["task"]["inputs"]["item_id"])
        submit_ok(client, other, cl["lease"]["id"], CRITIQUE)
    assert p1 in got and len(set(got)) == 2
    assert claim(client, other).status_code == 204
    advance(client)
    assert claim(client, newbie).status_code == 204  # non-verified can't vote
    cl = claim_ok(client, pats[0])
    assert cl["task"]["type"] == "steer.vote"
    assert claim(client, pats[1]).status_code == 204  # one ballot at a time per person


def test_vote_order_shuffled_per_lease(client, conn):
    hs = [member(client, conn, f"mem{i}", fam) for i, fam in enumerate(["claude", "gpt", "gemini", "open-weight"])]
    open_cycle(client)
    for i, h in enumerate(hs):
        propose(client, h, proposal(f"p{i}", "reweight", {"track_id": "map-harnesses", "weight": 1 + i % 5}))
        propose(client, h, proposal(f"q{i}", "reweight", {"track_id": "map-harnesses", "weight": 1 + i % 5}))
    advance(client)
    advance(client)
    orders = []
    for h in hs:
        cl = claim_ok(client, h)
        orders.append([x["item_id"] for x in cl["task"]["inputs"]["items"]])
        again = client.get(f"{API}/tasks/{cl['task']['id']}").json()["inputs"]["items"]
        assert [x["item_id"] for x in again] == orders[-1]  # stable for the same lease
    assert all(sorted(o) == sorted(orders[0]) for o in orders) and len({tuple(o) for o in orders}) > 1


def test_overflow_round_robin(client, conn, monkeypatch):
    monkeypatch.setattr(config, "COUNCIL_MAX_BALLOT", 2)
    x, y = member(client, conn, "xxx"), member(client, conn, "yyy", "gpt")
    open_cycle(client)
    x1 = propose(client, x, proposal("x1", "reweight", {"track_id": "map-harnesses", "weight": 2}))
    propose(client, x, proposal("x2", "reweight", {"track_id": "map-harnesses", "weight": 3}))
    y1 = propose(client, y, proposal("y1", "reweight", {"track_id": "map-harnesses", "weight": 4}))
    cyc = advance(client)
    st = {i["id"]: i["status"] for i in cyc["items"]}
    assert {k for k, v in st.items() if v == "balloted"} == {x1, y1}
    assert list(st.values()).count("overflow") == 1


def test_withdraw(client, conn):
    a, b = member(client, conn, "aaa"), member(client, conn, "bbb", "gpt")
    open_cycle(client)
    item = propose(client, a, proposal("dup", "reweight", {"track_id": "map-harnesses", "weight": 2}))
    advance(client)
    assert client.post(f"{API}/admin/council/items/{item}/withdraw", json={}, headers=STEWARD).status_code == 422
    r = client.post(f"{API}/admin/council/items/{item}/withdraw", json={"reason": "duplicate of last cycle"}, headers=STEWARD)
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert claim(client, b).status_code == 204  # its critique tasks were closed
    it = client.get(f"{API}/council").json()["cycle"]["items"][0]
    assert it["steward"] == {"decision": "withdraw", "reason": "duplicate of last cycle", "by": "steward"}


def test_retire_and_new_track_effects(client, conn):
    a, b = member(client, conn, "aaa"), member(client, conn, "bbb", "gpt")
    open_task = create_task(client)  # open map.extract in map-harnesses
    open_cycle(client)
    r_item = propose(client, a, proposal("retire", "retire", {"track_id": "map-harnesses"}))
    n_item = propose(client, b, proposal("new", "new_track", {"id": "map-agents", "name": "Agents", "workstream": "map",
                                                               "summary": "s", "why": "w", "weight": 2,
                                                               "tasks": extract_tasks(1)}, track_id="map-agents"))
    advance(client)
    advance(client)
    for h in (a, b):
        cl = claim_ok(client, h, task_types=["steer.vote"])
        submit_ok(client, h, cl["lease"]["id"], {"approve": [r_item, n_item], "forecasts": {r_item: 0.5, n_item: 0.5}})
    advance(client)
    for i in (r_item, n_item):
        assert client.post(f"{API}/admin/council/items/{i}/ratify", json={"decision": "approve"}, headers=STEWARD).status_code == 200
    tracks = {t["id"]: t for t in client.get(f"{API}/tracks").json()}
    assert tracks["map-harnesses"]["weight"] == 0 and tracks["map-harnesses"]["paused"] is True
    assert tracks["map-agents"]["weight"] == 2
    assert db.scalar(conn, "SELECT status FROM tasks WHERE id=?", (open_task,)) == "closed"
    assert db.scalar(conn, "SELECT COUNT(*) FROM tasks WHERE track_id='map-agents' AND status='open'") == 1


# ------------------------------------------------------------------ applicability, paused tracks, not_useful


def _artifact(conn, aid, kind):
    now = db.now_ts()
    with db.tx(conn):
        conn.execute("""INSERT INTO artifacts (id,name,layer,kind,url,license,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?)""", (aid, aid.title(), "harnesses", kind, "https://example.org", None, now, now))


def test_default_rule_and_taskgen(client, conn):
    rules = client.get(f"{API}/council/rules").json()["active"]
    assert [(r["task_type"], r["mode"], r["artifact_kinds"]) for r in rules] == [("map.extract", "exclude", ["dataset", "library", "tool"])]
    _artifact(conn, "some-dataset", "dataset")
    stale = create_task(client, inputs={"artifact_id": "some-dataset"})  # open, unleased, violates the rule
    taskgen.generate(conn)
    assert db.scalar(conn, "SELECT status FROM tasks WHERE id=?", (stale,)) == "closed"
    q = "SELECT COUNT(*) FROM tasks WHERE type=? AND json_extract(inputs,'$.artifact_id')=? AND status='open'"
    assert db.scalar(conn, q, ("map.extract", "some-dataset")) == 0
    assert db.scalar(conn, q, ("map.profile", "some-dataset")) == 1  # profile has no rule
    assert db.scalar(conn, q, ("map.extract", "foo-agent")) == 1
    assert any(e["kind"] == "tasks_closed_by_rule" for e in client.get(f"{API}/activity").json())
    # a new include rule replaces the type's previous rule and closes violating tasks at once
    council.add_rule(conn, "map.extract", "include", ["model"], "steward", "test")
    assert db.scalar(conn, q, ("map.extract", "foo-agent")) == 0


def test_paused_track(client, conn):
    h = register(client, "worker")
    tid = create_task(client)
    with db.tx(conn):
        conn.execute("UPDATE tracks SET weight=0 WHERE id='map-harnesses'")
    r = claim(client, h)
    assert r.status_code == 204  # tasks of a paused track are not offered
    conn.execute("UPDATE tasks SET status='closed' WHERE id=?", (tid,))
    taskgen.generate(conn)
    assert db.scalar(conn, "SELECT COUNT(*) FROM tasks WHERE status='open' AND track_id='map-harnesses'") == 0


def test_not_useful_release(client, conn):
    h = register(client, "worker")
    tid = create_task(client)
    lease = claim_ok(client, h)["lease"]["id"]
    r = client.post(f"{API}/leases/{lease}/release", json={"reason": "not_useful"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "note_required"
    r = client.post(f"{API}/leases/{lease}/release", json={"reason": "not_useful", "note": "harness has no benchmarks"}, headers=h)
    assert r.status_code == 200
    assert db.scalar(conn, "SELECT attempts FROM tasks WHERE id=?", (tid,)) == 0  # free release
    ev = client.get(f"{API}/council/evidence").json()
    by_type = {t["task_type"]: t for t in ev["by_task_type"]}
    assert by_type["map.extract"]["all"]["releases"]["not_useful"] == 1
    assert "30d" not in by_type["map.extract"]  # identical to `all` → omitted
    tr = {t["track_id"]: t for t in ev["by_track"]}
    assert tr["map-harnesses"]["all"]["releases"]["not_useful"] == 1 and tr["map-harnesses"]["weight"] == 5
    assert ev["coverage"][0]["layer"] == "harnesses" and ev["rules"][0]["task_type"] == "map.extract"


def test_steward_cannot_create_steer_tasks(client):
    r = client.post(f"{API}/admin/tasks", json={"type": "steer.vote", "title": "x"}, headers=STEWARD)
    assert r.status_code == 422


@pytest.mark.parametrize("payload,field", [
    ({"approve": "x", "forecasts": {}}, "approve"),
    ({"approve": [], "forecasts": {"a": 1.5}}, "forecasts"),
])
def test_vote_payload_validation(payload, field):
    assert field in {e["field"] for e in council.validate_payload("steer.vote", payload)}


# ------------------------------------------------------------------ v1.1: field-test fixes


def test_rules_apply_to_existing_tasks_at_claim_and_startup(app, client, conn):
    """Open tasks that break an active rule are never offered, and the startup sweep closes them (idempotently)."""
    from agentdao.app import _startup_sweep
    h = register(client, "worker")
    _artifact(conn, "some-dataset", "dataset")
    bad = create_task(client, inputs={"artifact_id": "some-dataset"}, priority=99)  # top of the queue
    good = create_task(client)
    assert claim_ok(client, h)["task"]["id"] == good  # the violating task is skipped although it ranks first
    _startup_sweep(app.state.settings.db_path)
    assert db.scalar(conn, "SELECT status FROM tasks WHERE id=?", (bad,)) == "closed"
    n_events = db.scalar(conn, "SELECT COUNT(*) FROM events WHERE kind='tasks_closed_by_rule'")
    _startup_sweep(app.state.settings.db_path)
    assert db.scalar(conn, "SELECT COUNT(*) FROM events WHERE kind='tasks_closed_by_rule'") == n_events == 1


def test_relaxed_rule_recreates_tasks(client, conn):
    _artifact(conn, "some-dataset", "dataset")
    q = "SELECT COUNT(*) FROM tasks WHERE type='map.extract' AND json_extract(inputs,'$.artifact_id')=? AND status='open'"
    taskgen.generate(conn)
    assert db.scalar(conn, q, ("some-dataset",)) == 0
    out = council.add_rule(conn, "map.extract", "exclude", ["tool"], "steward", "datasets do have leaderboards")
    assert len(out["recreated_task_ids"]) == 1 and db.scalar(conn, q, ("some-dataset",)) == 1
    out = council.add_rule(conn, "map.extract", "exclude", ["dataset"], "steward", "back again")
    assert out["closed_tasks"] == 1 and out["recreated_task_ids"] == [] and db.scalar(conn, q, ("some-dataset",)) == 0


def test_proposal_for_rule_excluded_artifact_is_rejected(client, conn):
    a = member(client, conn, "aaa")
    _artifact(conn, "some-dataset", "dataset")
    open_cycle(client)
    cl = claim_ok(client, a)
    bad = proposal("x", "tasks", {"track_id": "map-harnesses", "tasks": [
        {"type": "map.extract", "title": "t", "inputs": {"artifact_id": "some-dataset"}}]})
    r = submit(client, a, cl["lease"]["id"], bad)
    assert r.status_code == 422 and "applicability rule" in r.text


def test_mes_skips_conflicting_item():
    items = [{"id": "A", "cost": 1, "title": "Exclude apps", "approvers": ["a", "b", "c"], "conflicts": ["B"]},
             {"id": "B", "cost": 1, "title": "Include models", "approvers": ["a", "b"], "conflicts": ["A"]},
             {"id": "C", "cost": 1, "approvers": ["c"]}]
    r = council.equal_shares(["a", "b", "c"], items, 9)
    assert r["A"]["funded"] and r["C"]["funded"] and not r["B"]["funded"]
    assert r["B"]["why"] == "Not funded: conflicts with Exclude apps (funded first)"


def test_ballot_relations():
    app_rule = {"kind": "applicability", "effect": {"task_type": "map.extract", "exclude_artifact_kinds": ["app"]}}
    items = [{"id": "A", "title": "Skip apps in extraction", **app_rule},
             {"id": "B", "title": "Only models", "kind": "applicability", "effect": {"task_type": "map.extract", "include_artifact_kinds": ["model"]}},
             {"id": "C", "title": "Raise harness weight", "kind": "reweight", "effect": {"track_id": "h", "weight": 5}},
             {"id": "D", "title": "Pause harnesses", "kind": "retire", "effect": {"track_id": "h"}},
             {"id": "E", "title": "Harness tasks", "kind": "tasks", "effect": {"track_id": "h", "tasks": []}},
             {"id": "F", "title": "More harness tasks", "kind": "tasks", "effect": {"track_id": "h", "tasks": []}},
             {"id": "G", "title": "Skip apps in profiling", "kind": "applicability", "effect": {"task_type": "map.profile"}}]
    r = council.ballot_relations(items)
    assert r["A"]["conflicts_with"] == ["B"] and r["C"]["conflicts_with"] == ["D"]
    assert sorted(r["D"]["conflicts_with"]) == ["C", "E", "F"] and r["E"]["conflicts_with"] == ["D"]
    assert r["E"]["similar_to"] == ["F"]  # same kind + target, no conflict
    assert r["A"]["similar_to"] == ["G"]  # title Jaccard 3/5 ≥ 0.5
    assert sorted(r["C"]["related"]) == ["D", "E", "F"] and r["G"]["related"] == []


def test_conflicts_shown_from_vote_and_critique_bodies_sealed(client, conn):
    a, b, c = member(client, conn, "aaa"), member(client, conn, "bbb", "gpt"), member(client, conn, "ccc", "gemini")
    open_cycle(client, budget_slots=10)
    x = propose(client, a, proposal("Skip apps", "applicability", {"task_type": "map.extract", "exclude_artifact_kinds": ["app"]},
                                    metric="no_results_rate", target=0.2, track_id=None))
    y = propose(client, b, proposal("Only models", "applicability", {"task_type": "map.extract", "include_artifact_kinds": ["model"]},
                                    metric="no_results_rate", target=0.2, track_id=None))
    cyc = advance(client)
    # CRITIQUE: only id/kind/title/cost publicly; critique tasks' proposals redacted in public reads
    assert all(i["proposal"] is None and i["conflicts_with"] is None for i in cyc["items"])
    assert "Answers which harnesses are best" not in public_dump(client)
    cl = claim_ok(client, c)
    assert cl["task"]["inputs"]["proposal"]["problem"].startswith("Answers")  # the lease holder sees it
    other = y if cl["task"]["inputs"]["item_id"] == x else x
    assert cl["task"]["inputs"]["related_items"] == [{"item_id": other, "title": "Only models" if other == y else "Skip apps",
                                                      "kind": "applicability", "conflicts": True}]
    pub = client.get(f"{API}/tasks/{cl['task']['id']}").json()["inputs"]["proposal"]
    assert "problem" not in pub and pub["sealed"]
    cyc = advance(client)
    items = {i["id"]: i for i in cyc["items"]}
    assert items[x]["conflicts_with"] == [y] and items[x]["proposal"]["problem"]
    for n, h in enumerate((a, b, c)):
        cl = claim_ok(client, h, task_types=["steer.vote"])
        if n == 0:
            assert {v["item_id"]: v["conflicts_with"] for v in cl["task"]["inputs"]["items"]} == {x: [y], y: [x]}
        submit_ok(client, h, cl["lease"]["id"], {"approve": [x, y], "forecasts": {x: 0.5, y: 0.5}})
    cyc = advance(client)
    t = {i["id"]: i["tally"] for i in cyc["items"]}
    assert t[x]["funded"] and not t[y]["funded"] and t[y]["why"] == "Not funded: conflicts with Skip apps (funded first)"
    assert t[y]["conflicts_with"] == [x]


def test_advance_needs_reason_and_is_recorded(client, conn):
    open_cycle(client)
    r = client.post(f"{API}/admin/council/advance", headers=STEWARD)
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    cyc = advance(client, reason="nobody is proposing")
    assert cyc["stage_notes"][0]["stage"] == "propose" and cyc["stage_notes"][0]["reason"] == "nobody is proposing"
    assert cyc["stage_notes"][0]["early"] is True
    assert any(e["summary"] == "steward closed the propose stage early: nobody is proposing"
               for e in client.get(f"{API}/activity").json())


def test_success_scope_validation_and_measure(client, conn):
    errs = lambda p: {e["field"] for e in council.validate_payload("steer.propose", p)}  # noqa: E731
    assert "success.scope" in errs(proposal("r", "reweight", {"track_id": "map-harnesses", "weight": 2}, scope="proposal_tasks"))
    assert "success.reported_by" in errs(proposal("r", "reweight", {"track_id": "map-harnesses", "weight": 2}, reported_by="third-party"))
    assert not errs(proposal("r", "reweight", {"track_id": "map-harnesses", "weight": 2}, metric="reproduced_claims",
                             reported_by="leaderboard"))
    assert council._clean_proposal(proposal("t", "tasks", {}))["success"]["scope"] == "proposal_tasks"
    assert council._clean_proposal(proposal("t", "retire", {}))["success"]["scope"] == "track"
    # measure: window [applied_at, review_due_at) and scope
    member(client, conn, "bob")
    t0, t1 = db.ts_in(days=-1), db.ts_in(days=1)
    mine = create_task(client, inputs={"artifact_id": "foo-agent", "council_item": "ci_x"})
    other = create_task(client)
    verify_task(conn, "bob", mine)
    verify_task(conn, "bob", other)
    item = lambda scope: {"id": "ci_x", "applied_at": t0, "review_due_at": t1, "payload": json.dumps(  # noqa: E731
        {"success": {"metric": "verified_outputs", "target": 1, "track_id": "map-harnesses", "scope": scope}})}
    assert council.measure(conn, item("proposal_tasks")) == 1 and council.measure(conn, item("track")) == 2
    assert council.measure(conn, {**item("track"), "review_due_at": db.ts_in(days=-0.5)}) == 0


def test_evidence_brief_same_shape_in_task_inputs(client, conn):
    a = member(client, conn, "aaa")
    open_cycle(client)
    full = client.get(f"{API}/council/evidence").json()
    compact = claim_ok(client, a)["task"]["inputs"]["evidence"]
    assert set(full) | {"full_brief_url"} == set(compact)
    assert full["last_cycle"] is None and compact["last_cycle"] is None
    assert [t["track_id"] for t in full["by_track"]] == [t["track_id"] for t in compact["by_track"]]
    st = compact["by_track"][0]["all"]
    assert set(st) == set(council.COMPACT_STAT_KEYS) and set(st) <= set(full["by_track"][0]["all"])
    assert {"open", "leased", "attempted", "median_open_priority"} <= set(st)
    assert full["coverage"][0]["artifacts_by_kind"] == {"harness": 1} and full["active_contributors_30d"] == {"claude": 1}
    assert "verified_outputs" in full["metric_definitions"] and compact["metric_definitions"] == full["metric_definitions"]


def test_no_task_headers(client, conn):
    h = member(client, conn, "aaa")
    create_task(client, budget_minutes=45)
    r = claim(client, h, max_minutes=10, task_types=["map.extract"])
    assert r.status_code == 204 and r.headers["x-no-task-reason"] == "all_over_max_minutes"
    assert r.headers["x-min-budget-minutes"] == "45"
    open_cycle(client)
    propose(client, h, proposal("p", "reweight", {"track_id": "map-harnesses", "weight": 2}))
    advance(client)
    r = claim(client, h, task_types=["steer.critique"])  # only its own proposal is on the ballot
    assert r.status_code == 204 and r.headers["x-no-task-detail"] == "all_items_critiqued_or_own"
