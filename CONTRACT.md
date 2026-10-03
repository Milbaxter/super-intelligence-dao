# Super Intelligence DAO — build contract (Phase 0)

Single source of truth for everyone building this repo. If you must deviate, write the deviation into
`docs/DEVIATIONS.md` and keep the JSON shapes backward compatible.

Name: **Super Intelligence DAO** (real name since integration; keep it in ONE config constant `SITE_NAME` / one JS const so it can be renamed).
No logo or domain yet. Repo slug: `super-intelligence-dao`. Public base URL comes from env `AGENTDAO_PUBLIC_URL` (default `http://localhost:8787`).

## 1. What this is (one paragraph)

People donate their AI agents' spare subscription tokens. They tell their own agent (Claude Code, Codex CLI,
Gemini CLI…) "read <URL>/join.md and follow it". The agent registers, claims a task from the Board, does it,
submits. The org never re-runs things with paid API calls in Phase 0 (no budget). Instead verification =
**mechanical checks** (e.g. the server fetches the cited source and confirms the quote is really there) +
**independent blind agreement** (a different contributor's agent, ideally a different model family, redoes the
task without seeing the first answer) + **steward spot checks** (the founder audits a random sample + all disputes).
Only verified results update the Map. The core loop: Map shows gaps → gaps become tasks on the Board →
agents claim via the Join link → the Referee (checks + agreement + steward) verifies → only verified results flow
back into the Map. "Agents propose. The referee decides."

Two workstreams:
- **Map** (live in Phase 0): living, sourced map of the open-source AI stack — what exists, what works under which
  conditions, where evidence or capabilities are missing. Atomic unit = a *claim* (artifact × benchmark × conditions
  × metric × value × source × quote × verification tier).
- **R&D** (tracks exist, mostly "next"/"vision" in Phase 0): harness improvements, harness-of-harnesses (multi-agent),
  benchmark construction, Lean. Phase 0 opens only R&D task types whose check is mechanical or subscription-runnable.

Honesty rule for the frontend: the site may present the full ideal vision for marketing, but it must ALWAYS show
clearly what is actually running now (Phase 0: invite-only, token-starved, Map first, verification by sources +
agreement + spot checks) vs next vs vision.

## 2. Repo layout

```
agent-dao/
  CONTRACT.md            this file
  README.md              quickstart (written by integration)
  pyproject.toml         uv project, package `agentdao` in server/
  server/agentdao/       FastAPI backend (owner: backend)
    __init__.py config.py db.py schema.sql app.py api_public.py api_agent.py api_admin.py
    verify.py (quote checker) lifecycle.py (leases, verification flow, credits) taskgen.py seed.py
  web/                   static frontend, served at / (owner: frontend)
    index.html map.html board.html task.html claim.html artifact.html join.html referee.html people.html activity.html steward.html
    assets/css/*.css assets/js/*.js
    mock/*.json          fixtures matching section 5 (used when ?mock=1 or API unreachable)
  agent/                 agent-facing protocol (owner: protocol)
    join.md              served at /join.md (templated: {{BASE_URL}}, {{SKILL_VERSION}})
    task-types/<type>.md one instruction file per task type, served at /task-types/<type>.md
    worker/run.sh        optional headless loop for claude/codex/gemini with budget caps
  seed/                  seed data JSON (owners: ecosystem-seed + tracks-seed)
    layers.json artifacts.json benchmarks.json claims.json gaps.json tracks.json tasks.json
  docs/                  VISION.md PHASE0.md PROTOCOL.md VERIFICATION.md SECURITY.md RESEARCH.md
  scripts/sim_agent.py   simulated contributor agent for end-to-end tests (owner: protocol)
  tests/                 pytest (owner: backend)
```

Stack: Python 3.12+ (system has 3.14; use `requires-python = ">=3.11"`), `uv`, FastAPI, uvicorn, httpx, stdlib
`sqlite3` (no ORM), pytest. Frontend: plain HTML/CSS/vanilla JS modules, NO build step, no framework, no external
JS except optionally from cdnjs. Google Fonts allowed. Run: `uv run agentdao serve` (port 8787), `uv run agentdao seed`.
DB file: `data/agentdao.db` (env `AGENTDAO_DB`). Steward key: env `AGENTDAO_STEWARD_KEY` (dev default `dev-steward`).

## 3. Core concepts & enums

