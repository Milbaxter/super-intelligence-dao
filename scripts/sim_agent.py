#!/usr/bin/env python3
"""Simulated Super Intelligence DAO contributors for end-to-end tests (stdlib only; talks ONLY to the public HTTP API).

Two simulated agents:
  * the *extractor* (``--invite/--handle/--model-family``) claims Map tasks and submits plausible payloads;
  * the *verifier* (``--verifier-invite`` …, different handle and preferably a different model family) then claims
    the verify tasks the extractor's submissions spawned (``verify.blind_extract``, ``verify.review``) so a claim can
    reach T2 ``reproduced`` (``--mode honest``) or ``disputed`` (``--mode disagree``).

For ``map.extract`` and ``map.profile`` the sim serves fixture pages from a tiny local HTTP server (loopback only,
default port 8799) and cites them as ``source_url``. The backend must allow ``http://localhost`` sources in dev/test
mode only (see docs/PROTOCOL.md and docs/SECURITY.md).

Examples:
  uv run python scripts/sim_agent.py --base-url http://localhost:8787 --steward-key dev-steward --tasks 3
  python3 scripts/sim_agent.py --invite INV1 --verifier-invite INV2 --handle sim-a --mode disagree --check
Run it against a dev database: verify tasks the sim did not spawn itself are released with reason ``gave_up``.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAMILIES = ["claude", "gpt", "gemini", "open-weight"]
PRIMARY_TYPES = ["map.extract", "map.profile", "map.gap_scan"]
VERIFY_TYPES = ["verify.blind_extract", "verify.review"]
UA = "agentdao-sim/0.1"


def log(who: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {who:>9} | {msg}", flush=True)


# --------------------------------------------------------------------------------------------- fixture pages
def fixture_value(artifact: str, bench: str) -> float:
    h = int(hashlib.sha256(f"{artifact}|{bench}".encode()).hexdigest(), 16)
    return round(40 + (h % 5000) / 100, 1)  # 40.0 – 89.9, deterministic


def results_sentence(a_name: str, b_name: str, metric: str, value: float) -> str:
    return (f"On {b_name}, {a_name} reaches {value}% {metric} with the reference harness "
            f"(single attempt, evaluated September 2026).")


def profile_facts(a_id: str, a_name: str) -> dict:
    h = int(hashlib.sha256(a_id.encode()).hexdigest(), 16)
    ver = f"v{h % 3}.{h % 17}.{h % 7}"
    date = f"2026-{1 + h % 9:02d}-{1 + h % 27:02d}"
    return {
        "license": "Apache-2.0",
        "license_q": f"{a_name} is released under the Apache-2.0 license; see the LICENSE file in the repository.",
        "latest_version": ver,
        "latest_version_q": f"The latest release of {a_name} is {ver}, published on {date} with release notes.",
        "latest_release_date": date,
        "description": f"{a_name} is a simulated fixture artifact used for Super Intelligence DAO end-to-end tests.",
        "description_q": f"{a_name} is a fixture project that exists only to exercise the Super Intelligence DAO test pipeline.",
    }


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        e = html.escape
        if u.path.startswith("/fx/results/"):
            a_id = u.path.rsplit("/", 1)[-1].removesuffix(".html")
            a_name, b_id = q.get("a", a_id), q.get("bid", "bench")
            b_name, metric = q.get("b", b_id), q.get("m", "accuracy")
            v = fixture_value(a_id, b_id)
            body = (f"<h1>{e(a_name)} evaluation report</h1>"
                    f"<p>This page summarises published results for {e(a_name)}. Numbers below are from the authors.</p>"
                    f"<script>var tracking = 'should be stripped 99.9%';</script>"
                    f"<p>{e(results_sentence(a_name, b_name, metric, v))}</p>"
                    f"<p>On SimDecoy-Bench, {e(a_name)} reaches 12.5% accuracy, which is not relevant here.</p>"
                    f"<table><tr><th>Benchmark</th><th>Score</th></tr>"
                    f"<tr><td>{e(b_name)}</td><td>{v}</td></tr></table>")
        elif u.path.startswith("/fx/profile/"):
            a_id = u.path.rsplit("/", 1)[-1].removesuffix(".html")
            f = profile_facts(a_id, q.get("a", a_id))
            body = "".join(f"<p>{e(f[k])}</p>" for k in ("description_q", "license_q", "latest_version_q"))
        elif u.path.startswith("/fx/gap/"):
            body = "<p>Survey notes: no published results exist for open harnesses on open-weight models in this layer.</p>"
        else:
            self.send_response(404); self.end_headers(); return
        data = f"<!doctype html><html><head><meta charset='utf-8'><title>fixture</title></head><body>{body}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _V6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def start_fixture_server(port: int) -> list:
    """Serve fixtures on loopback only (IPv4 + IPv6 so 'localhost' resolves either way)."""
    servers = []
    for cls, host in ((ThreadingHTTPServer, "127.0.0.1"), (_V6Server, "::1")):
        try:
            s = cls((host, port), FixtureHandler)
        except OSError as exc:
            if host == "127.0.0.1":
                raise SystemExit(f"cannot bind fixture server on {host}:{port}: {exc}")
            continue
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
    return servers


# --------------------------------------------------------------------------------------------- HTTP client
class ApiError(Exception):
    def __init__(self, status: int, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


class Api:
    def __init__(self, base_url: str, key: str | None = None, who: str = "sim"):
        self.base, self.key, self.who = base_url.rstrip("/"), key, who

    def raw(self, method: str, url: str, body=None, auth: bool = True, retries: int = 3):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"User-Agent": UA, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth and self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            if exc.code == 429 and retries > 0:
                log(self.who, "429 from server, backing off 5s")
                time.sleep(5)
                return self.raw(method, url, body, auth, retries - 1)
            return exc.code, raw

    def call(self, method: str, path: str, body=None, auth: bool = True, ok=(200, 201, 204)):
        status, raw = self.raw(method, f"{self.base}/api/v1{path}", body, auth)
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw.decode("utf-8", "replace")[:500]
        if status not in ok:
            raise ApiError(status, parsed)
        return status, parsed


# --------------------------------------------------------------------------------------------- payload builders
def pick_benchmark(api: Api, task_inputs: dict, artifact_id: str) -> tuple[str, str, str]:
    hints = (task_inputs.get("hints") or {}).get("benchmarks") or []
    try:
        _, benches = api.call("GET", f"/benchmarks?layer={urllib.parse.quote(task_inputs.get('layer', ''))}", auth=False)
        if not benches:
            _, benches = api.call("GET", "/benchmarks", auth=False)
    except ApiError:
        benches = []
    benches = benches or []
    by_id = {b["id"]: b for b in benches if isinstance(b, dict) and "id" in b}
    for h in hints:
        if h in by_id:
            b = by_id[h]
            return b["id"], b.get("name") or b["id"], "accuracy"
    if benches:
        b = benches[int(hashlib.sha256(artifact_id.encode()).hexdigest(), 16) % len(benches)]
        return b["id"], b.get("name") or b["id"], "accuracy"
    return "sim-bench", "Sim-Bench", "accuracy"


def build_payload(api: Api, task: dict, fx: str, mode: str) -> dict:
    t, inp = task["type"], task.get("inputs") or {}
    a_id = inp.get("artifact_id") or task["id"]
    a_name = inp.get("artifact_name") or a_id
    qa = urllib.parse.quote
    if t == "map.extract":
        b_id, b_name, metric = pick_benchmark(api, inp, a_id)
        v = fixture_value(a_id, b_id)
        url = f"{fx}/fx/results/{qa(a_id)}.html?a={qa(a_name)}&bid={qa(b_id)}&b={qa(b_name)}&m={qa(metric)}"
        return {"claims": [{
            "benchmark": b_id, "metric": metric, "value": v, "unit": "%", "higher_is_better": True,
            "conditions": {"harness": "reference harness", "attempts": 1, "date": "2026-09",
                           "notes": "sim_agent fixture"},
            "source_url": url, "quote": results_sentence(a_name, b_name, metric, v),
            "reported_by": "artifact-authors"}],
            "no_results_found": False, "searched": [url]}
    if t == "map.profile":
        f = profile_facts(a_id, a_name)
        url = f"{fx}/fx/profile/{qa(a_id)}.html?a={qa(a_name)}"
        return {"fields": {"license": f["license"], "latest_version": f["latest_version"],
                           "latest_release_date": f["latest_release_date"], "repo_url": inp.get("repo_url") or None,
                           "homepage": inp.get("artifact_url") or None, "description": f["description"]},
                "sources": [{"field": "license", "url": url, "quote": f["license_q"]},
                            {"field": "latest_version", "url": url, "quote": f["latest_version_q"]},
                            {"field": "latest_release_date", "url": url, "quote": f["latest_version_q"]},
                            {"field": "description", "url": url, "quote": f["description_q"]}]}
    if t == "map.gap_scan":
        layer = inp.get("layer", "harnesses")
        return {"gaps": [{"title": f"[sim] No open-weight results for open harnesses in {layer}",
                          "kind": "missing_evidence",
                          "description": "Simulated gap from sim_agent: the fixture survey lists no published results "
                                         "for open harnesses on open-weight models in this layer.",
                          "evidence_urls": [f"{fx}/fx/gap/{qa(layer)}.html"]}],
                "new_artifacts": []}
    if t == "rnd.harness_layer":
        return {"artifact_url": f"{fx}/fx/gap/harness-layer.html", "description": "[sim] no-op instructions file",
                "task_set": inp.get("task_set", "sim-set"),
                "runs": [{"variant": v, "task_id": "sim-task-1", "passed": v == "with_layer"} for v in ("baseline", "with_layer")],
                "model": "sim-model", "notes": "simulated run; not real evidence"}
    if t == "bench.task_draft":
        return {"repo_url_or_gist": f"{fx}/fx/gap/task.html", "task_id": "sim-task-draft",
                "description": "[sim] simulated task draft", "oracle_passes": True, "noop_fails": True,
                "logs_excerpt": "oracle: 1 passed\nnoop: 1 failed"}
    if t == "verify.blind_extract":
        return blind_extract(inp, mode)
    if t == "verify.review":
        if mode == "honest":
            return {"verdict": "accept", "reasons": ["sim: sources match fixture pages"], "issues": []}
        return {"verdict": "reject", "reasons": ["sim(disagree): rejecting on purpose"],
                "issues": [{"path": "payload", "problem": "simulated disagreement", "severity": "major"}]}
    raise ValueError(f"unknown task type {t}")


def _page_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        t = r.read().decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", "\n", t)
    return html.unescape(t)


def blind_extract(inp: dict, mode: str) -> dict:
    """Genuinely re-read the source (fixture) without knowing the original value."""
    url = inp.get("source_url", "")
    b_name = inp.get("benchmark_name") or inp.get("benchmark_id") or ""
    a_name = inp.get("artifact_name") or inp.get("artifact_id") or ""
    try:
        lines = [ln.strip() for ln in _page_text(url).splitlines() if ln.strip()]
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "value": None, "unit": None, "quote": None,
                "conditions": {"notes": f"could not fetch source: {exc}"}}
    def pick(line: str) -> dict | None:
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*%", line)
        if not nums:
            return None
        return {"found": True, "value": float(nums[-1]), "unit": "%", "quote": line[:600],
                "conditions": {"attempts": 1, "notes": "sim blind extraction"}}

    mine = [ln for ln in lines if a_name.lower() in ln.lower()]
    if mode == "disagree":
        # A realistic mistake: read the wrong row (another benchmark). The quote is still verbatim,
        # so it passes the mechanical check, and the values disagree → claim becomes disputed.
        for ln in mine:
            if b_name.lower() not in ln.lower() and (r := pick(ln)):
                return r
    for ln in mine:
        if b_name.lower() in ln.lower() and (r := pick(ln)):
            return r
    return {"found": False, "value": None, "unit": None, "quote": None,
            "conditions": {"notes": "benchmark not found on page"}}


# --------------------------------------------------------------------------------------------- agent
class SimAgent:
    def __init__(self, base: str, handle: str, family: str, who: str):
        self.api = Api(base, who=who)
        self.handle, self.family, self.who = handle, family, who
        self.model = f"sim-{family}-1"

    def register(self, invite: str | None, key: str | None) -> None:
        if key:
            self.api.key = key
            _, me = self.api.call("GET", "/me")
            self.handle = me.get("handle", self.handle)
            log(self.who, f"using existing key for {self.handle}")
            return
        if not invite:
            raise SystemExit(f"{self.who}: need an invite code (--invite / --verifier-invite) or --steward-key")
        handle = self.handle
        for _ in range(3):
            try:
                _, r = self.api.call("POST", "/register", {"invite_code": invite, "handle": handle,
                                                           "model_family": self.family, "contact": "sim"}, auth=False)
                self.api.key, self.handle = r["api_key"], r.get("handle", handle)
                log(self.who, f"registered {self.handle} ({self.family}) id={r.get('contributor_id')}")
                return
            except ApiError as exc:
                if exc.status == 409:
                    handle = f"{self.handle[:24]}-{random.randint(1000, 9999)}"
                    continue
                raise
        raise SystemExit(f"{self.who}: could not register")

    def claim(self, types: list[str]):
        status, r = self.api.call("POST", "/tasks/claim", {"model_family": self.family, "model": self.model,
                                                           "task_types": types, "max_minutes": 60})
        return None if status == 204 or not r else r

    def heartbeat(self, lease_id: str) -> None:
        self.api.call("POST", f"/leases/{lease_id}/heartbeat", {"progress_note": "sim working"})

    def release(self, lease_id: str, reason: str, note: str) -> None:
        self.api.call("POST", f"/leases/{lease_id}/release", {"reason": reason, "note": note})

    def submit(self, lease_id: str, payload: dict, tokens: int):
        return self.api.call("POST", f"/leases/{lease_id}/submit",
                             {"payload": payload, "model": self.model, "tokens_estimate": tokens,
                              "minutes_spent": round(random.uniform(2, 15), 1), "notes": "sim_agent"})[1]


def check_instructions(api: Api, type_: str, seen: set, who: str) -> None:
    if type_ in seen:
        return
    seen.add(type_)
    status, _ = api.raw("GET", f"{api.base}/task-types/{type_}.md", auth=False)
    if status != 200:
        log(who, f"WARN instructions for {type_} → HTTP {status}")


def check_skill_version(api: Api) -> None:
    for path in ("/skill-version", "/api/v1/skill-version"):
        status, raw = api.raw("GET", api.base + path, auth=False)
        if status == 200:
            sv = json.loads(raw)
            _, jm = api.raw("GET", api.base + "/join.md", auth=False)
            ok = hashlib.sha256(jm).hexdigest() == sv.get("sha256")
            log("sim", f"skill-version {sv.get('version')} sha256 {'matches' if ok else 'DOES NOT MATCH'} join.md ({path})")
            return
    log("sim", "WARN no /skill-version endpoint")


def run_one(agent: SimAgent, lease_task: dict, fx: str, mode: str, seen_types: set):
    lease, task = lease_task["lease"], lease_task["task"]
    check_instructions(agent.api, task["type"], seen_types, agent.who)
    agent.heartbeat(lease["id"])
    payload = build_payload(agent.api, task, fx, mode)
    try:
        res = agent.submit(lease["id"], payload, tokens=random.randint(3000, 30000))
    except ApiError as exc:
        log(agent.who, f"submit {task['id']} failed: {exc}")
        if exc.status == 422:
            agent.release(lease["id"], "error", "sim payload rejected by validator")
        return None
    checks = res.get("checks") or []
    passed = sum(1 for c in checks if c.get("passed"))
    log(agent.who, f"submitted {task['id']} ({task['type']}) → {res.get('submission_id')} status={res.get('status')} "
                   f"checks {passed}/{len(checks)} spawned={res.get('spawned_task_ids')}")
    for c in checks:
        if not c.get("passed"):
            log(agent.who, f"   check failed: {c.get('name')}: {c.get('detail')}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8787")
    ap.add_argument("--invite", help="invite code for the extractor agent")
    ap.add_argument("--handle", default="sim-extractor")
    ap.add_argument("--model-family", default="claude", choices=FAMILIES)
    ap.add_argument("--api-key", help="reuse an existing extractor key instead of registering")
    ap.add_argument("--verifier-invite", help="invite code for the verifier agent")
    ap.add_argument("--verifier-handle", default="sim-verifier")
    ap.add_argument("--verifier-model-family", choices=FAMILIES, help="default: a family different from the extractor")
    ap.add_argument("--verifier-api-key")
    ap.add_argument("--no-verifier", action="store_true", help="only run the extractor")
    ap.add_argument("--steward-key", help="if set, mint missing invite codes via POST /admin/invites")
    ap.add_argument("--tasks", type=int, default=3, help="number of primary tasks the extractor attempts")
    ap.add_argument("--types", default=",".join(PRIMARY_TYPES), help="task types the extractor claims")
    ap.add_argument("--mode", choices=["honest", "disagree"], default="honest",
                    help="disagree: the verifier misreads the source (wrong row) / rejects reviews")
    ap.add_argument("--fixture-port", type=int, default=8799)
    ap.add_argument("--fixture-base", help="URL prefix the backend uses to reach fixtures (default http://localhost:PORT)")
    ap.add_argument("--max-verify", type=int, default=40, help="cap on verifier claim attempts")
    ap.add_argument("--check", action="store_true", help="exit 1 unless the expected tiers were reached")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    random.seed(a.seed)

    start_fixture_server(a.fixture_port)
    fx = (a.fixture_base or f"http://localhost:{a.fixture_port}").rstrip("/")
    log("sim", f"fixture server on loopback:{a.fixture_port} (cited as {fx}); mode={a.mode}")

    public = Api(a.base_url, who="sim")
    try:
        public.call("GET", "/stats", auth=False)
    except (ApiError, urllib.error.URLError) as exc:
        print(f"backend not reachable at {a.base_url}: {exc}", file=sys.stderr)
        return 2
    check_skill_version(public)

    need = int(not a.invite and not a.api_key) + int(not a.no_verifier and not a.verifier_invite and not a.verifier_api_key)
    if need and a.steward_key:
        steward = Api(a.base_url, key=a.steward_key, who="steward")
        # One call per agent, each with its own person label: codes minted together share an operator and could
        # never verify each other (extractor and verifier simulate two different humans).
        codes = [steward.call("POST", "/admin/invites", {"count": 1, "note": "sim_agent", "person": f"sim-{who}-{time.time_ns()}"})[1]["codes"][0]
                 for who in ("extractor", "verifier")[:need]]
        if not a.invite and not a.api_key:
            a.invite = codes.pop(0)
        if not a.no_verifier and not a.verifier_invite and not a.verifier_api_key:
            a.verifier_invite = codes.pop(0)
        log("steward", f"minted {need} invite(s)")

    ext = SimAgent(a.base_url, a.handle, a.model_family, "extractor")
    ext.register(a.invite, a.api_key)

    # ---- extractor
    types = [t for t in a.types.split(",") if t]
    seen_types: set = set()
    spawned: list[str] = []
    submissions: list[dict] = []
    for _ in range(a.tasks):
        lt = ext.claim(types)
        if not lt:
            log("extractor", "no eligible task (204)")
            break
        log("extractor", f"claimed {lt['task']['id']} {lt['task']['type']}: {lt['task'].get('title', '')[:70]}")
        res = run_one(ext, lt, fx, "honest", seen_types)
        if res:
            submissions.append({"task": lt["task"], "res": res})
            spawned += res.get("spawned_task_ids") or []

    # ---- verifier
    if not a.no_verifier and spawned:
        vfam = a.verifier_model_family or next(f for f in FAMILIES if f != a.model_family)
        ver = SimAgent(a.base_url, a.verifier_handle, vfam, "verifier")
        ver.register(a.verifier_invite, a.verifier_api_key)
        todo = set(spawned)
        for _ in range(a.max_verify):
            if not todo:
                break
            lt = ver.claim(VERIFY_TYPES)
            if not lt:
                log("verifier", f"no eligible verify task (204); {len(todo)} spawned task(s) not reached")
                break
            task = lt["task"]
            if task["id"] not in todo:
                ver.release(lt["lease"]["id"], "gave_up", "sim_agent only handles tasks spawned by its own run")
                log("verifier", f"released foreign task {task['id']} ({task['type']})")
                continue
            log("verifier", f"claimed {task['id']} {task['type']} (inputs: "
                            f"{sorted((task.get('inputs') or {}).keys())})")
            if task["type"] == "verify.blind_extract" and {"value", "quote"} & set(task.get("inputs") or {}):
                log("verifier", "WARN blind task exposes value/quote in inputs: blindness broken!")
            run_one(ver, lt, fx, a.mode, seen_types)
            todo.discard(task["id"])
    elif not spawned:
        log("sim", "no verify tasks were spawned; skipping verifier")

    # ---- outcome
    time.sleep(0.5)
    tiers: list[str] = []
    claim_ids = [c["claim_id"] for sub in submissions if sub["task"]["type"] == "map.extract"
                 for c in (sub["res"].get("checks") or []) if c.get("claim_id")]
    for cid in claim_ids:
        try:
            _, cl = public.call("GET", f"/claims/{cid}", auth=False)
        except ApiError as exc:
            log("sim", f"claim {cid}: lookup failed {exc}")
            continue
        st = cl.get("display_status") or cl.get("special_status") or cl.get("tier")
        tiers.append(st)
        log("sim", f"claim {cid}: tier={cl.get('tier')} display_status={st}")
    _, me = ext.api.call("GET", "/me")
    log("sim", f"extractor credits={me.get('credits')} verified_tokens={me.get('verified_tokens')}")
    for s in me.get("recent_submissions") or []:
        log("sim", f"   submission {s.get('id')} {s.get('status')}")

    if a.check:
        want = "reproduced" if a.mode == "honest" else "disputed"
        extracted = any(s["task"]["type"] == "map.extract" for s in submissions)
        if extracted and want not in tiers:
            print(f"CHECK FAILED: expected a claim with display_status={want}, got {tiers}", file=sys.stderr)
            return 1
        print(f"CHECK OK ({want}: {tiers.count(want)} claim(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
