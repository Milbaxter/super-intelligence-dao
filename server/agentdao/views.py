"""Row → API JSON shapes (CONTRACT §5), including blind-value redaction."""

from __future__ import annotations

from . import config, db
from .db import jload

# A claim whose blind round is undecided must not reveal anything that carries the value: value, quote,
# check_result and trail details are withheld. Undecided = a blind task for it is still on the board
# (draft/open/leased/submitted), holds a verdict of the open round ('verifying': the task mirrors its verifier
# submission, which stays 'verifying' until the round is decided, see lifecycle._round_votes), or is stuck in
# 'needs_steward' (max attempts hit, or the round was handed to the steward) — a steward may put it back on the
# board, so the value must stay hidden until the steward resolves the claim.
BLIND_PENDING_STATUSES = ("draft", "open", "leased", "submitted", "verifying", "needs_steward")
_BLIND_PENDING_IN = ",".join(f"'{s}'" for s in BLIND_PENDING_STATUSES)
# Belt and braces: a verdict whose verifier submission is still 'verifying' also marks an undecided round.
_ROUND_OPEN_CLAIMS_SQL = """SELECT v.claim_id FROM verifications v JOIN submissions s ON s.id = v.verifier_submission_id
                            WHERE v.verdict IN ('agree','disagree') AND s.status='verifying'"""
# Target claim ids whose value is currently withheld ("awaiting referee" on public pages).
BLIND_PENDING_CLAIMS_SQL = f"""SELECT target_claim_id FROM tasks WHERE type='verify.blind_extract'
                               AND status IN ({_BLIND_PENDING_IN}) UNION {_ROUND_OPEN_CLAIMS_SQL}"""
_BLIND_PENDING_SQL = f"""SELECT EXISTS(SELECT 1 FROM tasks WHERE type='verify.blind_extract' AND target_claim_id=:id
                                       AND status IN ({_BLIND_PENDING_IN}))
                         OR EXISTS({_ROUND_OPEN_CLAIMS_SQL} AND v.claim_id=:id)"""


def blind_pending(conn, claim_id: str) -> bool:
    """True while the claim's blind round is undecided (see BLIND_PENDING_STATUSES)."""
    return bool(db.scalar(conn, _BLIND_PENDING_SQL, {"id": claim_id}))


def display_status(row: dict, now: str | None = None) -> str:
    if row.get("special_status"):
        return row["special_status"]
    if row.get("expires_at") and row["expires_at"] < (now or db.now_ts()):
        return "stale"
    return row["tier"]


DISPLAY_STATUS_SQL = """CASE WHEN c.special_status IS NOT NULL THEN c.special_status
                             WHEN c.expires_at < :now THEN 'stale' ELSE c.tier END"""

CLAIM_SELECT = """SELECT c.*, a.name AS artifact_name, a.layer AS layer, b.name AS benchmark_name
                  FROM claims c JOIN artifacts a ON a.id = c.artifact_id JOIN benchmarks b ON b.id = c.benchmark_id"""


def claim_json(conn, row: dict, redact: bool | None = None) -> dict:
    hidden = blind_pending(conn, row["id"]) if redact is None else redact
    out = {
        "id": row["id"], "artifact_id": row["artifact_id"], "artifact_name": row.get("artifact_name"),
        "layer": row.get("layer"), "benchmark_id": row["benchmark_id"], "benchmark_name": row.get("benchmark_name"),
        "metric": row["metric"], "value": row["value"], "unit": row["unit"],
        "higher_is_better": bool(row["higher_is_better"]), "conditions": jload(row["conditions"], {}),
        "source_url": row["source_url"], "quote": row["quote"], "reported_by": row["reported_by"],
        "tier": row["tier"], "special_status": row["special_status"], "display_status": display_status(row),
        "created_at": row["created_at"], "tier_changed_at": row["tier_changed_at"], "expires_at": row["expires_at"],
        "seed": bool(row["seed"]), "check_result": jload(row["check_result"]), "value_hidden": hidden,
    }
    if hidden:
        out.update(value=None, quote=None, check_result=None)
        out["conditions"] = {k: v for k, v in out["conditions"].items() if k != "notes"}
    return out


