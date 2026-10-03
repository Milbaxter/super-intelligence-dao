"""Fixes from the real-agent field tests: same-IP verify block, release cooldown + `conflict`,
coarse blind hints, ambiguous quotes, /stats in-progress count; X-No-Task-Reason, skill pinning per claim,
minutes capped at lease age, zero-width normalisation, no-results checks, task track_name."""

from datetime import timedelta

from agentdao import db
from agentdao.verify import FetchResult, normalize, quote_ambiguity
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


def test_quote_ambiguity_two_candidates_and_identifiers():
    # two same-format numbers are enough: either value would pass the quote check
    assert quote_ambiguity("reaches 85.9% and 87.7% in Pass@1", 85.9)
    assert quote_ambiguity("reaches 85.9% and 87.7% in Pass@1", 87.7)
    assert not quote_ambiguity("reaches 85.9% in Pass@1 on the 2026 split", 85.9)
    # version numbers inside identifiers don't count
    for name in ("GLM-5.3", "V4.1", "gpt-4.1", "DeepSeek-V3.1", "GLM\u20115.3"):
        assert not quote_ambiguity(f"{name} scores 64.0 on the benchmark", 64.0), name
    assert not quote_ambiguity("Qwen3-8B scores 64 on the benchmark with 128k context", 64)
    assert quote_ambiguity("GLM 5.3 Flash scores 64.0 on the benchmark", 64.0)  # space-separated: accepted false positive
    assert quote_ambiguity("72.4x and 72.4. and 68.1", 72.4)  # "72.4x" skipped, "72.4." and "68.1" counted


def test_two_number_quote_needs_notes(client, fetcher):
    url = "https://example.org/two"
    quote = "Foo-Agent reaches 85.9% and 87.7% in Pass@1 on SWE-bench Verified"
    fetcher.pages[url] = FetchResult(url, 200, "text/html", f"<p>{quote}</p>".encode())
    h = register(client, "alice")
    create_task(client)
    p = extract_payload(value=85.9, quote=quote, source=url)
    p["claims"][0]["conditions"] = {"model": "claude-x"}
    res = submit(client, h, claim(client, h).json()["lease"]["id"], p).json()
    assert res["checks"][0]["detail"] == "ambiguous_quote_needs_notes" and res["status"] == "rejected"


def test_normalize_strips_zero_width():
    assert normalize("72.4\u200b% of\u200c ta\u200dsks\u2060\ufeff") == "72.4% of tasks"


def test_zero_width_in_page_and_quote(client, fetcher):
    url = "https://example.org/zw"
    fetcher.pages[url] = FetchResult(url, 200, "text/html",
                                     "<p>On SWE-bench Verified, Foo\u200b-Agent resolves 72.4% of tasks</p>".encode())
    h = register(client, "alice")
    create_task(client)
    p = extract_payload(quote="On SWE-bench Verified, Foo-Agent\ufeff resolves 72.4% of tasks", source=url)
    res = submit(client, h, claim(client, h).json()["lease"]["id"], p).json()
    assert res["checks"][0]["passed"], res


def _reason(r):
    assert r.status_code == 204 and not r.content
    return r.headers["X-No-Task-Reason"]


def test_no_task_reason_header(client):
    h = register(client, "alice")
    assert _reason(claim(client, h)) == "no_open_tasks"
    create_task(client, budget_minutes=30)
    assert _reason(claim(client, h, task_types=["map.profile"])) == "no_tasks_of_requested_types"
    assert _reason(claim(client, h, task_types=["map.extract"], max_minutes=10)) == "all_over_max_minutes"
    assert _reason(claim(client, h, max_minutes=10)) == "all_over_max_minutes"
    create_task(client, title="gpt only", allowed_model_families=["gpt"], budget_minutes=5)
    assert _reason(claim(client, h, max_minutes=10)) == "none_eligible_for_you"  # fits, but wrong family
    assert claim(client, h, task_types=["map.extract"]).status_code == 200


def test_no_task_reason_own_work(client):
    h = register(client, "alice")
    do_extract(client, h)
    assert _reason(claim(client, h, task_types=["verify.blind_extract"])) == "none_eligible_for_you"


def test_claim_skill_pin(app, client):
    agent = app.state.settings.agent_dir
    agent.mkdir(parents=True)
    (agent / "join.md").write_text("Join v{{SKILL_VERSION}}")
    sv = client.get("/skill-version").json()
    tid = create_task(client)
    h = register(client, "alice")
    r = claim(client, h, skill_sha256="0" * 64)
    err = r.json()["error"]
    assert r.status_code == 409 and err["code"] == "skill_changed"
    assert err["current_version"] == sv["version"] and err["current_sha256"] == sv["sha256"]
    assert client.get(f"/api/v1/tasks/{tid}").json()["status"] == "open"
    assert client.get("/api/v1/me", headers=h).json()["active_leases"] == []
    assert claim(client, h, skill_sha256=sv["sha256"].upper()).status_code == 200


def test_minutes_spent_capped_at_lease_age(client, conn):
    h = register(client, "alice")
    minutes = {}
    for label, reported, age_s in (("over", 120, 0), ("over_aged", 120, 630), ("under", 4, 630), ("omitted", None, 630)):
        create_task(client, title=label)
        lease = claim(client, h).json()["lease"]
        conn.execute("UPDATE leases SET created_at=? WHERE id=?", (db.ts_in(seconds=-age_s), lease["id"]))
        body = {"payload": extract_payload(), "model": "m"}
        if reported is not None:
            body["minutes_spent"] = reported
        sid = client.post(f"/api/v1/leases/{lease['id']}/submit", json=body, headers=h).json()["submission_id"]
        minutes[label] = db.scalar(conn, "SELECT minutes_spent FROM submissions WHERE id=?", (sid,))
    assert minutes == {"over": 1, "over_aged": 11, "under": 4, "omitted": 11}


def test_no_results_needs_searched_url_and_reports_check(client):
    h = register(client, "alice")
    create_task(client)
    lease = claim(client, h).json()["lease"]
    for searched in ([], ["not a url"], ["ftp://x"]):
        r = submit(client, h, lease["id"], {"claims": [], "no_results_found": True, "searched": searched})
        assert r.status_code == 422 and r.json()["error"]["fields"][0]["field"] == "searched"
    res = submit(client, h, lease["id"], {"claims": [], "no_results_found": True,
                                         "searched": ["https://example.org/a", "https://example.org/b", "junk"]}).json()
    assert res["status"] == "verifying" and len(res["spawned_task_ids"]) == 1
    assert res["checks"] == [{"name": "no_results", "passed": True,
                              "detail": "queued for verify.review; 2 searched URLs listed"}]


def test_task_json_has_track_name(client):
    tid = create_task(client)
    assert client.get(f"/api/v1/tasks/{tid}").json()["track_name"] == "Map harnesses"
    assert client.get("/api/v1/tasks").json()["items"][0]["track_name"] == "Map harnesses"
    h = register(client, "alice")
    assert claim(client, h).json()["task"]["track_name"] == "Map harnesses"


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
