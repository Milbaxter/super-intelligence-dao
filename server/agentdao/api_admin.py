"""Steward API (Bearer steward key)."""

from __future__ import annotations

import random
import secrets

from fastapi import APIRouter, Body, Depends, Request

from . import config, council, db, lifecycle, taskgen, views
from .db import jload, tx
from .deps import get_conn, require_steward
from .errors import ApiError, check_json, not_found

router = APIRouter(prefix="/admin", dependencies=[Depends(require_steward)])


def _obj(body) -> dict:
    if not isinstance(body, dict):
        raise ApiError(422, "invalid_body", "JSON object expected")
    check_json(body)
    return body


def create_invites(conn, count: int, note: str | None, person: str | None = None) -> list[str]:
    """Codes minted with one `person` label share it (= one human/operator: they can never verify each other).
    Without a label every code gets its own fresh person id (= separate people)."""
    codes = []
    with tx(conn):
        for _ in range(count):
            code = "inv-" + secrets.token_urlsafe(9)
            db.insert(conn, "invites", {"code": code, "created_at": db.now_ts(), "used_by": None, "note": note,
                                        "person": ("op:" + person) if person else db.new_id("p", 12)})
            codes.append(code)
        lifecycle.emit(conn, "invites_created", f"steward created {count} invite(s)", "steward")
    return codes


@router.post("/invites")
def invites(body=Body(default={}), conn=Depends(get_conn)):
    body = _obj(body or {})
    count = body.get("count", 1)
    if not isinstance(count, int) or not 1 <= count <= 100:
        raise ApiError(422, "invalid_count", "count must be 1–100")
    person = body.get("person")
    if person is not None and (not isinstance(person, str) or len(person.strip()) > 100):
        raise ApiError(422, "invalid_person", "person must be a string of at most 100 chars")
    person = (person or "").strip() or None
    return {"codes": create_invites(conn, count, str(body.get("note") or "")[:200] or None, person),
            "person": person}


@router.get("/queue")
def queue(conn=Depends(get_conn)):
    needs = []
    for s in db.all_(conn, """SELECT s.id, s.task_id, s.status, s.created_at, s.payload, s.checks, t.type, t.title, c.handle
                              FROM submissions s JOIN tasks t ON t.id=s.task_id JOIN contributors c ON c.id=s.contributor_id
                              WHERE s.status='needs_steward' ORDER BY s.created_at"""):
        needs.append({"kind": "submission", "id": s["id"], "task_id": s["task_id"], "task_type": s["type"],
                      "title": s["title"], "contributor": s["handle"], "created_at": s["created_at"],
                      "payload": jload(s["payload"], {}), "checks": jload(s["checks"], [])})
    for t in db.all_(conn, "SELECT * FROM tasks WHERE status='needs_steward' ORDER BY updated_at"):
        needs.append({"kind": "task", "id": t["id"], "task_id": t["id"], "task_type": t["type"], "title": t["title"],
                      "attempts": t["attempts"], "created_at": t["created_at"]})
    disputed = []
    for c in db.all_(conn, views.CLAIM_SELECT + " WHERE c.special_status='disputed' ORDER BY c.tier_changed_at"):
        item = views.claim_json(conn, c, redact=False)
        item["verifications"] = [{**v, "detail": jload(v["detail"], {})} for v in
                                 db.all_(conn, "SELECT * FROM verifications WHERE claim_id=? ORDER BY created_at", (c["id"],))]
        disputed.append(item)
    flagged = []  # T1+ claims whose quote was ambiguous (table row); cleared once a steward resolves the claim
    for c in db.all_(conn, views.CLAIM_SELECT + """ WHERE json_extract(c.check_result, '$.flag') IS NOT NULL
                     AND c.special_status IS NOT 'retracted' AND NOT EXISTS (SELECT 1 FROM events e
                     WHERE e.kind='steward_claim_resolved' AND e.ref_type='claim' AND e.ref_id=c.id)
                     ORDER BY c.created_at"""):
        item = views.claim_json(conn, c, redact=False)
        item["flag"] = (jload(c["check_result"], {}) or {}).get("flag")
        flagged.append(item)
    undecided = undecided_blind_rounds(conn)
    proposed = [views.gap_json(g) for g in db.all_(conn, "SELECT * FROM gaps WHERE status='proposed' ORDER BY created_at")]
    recent = db.all_(conn, """SELECT s.id AS submission_id, s.task_id, t.type AS task_type, c.handle AS contributor,
                              s.created_at, s.resolved_at FROM submissions s JOIN tasks t ON t.id=s.task_id
                              JOIN contributors c ON c.id=s.contributor_id
                              WHERE s.status='verified' AND COALESCE(s.resolved_at, s.created_at) >= ?""", (db.ts_in(days=-7),))
    sample = random.sample(recent, max(1, round(len(recent) * 0.1))) if recent else []
    for item in sample:  # additive: the claims the sampled work produced or verified, so the steward can audit them
        item["claim_ids"] = [r["id"] for r in db.all_(conn, """SELECT id FROM claims WHERE submission_id=? UNION
                             SELECT target_claim_id FROM tasks WHERE id=? AND target_claim_id IS NOT NULL""",
                                                       (item["submission_id"], item["task_id"]))]
    return {"needs_steward": needs, "disputed_claims": disputed, "flagged_claims": flagged,
            "undecided_blind_rounds": undecided, "proposed_gaps": proposed, "spot_check_sample": sample}


