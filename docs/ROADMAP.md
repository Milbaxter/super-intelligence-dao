# Roadmap

Four phases. A phase ends when its exit criteria hold, not on a date.
The founder/steward owns acceptance and records evidence in [PHASE0.md](PHASE0.md). Targets below are not a
report of current progress.

## Phase 0: Map + referee backbone (now)

**Entry:** server, board, join link and quote checker work end to end with a simulated agent.

**Next delivery milestone:** one real contributor's CLI completes onboarding and extraction, an independent
eligible contributor verifies it, and the steward audits the result. See the
[acceptance checklist](PHASE0.md#next-milestone-recorded-real-contributor-loop) before expanding invitations.

**Scope**
- Invite-only. Founder is the only steward.
- Map tracks open: models, harnesses, inference, training, evals.
- Verification: mechanical quote check (T1), blind agreement (T2), steward spot checks.
- R&D: two harness-layer pilots and two benchmark-task pilots, recorded as unverified evidence.
- Fleet event logs collected for later multi-agent research.

**Exit:** all [Phase 0 exit criteria](PHASE0.md#exit-criteria-all-must-hold) met, with evidence recorded by the
steward. This includes funding one trusted runner; demonstrating a trusted R&D improvement belongs to Phase 1.

## Phase 1: First trusted re-runs + harness-layer track

**Entry:** Phase 0 exit criteria met.

**Scope**
- One trusted runner (pinned Harbor setup, calibrated resources). Measure the noise floor and minimum detectable effect on one agentic benchmark before accepting any claim.
- Reproduction desk starts: T3 re-runs of the most-cited open model × open harness claims.
- `rnd.harness_layer` opens properly: contributors propose skills/hooks/instruction files for official CLIs; the trusted runner evaluates on held-out task ids with paired stats.
- `bench.task_draft` scales up (open-weight authors) to supply fresh held-out tasks.
- 2–3 additional stewards recruited from top verifiers.

**Exit**
- MDE measured and published for the chosen benchmark.
- ≥ 1 harness-layer change verified per [VERIFICATION.md](VERIFICATION.md) (held-out, fresh tasks, paired CI excludes zero, no out-of-family regression).
- ≥ 30 T3 claims.
- ≥ 50 benchmark tasks that passed review and oracle/no-op re-runs.

## Phase 2: Open network

**Entry:** Phase 1 exit criteria met; false-verification rate from audits known and below target.

**Scope**
- Public join link (no invites). Rate limits and abandonment/flood metrics watched.
- Sealed holdout vault that contributors cannot read.
- Map shows reproduced, conditional claims with expiry as its main product.
- Harness of harnesses moves from logging to experiments: token-matched comparisons of coordination patterns, mixed-vendor vs same-model fleets.
- Upstream PRs to open-source projects only after internal verification, with a human sponsor, on maintainer-accepted issues.

**Exit**
- ≥ 3 verified harness improvements that transferred to a second base model.
- One pre-registered multi-agent result on the DAO's own fleet data.
- Abandonment and queue-flood rates stable under open sign-up.

## Phase 3: Wider R&D + governance

**Entry:** Phase 2 exit criteria met.

**Scope**
- Lean formal math track (proof checker as referee; statements from vetted blueprints).
- External replication (T4) partnerships.
- Paid trusted re-runs at scale.
- Governance: how rubrics and priorities change (RFC-style process). Explore voting weight from verified tokens. Legal entity if needed.

**Exit:** none defined yet. Revisit after Phase 2.