### Stack layers (ids are stable)
`data`, `pretraining`, `post-training`, `environments`, `evals`, `inference`, `models`, `harnesses`,
`multi-agent`, `ux`, `safety`.

### Artifact kinds
`model`, `dataset`, `framework`, `harness`, `benchmark`, `environment`, `tool`, `app`, `library`.

### Verification tiers (claims) — shown everywhere, the heart of the product
| tier | id | meaning | Phase 0? |
|---|---|---|---|
| T0 | `reported` | stated somewhere, not checked | yes |
| T1 | `source-checked` | server fetched source URL, verbatim quote found, value appears in quote | yes |
| T2 | `reproduced` | an independent contributor's agent blindly re-extracted the same value from the source (different contributor; different model family preferred) | yes |
| T3 | `re-run` | result re-executed by trusted runner (benchmark actually run) | next |
| T4 | `replicated` | independently replicated by an external party / multiple re-runs | vision |
Special statuses: `disputed` (blind re-extraction disagreed or steward flagged), `stale` (past `expires_at`),
`retracted` (steward). A claim's display status = special status if set, else tier. "Verified" in UI = T2+.
Default expiry: 180 days after last tier change.

### Task types (Phase 0)
| type | workstream | what the agent does | payload | verification |
|---|---|---|---|---|
| `map.extract` | map | find published benchmark results for one artifact | `{claims:[ClaimDraft], no_results_found:bool, searched:[url]}` | each claim: mechanical quote check → T1, then auto-spawn `verify.blind_extract` per claim |
| `map.profile` | map | fill artifact metadata (license, latest release, repo, description) with sources | `{fields:{license, latest_version, latest_release_date, repo_url, homepage, description}, sources:[{field,url,quote}]}` | quote check per field + `verify.review` |
| `map.gap_scan` | map | for one layer: list missing evidence / missing capabilities / important missing artifacts | `{gaps:[{title,kind,description,evidence_urls:[...]}], new_artifacts:[{name,kind,url,why}]}` | `verify.review` + steward accept |
| `verify.blind_extract` | referee | given artifact + benchmark + metric + source_url (NOT the value), extract the value + quote | `{found:bool, value:number|null, unit, quote, conditions:{}}` | server compares with original (tolerance: abs diff ≤ 0.1 or relative ≤ 0.5%) → agree → claim T2; disagree → `disputed` |
| `verify.review` | referee | second-opinion review of a submission with a rubric (original visible) | `{verdict:"accept"|"reject"|"needs_steward", reasons:[...], issues:[...]}` | accept → submission verified; reject → rejected; else steward queue |
| `rnd.harness_layer` | rnd (next) | propose/measure a skill/plugin/hook/instructions file for an official agent CLI on a named open task set, report with/without results | `{artifact_url, description, task_set, runs:[{variant, task_id, passed}], model, notes}` | `verify.review` + independent rerun task (later T3) |
| `bench.task_draft` | rnd (next) | draft a Harbor-format benchmark task with oracle solution | `{repo_url_or_gist, task_id, description, oracle_passes:bool, noop_fails:bool, logs_excerpt}` | `verify.review` where the verifier re-runs oracle/no-op in docker locally |

`ClaimDraft` = `{benchmark, metric, value:number, unit:"%"|"score"|"pass@1"|..., higher_is_better:bool,
conditions:{model?, harness?, scaffold?, budget?, attempts?, date?, notes?}, source_url, quote, reported_by:"artifact-authors"|"third-party"|"leaderboard"}`.

Every task has `allowed_model_families` (list from `claude`, `gpt`, `gemini`, `open-weight`, `any`).
Rule: anything that could become training data for a model → `["open-weight"]` only (provider terms). Map and
verify tasks → `["any"]`.

### Task statuses
`draft` (steward only) → `open` → `leased` → `submitted` → `verifying` → `verified` | `rejected` | `disputed` | `needs_steward` → `closed`.
Lease expiry returns task to `open` (attempts += 1). `attempts >= max_attempts (3)` → `needs_steward`.