def get_claim(conn, claim_id: str) -> dict | None:
    return db.one(conn, CLAIM_SELECT + " WHERE c.id = ?", (claim_id,))


def claim_trail(conn, claim: dict, hidden: bool) -> list[dict]:
    trail = [{"ts": claim["created_at"], "kind": "created",
              "actor": "seed" if claim["seed"] else None,
              "summary": f"claim recorded as {'seed data' if claim['seed'] else 'submission ' + str(claim['submission_id'])}",
              "detail": None}]
    for e in db.all_(conn, "SELECT * FROM events WHERE ref_type='claim' AND ref_id=? ORDER BY id", (claim["id"],)):
        trail.append({"ts": e["ts"], "kind": e["kind"], "actor": e["actor_handle"], "summary": e["summary"],
                      "detail": None if hidden else jload(e["detail"])})
    return trail


def task_summary(row: dict, conn=None) -> dict:
    # track_name: the human-readable track (a "multi-agent" layer task sits in map-harnesses, which confused agents).
    # Taken from a joined `track_name` column, else looked up when a connection is given.
    name = row.get("track_name")
    if name is None and conn is not None and row.get("track_id"):
        name = db.scalar(conn, "SELECT name FROM tracks WHERE id=?", (row["track_id"],))
    return {
        "id": row["id"], "type": row["type"], "track_id": row["track_id"], "track_name": name, "title": row["title"],
        "status": row["status"], "priority": row["priority"],
        "allowed_model_families": jload(row["allowed_model_families"], ["any"]),
        "budget_minutes": row["budget_minutes"], "attempts": row["attempts"], "created_at": row["created_at"],
    }


def task_full(conn, row: dict, base_url: str) -> dict:
    """Public/agent task view. Never includes target_claim_id or anything derived from the claim value."""
    subs = db.all_(conn, """SELECT s.id, c.handle AS contributor, s.status, s.created_at FROM submissions s
                            JOIN contributors c ON c.id = s.contributor_id WHERE s.task_id=? ORDER BY s.created_at""", (row["id"],))
    return {
        **task_summary(row, conn), "spec_md": row["spec_md"] or "", "inputs": jload(row["inputs"], {}),
        "instructions_url": f"{base_url}/task-types/{row['type']}.md", "submissions": subs,
    }


def gap_json(row: dict) -> dict:
    return {
        "id": row["id"], "layer": row["layer"], "kind": row["kind"], "title": row["title"],
        "description": row["description"], "evidence_urls": jload(row["evidence_urls"], []),
        "status": row["status"], "created_at": row["created_at"], "task_ids": jload(row["task_ids"], []),
    }


def best_tier(statuses: list[str]) -> str | None:
    ranked = [s for s in statuses if s in config.TIER_RANK]
    return max(ranked, key=config.TIER_RANK.__getitem__) if ranked else None


def artifact_counts(conn) -> dict[str, dict]:
    """artifact_id → {claim_count, verified_claim_count, best_tier} (retracted claims excluded)."""
    now = db.now_ts()
    rows = db.all_(conn, f"SELECT c.artifact_id, {DISPLAY_STATUS_SQL} AS ds FROM claims c WHERE c.special_status IS NOT 'retracted'",
                   {"now": now})
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["artifact_id"], {"claim_count": 0, "verified_claim_count": 0, "_st": []})
        d["claim_count"] += 1
        d["verified_claim_count"] += r["ds"] in config.VERIFIED_TIERS
        d["_st"].append(r["ds"])
    for d in out.values():
        d["best_tier"] = best_tier(d.pop("_st"))
    return out


def artifact_summary(row: dict, counts: dict) -> dict:
    c = counts.get(row["id"], {"claim_count": 0, "verified_claim_count": 0, "best_tier": None})
    return {
        "id": row["id"], "name": row["name"], "layer": row["layer"], "kind": row["kind"], "url": row["url"],
        "repo_url": row["repo_url"], "license": row["license"], "description": row["description"],
        "open_weights": None if row["open_weights"] is None else bool(row["open_weights"]), **c,
    }


def fmt_value(value: float, unit: str | None) -> str:
    v = f"{value:g}"
    return f"{v}%" if unit == "%" else f"{v} {unit}" if unit and unit != "score" else v
