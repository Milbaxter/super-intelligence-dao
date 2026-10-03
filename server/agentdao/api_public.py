"""Public read-only API (no auth)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from . import config, db, views
from .deps import get_conn
from .errors import not_found

router = APIRouter()

IN_PROGRESS = ("leased",)  # someone holds an active lease (orphans are healed by lifecycle.sweep_expired)
AWAITING_VERIFICATION = ("submitted", "verifying")


@router.get("/stats")
def stats(conn=Depends(get_conn)):
    now = db.now_ts()
    by = {k: 0 for k in ("reported", "source-checked", "reproduced", "re-run", "replicated", "disputed", "stale")}
    for r in db.all_(conn, f"SELECT {views.DISPLAY_STATUS_SQL} AS ds, COUNT(*) n FROM claims c GROUP BY ds", {"now": now}):
        if r["ds"] in by:
            by[r["ds"]] = r["n"]
    q = lambda sql, p=(): db.scalar(conn, sql, p) or 0  # noqa: E731
    since = db.ts_in(days=-1)
    return {
        "contributors": q("SELECT COUNT(*) FROM contributors"),
        "agents_active_24h": q("""SELECT COUNT(DISTINCT contributor_id) FROM (
                SELECT contributor_id FROM leases WHERE heartbeat_at >= ? OR created_at >= ?
                UNION SELECT contributor_id FROM submissions WHERE created_at >= ?)""", (since, since, since)),
        "tasks_open": q("SELECT COUNT(*) FROM tasks WHERE status='open'"),
        "tasks_in_progress": q("SELECT COUNT(*) FROM tasks WHERE status='leased'"),
        "tasks_awaiting_verification": q("SELECT COUNT(*) FROM tasks WHERE status IN ('submitted','verifying')"),
        "tasks_verified": q("SELECT COUNT(*) FROM tasks WHERE status='verified'"),
        "submissions_total": q("SELECT COUNT(*) FROM submissions"),
        "claims_total": q("SELECT COUNT(*) FROM claims WHERE special_status IS NOT 'retracted'"),
        "claims_by_tier": by,
        # Claims whose value is withheld while their blind round is undecided (same condition as views.blind_pending).
        "claims_awaiting_referee": q(f"""SELECT COUNT(*) FROM claims WHERE special_status IS NOT 'retracted'
                AND id IN ({views.BLIND_PENDING_CLAIMS_SQL})"""),
        "artifacts_total": q("SELECT COUNT(*) FROM artifacts"),
        "gaps_open": q("SELECT COUNT(*) FROM gaps WHERE status IN ('accepted','proposed')"),
        "verified_tokens": q("SELECT COALESCE(SUM(tokens_estimate),0) FROM submissions WHERE status='verified'"),
        "phase": config.PHASE,
    }


@router.get("/layers")
def layers(conn=Depends(get_conn)):
    counts = views.artifact_counts(conn)
    out = []
    for l in db.all_(conn, "SELECT * FROM layers ORDER BY sort, id"):
        arts = [r["id"] for r in db.all_(conn, "SELECT id FROM artifacts WHERE layer=?", (l["id"],))]
        out.append({
            **l, "artifact_count": len(arts),
            "claim_count": sum(counts.get(a, {}).get("claim_count", 0) for a in arts),
            "verified_claim_count": sum(counts.get(a, {}).get("verified_claim_count", 0) for a in arts),
            "gap_count": db.scalar(conn, "SELECT COUNT(*) FROM gaps WHERE layer=? AND status IN ('accepted','proposed')", (l["id"],)),
        })
    return out


@router.get("/artifacts")
def artifacts(layer: str | None = None, kind: str | None = None, q: str | None = None, conn=Depends(get_conn)):
    sql, p = "SELECT * FROM artifacts WHERE 1=1", []
    if layer:
        sql += " AND layer=?"; p.append(layer)
    if kind:
        sql += " AND kind=?"; p.append(kind)
    if q:
        sql += " AND (lower(name) LIKE ? OR lower(COALESCE(description,'')) LIKE ? OR id LIKE ?)"
        like = f"%{q.lower()[:100]}%"; p += [like, like, like]
    counts = views.artifact_counts(conn)
    return [views.artifact_summary(r, counts) for r in db.all_(conn, sql + " ORDER BY name", p)]


@router.get("/artifacts/{artifact_id}")
def artifact(artifact_id: str, conn=Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM artifacts WHERE id=?", (artifact_id,))
    if not row:
        raise not_found("artifact", artifact_id)
    counts = views.artifact_counts(conn)
    out = {**row, **views.artifact_summary(row, counts)}
    out["claims"] = [views.claim_json(conn, c) for c in db.all_(conn, views.CLAIM_SELECT + " WHERE c.artifact_id=? ORDER BY b.name, c.metric", (artifact_id,))]
    out["gaps"] = [views.gap_json(g) for g in db.all_(conn, "SELECT * FROM gaps WHERE layer=? AND status != 'rejected' AND (title LIKE ? OR description LIKE ?) ORDER BY created_at DESC",
                                                       (row["layer"], f"%{row['name']}%", f"%{row['name']}%"))]
    out["tasks"] = [views.task_summary(t) for t in db.all_(conn, "SELECT * FROM tasks WHERE status != 'draft' AND json_extract(inputs, '$.artifact_id')=? ORDER BY created_at DESC", (artifact_id,))]
    return out


@router.get("/benchmarks")
def benchmarks(layer: str | None = None, conn=Depends(get_conn)):
    sql, p = "SELECT b.*, (SELECT COUNT(*) FROM claims c WHERE c.benchmark_id=b.id AND c.special_status IS NOT 'retracted') AS claim_count FROM benchmarks b", []
    if layer:
        sql += " WHERE b.layer=?"; p.append(layer)
    return [{"id": r["id"], "name": r["name"], "layer": r["layer"], "url": r["url"], "description": r["description"],
             "measures": r["measures"], "saturated": bool(r["saturated"]), "claim_count": r["claim_count"]}
            for r in db.all_(conn, sql + " ORDER BY b.name", p)]


@router.get("/claims")
def claims(layer: str | None = None, artifact: str | None = None, benchmark: str | None = None,
           tier: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
           conn=Depends(get_conn)):
    where, p = ["1=1"], {"now": db.now_ts()}
    if layer:
        where.append("a.layer = :layer"); p["layer"] = layer
    if artifact:
        where.append("c.artifact_id = :artifact"); p["artifact"] = artifact
    if benchmark:
        where.append("c.benchmark_id = :benchmark"); p["benchmark"] = benchmark
    if tier:
        where.append(f"({views.DISPLAY_STATUS_SQL}) = :tier"); p["tier"] = tier
    w = " WHERE " + " AND ".join(where)
    total = db.scalar(conn, "SELECT COUNT(*) FROM claims c JOIN artifacts a ON a.id=c.artifact_id" + w, p)
    rows = db.all_(conn, views.CLAIM_SELECT + w + " ORDER BY c.tier_changed_at DESC LIMIT :lim OFFSET :off",
                   {**p, "lim": limit, "off": offset})
    return {"items": [views.claim_json(conn, r) for r in rows], "total": total}


@router.get("/claims/{claim_id}")
def claim(claim_id: str, conn=Depends(get_conn)):
    row = views.get_claim(conn, claim_id)
    if not row:
        raise not_found("claim", claim_id)
    out = views.claim_json(conn, row)
    out["trail"] = views.claim_trail(conn, row, out["value_hidden"])
    return out


@router.get("/map")
def map_(conn=Depends(get_conn)):
    counts = views.artifact_counts(conn)
    now = db.now_ts()
    all_claims = db.all_(conn, views.CLAIM_SELECT + " WHERE c.special_status IS NOT 'retracted'")
    hidden = {r["target_claim_id"] for r in db.all_(conn, views.BLIND_PENDING_CLAIMS_SQL)}
    benches = {b["id"]: b for b in db.all_(conn, "SELECT * FROM benchmarks")}
    layers_out = []
    for l in db.all_(conn, "SELECT * FROM layers ORDER BY sort, id"):
        arts = db.all_(conn, "SELECT * FROM artifacts WHERE layer=? ORDER BY name", (l["id"],))
        art_ids = {a["id"] for a in arts}
        cells: dict[tuple, list] = {}
        for c in all_claims:
            if c["artifact_id"] in art_ids:
                cells.setdefault((c["artifact_id"], c["benchmark_id"]), []).append(c)
        bench_ids = sorted({b for _, b in cells} | {b["id"] for b in benches.values() if b["layer"] == l["id"]},
                           key=lambda b: benches[b]["name"].lower())
        cell_out = []
        for (aid, bid), cs in sorted(cells.items()):
            statuses = [views.display_status(c, now) for c in cs]
            top = max(cs, key=lambda c: (views.display_status(c, now) in config.TIER_RANK,
                                         config.TIER_RANK.get(views.display_status(c, now), -1), c["tier_changed_at"]))
            top_hidden = top["id"] in hidden
            summary = "awaiting referee" if top_hidden else views.fmt_value(top["value"], top["unit"])
            if len(cs) > 1:
                summary += f" (+{len(cs) - 1} more)"
            cell_out.append({"artifact_id": aid, "benchmark_id": bid, "claim_ids": [c["id"] for c in cs],
                             "best_tier": views.best_tier(statuses), "value_summary": summary, "value_hidden": top_hidden})
        layers_out.append({
            "id": l["id"], "name": l["name"], "description": l["description"],
            "artifacts": [{k: v for k, v in views.artifact_summary(a, counts).items() if k not in ("description",)} for a in arts],
            "benchmarks": [{"id": b, "name": benches[b]["name"], "url": benches[b]["url"], "measures": benches[b]["measures"],
                            "saturated": bool(benches[b]["saturated"])} for b in bench_ids],
            "cells": cell_out,
            "gap_ids": [g["id"] for g in db.all_(conn, "SELECT id FROM gaps WHERE layer=? AND status IN ('accepted','proposed') ORDER BY created_at", (l["id"],))],
        })
    return {"layers": layers_out, "generated_at": now}


@router.get("/gaps")
def gaps(layer: str | None = None, status: str | None = None, conn=Depends(get_conn)):
    sql, p = "SELECT * FROM gaps WHERE 1=1", []
    if layer:
        sql += " AND layer=?"; p.append(layer)
    if status:
        sql += " AND status=?"; p.append(status)
    return [views.gap_json(g) for g in db.all_(conn, sql + " ORDER BY created_at DESC", p)]


@router.get("/tracks")
def tracks(conn=Depends(get_conn)):
    out = []
    for t in db.all_(conn, "SELECT * FROM tracks ORDER BY sort, id"):
        c = lambda st: db.scalar(conn, f"SELECT COUNT(*) FROM tasks WHERE track_id=? AND status IN ({','.join('?' * len(st))})", (t["id"], *st))  # noqa: E731
        out.append({**{k: t[k] for k in ("id", "name", "workstream", "phase", "summary", "why", "verification", "weight")},
                    "counts": {"open": c(("open",)), "in_progress": c(IN_PROGRESS),
                               "awaiting_verification": c(AWAITING_VERIFICATION), "verified": c(("verified",))}})
    return out


@router.get("/tasks")
def tasks(status: str | None = None, track: str | None = None, type: str | None = None,
          limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), conn=Depends(get_conn)):
    where, p = ["status != 'draft'"], []
    if status:
        where.append("status=?"); p.append(status)
    if track:
        where.append("track_id=?"); p.append(track)
    if type:
        where.append("type=?"); p.append(type)
    w = " WHERE " + " AND ".join(where)
    total = db.scalar(conn, "SELECT COUNT(*) FROM tasks" + w, p)
    rows = db.all_(conn, "SELECT * FROM tasks" + w + " ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?", [*p, limit, offset])
    return {"items": [views.task_summary(r) for r in rows], "total": total}


@router.get("/tasks/{task_id}")
def task(task_id: str, request: Request, conn=Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM tasks WHERE id=? AND status != 'draft'", (task_id,))
    if not row:
        raise not_found("task", task_id)
    return views.task_full(conn, row, request.app.state.settings.public_url)


@router.get("/contributors")
def contributors(conn=Depends(get_conn)):
    rows = db.all_(conn, """
        SELECT c.handle, c.model_family, c.joined_at, c.github_login,
          (SELECT COALESCE(SUM(amount),0) FROM ledger l WHERE l.contributor_id=c.id) AS credits,
          (SELECT COALESCE(SUM(tokens_estimate),0) FROM submissions s WHERE s.contributor_id=c.id AND s.status='verified') AS verified_tokens,
          (SELECT COUNT(*) FROM submissions s JOIN tasks t ON t.id=s.task_id WHERE s.contributor_id=c.id
             AND s.status='verified' AND t.type NOT LIKE 'verify.%') AS tasks_verified,
          (SELECT COUNT(*) FROM submissions s JOIN tasks t ON t.id=s.task_id WHERE s.contributor_id=c.id
             AND t.type LIKE 'verify.%' AND s.status IN ('verified','disputed','needs_steward')) AS verifications_done
        FROM contributors c WHERE c.status='active' ORDER BY credits DESC, verified_tokens DESC, c.joined_at""")
    return rows


@router.get("/activity")
def activity(limit: int = Query(50, ge=1, le=200), conn=Depends(get_conn)):
    return [{"ts": e["ts"], "kind": e["kind"], "actor": e["actor_handle"], "summary": e["summary"],
             "ref_type": e["ref_type"], "ref_id": e["ref_id"]}
            for e in db.all_(conn, "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]
