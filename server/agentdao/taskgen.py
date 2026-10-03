"""Task generation: turn map gaps into Board tasks (CONTRACT §5 /admin/generate).

Idempotent: only creates a task when no pending (non-terminal) task of that kind exists
for the same target.
"""

from __future__ import annotations

from . import config, council, db, lifecycle
from .db import tx

_NOT_DONE = "status NOT IN ('verified','rejected','closed')"


def _has_pending(conn, task_type: str, key: str, value: str) -> bool:
    return bool(db.scalar(conn, f"SELECT 1 FROM tasks WHERE type=? AND json_extract(inputs, '$.{key}')=? AND {_NOT_DONE} LIMIT 1",
                          (task_type, value)))


def generate(conn) -> list[str]:
    created: list[str] = []
    with tx(conn):
        council.enforce_rules(conn, "taskgen")  # close open tasks that applicability rules exclude
        rules = council.active_rules(conn)
        paused = {r["id"] for r in db.all_(conn, "SELECT id FROM tracks WHERE weight = 0")}

        def ok(task_type: str, layer: str | None, kind: str | None = None) -> bool:
            """Applicability rules allow it and its track isn't paused (weight 0)."""
            if kind is not None and not council.task_allowed(rules, task_type, kind):
                return False
            return lifecycle.track_for(conn, task_type, layer) not in paused

        arts = db.all_(conn, """SELECT a.*, (SELECT COUNT(*) FROM claims c WHERE c.artifact_id=a.id
                                AND c.special_status IS NOT 'retracted') AS n FROM artifacts a ORDER BY a.layer, a.name""")
        for a in arts:
            if a["n"] == 0 and ok("map.extract", a["layer"], a["kind"]) and not _has_pending(conn, "map.extract", "artifact_id", a["id"]):
                created.append(lifecycle.create_task(
                    conn, type="map.extract", layer=a["layer"], created_by="taskgen", bonus=1.5, announce=False,
                    title=f"Find published benchmark results for {a['name']}",
                    inputs={"artifact_id": a["id"], "artifact_name": a["name"], "layer": a["layer"],
                            "artifact_url": a["url"], "url": a["url"], "repo_url": a["repo_url"]},
                    spec_md=(f"Find published benchmark results for **{a['name']}** ({a['kind']}, layer `{a['layer']}`). "
                             f"Start from {a['url'] or a['repo_url'] or 'its official pages'}. Each claim needs a verbatim "
                             f"quote (20–600 chars) from the source that contains the value. If nothing is published, "
                             f"submit `no_results_found: true` with the URLs you searched.")))
            if (not (a["license"] or "").strip() and ok("map.profile", a["layer"], a["kind"])
                    and not _has_pending(conn, "map.profile", "artifact_id", a["id"])):
                created.append(lifecycle.create_task(
                    conn, type="map.profile", layer=a["layer"], created_by="taskgen", announce=False,
                    title=f"Profile {a['name']}: license, latest release, repo",
                    inputs={"artifact_id": a["id"], "artifact_name": a["name"], "layer": a["layer"], "kind": a["kind"],
                            "artifact_url": a["url"], "url": a["url"], "repo_url": a["repo_url"],
                            "missing_fields": ["license"]},
                    spec_md=f"Fill in license, latest version/release date, repo and homepage for **{a['name']}**, each with a source URL and verbatim quote."))

        for l in db.all_(conn, "SELECT * FROM layers ORDER BY sort"):
            if ok("map.gap_scan", l["id"]) and not _has_pending(conn, "map.gap_scan", "layer", l["id"]):
                created.append(lifecycle.create_task(
                    conn, type="map.gap_scan", layer=l["id"], created_by="taskgen", announce=False,
                    title=f"Gap scan: {l['name']}",
                    inputs={"layer": l["id"], "layer_name": l["name"]},
                    spec_md=(f"Review the `{l['id']}` layer of the map. List missing evidence, missing capabilities and "
                             f"important missing artifacts, each with evidence URLs.")))

        # Re-verify stale claims (past expires_at) and blind-check unverified T1 claims (capped per run).
        now = db.now_ts()
        pending_claims = {r["target_claim_id"] for r in db.all_(conn, f"""SELECT target_claim_id FROM tasks
                           WHERE type='verify.blind_extract' AND {_NOT_DONE}""")}
        stale = db.all_(conn, """SELECT * FROM claims WHERE special_status IS NULL AND expires_at < ?
                                 AND tier != 'reported' ORDER BY expires_at""", (now,))
        fresh_t1 = db.all_(conn, """SELECT c.* FROM claims c WHERE c.special_status IS NULL AND c.tier='source-checked'
                                    AND c.expires_at >= ? AND NOT EXISTS (SELECT 1 FROM tasks t
                                    WHERE t.type='verify.blind_extract' AND t.target_claim_id=c.id) ORDER BY c.created_at""", (now,))
        budget = config.TASKGEN_MAX_BLIND_PER_RUN
        for claim, bonus in [*((c, 1.5) for c in stale), *((c, 1.0) for c in fresh_t1)]:
            if budget <= 0:
                break
            if claim["id"] in pending_claims:
                continue
            created.append(lifecycle.spawn_blind_task(conn, claim, claim["submission_id"], bonus=bonus, created_by="taskgen", announce=False))
            pending_claims.add(claim["id"])
            budget -= 1

        if created:
            lifecycle.emit(conn, "taskgen", f"task generator created {len(created)} tasks", "steward")
    return created
