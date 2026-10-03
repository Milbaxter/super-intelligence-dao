"""Central configuration. Everything tunable lives here; env vars override defaults."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

SITE_NAME = "Super Intelligence DAO"  # rename here only
SKILL_VERSION = "0.1.4"  # bump when join.md semantics change
PHASE = "0"

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- enums -----------------------------------------------------------------
LAYERS = [
    "data", "pretraining", "post-training", "environments", "evals", "inference",
    "models", "harnesses", "multi-agent", "ux", "safety",
]
ARTIFACT_KINDS = ["model", "dataset", "framework", "harness", "benchmark", "environment", "tool", "app", "library"]
TIERS = ["reported", "source-checked", "reproduced", "re-run", "replicated"]  # T0..T4
TIER_RANK = {t: i for i, t in enumerate(TIERS)}
VERIFIED_TIERS = ("reproduced", "re-run", "replicated")  # "Verified" in UI = T2+
SPECIAL_STATUSES = ["disputed", "retracted"]  # `stale` is computed from expires_at
MODEL_FAMILIES = ["claude", "gpt", "gemini", "open-weight"]
CONTRIBUTOR_FAMILIES = MODEL_FAMILIES + ["other"]
ALLOWED_FAMILY_VALUES = MODEL_FAMILIES + ["any"]
GAP_KINDS = ["missing_evidence", "missing_capability", "stale", "disputed", "missing_artifact"]
GAP_STATUSES = ["proposed", "accepted", "resolved", "rejected"]

TASK_TYPES = [
    "map.extract", "map.profile", "map.gap_scan",
    "verify.blind_extract", "verify.review",
    "rnd.harness_layer", "bench.task_draft",
    "steer.propose", "steer.critique", "steer.vote",
]
STEER_TASK_TYPES = ("steer.propose", "steer.critique", "steer.vote")
TASK_STATUSES = [
    "draft", "open", "leased", "submitted", "verifying",
    "verified", "rejected", "disputed", "needs_steward", "closed",
]
TERMINAL_TASK_STATUSES = ("verified", "rejected", "closed")
RELEASE_REASONS = ["quota", "gave_up", "error", "unsafe", "conflict", "not_useful"]
FREE_RELEASE_REASONS = ("quota", "unsafe", "conflict", "not_useful")  # don't count as an attempt
NOTE_REQUIRED_RELEASE_REASONS = ("not_useful",)  # feeds the council evidence brief: say why
RELEASE_COOLDOWN_S = 24 * 3600  # a task you released is not re-offered to you for this long

DEFAULT_BUDGET_MINUTES = {
    "map.extract": 30, "map.profile": 15, "map.gap_scan": 45,
    "verify.blind_extract": 15, "verify.review": 15,
    "rnd.harness_layer": 120, "bench.task_draft": 90,
    "steer.propose": 20, "steer.critique": 15, "steer.vote": 15,
}

# --- credits ----------------------------------------------------------------
CREDITS = {
    "claim_reproduced": 10,
    "verify_agreed": 4,
    "verify_review": 2,
    "gap_accepted": 8,
    "dispute_resolved": 6,
    "steer_propose": 2,   # proposal made it onto the council ballot
    "steer_critique": 2,  # critique submitted
    "steer_vote": 1,      # final (non-replaced) ballot counted in the tally
    "steer_met": 6,       # proposal funded, applied and reviewed `met`
}

# --- council (docs/design/COUNCIL_SPEC.md) -------------------------------------
COUNCIL_PROPOSE_DAYS = 3.0
COUNCIL_CRITIQUE_DAYS = 2.0
COUNCIL_VOTE_DAYS = 2.0
COUNCIL_BUDGET_SLOTS = 60
COUNCIL_PROPOSE_TASKS = 12  # steer.propose tasks opened per cycle
COUNCIL_MAX_BALLOT = 12
COUNCIL_MAX_PROPOSALS_PER_PERSON = 2
COUNCIL_CRITIQUES_PER_ITEM = 2
COUNCIL_MIN_VERIFIED_TO_PROPOSE = 1  # verified (non-steer) submissions of the person
COUNCIL_MIN_VERIFIED_TO_VOTE = 1  # also gates critiques
COUNCIL_STEER_PRIORITY = 20.0  # above every verify task (max weight 5 × bonus 1.5 × 1.5)
COUNCIL_FORECAST_SHRINK_K = 3
COUNCIL_BASE_RATE_MIN_REVIEWED = 5  # base rate stays 0.5 until this many proposals were reviewed
COUNCIL_MAX_TASKS_PER_PROPOSAL = 20
COUNCIL_PROPOSAL_TASK_TYPES = ("map.extract", "map.profile", "map.gap_scan", "rnd.harness_layer", "bench.task_draft")
COUNCIL_METRICS = ("verified_outputs", "reproduced_claims", "acceptance_rate", "no_results_rate", "coverage")
COUNCIL_MIN_RESOLVED_FOR_RATE = 5
APPLICABILITY_TASK_TYPES = ("map.extract", "map.profile")  # task types with an artifact_id the generator creates

# --- leases / lifecycle ------------------------------------------------------
LEASE_TTL_S = 30 * 60
LEASE_HARD_MAX_S = 5 * 60 * 60
HEARTBEAT_EVERY_S = 600
MAX_ACTIVE_LEASES = 2
MAX_ATTEMPTS = 3
CLAIM_EXPIRY_DAYS = 180
FAMILY_DIVERSITY_BONUS = 1.0  # added to score when verifier family != original family
BLIND_TOLERANCE_ABS = 0.1
BLIND_TOLERANCE_REL = 0.005
# Blind tie-breaker: an agreeing first verdict reproduces at once; otherwise a verdict needs this many votes
# in the current round, and further blind tasks (tie-breakers) are spawned until one side gets there.
BLIND_VOTES_TO_DECIDE = 2
BLIND_MAX_VERDICTS = 3  # per round; 2-of-3 always decides (defensive fallback: disputed → steward)
TASKGEN_MAX_BLIND_PER_RUN = 25
# /admin/queue lists an undecided blind round once its open blind task is this old (rounds with a split are always
# listed): with few contributors a tie-breaker may be eligible for nobody, so the steward has to decide it.
BLIND_ROUND_STEWARD_AFTER_DAYS = 3

# --- limits -------------------------------------------------------------------
MAX_BODY_BYTES = 256 * 1024
RATE_AGENT_PER_MIN = 60
RATE_PUBLIC_PER_MIN = 300

# --- quote check --------------------------------------------------------------
FETCH_TIMEOUT_S = 10.0
FETCH_MAX_BYTES = 3 * 1024 * 1024
FETCH_MAX_REDIRECTS = 3
FETCH_CACHE_TTL_S = 3600
QUOTE_MIN_CHARS = 20
QUOTE_MAX_CHARS = 600
PRECHECK_WORKERS = 6  # concurrent quote checks per submission
PRECHECK_DEADLINE_S = 60.0  # checks unfinished by then soft-fail as "timeout" (claim stays T0)
MAX_EXTRACT_CLAIMS = 30  # claims per map.extract submission
AMBIGUOUS_QUOTE_MIN_NUMBERS = 2  # ≥ this many same-format numbers in a quote → claim flagged "ambiguous_quote"
AMBIGUOUS_QUOTE_REQUIRE_NOTES_AT = 3  # ≥ this many (table row) → conditions.notes required, else the claim is dropped

# --- GitHub identity (required for verify.* work) -----------------------------
GITHUB_API_HOST = "api.github.com"  # the only host the GitHub client ever talks to
GITHUB_MIN_AGE_DAYS = 90
GITHUB_CHALLENGE_TTL_S = 3600
GITHUB_TIMEOUT_S = 10.0
GITHUB_MAX_BYTES = 2 * 1024 * 1024


DEV_STEWARD_KEY = "dev-steward"  # public, documented default: local development only
DEFAULT_IP_SALT = "agentdao-ip-v1"  # public default: set SIDAO_IP_SALT (or AGENTDAO_IP_SALT) to a secret in production
MIN_STEWARD_KEY_CHARS = 24
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# --- submissions ----------------------------------------------------------------
# tokens_estimate is self-reported by the agent; clamp it to a plausible per-task bound.
TOKENS_ESTIMATE_MAX = 5_000_000
TOKENS_PER_BUDGET_MINUTE_MAX = 100_000

# --- env vars -----------------------------------------------------------------
ENV_PREFIX = "SIDAO_"  # Super Intelligence DAO
LEGACY_ENV_PREFIX = "AGENTDAO_"  # backward-compatible fallback (production still sets these)


def _env(name: str, default: str = "") -> str:
    """Read SIDAO_<name>, falling back to legacy AGENTDAO_<name>, then `default`."""
    for key in (ENV_PREFIX + name, LEGACY_ENV_PREFIX + name):
        val = os.environ.get(key)
        if val is not None:
            return val
    return default


@dataclass
class Settings:
    """Runtime settings, resolved from env at app/CLI start (tests pass explicit values).

    Each field reads SIDAO_<NAME>, falling back to the legacy AGENTDAO_<NAME> (see `_env`).
    """

    db_path: str = field(default_factory=lambda: _env("DB", str(REPO_ROOT / "data" / "agentdao.db")))
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", "http://localhost:8787").rstrip("/"))
    steward_key: str = field(default_factory=lambda: _env("STEWARD_KEY", DEV_STEWARD_KEY))
    web_dir: Path = REPO_ROOT / "web"
    agent_dir: Path = REPO_ROOT / "agent"
    seed_dir: Path = REPO_ROOT / "seed"
    rate_agent_per_min: int = RATE_AGENT_PER_MIN
    rate_public_per_min: int = RATE_PUBLIC_PER_MIN
    # Dev/test only: let the quote checker fetch http://localhost|127.0.0.1|[::1] sources (scripts/sim_agent.py fixtures).
    allow_local_sources: bool = field(default_factory=lambda: _env("ALLOW_LOCAL_SOURCES") == "1")
    # Dev/test only: let contributors registered from the same IP verify each other (sim agents share one machine).
    # Also implied by allow_local_sources. Never set in production.
    dev_allow_same_ip: bool = field(default_factory=lambda: _env("DEV_ALLOW_SAME_IP") == "1")
    # Salt for contributors.registered_ip_hash (keep it stable; changing it breaks same-IP matching for old accounts).
    ip_salt: str = field(default_factory=lambda: _env("IP_SALT", DEFAULT_IP_SALT))
    # Minimum GitHub account age for linking (verify.* tasks need a linked account).
    github_min_age_days: int = field(default_factory=lambda: int(_env("GITHUB_MIN_AGE_DAYS") or GITHUB_MIN_AGE_DAYS))
    # Optional: only raises GitHub API rate limits (60/h unauthenticated → 5000/h). Never sent anywhere else.
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""), repr=False)

    @property
    def same_ip_verify_allowed(self) -> bool:
        return self.dev_allow_same_ip or self.allow_local_sources

    @property
    def github_required_for_verify(self) -> bool:
        """Dev flags (sim agents) also skip the linked-GitHub requirement; both refuse a public bind."""
        return not self.same_ip_verify_allowed


def render_agent_file(settings: Settings, rel: str) -> str | None:
    """agent/<rel> with {{BASE_URL}}/{{SKILL_VERSION}}/{{SITE_NAME}} filled in; None if missing (or outside agent_dir)."""
    path = (settings.agent_dir / rel).resolve()
    if not path.is_relative_to(settings.agent_dir.resolve()) or not path.is_file():
        return None
    return (path.read_text(encoding="utf-8")
            .replace("{{BASE_URL}}", settings.public_url)
            .replace("{{SKILL_VERSION}}", SKILL_VERSION)
            .replace("{{SITE_NAME}}", SITE_NAME))


def skill_sha256(settings: Settings) -> str | None:
    """sha256 of the rendered join.md, as served by /skill-version and pinned by claims (`skill_sha256`)."""
    text = render_agent_file(settings, "join.md")
    return hashlib.sha256(text.encode()).hexdigest() if text is not None else None


def unsafe_for_public_bind(settings: Settings, host: str) -> list[str]:
    """Reasons this configuration must not listen on a non-loopback interface (empty = OK)."""
    if host in LOOPBACK_HOSTS:
        return []
    problems = []
    if settings.steward_key == DEV_STEWARD_KEY or len(settings.steward_key or "") < MIN_STEWARD_KEY_CHARS:
        problems.append(f"SIDAO_STEWARD_KEY (alias AGENTDAO_STEWARD_KEY) is the dev default or shorter than {MIN_STEWARD_KEY_CHARS} chars "
                        "(generate one: python3 -c 'import secrets;print(secrets.token_urlsafe(32))')")
    if settings.allow_local_sources:
        problems.append("SIDAO_ALLOW_LOCAL_SOURCES=1 (alias AGENTDAO_ALLOW_LOCAL_SOURCES) is a dev/test-only SSRF escape hatch")
    if settings.dev_allow_same_ip:
        problems.append("SIDAO_DEV_ALLOW_SAME_IP=1 (alias AGENTDAO_DEV_ALLOW_SAME_IP) disables the same-IP self-verification block and the "
                        "GitHub requirement for verify tasks (dev only)")
    return problems
