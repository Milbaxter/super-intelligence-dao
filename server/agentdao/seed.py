"""Load seed/*.json (CONTRACT §7). Tolerant: missing files are skipped, bad rows are reported, not fatal.

Re-running is safe: layers/tracks/artifacts/benchmarks/gaps upsert by id; claims and tasks
are de-duplicated by their natural keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config, db, lifecycle, taskgen
from .db import jdump, tx
from .verify import QuoteChecker

FILES = ["layers", "tracks", "artifacts", "benchmarks", "claims", "gaps", "tasks"]


def _need(row: dict, keys: list[str]) -> str | None:
    missing = [k for k in keys if row.get(k) in (None, "")]
    return f"missing {', '.join(missing)}" if missing else None


def _load(seed_dir: Path, name: str, report: dict) -> list:
    path = seed_dir / f"{name}.json"
    r = report.setdefault(name, {"loaded": 0, "skipped": 0, "errors": []})
    if not path.exists():
        r["errors"].append("file not found (skipped)")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        r["errors"].append(f"invalid JSON: {e}")
        return []
    if not isinstance(data, list):
        r["errors"].append("top level must be a list")
        return []
    return data


def _bad(report, name, i, row, why):
    report[name]["skipped"] += 1
    label = row.get("id") or row.get("title") or row.get("name") if isinstance(row, dict) else None
    report[name]["errors"].append(f"row {i}{f' ({label})' if label else ''}: {why}")


def load_seed(conn, seed_dir: Path) -> dict:
    report: dict = {}
    now = db.now_ts()
    with tx(conn):
        for i, r in enumerate(_load(seed_dir, "layers", report)):
            if not isinstance(r, dict) or (why := _need(r, ["id", "name"])):
                _bad(report, "layers", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            conn.execute("""INSERT INTO layers (id,name,description,sort) VALUES (?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, sort=excluded.sort""",
                         (r["id"], r["name"], r.get("description"), int(r.get("sort") or 0)))
            report["layers"]["loaded"] += 1
        # Contract layer ids always exist so artifacts can reference them even without layers.json.
        for n, lid in enumerate(config.LAYERS):
            conn.execute("INSERT OR IGNORE INTO layers (id,name,description,sort) VALUES (?,?,?,?)",
                         (lid, lid.replace("-", " ").title(), None, 100 + n))
        layers = {x["id"] for x in db.all_(conn, "SELECT id FROM layers")}

        for i, r in enumerate(_load(seed_dir, "tracks", report)):
            if not isinstance(r, dict) or (why := _need(r, ["id", "name", "workstream", "phase"])):
                _bad(report, "tracks", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            if r["workstream"] not in ("map", "rnd", "referee") or r["phase"] not in ("now", "next", "vision"):
                _bad(report, "tracks", i, r, "bad workstream/phase"); continue
            conn.execute("""INSERT INTO tracks (id,name,workstream,phase,summary,why,verification,weight,sort) VALUES (?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET name=excluded.name, workstream=excluded.workstream, phase=excluded.phase,
                            summary=excluded.summary, why=excluded.why, verification=excluded.verification,
                            weight=excluded.weight, sort=excluded.sort""",
                         (r["id"], r["name"], r["workstream"], r["phase"], r.get("summary"), r.get("why"),
                          r.get("verification"), min(5, max(1, int(r.get("weight") or 3))), int(r.get("sort") or 0)))
            report["tracks"]["loaded"] += 1

        for i, r in enumerate(_load(seed_dir, "artifacts", report)):
            if not isinstance(r, dict) or (why := _need(r, ["id", "name", "layer", "kind"])):
                _bad(report, "artifacts", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            if r["layer"] not in layers:
                _bad(report, "artifacts", i, r, f"unknown layer {r['layer']!r}"); continue
            if r["kind"] not in config.ARTIFACT_KINDS:
                _bad(report, "artifacts", i, r, f"unknown kind {r['kind']!r}"); continue
            ow = r.get("open_weights")
            conn.execute("""INSERT INTO artifacts (id,name,layer,kind,url,repo_url,license,description,open_weights,created_at,updated_at,source)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,'seed')
                            ON CONFLICT(id) DO UPDATE SET name=excluded.name, layer=excluded.layer, kind=excluded.kind, url=excluded.url,
                            repo_url=COALESCE(excluded.repo_url, artifacts.repo_url), license=COALESCE(excluded.license, artifacts.license),
                            description=excluded.description, open_weights=excluded.open_weights, updated_at=excluded.updated_at""",
                         (r["id"], r["name"], r["layer"], r["kind"], r.get("url"), r.get("repo_url"), r.get("license"),
                          r.get("description"), None if ow is None else int(bool(ow)), now, now))
            report["artifacts"]["loaded"] += 1

        for i, r in enumerate(_load(seed_dir, "benchmarks", report)):
            if not isinstance(r, dict) or (why := _need(r, ["id", "name"])):
                _bad(report, "benchmarks", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            conn.execute("""INSERT INTO benchmarks (id,name,layer,url,description,measures,saturated,notes) VALUES (?,?,?,?,?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET name=excluded.name, layer=excluded.layer, url=excluded.url,
                            description=excluded.description, measures=excluded.measures, saturated=excluded.saturated, notes=excluded.notes""",
                         (r["id"], r["name"], r.get("layer") or "evals", r.get("url"), r.get("description"), r.get("measures"),
                          int(bool(r.get("saturated"))), r.get("notes")))
            report["benchmarks"]["loaded"] += 1

        for i, r in enumerate(_load(seed_dir, "claims", report)):
            if not isinstance(r, dict) or (why := _need(r, ["artifact_id", "benchmark_id", "metric", "value", "source_url", "quote"])):
                _bad(report, "claims", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            if not isinstance(r["value"], (int, float)) or isinstance(r["value"], bool):
                _bad(report, "claims", i, r, "value must be a number"); continue
            if not db.scalar(conn, "SELECT 1 FROM artifacts WHERE id=?", (r["artifact_id"],)):
                _bad(report, "claims", i, r, f"unknown artifact {r['artifact_id']!r}"); continue
            if not db.scalar(conn, "SELECT 1 FROM benchmarks WHERE id=?", (r["benchmark_id"],)):
                _bad(report, "claims", i, r, f"unknown benchmark {r['benchmark_id']!r}"); continue
            if db.scalar(conn, "SELECT 1 FROM claims WHERE artifact_id=? AND benchmark_id=? AND metric=? AND source_url=? AND abs(value-?)<1e-9",
                         (r["artifact_id"], r["benchmark_id"], r["metric"], r["source_url"], r["value"])):
                report["claims"]["skipped"] += 1; continue
            lifecycle._insert_claim(conn, r["artifact_id"], r["benchmark_id"],
                                    {**r, "conditions": r.get("conditions") if isinstance(r.get("conditions"), dict) else {}},
                                    "reported", None, None, seed=1)
            report["claims"]["loaded"] += 1

        for i, r in enumerate(_load(seed_dir, "gaps", report)):
            if not isinstance(r, dict) or (why := _need(r, ["layer", "kind", "title"])):
                _bad(report, "gaps", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            if r["kind"] not in config.GAP_KINDS:
                _bad(report, "gaps", i, r, f"unknown kind {r['kind']!r}"); continue
            gid = r.get("id") or "g_seed_" + lifecycle._slug(r["layer"] + "-" + r["title"])[:40]
            conn.execute("""INSERT INTO gaps (id,layer,kind,title,description,evidence_urls,status,created_by,created_at,task_ids)
                            VALUES (?,?,?,?,?,?,'accepted','steward-seed',?,'[]')
                            ON CONFLICT(id) DO UPDATE SET layer=excluded.layer, kind=excluded.kind, title=excluded.title,
                            description=excluded.description, evidence_urls=excluded.evidence_urls""",
                         (gid, r["layer"], r["kind"], r["title"], r.get("description"),
                          jdump(r.get("evidence_urls") if isinstance(r.get("evidence_urls"), list) else []), now))
            report["gaps"]["loaded"] += 1

        tracks = {x["id"] for x in db.all_(conn, "SELECT id FROM tracks")}
        for i, r in enumerate(_load(seed_dir, "tasks", report)):
            if not isinstance(r, dict) or (why := _need(r, ["type", "title"])):
                _bad(report, "tasks", i, r if isinstance(r, dict) else {}, why or "not an object"); continue
            if r["type"] not in config.TASK_TYPES:
                _bad(report, "tasks", i, r, f"unknown type {r['type']!r}"); continue
            fams = r.get("allowed_model_families") or ["any"]
            if not isinstance(fams, list) or any(f not in config.ALLOWED_FAMILY_VALUES for f in fams):
                _bad(report, "tasks", i, r, "bad allowed_model_families"); continue
            if db.scalar(conn, "SELECT 1 FROM tasks WHERE type=? AND title=?", (r["type"], r["title"])):
                report["tasks"]["skipped"] += 1; continue
            track = r.get("track_id") if r.get("track_id") in tracks else None
            inputs = dict(r.get("inputs")) if isinstance(r.get("inputs"), dict) else {}
            if r["type"] in ARTIFACT_TASK_TYPES:
                art = _resolve_artifact(conn, inputs)
                if art is None:
                    _bad(report, "tasks", i, r, f"unknown artifact {inputs.get('artifact_id') or inputs.get('artifact_name')!r}"); continue
                # Protocol requires artifact_id, artifact_name, layer for extract/profile tasks.
                inputs.update(artifact_id=art["id"], artifact_name=art["name"], layer=art["layer"])
                inputs.setdefault("kind", art["kind"])
            elif r["type"] == "map.gap_scan" and inputs.get("layer") not in layers:
                _bad(report, "tasks", i, r, f"unknown layer {inputs.get('layer')!r}"); continue
            lifecycle.create_task(conn, type=r["type"], title=r["title"], spec_md=r.get("spec_md") or "", inputs=inputs,
                                  track_id=track, layer=inputs.get("layer"), allowed=fams,
                                  budget_minutes=r.get("budget_minutes"), priority=r.get("priority"),
                                  created_by="steward-seed", announce=False)
            report["tasks"]["loaded"] += 1
        lifecycle.emit(conn, "seeded", "map seeded from curated data", "steward")
    return report


ARTIFACT_TASK_TYPES = ("map.extract", "map.profile")


def _norm_name(s) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _resolve_artifact(conn, inputs: dict):
    """Find a task's artifact: by id, else by exact (normalized) name, else by URL, else by name prefix."""
    aid = inputs.get("artifact_id")
    if aid and (row := db.one(conn, "SELECT * FROM artifacts WHERE id=?", (aid,))):
        return row
    rows = db.all_(conn, "SELECT * FROM artifacts")
    name = _norm_name(inputs.get("artifact_name"))
    if name:
        for a in rows:
            if _norm_name(a["name"]) == name:
                return a
    urls = {u.rstrip("/").lower() for u in (inputs.get("artifact_url"), inputs.get("url"), inputs.get("repo_url")) if u}
    if urls:
        for a in rows:
            if {u.rstrip("/").lower() for u in (a["url"], a["repo_url"]) if u} & urls:
                return a
    if name:
        hits = [a for a in rows if (n := _norm_name(a["name"])) and (name.startswith(n) or n.startswith(name))]
        if len(hits) == 1:
            return hits[0]
    return None


def check_sources(conn, checker: QuoteChecker, progress=None) -> dict:
    """Run the quote check on seed claims still at T0; promote passes to T1."""
    out = {"checked": 0, "promoted": 0, "failed": {}}
    rows = db.all_(conn, "SELECT * FROM claims WHERE seed=1 AND tier='reported' AND special_status IS NULL")
    for c in rows:
        res = checker.check(c["source_url"], c["quote"] or "", c["value"])
        out["checked"] += 1
        with tx(conn):
            fields = {"check_result": jdump(res)}
            if res["passed"]:
                fields.update(tier="source-checked", tier_changed_at=db.now_ts(), expires_at=db.ts_in(days=config.CLAIM_EXPIRY_DAYS))
                out["promoted"] += 1
            else:
                out["failed"][res["reason"]] = out["failed"].get(res["reason"], 0) + 1
            db.update(conn, "claims", c["id"], fields)
            lifecycle.emit(conn, "claim_checked", f"seed claim quote check: {res['reason']}", "referee", "claim", c["id"], {"check_result": res})
        if progress:
            progress(c, res)
    return out


def run(settings: config.Settings, reset: bool = False, check: bool = False, checker: QuoteChecker | None = None) -> dict:
    if reset:
        db.reset_db(settings.db_path)
    else:
        db.init_db(settings.db_path)
    conn = db.connect(settings.db_path)
    try:
        report = {"files": load_seed(conn, settings.seed_dir)}
        if check:
            report["check_sources"] = check_sources(conn, checker or QuoteChecker())
        report["taskgen_created"] = len(taskgen.generate(conn))
        return report
    finally:
        conn.close()
