"""Concurrent quote prechecks: ordering, per-URL fetch dedupe, overall deadline, claim cap."""

from agentdao import config
from agentdao.lifecycle import validate_payload
from agentdao.verify import FetchResult, QuoteChecker
from conftest import PAGE, QUOTE, SOURCE, FakeFetcher, claim, create_task, extract_payload, register, submit


def _page(url):
    return FetchResult(url, 200, "text/html", PAGE.encode())


def test_check_many_keeps_input_order():
    f = FakeFetcher()
    urls = [f"https://example.org/p{i}" for i in range(8)]
    for i, u in enumerate(urls):
        f.pages[u] = _page(u)
        f.delays[u] = 0.01 * (8 - i)  # earlier items finish last
    items = [(u, QUOTE, 72.4 if i % 2 == 0 else 99.9) for i, u in enumerate(urls)]
    items.append(("https://missing.example/x", QUOTE, 72.4))
    res = QuoteChecker(f).check_many(items, workers=8)
    assert [r["reason"] for r in res] == ["ok", "value_not_in_quote"] * 4 + ["http_error"]
    assert [r["fetched_url"] for r in res[:8:2]] == urls[::2]


def test_same_url_fetched_once_under_concurrency():
    f = FakeFetcher()
    f.delays[SOURCE] = 0.05  # all workers ask while the first fetch is in flight
    res = QuoteChecker(f).check_many([(SOURCE, QUOTE, 72.4)] * 25, workers=8)
    assert all(r["passed"] for r in res) and len(res) == 25
    assert f.calls == [SOURCE]


def test_deadline_yields_timeout_soft_fail(monkeypatch):
    monkeypatch.setattr(config, "PRECHECK_DEADLINE_S", 0.1)
    f = FakeFetcher()
    slow = "https://slow.example/x"
    f.pages[slow] = _page(slow)
    f.delays[slow] = 0.5
    res = QuoteChecker(f).check_many([(slow, QUOTE, 72.4), (SOURCE, QUOTE, 72.4)])
    assert res[0]["reason"] == "timeout" and not res[0]["passed"]
    assert res[1]["passed"]


def test_submit_with_slow_source_keeps_claim_t0(client, fetcher, monkeypatch):
    monkeypatch.setattr(config, "PRECHECK_DEADLINE_S", 0.1)
    slow = "https://slow.example/x"
    fetcher.pages[slow] = _page(slow)
    fetcher.delays[slow] = 0.5
    h = register(client, "slowpoke")
    create_task(client)
    lease = claim(client, h, task_types=["map.extract"]).json()["lease"]["id"]
    r = submit(client, h, lease, extract_payload(source=slow))
    assert r.status_code == 200, r.text
    check = next(c for c in r.json()["checks"] if c["name"] == "claims[0].quote_check")
    assert check["detail"] == "timeout" and check["tier"] == "reported"


def test_extract_claim_cap():
    one = extract_payload()["claims"][0]
    ok = {"claims": [one] * config.MAX_EXTRACT_CLAIMS, "no_results_found": False, "searched": [SOURCE]}
    assert not [e for e in validate_payload("map.extract", ok) if e["field"] == "claims"]


def test_submit_over_claim_cap_rejected(client):
    h = register(client, "greedy")
    create_task(client)
    lease = claim(client, h, task_types=["map.extract"]).json()["lease"]["id"]
    payload = extract_payload()
    payload["claims"] = payload["claims"] * 31
    assert submit(client, h, lease, payload).status_code == 422
