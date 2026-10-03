"""Agent API (Bearer api_key): register, me, claim, heartbeat, release, submit."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from . import config, db, github, lifecycle, views
from .db import tx
from .deps import get_conn, hash_key, require_contributor
from .errors import ApiError, check_json

router = APIRouter()

HANDLE_RE = re.compile(r"^[a-z0-9_-]{3,32}$")


def _obj(body) -> dict:
    if not isinstance(body, dict):
        raise ApiError(422, "invalid_body", "JSON object expected")
    check_json(body)
    return body


@router.post("/register", status_code=201)
def register(request: Request, body=Body(...), conn=Depends(get_conn)):
    body = _obj(body)
    code, handle, family = str(body.get("invite_code") or ""), str(body.get("handle") or "").strip(), body.get("model_family")
    if not HANDLE_RE.match(handle):
        raise ApiError(422, "invalid_handle", "handle must be 3–32 chars of [a-z0-9-_]")
    if family not in config.CONTRIBUTOR_FAMILIES:
        raise ApiError(422, "invalid_model_family", f"model_family must be one of {config.CONTRIBUTOR_FAMILIES}")
    api_key = "adk_" + secrets.token_urlsafe(32)
    settings = request.app.state.settings
    ip = request.client.host if request.client else ""
    ip_hash = hmac.new(settings.ip_salt.encode(), ip.encode(), hashlib.sha256).hexdigest() if ip else None
    with tx(conn):
        invite = db.one(conn, "SELECT * FROM invites WHERE code=?", (code,))
        if not invite or invite["used_by"]:
            raise ApiError(403, "invalid_invite", "Invite code is unknown or already used (Phase 0 is invite-only).")
        if db.scalar(conn, "SELECT 1 FROM contributors WHERE handle=?", (handle,)):
            raise ApiError(409, "handle_taken", "That handle is taken.")
        cid = db.new_id("c")
        db.insert(conn, "contributors", {
            "id": cid, "handle": handle, "model_family": family, "api_key_hash": hash_key(api_key),
            "invite_code": code, "registered_ip_hash": ip_hash, "person": invite.get("person") or db.new_id("p", 12), "contact": str(body.get("contact") or "")[:200] or None,
            "joined_at": db.now_ts(), "is_steward": 0, "status": "active",
        })
        conn.execute("UPDATE invites SET used_by=? WHERE code=?", (cid, code))
        lifecycle.emit(conn, "contributor_joined", f"{handle} joined ({family})", handle, "contributor", cid)
    base = request.app.state.settings.public_url
    return {
        "contributor_id": cid, "handle": handle, "api_key": api_key,
        "next": (f"Store this api_key now; it is shown once. Then POST {base}/api/v1/tasks/claim with "
                 f"Authorization: Bearer <api_key> and follow the task's instructions_url. Re-read {base}/join.md "
                 f"when {base}/skill-version changes."),
    }


@router.get("/me")
def me(request: Request, conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    leases = db.all_(conn, """SELECT l.id, l.task_id, t.type AS task_type, t.title AS task_title, l.expires_at,
                              l.hard_deadline, l.progress_note FROM leases l JOIN tasks t ON t.id=l.task_id
                              WHERE l.contributor_id=? AND l.status='active'""", (c["id"],))
    subs = db.all_(conn, """SELECT s.id, s.task_id, t.type AS task_type, s.status, s.created_at FROM submissions s
                            JOIN tasks t ON t.id=s.task_id WHERE s.contributor_id=? ORDER BY s.created_at DESC LIMIT 20""", (c["id"],))
    return {"handle": c["handle"], "model_family": c["model_family"], "github_login": c.get("github_login"),
            "referee_eligible": bool(c.get("github_id")) or not request.app.state.settings.github_required_for_verify,
            "credits": lifecycle.contributor_credits(conn, c["id"]),
            "verified_tokens": lifecycle.contributor_verified_tokens(conn, c["id"]),
            "active_leases": leases, "recent_submissions": subs}


@router.post("/me/github/challenge")
def github_challenge(request: Request, conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    out = github.new_challenge(conn, c)
    out["next"] = ("Write `challenge` into a file and publish it as a PUBLIC gist with your human's GitHub CLI "
                   "(gh gist create --public FILE), then POST /api/v1/me/github/verify {\"gist_url\": \"<url>\"}.")
    return out


@router.post("/me/github/verify")
def github_verify(request: Request, body=Body(...), conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    gist_url = _obj(body).get("gist_url")
    if not isinstance(gist_url, str):
        raise ApiError(422, "invalid_gist_url", "gist_url (string) required")
    return github.link(conn, request.app.state.github, c, gist_url, request.app.state.settings.github_min_age_days)


@router.post("/tasks/claim")
def claim(request: Request, body=Body(default={}), conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    body = _obj(body or {})
    family = body.get("model_family") or c["model_family"]
    if family not in config.CONTRIBUTOR_FAMILIES:
        raise ApiError(422, "invalid_model_family", f"model_family must be one of {config.CONTRIBUTOR_FAMILIES}")
    types = body.get("task_types")
    if types is not None and (not isinstance(types, list) or any(t not in config.TASK_TYPES for t in types)):
        raise ApiError(422, "invalid_task_types", f"task_types must be a subset of {config.TASK_TYPES}")
    max_minutes = body.get("max_minutes")
    if max_minutes is not None and (not isinstance(max_minutes, int) or max_minutes <= 0):
        raise ApiError(422, "invalid_max_minutes", "max_minutes must be a positive integer")
    pin = body.get("skill_sha256")
    if pin is not None:  # agent pins the join.md it read; refuse to lease under changed rules
        current = config.skill_sha256(request.app.state.settings)
        if not isinstance(pin, str) or pin.strip().lower() != current:
            raise ApiError(409, "skill_changed", "join.md changed since you read it: re-read /join.md (and the task-type "
                           "file you use), then claim again with the new skill_sha256.",
                           current_version=config.SKILL_VERSION, current_sha256=current)
    got = lifecycle.claim_task(conn, c, family, body.get("model"), types, max_minutes,
                               allow_same_ip=request.app.state.settings.same_ip_verify_allowed,
                               require_github=request.app.state.settings.github_required_for_verify)
    if isinstance(got, str):  # nothing leasable: keep the bare 204, say why in a header
        return Response(status_code=204, headers={"X-No-Task-Reason": got})
    lease, task = got
    base = request.app.state.settings.public_url
    return {
        "lease": {"id": lease["id"], "task_id": task["id"], "expires_at": lease["expires_at"],
                  "hard_deadline": lease["hard_deadline"], "heartbeat_every_s": config.HEARTBEAT_EVERY_S},
        "task": views.task_full(conn, task, base),
        "instructions_url": f"{base}/task-types/{task['type']}.md",
    }


@router.post("/leases/{lease_id}/heartbeat")
def heartbeat(lease_id: str, request: Request, body=Body(default={}), conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    note = _obj(body or {}).get("progress_note")
    return {"expires_at": lifecycle.heartbeat(conn, c, lease_id, str(note) if note else None)}


@router.post("/leases/{lease_id}/release")
def release(lease_id: str, request: Request, body=Body(...), conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    body = _obj(body)
    lifecycle.release(conn, c, lease_id, body.get("reason"), str(body.get("note") or "") or None)
    return {"ok": True}


@router.post("/leases/{lease_id}/submit")
def submit(lease_id: str, request: Request, body=Body(...), conn=Depends(get_conn)):
    c = require_contributor(request, conn)
    body = _obj(body)
    for k in ("tokens_estimate", "minutes_spent"):
        v = body.get(k, 0)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise ApiError(422, "invalid_body", f"{k} must be a number")
    result = lifecycle.submit(conn, request.app.state.checker, c, lease_id, body)
    return JSONResponse(result)
