"""Task lifecycle: leases, claim eligibility, submission processing, verification flow, credits.

Flow summary (CONTRACT §3):
  map.extract  → quote check per claim → claim T1 (pass) / T0 (source unreadable) / dropped (hard fail)
                 → one verify.blind_extract per T1 claim
  blind_extract → compare with original (tolerance) → agree: claim T2 + credits; disagree: claim disputed
                 → when all blind tasks of an extract submission settle, the submission is finalized
  map.profile / map.gap_scan / rnd.* / bench.* / extract(no results) → verify.review
  verify.review → accept/reject finalizes the reviewed submission; needs_steward → steward queue

Network work (quote checks) is always done *before* opening the write transaction.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import config, db
from .db import jdump, jload, tx
from .errors import ApiError, not_found
from .verify import SOFT_FAIL_REASONS, QuoteChecker, quote_ambiguity

PENDING_TASK_STATUSES = ("draft", "open", "leased", "submitted", "verifying")
# Blind tasks get only the coarse identifiers needed to find the right number — never notes/column/attempts/date,
# which would let the verifier skip the reading (or be led to a row) instead of extracting independently.
CLAIM_HINT_KEYS = ("model", "harness", "scaffold")


# ------------------------------------------------------------------ events & credits


def emit(conn, kind: str, summary: str, actor: str | None = None, ref_type: str | None = None,
         ref_id: str | None = None, detail: Any = None) -> None:
    """Append to the activity feed. Summaries must never contain claim values (blind safety)."""
    db.insert(conn, "events", {
        "ts": db.now_ts(), "kind": kind, "actor_handle": actor, "summary": summary[:300],
        "ref_type": ref_type, "ref_id": ref_id, "detail": jdump(detail) if detail is not None else None,
    })


def credit(conn, contributor_id: str | None, kind: str, ref_type: str, ref_id: str) -> bool:
    """Idempotent: one ledger row per (contributor, kind, ref)."""
    if not contributor_id or not db.scalar(conn, "SELECT 1 FROM contributors WHERE id=?", (contributor_id,)):
        return False
    if db.scalar(conn, "SELECT 1 FROM ledger WHERE contributor_id=? AND kind=? AND ref_type=? AND ref_id=?",
                 (contributor_id, kind, ref_type, ref_id)):
        return False
    amount = config.CREDITS[kind]
    db.insert(conn, "ledger", {"contributor_id": contributor_id, "kind": kind, "amount": amount,
                               "ref_type": ref_type, "ref_id": ref_id, "ts": db.now_ts()})
    emit(conn, "credit", f"+{amount} {kind}", handle_of(conn, contributor_id), ref_type, ref_id)
    return True


def handle_of(conn, contributor_id: str | None) -> str | None:
    if not contributor_id:
        return None
    return db.scalar(conn, "SELECT handle FROM contributors WHERE id=?", (contributor_id,)) or contributor_id


# ------------------------------------------------------------------ tasks


_LAYER_TRACK_HINTS = {
    "models": ["map-models"], "harnesses": ["map-harnesses"], "multi-agent": ["map-harnesses"],
    "ux": ["map-harnesses"], "inference": ["map-inference"], "data": ["map-training"],
    "pretraining": ["map-training"], "post-training": ["map-training"], "evals": ["map-evals"],
    "environments": ["map-evals"], "safety": ["map-evals"],
}
_TYPE_TRACK_HINTS = {
    "verify.blind_extract": ["referee-agreement"], "verify.review": ["referee-agreement"],
    "rnd.harness_layer": ["rnd-harness-layers"], "bench.task_draft": ["rnd-bench-construction"],
}


def track_for(conn, task_type: str, layer: str | None = None) -> str | None:
    """Pick a track id for a generated task: exact hints first, then first track of the workstream."""
    hints = list(_TYPE_TRACK_HINTS.get(task_type, []))
    if task_type.startswith("map.") and layer:
        hints = [f"map-{layer}", *_LAYER_TRACK_HINTS.get(layer, [])]
    for h in hints:
        if db.scalar(conn, "SELECT 1 FROM tracks WHERE id=?", (h,)):
            return h
    ws = {"map": "map", "verify": "referee", "rnd": "rnd", "bench": "rnd"}[task_type.split(".")[0]]
    return db.scalar(conn, "SELECT id FROM tracks WHERE workstream=? ORDER BY sort, id LIMIT 1", (ws,))


def compute_priority(conn, track_id: str | None, task_type: str, bonus: float = 1.0) -> float:
    """priority = track weight (1–5, default 3) × staleness/gap bonus × (1.5 if verify task)."""
    weight = db.scalar(conn, "SELECT weight FROM tracks WHERE id=?", (track_id,)) if track_id else None
    weight = min(5, max(1, int(weight or 3)))
    return round(weight * bonus * (1.5 if task_type.startswith("verify.") else 1.0), 3)


def create_task(conn, *, type: str, title: str, spec_md: str = "", inputs: dict | None = None,
                track_id: str | None = None, layer: str | None = None, allowed: list[str] | None = None,
                budget_minutes: int | None = None, priority: float | None = None, status: str = "open",
                parent_submission_id: str | None = None, target_claim_id: str | None = None,
                created_by: str = "system", bonus: float = 1.0, announce: bool = True) -> str:
    inputs = dict(inputs or {})
    if type in ("map.extract", "map.profile") and inputs.get("artifact_id"):
        # Protocol: extract/profile inputs always carry artifact_id, artifact_name, layer.
        art = db.one(conn, "SELECT name, layer FROM artifacts WHERE id=?", (inputs["artifact_id"],))
        if art:
            inputs.setdefault("artifact_name", art["name"])
            inputs.setdefault("layer", art["layer"])
            layer = layer or art["layer"]
    track_id = track_id or track_for(conn, type, layer)
    tid = db.new_id("t")
    now = db.now_ts()
    db.insert(conn, "tasks", {
        "id": tid, "type": type, "track_id": track_id, "title": title[:200], "spec_md": spec_md,
        "inputs": inputs or {}, "allowed_model_families": allowed or ["any"],
        "budget_minutes": budget_minutes or config.DEFAULT_BUDGET_MINUTES.get(type, 30),
        "status": status, "priority": priority if priority is not None else compute_priority(conn, track_id, type, bonus),
        "attempts": 0, "max_attempts": config.MAX_ATTEMPTS, "parent_submission_id": parent_submission_id,
        "target_claim_id": target_claim_id, "created_by": created_by, "created_at": now, "updated_at": now,
    })
    if status == "open" and announce:
        emit(conn, "task_created", f"New {type} task: {title[:120]}", created_by, "task", tid)
    return tid


def set_task_status(conn, task_id: str, status: str) -> None:
    conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, db.now_ts(), task_id))


def spawn_blind_task(conn, claim: dict, parent_submission_id: str | None, bonus: float = 1.0,
                     created_by: str = "referee", announce: bool = True) -> str:
    """verify.blind_extract inputs deliberately omit value, unit, quote and condition notes."""
    art = db.one(conn, "SELECT id, name, layer FROM artifacts WHERE id=?", (claim["artifact_id"],))
    bench = db.one(conn, "SELECT id, name FROM benchmarks WHERE id=?", (claim["benchmark_id"],))
    conds = jload(claim["conditions"], {}) if isinstance(claim["conditions"], str) else (claim["conditions"] or {})
    hints = {k: str(conds[k])[:100] for k in CLAIM_HINT_KEYS if k in conds and conds[k] not in (None, "")}
    inputs = {
        "artifact_id": art["id"], "artifact_name": art["name"],
        "benchmark_id": bench["id"], "benchmark_name": bench["name"],
        "metric": claim["metric"], "source_url": claim["source_url"], "conditions_hint": hints,
    }
    spec = (
        f"Open the source and find the reported **{claim['metric']}** of **{art['name']}** on "
        f"**{bench['name']}**. Report the value exactly as published plus a verbatim quote "
        f"(20–600 chars) containing it. You are not told the expected value on purpose. "
        f"If the source does not report it, submit `found: false`."
    )
    return create_task(conn, type="verify.blind_extract", title=f"Blind check: {art['name']} · {bench['name']} · {claim['metric']}",
                       spec_md=spec, inputs=inputs, layer=art["layer"], parent_submission_id=parent_submission_id,
                       target_claim_id=claim["id"], created_by=created_by, bonus=bonus, announce=announce)


def spawn_review_task(conn, submission: dict, task: dict) -> str:
    inputs = {
        "submission_id": submission["id"], "task_id": task["id"], "task_type": task["type"],
        "task_title": task["title"], "task_inputs": jload(task["inputs"], {}),
        "payload": jload(submission["payload"], {}), "checks": jload(submission["checks"], []),
        "rubric": [
            "Are all statements supported by the cited sources?",
            "Are sources primary/authoritative where possible?",
            "Is anything important missing, duplicated or misleading?",
            "accept = good enough to enter the map; reject = wrong or unsupported; needs_steward = unsure",
        ],
    }
    return create_task(conn, type="verify.review", title=f"Review: {task['title'][:150]}",
                       spec_md="Review the submission below against the rubric. The original is visible.",
                       inputs=inputs, parent_submission_id=submission["id"], created_by="referee")


# ------------------------------------------------------------------ leases


def sweep_expired(conn) -> int:
    """Expire overdue leases and return their tasks to the queue. Cheap no-op when nothing is due."""
    now = db.now_ts()
    due = db.all_(conn, "SELECT * FROM leases WHERE status='active' AND (expires_at < ? OR hard_deadline < ?)", (now, now))
    orphans = _orphan_leased_tasks(conn)
    if not due and not orphans:
        return 0
    with tx(conn):
        for lease in due:
            cur = conn.execute("UPDATE leases SET status='expired' WHERE id=? AND status='active'", (lease["id"],))
            if cur.rowcount:
                _return_to_open(conn, lease["task_id"], count_attempt=True, why="lease expired",
                                actor=handle_of(conn, lease["contributor_id"]))
        for task_id in _orphan_leased_tasks(conn):  # re-read inside the lock
            _return_to_open(conn, task_id, count_attempt=False, why="no active lease", actor=None)
    return len(due) + len(orphans)


def _orphan_leased_tasks(conn) -> list[str]:
    """Tasks in `leased` with no active lease (e.g. a steward set the status by hand). Self-healing."""
    return [r["id"] for r in db.all_(conn, """SELECT id FROM tasks t WHERE status='leased' AND NOT EXISTS
                                             (SELECT 1 FROM leases l WHERE l.task_id=t.id AND l.status='active')""")]


def _return_to_open(conn, task_id: str, count_attempt: bool, why: str, actor: str | None) -> None:
    task = db.one(conn, "SELECT * FROM tasks WHERE id=?", (task_id,))
    if not task or task["status"] != "leased":
        return
    attempts = task["attempts"] + (1 if count_attempt else 0)
    status = "needs_steward" if attempts >= task["max_attempts"] else "open"
    conn.execute("UPDATE tasks SET status=?, attempts=?, updated_at=? WHERE id=?", (status, attempts, db.now_ts(), task_id))
    emit(conn, "task_reopened" if status == "open" else "task_needs_steward",
         f"{task['title'][:120]} → {status} ({why})", actor, "task", task_id)


def _active_lease_count(conn, contributor_id: str) -> int:
    return db.scalar(conn, "SELECT COUNT(*) FROM leases WHERE contributor_id=? AND status='active'", (contributor_id,))


def _original_contributor(conn, task: dict) -> tuple[str | None, str | None]:
    """(contributor_id, model_family) of the work a verify task targets."""
    sub_id = task["parent_submission_id"]
    if not sub_id and task["target_claim_id"]:
        sub_id = db.scalar(conn, "SELECT submission_id FROM claims WHERE id=?", (task["target_claim_id"],))
    if not sub_id:
        return None, None
    row = db.one(conn, "SELECT contributor_id, model_family FROM submissions WHERE id=?", (sub_id,))
    return (row["contributor_id"], row["model_family"]) if row else (None, None)


def same_person(conn, contributor: dict, other_id: str) -> bool:
    """True if `other_id` is known to be run by the same human: same invite person label or same GitHub id."""
    other = db.one(conn, "SELECT person, github_id FROM contributors WHERE id=?", (other_id,))
    if not other:
        return False
    if contributor.get("person") and other["person"] == contributor["person"]:
        return True
    return bool(contributor.get("github_id") and other["github_id"] == contributor["github_id"])


def eligible_score(conn, task: dict, contributor: dict, family: str, allow_same_ip: bool = False,
                   require_github: bool = False) -> float | None:
    """None if the contributor may not take this task, else a ranking score."""
    allowed = jload(task["allowed_model_families"], ["any"])
    if "any" not in allowed and family not in allowed:
        return None
    if db.scalar(conn, "SELECT 1 FROM leases WHERE task_id=? AND contributor_id=? AND status='released' AND released_at >= ?",
                 (task["id"], contributor["id"], db.ts_in(seconds=-config.RELEASE_COOLDOWN_S))):
        return None  # you released it recently; don't hand it straight back
    score = float(task["priority"])
    if not task["type"].startswith("verify."):
        return score
    if require_github and not contributor.get("github_id"):
        return None  # referee work needs a linked, aged GitHub account (POST /me/github/challenge)
    orig_id, orig_family = _original_contributor(conn, task)
    if orig_id == contributor["id"]:
        return None  # never verify your own work
    if orig_id and same_person(conn, contributor, orig_id):
        return None  # same operator (invite person label) or same GitHub account as the author
    if orig_id and not allow_same_ip and contributor.get("registered_ip_hash") and db.scalar(
            conn, "SELECT 1 FROM contributors WHERE id=? AND registered_ip_hash=?", (orig_id, contributor["registered_ip_hash"])):
        return None  # registered from the same IP as the author: likely the same person (Sybil guard)
    if task["target_claim_id"] and db.scalar(conn, """
            SELECT 1 FROM leases l JOIN tasks t ON t.id = l.task_id
            WHERE l.contributor_id=? AND t.target_claim_id=? AND t.id != ?""",
            (contributor["id"], task["target_claim_id"], task["id"])):
        return None  # at most one verify task per claim per contributor
    if task["type"] == "verify.review" and task["parent_submission_id"] and db.scalar(conn, """
            SELECT 1 FROM leases l JOIN tasks t ON t.id = l.task_id
            WHERE l.contributor_id=? AND t.type='verify.review' AND t.parent_submission_id=? AND t.id != ?""",
            (contributor["id"], task["parent_submission_id"], task["id"])):
        return None
    if orig_family and orig_family != family:
        score += config.FAMILY_DIVERSITY_BONUS
    return score


def claim_task(conn, contributor: dict, model_family: str, model: str | None,
               task_types: list[str] | None, max_minutes: int | None,
               allow_same_ip: bool = False, require_github: bool = False) -> tuple[dict, dict] | None:
    """Lease the best eligible open task. Returns (lease, task) or None (→ 204)."""
    with tx(conn):
        if _active_lease_count(conn, contributor["id"]) >= config.MAX_ACTIVE_LEASES:
            raise ApiError(409, "lease_limit", f"You already hold {config.MAX_ACTIVE_LEASES} active leases; submit or release one first.")
        sql, params = "SELECT * FROM tasks WHERE status='open'", []
        if task_types:
            sql += f" AND type IN ({','.join('?' for _ in task_types)})"
            params += task_types
        if max_minutes:
            sql += " AND budget_minutes <= ?"
            params.append(max_minutes)
        sql += " ORDER BY priority DESC, created_at ASC LIMIT 500"
        best, best_score = None, None
        for task in db.all_(conn, sql, params):
            s = eligible_score(conn, task, contributor, model_family, allow_same_ip, require_github)
            if s is not None and (best_score is None or s > best_score):
                best, best_score = task, s
        if not best:
            return None
        now = db.now_ts()
        hard = db.ts_in(seconds=config.LEASE_HARD_MAX_S)
        lease = {
            "id": db.new_id("l"), "task_id": best["id"], "contributor_id": contributor["id"],
            "model_family": model_family, "model": (model or "")[:100], "created_at": now, "heartbeat_at": now,
            "expires_at": min(db.ts_in(seconds=config.LEASE_TTL_S), hard), "hard_deadline": hard,
            "status": "active", "progress_note": None,
        }
        db.insert(conn, "leases", lease)
        set_task_status(conn, best["id"], "leased")
        emit(conn, "task_claimed", f"claimed {best['type']}: {best['title'][:120]}", contributor["handle"], "task", best["id"])
        best["status"] = "leased"
        return lease, best


def own_lease(conn, contributor: dict, lease_id: str, require_active: bool = True) -> dict:
    lease = db.one(conn, "SELECT * FROM leases WHERE id=?", (lease_id,))
    if not lease or lease["contributor_id"] != contributor["id"]:
        raise not_found("lease", lease_id)
    if require_active and lease["status"] != "active":
        raise ApiError(409, "lease_not_active", f"Lease is {lease['status']}; claim a new task.")
    return lease


def heartbeat(conn, contributor: dict, lease_id: str, note: str | None) -> str:
    with tx(conn):
        lease = own_lease(conn, contributor, lease_id)
        expires = min(db.ts_in(seconds=config.LEASE_TTL_S), lease["hard_deadline"])
        conn.execute("UPDATE leases SET heartbeat_at=?, expires_at=?, progress_note=COALESCE(?, progress_note) WHERE id=?",
                     (db.now_ts(), expires, (note or None) and note[:500], lease_id))
        return expires


def release(conn, contributor: dict, lease_id: str, reason: str, note: str | None) -> None:
    if reason not in config.RELEASE_REASONS:
        raise ApiError(422, "invalid_reason", f"reason must be one of {config.RELEASE_REASONS}")
    with tx(conn):
        lease = own_lease(conn, contributor, lease_id)
        conn.execute("""UPDATE leases SET status='released', released_at=?, release_reason=?,
                        progress_note=COALESCE(?, progress_note) WHERE id=?""",
                     (db.now_ts(), reason, (note or None) and note[:500], lease_id))
        _return_to_open(conn, lease["task_id"], count_attempt=reason not in config.FREE_RELEASE_REASONS,
                        why=f"released: {reason}", actor=contributor["handle"])
        if reason == "conflict":
            emit(conn, "task_conflict", "contributor declined a verify task: conflict of interest",
                 contributor["handle"], "task", lease["task_id"])
        if reason == "unsafe":
            emit(conn, "task_flagged_unsafe", "task flagged unsafe by contributor — steward please review",
                 contributor["handle"], "task", lease["task_id"], {"note": (note or "")[:500]})


# ------------------------------------------------------------------ payload validation


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _str(v, max_len=2000, min_len=1) -> bool:
    return isinstance(v, str) and min_len <= len(v.strip()) and len(v) <= max_len


def _url(v) -> bool:
    return _str(v, 2000) and re.match(r"^https?://", v.strip()) is not None


def validate_payload(task_type: str, p: Any) -> list[dict]:
    """Returns a list of {field, message}; empty means valid."""
    errs: list[dict] = []

    def err(field, msg):
        errs.append({"field": field, "message": msg})

    if not isinstance(p, dict):
        return [{"field": "payload", "message": "must be an object"}]
    if task_type == "map.extract":
        claims = p.get("claims", [])
        if not isinstance(claims, list) or len(claims) > config.MAX_EXTRACT_CLAIMS:
            err("claims", f"must be a list of at most {config.MAX_EXTRACT_CLAIMS} ClaimDrafts")
            claims = []
        if not isinstance(p.get("no_results_found", False), bool):
            err("no_results_found", "must be a boolean")
        if not isinstance(p.get("searched", []), list):
            err("searched", "must be a list of urls")
        if not claims and not p.get("no_results_found"):
            err("claims", "empty; set no_results_found=true if nothing was found")
        for i, c in enumerate(claims):
            f = f"claims[{i}]"
            if not isinstance(c, dict):
                err(f, "must be an object"); continue
            if not _str(c.get("benchmark"), 200): err(f"{f}.benchmark", "required string")
            if not _str(c.get("metric"), 200): err(f"{f}.metric", "required string")
            if not _num(c.get("value")): err(f"{f}.value", "required number")
            if not _str(c.get("unit", "score"), 40): err(f"{f}.unit", "string")
            if not isinstance(c.get("higher_is_better", True), bool): err(f"{f}.higher_is_better", "boolean")
            if not isinstance(c.get("conditions", {}), dict): err(f"{f}.conditions", "object")
            if not _url(c.get("source_url")): err(f"{f}.source_url", "required http(s) url")
            if not _str(c.get("quote"), config.QUOTE_MAX_CHARS, config.QUOTE_MIN_CHARS):
                err(f"{f}.quote", f"required, {config.QUOTE_MIN_CHARS}–{config.QUOTE_MAX_CHARS} chars")
            if c.get("reported_by", "artifact-authors") not in ("artifact-authors", "third-party", "leaderboard"):
                err(f"{f}.reported_by", "artifact-authors|third-party|leaderboard")
    elif task_type == "map.profile":
        fields = p.get("fields")
        if not isinstance(fields, dict) or not fields:
            err("fields", "required object")
        else:
            allowed = {"license", "latest_version", "latest_release_date", "repo_url", "homepage", "description"}
            for k, v in fields.items():
                if k not in allowed: err(f"fields.{k}", "unknown field")
                elif v is not None and not _str(v, 2000): err(f"fields.{k}", "string or null")
        sources = p.get("sources")
        if not isinstance(sources, list) or not sources:
            err("sources", "required list of {field,url,quote}")
        else:
            for i, s in enumerate(sources):
                if not isinstance(s, dict) or not _str(s.get("field"), 50) or not _url(s.get("url")) or not _str(s.get("quote"), 600):
                    err(f"sources[{i}]", "needs field, url, quote")
    elif task_type == "map.gap_scan":
        gaps, arts = p.get("gaps", []), p.get("new_artifacts", [])
        if not isinstance(gaps, list) or not isinstance(arts, list):
            err("gaps", "gaps and new_artifacts must be lists")
        else:
            if not gaps and not arts: err("gaps", "nothing proposed")
            for i, g in enumerate(gaps[:100]):
                if not isinstance(g, dict) or not _str(g.get("title"), 200) or g.get("kind") not in config.GAP_KINDS:
                    err(f"gaps[{i}]", f"needs title and kind in {config.GAP_KINDS}")
            for i, a in enumerate(arts[:100]):
                if not isinstance(a, dict) or not _str(a.get("name"), 200) or not _url(a.get("url")):
                    err(f"new_artifacts[{i}]", "needs name and url")
            if len(gaps) > 100 or len(arts) > 100: err("gaps", "at most 100 items each")
    elif task_type == "verify.blind_extract":
        if not isinstance(p.get("found"), bool):
            err("found", "required boolean")
        elif p["found"]:
            if not _num(p.get("value")): err("value", "required number when found")
            if not _str(p.get("quote"), config.QUOTE_MAX_CHARS, config.QUOTE_MIN_CHARS):
                err("quote", f"required, {config.QUOTE_MIN_CHARS}–{config.QUOTE_MAX_CHARS} chars")
        if p.get("unit") is not None and not _str(p.get("unit"), 40): err("unit", "string")
    elif task_type == "verify.review":
        if p.get("verdict") not in ("accept", "reject", "needs_steward"):
            err("verdict", "accept|reject|needs_steward")
        if not isinstance(p.get("reasons", []), list): err("reasons", "list")
        if not isinstance(p.get("issues", []), list): err("issues", "list")
    elif task_type == "rnd.harness_layer":
        for k in ("artifact_url", "description", "task_set", "model"):
            if not _str(p.get(k), 4000): err(k, "required string")
        if not isinstance(p.get("runs"), list): err("runs", "required list")
    elif task_type == "bench.task_draft":
        for k in ("repo_url_or_gist", "task_id", "description"):
            if not _str(p.get(k), 4000): err(k, "required string")
        for k in ("oracle_passes", "noop_fails"):
            if not isinstance(p.get(k), bool): err(k, "required boolean")
    return errs


# ------------------------------------------------------------------ submit


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "unnamed"


def _precheck(task: dict, payload: dict, checker: QuoteChecker) -> dict:
    """All network-bound checks for a submission, run outside any transaction.

    Checks run concurrently (config.PRECHECK_WORKERS) under one overall deadline (config.PRECHECK_DEADLINE_S);
    unfinished ones soft-fail with reason "timeout". Results keep payload order."""
    t = task["type"]
    if t == "map.extract":
        return {"claims": checker.check_many([(c["source_url"], c["quote"], c["value"])
                                              for c in payload.get("claims", [])])}
    if t == "map.profile":
        fields = payload.get("fields") or {}
        items = []
        for s in payload.get("sources", []):
            val = fields.get(s["field"])
            # value-in-quote only for short factual fields; descriptions are paraphrased
            must = val if s["field"] in ("license", "latest_version") and val else None
            items.append((s["url"], s["quote"], must))
        return {"sources": checker.check_many(items)}
    if t == "verify.blind_extract" and payload.get("found"):
        src = (jload(task["inputs"], {}) or {}).get("source_url", "")
        return {"blind": checker.check_many([(src, payload["quote"], payload["value"])])[0]}
    return {}


def submit(conn, checker: QuoteChecker, contributor: dict, lease_id: str, body: dict) -> dict:
    lease = own_lease(conn, contributor, lease_id)
    task = db.one(conn, "SELECT * FROM tasks WHERE id=?", (lease["task_id"],))
    payload = body.get("payload")
    errors = validate_payload(task["type"], payload)
    if errors:
        raise ApiError(422, "invalid_payload", f"payload does not match {task['type']} schema", fields=errors)
    pre = _precheck(task, payload, checker)

    with tx(conn):
        lease = own_lease(conn, contributor, lease_id)  # re-check inside the lock
        sub = {
            "id": db.new_id("s"), "task_id": task["id"], "lease_id": lease_id, "contributor_id": contributor["id"],
            "model_family": lease["model_family"] or contributor["model_family"],
            "model": str(body.get("model") or lease["model"] or "")[:100], "payload": jdump(payload),
            "tokens_estimate": max(0, min(int(body.get("tokens_estimate") or 0), config.TOKENS_ESTIMATE_MAX,  # self-reported
                                           int(task["budget_minutes"] or 0) * config.TOKENS_PER_BUDGET_MINUTE_MAX)),
            "minutes_spent": max(0.0, min(float(body.get("minutes_spent") or 0), 10_000.0)),
            "notes": str(body.get("notes") or "")[:4000], "checks": "[]", "status": "pending", "created_at": db.now_ts(),
        }
        db.insert(conn, "submissions", sub)
        conn.execute("UPDATE leases SET status='submitted' WHERE id=?", (lease_id,))
        set_task_status(conn, task["id"], "submitted")
        emit(conn, "submission_received", f"submitted {task['type']}: {task['title'][:120]}", contributor["handle"], "submission", sub["id"])

        handler = {
            "map.extract": _process_extract, "verify.blind_extract": _process_blind,
            "verify.review": _process_review, "map.profile": _process_profile,
        }.get(task["type"], _process_needs_review)
        status, checks, spawned = handler(conn, task, sub, payload, pre, contributor)
        conn.execute("UPDATE submissions SET checks=? WHERE id=?", (jdump(checks), sub["id"]))
        return {"submission_id": sub["id"], "status": status, "checks": checks, "spawned_task_ids": spawned}


def _set_sub(conn, sub_id: str, status: str, task_id: str | None = None, task_status: str | None = None) -> None:
    final = status in ("verified", "rejected")
    conn.execute("UPDATE submissions SET status=?, resolved_at=CASE WHEN ? THEN ? ELSE resolved_at END WHERE id=?",
                 (status, final, db.now_ts(), sub_id))
    if task_id:
        set_task_status(conn, task_id, task_status or status)


def _process_extract(conn, task, sub, payload, pre, contributor):
    inputs = jload(task["inputs"], {})
    checks, spawned, n_t1, n_t0 = [], [], 0, 0
    for i, (c, res) in enumerate(zip(payload.get("claims", []), pre["claims"])):
        name = f"claims[{i}].quote_check"
        artifact_id = inputs.get("artifact_id") or c.get("artifact_id")
        if not artifact_id or not db.scalar(conn, "SELECT 1 FROM artifacts WHERE id=?", (artifact_id,)):
            checks.append({"name": name, "passed": False, "detail": "unknown artifact"}); continue
        soft = not res["passed"] and res["reason"] in SOFT_FAIL_REASONS
        if not res["passed"] and not soft:
            checks.append({"name": name, "passed": False, "detail": res["reason"], "result": res}); continue
        if res["passed"] and quote_ambiguity(c["quote"], c["value"]):
            notes = (c.get("conditions") or {}).get("notes")
            if not isinstance(notes, str) or not notes.strip():
                checks.append({"name": name, "passed": False, "detail": "ambiguous_quote_needs_notes",
                               "message": "quote has several same-format numbers (table row?): put the column header "
                                          "in conditions.notes and resubmit"}); continue
            res = {**res, "flag": "ambiguous_quote"}
        bench_id = _resolve_benchmark(conn, c["benchmark"], sub["id"])
        if db.scalar(conn, "SELECT 1 FROM claims WHERE artifact_id=? AND benchmark_id=? AND metric=? AND source_url=? AND abs(value - ?) < 1e-9",
                     (artifact_id, bench_id, c["metric"], c["source_url"], c["value"])):
            checks.append({"name": name, "passed": False, "detail": "duplicate of an existing claim"}); continue
        tier = "source-checked" if res["passed"] else "reported"
        claim = _insert_claim(conn, artifact_id, bench_id, c, tier, res, sub["id"])
        checks.append({"name": name, "passed": res["passed"], "detail": res["reason"], "claim_id": claim["id"], "tier": tier,
                       **({"flag": res["flag"]} if res.get("flag") else {})})
        emit(conn, "claim_created", f"new {tier} claim: {artifact_id} on {bench_id}", contributor["handle"], "claim", claim["id"],
             {"check_result": res})
        if res["passed"]:
            n_t1 += 1
            spawned.append(spawn_blind_task(conn, claim, sub["id"]))
        else:
            n_t0 += 1
    if n_t1:
        status = "verifying"
    elif n_t0:
        status = "needs_steward"
    elif payload.get("no_results_found") and not payload.get("claims"):
        spawned.append(spawn_review_task(conn, sub, task))
        status = "verifying"
    else:
        status = "rejected"
    _set_sub(conn, sub["id"], status, task["id"])
    return status, checks, spawned


def _resolve_benchmark(conn, name: str, sub_id: str) -> str:
    slug = _slug(name)
    found = db.scalar(conn, "SELECT id FROM benchmarks WHERE id=? OR lower(name)=lower(?) LIMIT 1", (slug, name.strip()))
    if found:
        return found
    db.insert(conn, "benchmarks", {"id": slug, "name": name.strip()[:200], "layer": "evals", "url": None,
                                   "description": None, "measures": None, "saturated": 0,
                                   "notes": f"auto-created from submission {sub_id}"})
    return slug


def _insert_claim(conn, artifact_id, bench_id, c, tier, check_result, sub_id, seed=0) -> dict:
    now = db.now_ts()
    claim = {
        "id": db.new_id("cl"), "artifact_id": artifact_id, "benchmark_id": bench_id, "metric": c["metric"][:200],
        "value": float(c["value"]), "unit": str(c.get("unit") or "score")[:40],
        "higher_is_better": int(c.get("higher_is_better", True)), "conditions": jdump(c.get("conditions") or {}),
        "source_url": c["source_url"].strip(), "quote": c["quote"].strip(),
        "reported_by": c.get("reported_by") or "artifact-authors", "tier": tier, "special_status": None,
        "created_at": now, "tier_changed_at": now, "expires_at": db.ts_in(days=config.CLAIM_EXPIRY_DAYS),
        "submission_id": sub_id, "check_result": jdump(check_result) if check_result else None, "seed": seed,
        "retrieved_at": c.get("retrieved_at"),
    }
    db.insert(conn, "claims", claim)
    return claim


def values_agree(a: float, unit_a: str | None, b: float, unit_b: str | None) -> bool:
    """abs diff ≤ 0.1 or relative ≤ 0.5%; tolerate %-vs-fraction when units differ."""
    def close(x, y):
        return abs(x - y) <= config.BLIND_TOLERANCE_ABS or abs(x - y) <= config.BLIND_TOLERANCE_REL * max(abs(x), abs(y))
    if close(a, b):
        return True
    ua, ub = (unit_a or "").strip().lower(), (unit_b or "").strip().lower()
    if ua != ub and ("%" in (ua, ub)):
        return close(a, b * 100) or close(a * 100, b)
    return False


def _process_blind(conn, task, sub, payload, pre, contributor):
    claim = db.one(conn, "SELECT * FROM claims WHERE id=?", (task["target_claim_id"],))
    if not claim:
        _set_sub(conn, sub["id"], "rejected", task["id"], "closed")
        return "rejected", [{"name": "target_claim", "passed": False, "detail": "claim no longer exists"}], []
    checks = []
    blind_check = pre.get("blind")
    if blind_check:
        checks.append({"name": "quote_check", "passed": blind_check["passed"], "detail": blind_check["reason"]})
        if not blind_check["passed"] and blind_check["reason"] not in SOFT_FAIL_REASONS:
            # Verifier's own evidence doesn't hold up: discard, give the task to someone else.
            _set_sub(conn, sub["id"], "rejected")
            set_task_status(conn, task["id"], "leased")  # so _return_to_open applies
            _return_to_open(conn, task["id"], count_attempt=True, why="blind quote failed check", actor=contributor["handle"])
            return "rejected", checks, []
    agree = bool(payload["found"]) and values_agree(claim["value"], claim["unit"], float(payload["value"]), payload.get("unit"))
    detail = {"original_value": claim["value"], "original_unit": claim["unit"], "found": payload["found"],
              "blind_value": payload.get("value"), "blind_unit": payload.get("unit"),
              "blind_quote": payload.get("quote"), "blind_quote_check": blind_check}
    db.insert(conn, "verifications", {
        "id": db.new_id("v"), "submission_id": claim["submission_id"], "claim_id": claim["id"],
        "verifier_submission_id": sub["id"], "verdict": "agree" if agree else "disagree",
        "detail": detail, "created_at": db.now_ts(),
    })
    checks.append({"name": "blind_agreement", "passed": agree,
                   "detail": "matches the original within tolerance" if agree else "does not match the original"})
    if agree:
        fields = {"tier_changed_at": db.now_ts(), "expires_at": db.ts_in(days=config.CLAIM_EXPIRY_DAYS)}
        if config.TIER_RANK[claim["tier"]] < config.TIER_RANK["reproduced"]:
            fields["tier"] = "reproduced"
        db.update(conn, "claims", claim["id"], fields)
        _set_sub(conn, sub["id"], "verified", task["id"])
        emit(conn, "claim_reproduced", f"claim reproduced blindly: {claim['artifact_id']} on {claim['benchmark_id']}",
             contributor["handle"], "claim", claim["id"], detail)
        orig = db.scalar(conn, "SELECT contributor_id FROM submissions WHERE id=?", (claim["submission_id"],)) if claim["submission_id"] else None
        credit(conn, orig, "claim_reproduced", "claim", claim["id"])
        credit(conn, contributor["id"], "verify_agreed", "submission", sub["id"])
        status = "verified"
    else:
        db.update(conn, "claims", claim["id"], {"special_status": "disputed"})
        _set_sub(conn, sub["id"], "disputed", task["id"])
        emit(conn, "claim_disputed", f"blind re-extraction disagreed: {claim['artifact_id']} on {claim['benchmark_id']}",
             contributor["handle"], "claim", claim["id"], detail)
        status = "disputed"
    if claim["submission_id"]:
        maybe_finalize_extract(conn, claim["submission_id"])
    return status, checks, []


def maybe_finalize_extract(conn, submission_id: str) -> None:
    """Settle a map.extract submission once none of its claims has a pending blind task."""
    sub = db.one(conn, "SELECT * FROM submissions WHERE id=?", (submission_id,))
    if not sub or sub["status"] not in ("verifying", "disputed", "needs_steward"):
        return
    claims = db.all_(conn, "SELECT * FROM claims WHERE submission_id=?", (submission_id,))
    if not claims:
        return
    ids = [c["id"] for c in claims]
    marks = ",".join("?" for _ in ids)
    pending = db.scalar(conn, f"""SELECT COUNT(*) FROM tasks WHERE type='verify.blind_extract' AND target_claim_id IN ({marks})
                                  AND status IN ({','.join('?' for _ in PENDING_TASK_STATUSES)})""", [*ids, *PENDING_TASK_STATUSES])
    if pending:
        return
    if any(c["tier"] in config.VERIFIED_TIERS and c["special_status"] is None for c in claims):
        status = "verified"
    elif any(c["special_status"] == "disputed" for c in claims):
        status = "disputed"
    elif all(c["special_status"] == "retracted" for c in claims):
        status = "rejected"
    else:
        status = "needs_steward"
    if status != sub["status"]:
        _set_sub(conn, submission_id, status, sub["task_id"])
        emit(conn, "submission_" + status, f"extraction settled as {status}", None, "submission", submission_id)


def _process_profile(conn, task, sub, payload, pre, contributor):
    checks = []
    for s, res in zip(payload["sources"], pre["sources"]):
        checks.append({"name": f"source[{s['field']}]", "passed": res["passed"], "detail": res["reason"], "field": s["field"]})
    if not any(c["passed"] for c in checks):
        _set_sub(conn, sub["id"], "rejected", task["id"])
        return "rejected", checks, []
    spawned = [spawn_review_task(conn, {**sub, "checks": jdump(checks)}, task)]
    _set_sub(conn, sub["id"], "verifying", task["id"])
    return "verifying", checks, spawned


def _process_needs_review(conn, task, sub, payload, pre, contributor):
    """gap_scan, rnd.*, bench.* → second-opinion review."""
    spawned = [spawn_review_task(conn, sub, task)]
    _set_sub(conn, sub["id"], "verifying", task["id"])
    return "verifying", [{"name": "schema", "passed": True, "detail": "queued for verify.review"}], spawned


def _process_review(conn, task, sub, payload, pre, contributor):
    parent = db.one(conn, "SELECT * FROM submissions WHERE id=?", (task["parent_submission_id"],))
    verdict = payload["verdict"]
    db.insert(conn, "verifications", {
        "id": db.new_id("v"), "submission_id": parent["id"] if parent else None, "claim_id": None,
        "verifier_submission_id": sub["id"], "verdict": verdict,
        "detail": {"reasons": payload.get("reasons", [])[:20], "issues": payload.get("issues", [])[:20]},
        "created_at": db.now_ts(),
    })
    emit(conn, "review_submitted", f"review verdict: {verdict}", contributor["handle"], "submission", parent["id"] if parent else sub["id"])
    checks = [{"name": "review", "passed": True, "detail": verdict}]
    if not parent:
        _set_sub(conn, sub["id"], "rejected", task["id"], "closed")
        return "rejected", checks, []
    if verdict == "needs_steward":
        _set_sub(conn, sub["id"], "needs_steward", task["id"])
        _set_sub(conn, parent["id"], "needs_steward", parent["task_id"])
        return "needs_steward", checks, []
    finalize_submission(conn, parent["id"], "verified" if verdict == "accept" else "rejected", actor=contributor["handle"])
    return db.scalar(conn, "SELECT status FROM submissions WHERE id=?", (sub["id"],)), checks, []


def finalize_submission(conn, submission_id: str, final: str, actor: str | None = None) -> None:
    """Final outcome for a reviewed submission: apply effects, settle reviewer credits."""
    sub = db.one(conn, "SELECT * FROM submissions WHERE id=?", (submission_id,))
    task = db.one(conn, "SELECT * FROM tasks WHERE id=?", (sub["task_id"],))
    _set_sub(conn, submission_id, final, task["id"])
    emit(conn, "submission_" + final, f"{task['type']} submission {final}: {task['title'][:100]}", actor, "submission", submission_id)
    if final == "verified":
        _apply_effects(conn, sub, task)
    # Reviews: +2 to reviewers whose verdict matched the final outcome.
    for v in db.all_(conn, "SELECT * FROM verifications WHERE submission_id=? AND verdict IN ('accept','reject','needs_steward')", (submission_id,)):
        rsub = db.one(conn, "SELECT * FROM submissions WHERE id=?", (v["verifier_submission_id"],))
        if not rsub:
            continue
        matched = (v["verdict"] == "accept") == (final == "verified") and v["verdict"] != "needs_steward"
        rstatus = "verified" if matched or v["verdict"] == "needs_steward" else "rejected"
        _set_sub(conn, rsub["id"], rstatus, rsub["task_id"])
        if matched:
            credit(conn, rsub["contributor_id"], "verify_review", "submission", rsub["id"])


def _apply_effects(conn, sub: dict, task: dict) -> None:
    payload = jload(sub["payload"], {})
    inputs = jload(task["inputs"], {})
    if task["type"] == "map.profile":
        art_id = inputs.get("artifact_id")
        passed = {c["field"] for c in jload(sub["checks"], []) if c.get("passed") and c.get("field")}
        fields = {k: v for k, v in (payload.get("fields") or {}).items() if k in passed and v}
        if art_id and fields and db.scalar(conn, "SELECT 1 FROM artifacts WHERE id=?", (art_id,)):
            db.update(conn, "artifacts", art_id, {**fields, "updated_at": db.now_ts(), "source": f"task:{task['id']}"})
            emit(conn, "artifact_updated", f"{art_id} profile updated ({', '.join(sorted(fields))})", None, "artifact", art_id)
    elif task["type"] == "map.gap_scan":
        layer = inputs.get("layer") or "evals"
        for g in payload.get("gaps", []):
            _propose_gap(conn, layer, g.get("kind", "missing_evidence"), g["title"], g.get("description", ""),
                         g.get("evidence_urls", []), sub)
        for a in payload.get("new_artifacts", []):
            _propose_gap(conn, layer, "missing_artifact", f"Missing artifact: {a['name']}",
                         f"{a.get('kind', '')}: {a.get('why', '')}".strip(": "), [a["url"]], sub)


def _propose_gap(conn, layer, kind, title, description, urls, sub) -> None:
    gid = db.new_id("g")
    urls = [u for u in (urls or []) if isinstance(u, str) and _url(u)][:20]
    db.insert(conn, "gaps", {"id": gid, "layer": layer, "kind": kind, "title": str(title)[:200],
                             "description": str(description or "")[:4000], "evidence_urls": urls, "status": "proposed",
                             "created_by": sub["contributor_id"], "created_at": db.now_ts(), "task_ids": [],
                             "submission_id": sub["id"]})
    emit(conn, "gap_proposed", f"gap proposed in {layer}: {str(title)[:120]}", handle_of(conn, sub["contributor_id"]), "gap", gid)


# ------------------------------------------------------------------ steward actions


def steward_resolve_claim(conn, claim_id: str, tier: str | None, special_status: str | None, note: str) -> dict:
    with tx(conn):
        claim = db.one(conn, "SELECT * FROM claims WHERE id=?", (claim_id,))
        if not claim:
            raise not_found("claim", claim_id)
        fields: dict = {}
        if tier:
            if tier not in config.TIERS:
                raise ApiError(422, "invalid_tier", f"tier must be one of {config.TIERS}")
            fields.update(tier=tier, tier_changed_at=db.now_ts(), expires_at=db.ts_in(days=config.CLAIM_EXPIRY_DAYS))
        if special_status is not None:
            new = None if special_status in ("none", "") else special_status
            if new not in (None, *config.SPECIAL_STATUSES):
                raise ApiError(422, "invalid_special_status", "special_status must be disputed|retracted|none")
            fields["special_status"] = new
            if claim["special_status"] == "disputed" and new != "disputed":
                _settle_dispute(conn, claim, extractor_wins=new is None)
        if not fields:
            raise ApiError(422, "nothing_to_do", "provide tier and/or special_status")
        db.update(conn, "claims", claim_id, fields)
        conn.execute("UPDATE tasks SET status='closed', updated_at=? WHERE target_claim_id=? AND status='disputed'", (db.now_ts(), claim_id))
        emit(conn, "steward_claim_resolved", f"steward resolved claim: {', '.join(f'{k}={v}' for k, v in fields.items() if k in ('tier', 'special_status'))}",
             "steward", "claim", claim_id, {"note": note})
        if claim["submission_id"]:
            maybe_finalize_extract(conn, claim["submission_id"])
        return db.one(conn, "SELECT * FROM claims WHERE id=?", (claim_id,))


def _settle_dispute(conn, claim: dict, extractor_wins: bool) -> None:
    if extractor_wins:
        orig = db.scalar(conn, "SELECT contributor_id FROM submissions WHERE id=?", (claim["submission_id"],)) if claim["submission_id"] else None
        credit(conn, orig, "dispute_resolved", "claim", claim["id"])
    else:
        for v in db.all_(conn, "SELECT verifier_submission_id FROM verifications WHERE claim_id=? AND verdict='disagree'", (claim["id"],)):
            who = db.scalar(conn, "SELECT contributor_id FROM submissions WHERE id=?", (v["verifier_submission_id"],))
            credit(conn, who, "dispute_resolved", "claim", claim["id"])


def steward_resolve_gap(conn, gap_id: str, status: str, note: str) -> dict:
    if status not in config.GAP_STATUSES:
        raise ApiError(422, "invalid_status", f"status must be one of {config.GAP_STATUSES}")
    with tx(conn):
        gap = db.one(conn, "SELECT * FROM gaps WHERE id=?", (gap_id,))
        if not gap:
            raise not_found("gap", gap_id)
        conn.execute("UPDATE gaps SET status=? WHERE id=?", (status, gap_id))
        if gap["status"] == "proposed" and status == "accepted":
            credit(conn, gap["created_by"], "gap_accepted", "gap", gap_id)
        emit(conn, "steward_gap_" + status, f"steward marked gap {status}: {gap['title'][:120]}", "steward", "gap", gap_id, {"note": note})
        return db.one(conn, "SELECT * FROM gaps WHERE id=?", (gap_id,))


def steward_resolve_submission(conn, submission_id: str, status: str, note: str) -> dict:
    if status not in ("verified", "rejected"):
        raise ApiError(422, "invalid_status", "status must be verified|rejected")
    with tx(conn):
        if not db.scalar(conn, "SELECT 1 FROM submissions WHERE id=?", (submission_id,)):
            raise not_found("submission", submission_id)
        finalize_submission(conn, submission_id, status, actor="steward")
        emit(conn, "steward_submission_resolved", f"steward set submission {status}", "steward", "submission", submission_id, {"note": note})
        return db.one(conn, "SELECT id, status FROM submissions WHERE id=?", (submission_id,))


def steward_set_task_status(conn, task_id: str, status: str) -> None:
    if status not in config.TASK_STATUSES:
        raise ApiError(422, "invalid_status", f"status must be one of {config.TASK_STATUSES}")
    with tx(conn):
        task = db.one(conn, "SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            raise not_found("task", task_id)
        if status != "leased":
            conn.execute("UPDATE leases SET status='released' WHERE task_id=? AND status='active'", (task_id,))
        set_task_status(conn, task_id, status)
        emit(conn, "steward_task_status", f"steward set task → {status}: {task['title'][:100]}", "steward", "task", task_id)


def recheck_claim(conn, checker: QuoteChecker, claim_id: str) -> dict:
    claim = db.one(conn, "SELECT * FROM claims WHERE id=?", (claim_id,))
    if not claim:
        raise not_found("claim", claim_id)
    checker._cache.pop(claim["source_url"], None)  # steward recheck bypasses cache
    res = checker.check(claim["source_url"], claim["quote"] or "", claim["value"])
    with tx(conn):
        fields: dict = {"check_result": jdump(res)}
        if res["passed"] and claim["tier"] == "reported":
            fields.update(tier="source-checked", tier_changed_at=db.now_ts(), expires_at=db.ts_in(days=config.CLAIM_EXPIRY_DAYS))
        db.update(conn, "claims", claim_id, fields)
        emit(conn, "claim_rechecked", f"quote re-check: {res['reason']}", "steward", "claim", claim_id, {"check_result": res})
    return {"claim_id": claim_id, "check_result": res, "tier": fields.get("tier", claim["tier"])}


def contributor_credits(conn: sqlite3.Connection, contributor_id: str) -> int:
    return int(db.scalar(conn, "SELECT COALESCE(SUM(amount),0) FROM ledger WHERE contributor_id=?", (contributor_id,)))


def contributor_verified_tokens(conn: sqlite3.Connection, contributor_id: str) -> int:
    return int(db.scalar(conn, "SELECT COALESCE(SUM(tokens_estimate),0) FROM submissions WHERE contributor_id=? AND status='verified'", (contributor_id,)))