def undecided_blind_rounds(conn) -> list[dict]:
    """Claims whose blind round is undecided with a blind task still on the board, listed when the round already
    has a verdict (a split waiting for a tie-breaker) or its open task is BLIND_ROUND_STEWARD_AFTER_DAYS old.
    With few contributors the tie-breaker can be eligible for nobody; the steward then decides via
    POST /admin/claims/{id}/resolve, which closes the open blind tasks and settles the round's verdicts."""
    pending = ",".join(f"'{s}'" for s in ("draft", "open", "leased", "submitted"))
    rows = db.all_(conn, f"""SELECT target_claim_id AS claim_id, MIN(created_at) AS since,
                             json_group_array(json_object('id', id, 'status', status, 'attempts', attempts,
                                                          'created_at', created_at)) AS tasks
                             FROM tasks WHERE type='verify.blind_extract' AND status IN ({pending})
                             AND target_claim_id IS NOT NULL GROUP BY target_claim_id ORDER BY since""")
    now = db.utcnow()
    out = []
    for r in rows:
        votes = lifecycle._round_votes(conn, r["claim_id"])
        age_days = round((now - db.parse_ts(r["since"])).total_seconds() / 86400, 2)
        overdue = age_days >= config.BLIND_ROUND_STEWARD_AFTER_DAYS
        if not votes and not overdue:
            continue  # first blind check still fresh: nothing for the steward yet
        row = views.get_claim(conn, r["claim_id"])
        if not row:
            continue
        item = views.claim_json(conn, row, redact=False)
        n_agree = sum(v["verdict"] == "agree" for v in votes)
        verdicts = {v["sub_id"]: v for v in votes}
        item["blind_round"] = {
            "votes": {"agree": n_agree, "disagree": len(votes) - n_agree},
            "open_tasks": jload(r["tasks"], []), "open_since": r["since"], "age_days": age_days, "overdue": overdue,
            "verdicts": [{"verdict": verdicts[v["verifier_submission_id"]]["verdict"],
                          "contributor": lifecycle.handle_of(conn, verdicts[v["verifier_submission_id"]]["contributor_id"]),
                          "created_at": v["created_at"], "detail": jload(v["detail"], {})}
                         for v in db.all_(conn, "SELECT * FROM verifications WHERE claim_id=? ORDER BY created_at, rowid",
                                          (r["claim_id"],)) if v["verifier_submission_id"] in verdicts],
        }
        out.append(item)
    return out


