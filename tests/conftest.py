"""Shared fixtures: isolated DB, fake fetcher (no network), helpers for agents and steward."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from agentdao import config, db
from agentdao.app import create_app
from agentdao.verify import FetchError, FetchResult

STEWARD = {"Authorization": "Bearer test-steward"}
SOURCE = "https://example.org/results"
PAGE = """<html><head><script>var x = 1;</script></head><body>
<h1>Results</h1><p>On SWE-bench Verified, Foo-Agent resolves <b>72.4%</b> of tasks with Claude &amp; tools.</p>
<p>HumanEval pass@1 is 91.0 for the base model, measured with greedy decoding.</p>
<p>Licensed under the Apache-2.0 license, see LICENSE for details.</p>
</body></html>"""
QUOTE = "On SWE-bench Verified, Foo-Agent resolves 72.4% of tasks"


class FakeFetcher:
    """url → FetchResult (or FetchError). Records calls (thread-safe); `delays[url]` sleeps before answering."""

    def __init__(self):
        self.pages = {SOURCE: FetchResult(SOURCE, 200, "text/html", PAGE.encode())}
        self.delays: dict[str, float] = {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, url):
        with self._lock:
            self.calls.append(url)
        if url in self.delays:
            time.sleep(self.delays[url])
        page = self.pages.get(url)
        if page is None:
            raise FetchError("http_error", "not found", 404)
        return page


@pytest.fixture
def fetcher():
    return FakeFetcher()


@pytest.fixture
def app(tmp_path, fetcher):
    settings = config.Settings(db_path=str(tmp_path / "t.db"), public_url="http://test", steward_key="test-steward",
                               web_dir=tmp_path / "web", agent_dir=tmp_path / "agent", seed_dir=tmp_path / "seed",
                               dev_allow_same_ip=True)  # TestClient: every agent shares one IP
    a = create_app(settings, fetcher=fetcher)
    conn = db.connect(settings.db_path)
    with db.tx(conn):
        conn.execute("INSERT INTO layers (id,name,description,sort) VALUES ('harnesses','Harnesses','',1)")
        conn.execute("INSERT INTO tracks (id,name,workstream,phase,weight,sort) VALUES ('map-harnesses','Map harnesses','map','now',5,1)")
        conn.execute("INSERT INTO tracks (id,name,workstream,phase,weight,sort) VALUES ('referee-agreement','Agreement','referee','now',5,2)")
        now = db.now_ts()
        conn.execute("""INSERT INTO artifacts (id,name,layer,kind,url,created_at,updated_at)
                        VALUES ('foo-agent','Foo-Agent','harnesses','harness','https://example.org',?,?)""", (now, now))
        conn.execute("INSERT INTO benchmarks (id,name,layer) VALUES ('swe-bench-verified','SWE-bench Verified','evals')")
    conn.close()
    return a


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def conn(app):
    c = db.connect(app.state.settings.db_path)
    yield c
    c.close()


def register(client, handle, family="claude"):
    code = client.post("/api/v1/admin/invites", json={"count": 1}, headers=STEWARD).json()["codes"][0]
    r = client.post("/api/v1/register", json={"invite_code": code, "handle": handle, "model_family": family})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def create_task(client, type_="map.extract", inputs=None, **kw):
    body = {"type": type_, "title": kw.pop("title", f"{type_} task"), "inputs": inputs or {"artifact_id": "foo-agent"}, **kw}
    r = client.post("/api/v1/admin/tasks", json=body, headers=STEWARD)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def claim(client, headers, **body):
    return client.post("/api/v1/tasks/claim", json=body, headers=headers)


def extract_payload(value=72.4, quote=QUOTE, source=SOURCE):
    return {"claims": [{"benchmark": "swe-bench-verified", "metric": "resolved rate", "value": value, "unit": "%",
                        "higher_is_better": True, "conditions": {"model": "claude-x", "notes": "value 72.4 noted"},
                        "source_url": source, "quote": quote, "reported_by": "artifact-authors"}],
            "no_results_found": False, "searched": [source]}


def submit(client, headers, lease_id, payload, tokens=1000):
    return client.post(f"/api/v1/leases/{lease_id}/submit",
                       json={"payload": payload, "model": "m", "tokens_estimate": tokens, "minutes_spent": 3}, headers=headers)


def do_extract(client, headers, value=72.4):
    """Create + claim + submit a map.extract; returns the submit response JSON."""
    create_task(client)
    r = claim(client, headers, task_types=["map.extract"])
    assert r.status_code == 200, r.text
    res = submit(client, headers, r.json()["lease"]["id"], extract_payload(value))
    assert res.status_code == 200, res.text
    return res.json()