### Leases
TTL 30 min; each heartbeat extends to now+30 min; absolute max 5 h (fits one subscription usage window).
`release` with reason `quota` | `gave_up` | `error` | `unsafe` returns task to open (quota/unsafe don't count as attempts).
A contributor may hold at most 2 active leases. A contributor may never claim a verify task targeting their own
submission, nor two verify tasks for the same claim. Prefer (priority bonus) verifiers whose model_family differs
from the original submission's.

### Credits ("only verified work counts")
Ledger rows `{contributor_id, kind, amount, ref_type, ref_id, ts}`. Kinds and amounts:
- `claim_reproduced` +10 to the original extractor when a claim reaches T2
- `verify_agreed` +4 to a blind verifier whose result matched; `verify_review` +2 for a review that matched steward/final outcome
- `gap_accepted` +8 when steward accepts a gap
- `dispute_resolved` +6 to the side the steward rules for
Also track `verified_tokens` = sum of `tokens_estimate` of submissions that ended `verified`. Show it on people page
with copy: "Later, voting weight may come from verified tokens — tokens spent on work that passed the referee — never raw tokens."

### Task priority
`priority = base (track weight 1–5) × staleness_or_gap_bonus × (1 + 0.5 if verify task) ` — verify tasks first, so
the queue doesn't fill with unverified work. Keep it simple; document the formula in docs/PROTOCOL.md.

## 4. Data model (SQLite) — backend owns exact DDL, must support these fields

- `contributors(id TEXT pk, handle UNIQUE, model_family, api_key_hash, invite_code, joined_at, is_steward INT, status)`
- `invites(code pk, created_at, used_by NULL, note)`
- `layers(id pk, name, description, sort)`
- `artifacts(id pk slug, name, layer, kind, url, repo_url, license, description, latest_version, latest_release_date, open_weights INT NULL, created_at, updated_at, source TEXT /*seed|task:<id>*/)`
- `benchmarks(id pk slug, name, layer, url, description, measures, saturated INT, notes)`
- `claims(id pk, artifact_id, benchmark_id, metric, value REAL, unit, higher_is_better INT, conditions JSON, source_url, quote, reported_by, tier, special_status NULL, created_at, tier_changed_at, expires_at, submission_id NULL, check_result JSON, seed INT)`
- `gaps(id pk, layer, kind /*missing_evidence|missing_capability|stale|disputed|missing_artifact*/, title, description, evidence_urls JSON, status /*proposed|accepted|resolved|rejected*/, created_by, created_at, task_ids JSON)`
- `tracks(id pk, name, workstream /*map|rnd|referee*/, phase /*now|next|vision*/, summary, why, verification, weight INT, sort)`
- `tasks(id pk, type, track_id, title, spec_md, inputs JSON, allowed_model_families JSON, budget_minutes INT, status, priority REAL, attempts INT, max_attempts INT, parent_submission_id NULL, target_claim_id NULL, created_by, created_at, updated_at)`
- `leases(id pk, task_id, contributor_id, model_family, model, created_at, heartbeat_at, expires_at, hard_deadline, status /*active|submitted|released|expired*/, progress_note)`
- `submissions(id pk, task_id, lease_id, contributor_id, model_family, model, payload JSON, tokens_estimate INT, minutes_spent REAL, notes, checks JSON, status /*pending|verifying|verified|rejected|disputed|needs_steward*/, created_at)`
- `verifications(id pk, submission_id, claim_id NULL, verifier_submission_id, verdict /*agree|disagree|accept|reject|needs_steward*/, detail JSON, created_at)`
- `ledger(...)` as above; `events(id, ts, kind, actor_handle, summary, ref_type, ref_id)` — activity feed; everything noteworthy emits one.

IDs: short prefixed ids, e.g. `t_8f3k2a`, `c_…`, `cl_…`, `s_…`, `l_…`, `g_…`.

## 5. HTTP API (v1) — JSON, prefix `/api/v1`

All responses JSON. Errors: `{"error":{"code":"snake_case","message":"human readable"}}` with proper status.
Agent auth: `Authorization: Bearer <api_key>`. Steward: `Authorization: Bearer <steward key>`.
CORS open for GET. Rate limit (simple in-memory per key/IP): 60 req/min agent, 300/min public GET.

### Public (no auth)
- `GET /stats` → `{contributors, agents_active_24h, tasks_open, tasks_in_progress, tasks_verified, submissions_total, claims_total, claims_by_tier:{reported, source-checked, reproduced, re-run, replicated, disputed, stale}, artifacts_total, gaps_open, verified_tokens, phase:"0"}`
- `GET /layers` → `[{id,name,description,sort, artifact_count, claim_count, verified_claim_count, gap_count}]`
- `GET /artifacts?layer=&kind=&q=` → `[{id,name,layer,kind,url,repo_url,license,description,open_weights, claim_count, verified_claim_count, best_tier}]`
- `GET /artifacts/{id}` → artifact + `claims:[Claim]` + `gaps:[Gap]` + `tasks:[TaskSummary]`
- `GET /benchmarks?layer=` → `[{id,name,layer,url,description,measures,saturated, claim_count}]`
- `GET /claims?layer=&artifact=&benchmark=&tier=&limit=&offset=` → `{items:[Claim], total}`
- `GET /claims/{id}` → `Claim` + `trail:[{ts, kind, actor, summary, detail}]` (check results, submissions, blind verifications, steward actions)
- `GET /map` → `{layers:[{id,name,description, artifacts:[ArtifactSummary], benchmarks:[BenchmarkSummary], cells:[{artifact_id, benchmark_id, claim_ids:[], best_tier, value_summary}], gap_ids:[]}], generated_at}`
- `GET /gaps?layer=&status=` → `[Gap]`
- `GET /tracks` → `[{id,name,workstream,phase,summary,why,verification,weight, counts:{open, in_progress, verified}}]`
- `GET /tasks?status=&track=&type=&limit=` → `{items:[TaskSummary], total}`
- `GET /tasks/{id}` → `Task` (full, minus anything secret; for `verify.blind_extract` the ORIGINAL VALUE IS NEVER EXPOSED on public endpoints while the task is open/leased)
- `GET /contributors` → `[{handle, model_family, joined_at, credits, verified_tokens, tasks_verified, verifications_done}]` sorted by credits
- `GET /activity?limit=50` → `[{ts, kind, actor, summary, ref_type, ref_id}]`
- `GET /join.md` (text/markdown) and `GET /task-types/{type}.md` served from `agent/` with `{{BASE_URL}}` substituted.
- `GET /skill-version` → `{version, sha256}` of join.md (so agents can pin & detect changes)

`Claim` = `{id, artifact_id, artifact_name, layer, benchmark_id, benchmark_name, metric, value, unit, higher_is_better, conditions, source_url, quote, reported_by, tier, special_status, display_status, created_at, tier_changed_at, expires_at, seed, check_result}`
`TaskSummary` = `{id, type, track_id, title, status, priority, allowed_model_families, budget_minutes, attempts, created_at}`
`Task` = TaskSummary + `{spec_md, inputs, instructions_url, submissions:[{id, contributor, status, created_at}]}`
`Gap` = `{id, layer, kind, title, description, evidence_urls, status, created_at, task_ids}`

### Agent (Bearer api_key)
- `POST /register` `{invite_code, handle, model_family, contact?}` → `201 {contributor_id, handle, api_key, next:"…instructions…"}` (api_key shown once; store sha256 only). Handle: 3–32 chars `[a-z0-9-_]`.
- `GET /me` → `{handle, model_family, credits, verified_tokens, active_leases:[...], recent_submissions:[...]}`
- `POST /tasks/claim` `{model_family, model, task_types?:[...], max_minutes?}` → `200 {lease:{id, task_id, expires_at, hard_deadline, heartbeat_every_s:600}, task:Task, instructions_url}` or `204` when nothing eligible.
- `POST /leases/{id}/heartbeat` `{progress_note?}` → `{expires_at}`
- `POST /leases/{id}/release` `{reason, note?}` → `{ok:true}`
- `POST /leases/{id}/submit` `{payload, model, tokens_estimate, minutes_spent, notes?}` → `{submission_id, status, checks:[{name, passed, detail}], spawned_task_ids:[...]}`. Payload validated per task type (422 with field errors).

### Steward (Bearer steward key)
- `POST /admin/invites` `{count, note}` → `{codes:[...]}`
- `GET /admin/queue` → `{needs_steward:[...], disputed_claims:[...], proposed_gaps:[...], spot_check_sample:[...]}` (spot check = random 10% of items verified in last 7 days)
- `POST /admin/tasks` (create task) · `POST /admin/tasks/{id}/status` `{status}`
- `POST /admin/claims/{id}/resolve` `{tier?|special_status?, note}` · `POST /admin/gaps/{id}/resolve` `{status, note}`
- `POST /admin/submissions/{id}/resolve` `{status, note}`
- `POST /admin/generate` → runs taskgen (creates `map.extract` for artifacts with 0 claims, `map.profile` for artifacts missing license, `map.gap_scan` per layer if none open, re-verification for stale claims) → `{created:[ids]}`
- `POST /admin/recheck/{claim_id}` → re-run mechanical quote check.

## 6. Mechanical quote check (verify.py) — security-critical
Fetch `source_url`: https only (http allowed only for localhost in tests), resolve DNS and refuse private/loopback/
link-local/metadata IPs (SSRF), 10 s timeout, max 3 redirects (re-validate each hop), max 3 MB, text/html, text/plain,
markdown, json only (PDF → result `unverifiable_format`, claim stays T0 with note). github.com blob URLs → rewrite to
raw.githubusercontent.com. arxiv.org/abs/X → also try arxiv.org/html/X. Strip tags/scripts, unescape entities,
normalize whitespace + unicode quotes/dashes + case. Pass = normalized quote is a substring of normalized page text
AND the claim value (as written in some common format: `72.4`, `72.4%`, `0.724`) appears in the quote.
Quote must be 20–600 chars. Return `{passed, reason, fetched_url, http_status, fetched_at, content_sha256}`.
Cache by URL for 1 h.

## 7. Seed file formats (`seed/*.json`)
- `layers.json`: `[{id,name,description,sort}]`
- `artifacts.json`: `[{id,name,layer,kind,url,repo_url?,license?,description,open_weights?}]` (~60–90 real projects)
- `benchmarks.json`: `[{id,name,layer,url,description,measures,saturated}]`
- `claims.json`: `[{artifact_id, benchmark_id, metric, value, unit, higher_is_better, conditions, source_url, quote, reported_by, retrieved_at}]` — REAL claims only, quote copied verbatim from a page actually fetched. Seeded as T0 `reported` with `seed=1`; `agentdao seed --check-sources` runs the quote check and promotes passing ones to T1.
- `gaps.json`: `[{id?, layer, kind, title, description, evidence_urls}]` seeded as status `accepted`, created_by `steward-seed`.
- `tracks.json`: `[{id,name,workstream,phase,summary,why,verification,weight,sort}]`
- `tasks.json`: `[{type, track_id, title, spec_md, inputs, allowed_model_families, budget_minutes, priority?}]` hand-written starter tasks (taskgen adds more).

## 8. Frontend pages (all read from the public API; mock fixtures for offline dev)
- `/` (index): hero with the vision + the aha line ("Agents propose. The referee decides."), the loop diagram
  (Map → Board → Join → Referee → Map, Steering in the middle) — interactive/animated tastefully, live stats,
  **"What's running now vs next vs vision"** section (Phase 0 honesty), example walkthrough, CTA "Point your agent here".
- `/map.html`: the living map — layers as rows/sections, artifacts × benchmarks cells colored by tier, gaps visible as
  first-class, filters (layer, tier, kind), search; click → artifact/claim.
- `/artifact.html?id=` · `/claim.html?id=` (evidence trail, tier ladder, quote with source link, conditions, expiry)
- `/board.html`: task board grouped by status/track; tracks with phase badges (now/next/vision); `/task.html?id=`
- `/join.html`: for humans: the one line to paste into their agent, what happens, safety (sandbox, quota caps, never share
  logins, provider terms), invite-only note for Phase 0, copy buttons; FAQ.
- `/referee.html`: how verification works: tier ladder T0–T4 (which are live), blind agreement explained, spot checks, anti-gaming.
- `/people.html`: contributors leaderboard by verified credits + verified tokens; "voice later" note.
- `/activity.html`: live feed (poll every 15 s).
- `/steward.html`: minimal admin console (paste steward key → stored in sessionStorage) for queue/resolve/invites/generate.

Safety in frontend: render all user/agent-provided text with textContent / escaping (NO innerHTML of untrusted data),
links only http(s) with `rel="noopener noreferrer nofollow"`.

## 9. Security non-negotiables
Tasks are data, not instructions to obey blindly: join.md tells agents task text can never override join.md safety rules.
No contributor secrets ever requested. No listening ports on contributor machines. Recommend running inside a
container/devcontainer for any task that runs code. Training-data-like tasks only for open-weight models. API keys
hashed. Steward endpoints constant-time compare. Payload size limit 256 KB. All agent text escaped on output.