@router.post("/tasks", status_code=201)
def create_task(body=Body(...), conn=Depends(get_conn)):
    b = _obj(body)
    if b.get("type") not in config.TASK_TYPES:
        raise ApiError(422, "invalid_type", f"type must be one of {config.TASK_TYPES}")
    if b["type"] in config.STEER_TASK_TYPES:
        raise ApiError(422, "invalid_type", "steer.* tasks are created by the council cycle (POST /admin/council/open)")
    if not isinstance(b.get("title"), str) or not b["title"].strip():
        raise ApiError(422, "invalid_title", "title required")
    allowed = b.get("allowed_model_families") or ["any"]
    if not isinstance(allowed, list) or any(f not in config.ALLOWED_FAMILY_VALUES for f in allowed):
        raise ApiError(422, "invalid_allowed_model_families", f"subset of {config.ALLOWED_FAMILY_VALUES}")
    status = b.get("status", "open")
    if status not in ("draft", "open"):
        raise ApiError(422, "invalid_status", "status must be draft|open")
    if b.get("track_id") and not db.scalar(conn, "SELECT 1 FROM tracks WHERE id=?", (b["track_id"],)):
        raise ApiError(422, "invalid_track", "unknown track_id")
    inputs = b.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ApiError(422, "invalid_inputs", "inputs must be an object")
    with tx(conn):
        tid = lifecycle.create_task(
            conn, type=b["type"], title=b["title"], spec_md=str(b.get("spec_md") or ""), inputs=inputs,
            track_id=b.get("track_id"), layer=inputs.get("layer"), allowed=allowed,
            budget_minutes=b.get("budget_minutes"), priority=b.get("priority"), status=status, created_by="steward")
    return {"id": tid}


@router.post("/tasks/{task_id}/status")
def task_status(task_id: str, body=Body(...), conn=Depends(get_conn)):
    lifecycle.steward_set_task_status(conn, task_id, _obj(body).get("status"))
    return {"ok": True, "id": task_id}


@router.post("/claims/{claim_id}/resolve")
def resolve_claim(claim_id: str, body=Body(...), conn=Depends(get_conn)):
    b = _obj(body)
    row = lifecycle.steward_resolve_claim(conn, claim_id, b.get("tier"), b.get("special_status"), str(b.get("note") or ""))
    return views.claim_json(conn, {**views.get_claim(conn, row["id"])}, redact=False)


@router.post("/gaps/{gap_id}/resolve")
def resolve_gap(gap_id: str, body=Body(...), conn=Depends(get_conn)):
    b = _obj(body)
    return views.gap_json(lifecycle.steward_resolve_gap(conn, gap_id, b.get("status"), str(b.get("note") or "")))


@router.post("/submissions/{submission_id}/resolve")
def resolve_submission(submission_id: str, body=Body(...), conn=Depends(get_conn)):
    b = _obj(body)
    return lifecycle.steward_resolve_submission(conn, submission_id, b.get("status"), str(b.get("note") or ""))


@router.post("/generate")
def generate(conn=Depends(get_conn)):
    return {"created": taskgen.generate(conn)}


@router.post("/recheck/{claim_id}")
def recheck(claim_id: str, request: Request, conn=Depends(get_conn)):
    if not db.scalar(conn, "SELECT 1 FROM claims WHERE id=?", (claim_id,)):
        raise not_found("claim", claim_id)
    return lifecycle.recheck_claim(conn, request.app.state.checker, claim_id)


# ------------------------------------------------------------------ the Council


@router.post("/council/open", status_code=201)
def council_open(body=Body(default={}), conn=Depends(get_conn)):
    b = _obj(body or {})
    cyc = council.open_cycle(conn, b.get("budget_slots"), b.get("propose_days"), b.get("critique_days"),
                             b.get("vote_days"), str(b.get("note") or "") or None)
    return council.cycle_json(conn, cyc)


@router.post("/council/advance")
def council_advance(body=Body(default={}), conn=Depends(get_conn)):
    reason = _obj(body or {}).get("reason")
    return council.cycle_json(conn, council.advance(conn, force=True, reason=reason))


@router.post("/council/items/{item_id}/withdraw")
def council_withdraw(item_id: str, body=Body(...), conn=Depends(get_conn)):
    item = council.withdraw(conn, item_id, _obj(body).get("reason"))
    return {"id": item["id"], "status": item["status"], "reason": item["ratify_reason"]}


@router.post("/council/items/{item_id}/ratify")
def council_ratify(item_id: str, body=Body(...), conn=Depends(get_conn)):
    b = _obj(body)
    reason = b.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError(422, "invalid_reason", "reason must be a string")
    item = council.ratify(conn, item_id, b.get("decision"), reason)
    return council.item_json(conn, item, council.get_cycle(conn, item["cycle_id"]))


@router.post("/council/review")
def council_review(conn=Depends(get_conn)):
    return {"reviewed": council.review_due(conn)}
