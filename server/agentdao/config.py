"""Central configuration. Everything tunable lives here; env vars override defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SITE_NAME = "Super Intelligence DAO"  # rename here only
SKILL_VERSION = "0.1.1"  # bump when join.md semantics change
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
]
TASK_STATUSES = [
    "draft", "open", "leased", "submitted", "verifying",
    "verified", "rejected", "disputed", "needs_steward", "closed",
]
TERMINAL_TASK_STATUSES = ("verified", "rejected", "closed")
RELEASE_REASONS = ["quota", "gave_up", "error", "unsafe", "conflict"]
FREE_RELEASE_REASONS = ("quota", "unsafe", "conflict")  # don't count as an attempt
RELEASE_COOLDOWN_S = 24 * 3600  # a task you released is not re-offered to you for this long

DEFAULT_BUDGET_MINUTES = {
    "map.extract": 30, "map.profile": 15, "map.gap_scan": 45,
    "verify.blind_extract": 15, "verify.review": 15,
    "rnd.harness_layer": 120, "bench.task_draft": 90,
}

# --- credits ----------------------------------------------------------------
CREDITS = {
    "claim_reproduced": 10,
    "verify_agreed": 4,
    "verify_review": 2,
    "gap_accepted": 8,
    "dispute_resolved": 6,
}

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
TASKGEN_MAX_BLIND_PER_RUN = 25

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
AMBIGUOUS_QUOTE_MIN_NUMBERS = 3  # ≥ this many same-format numbers in a quote → "ambiguous_quote" (table row)

# --- GitHub identity (required for verify.* work) -----------------------------
GITHUB_API_HOST = "api.github.com"  # the only host the GitHub client ever talks to
GITHUB_MIN_AGE_DAYS = 90
GITHUB_CHALLENGE_TTL_S = 3600
GITHUB_TIMEOUT_S = 10.0
GITHUB_MAX_BYTES = 2 * 1024 * 1024


DEV_STEWARD_KEY = "dev-steward"  # public, documented default: local development only
MIN_STEWARD_KEY_CHARS = 24
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass
class Settings:
    """Runtime settings, resolved from env at app/CLI start (tests pass explicit values)."""

    db_path: str = field(default_factory=lambda: os.environ.get("AGENTDAO_DB", str(REPO_ROOT / "data" / "agentdao.db")))
    public_url: str = field(default_factory=lambda: os.environ.get("AGENTDAO_PUBLIC_URL", "http://localhost:8787").rstrip("/"))
    steward_key: str = field(default_factory=lambda: os.environ.get("AGENTDAO_STEWARD_KEY", DEV_STEWARD_KEY))
    web_dir: Path = REPO_ROOT / "web"
    agent_dir: Path = REPO_ROOT / "agent"
    seed_dir: Path = REPO_ROOT / "seed"
    rate_agent_per_min: int = RATE_AGENT_PER_MIN
    rate_public_per_min: int = RATE_PUBLIC_PER_MIN
    # Dev/test only: let the quote checker fetch http://localhost|127.0.0.1|[::1] sources (scripts/sim_agent.py fixtures).
    allow_local_sources: bool = field(default_factory=lambda: os.environ.get("AGENTDAO_ALLOW_LOCAL_SOURCES", "") == "1")
    # Dev/test only: let contributors registered from the same IP verify each other (sim agents share one machine).
    # Also implied by allow_local_sources. Never set in production.
    dev_allow_same_ip: bool = field(default_factory=lambda: os.environ.get("AGENTDAO_DEV_ALLOW_SAME_IP", "") == "1")
    # Salt for contributors.registered_ip_hash (keep it stable; changing it breaks same-IP matching for old accounts).
    ip_salt: str = field(default_factory=lambda: os.environ.get("AGENTDAO_IP_SALT", "agentdao-ip-v1"))
    # Minimum GitHub account age for linking (verify.* tasks need a linked account).
    github_min_age_days: int = field(default_factory=lambda: int(os.environ.get("AGENTDAO_GITHUB_MIN_AGE_DAYS")
                                                                 or GITHUB_MIN_AGE_DAYS))
    # Optional: only raises GitHub API rate limits (60/h unauthenticated → 5000/h). Never sent anywhere else.
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""), repr=False)

    @property
    def same_ip_verify_allowed(self) -> bool:
        return self.dev_allow_same_ip or self.allow_local_sources

    @property
    def github_required_for_verify(self) -> bool:
        """Dev flags (sim agents) also skip the linked-GitHub requirement; both refuse a public bind."""
        return not self.same_ip_verify_allowed


def unsafe_for_public_bind(settings: Settings, host: str) -> list[str]:
    """Reasons this configuration must not listen on a non-loopback interface (empty = OK)."""
    if host in LOOPBACK_HOSTS:
        return []
    problems = []
    if settings.steward_key == DEV_STEWARD_KEY or len(settings.steward_key or "") < MIN_STEWARD_KEY_CHARS:
        problems.append(f"AGENTDAO_STEWARD_KEY is the dev default or shorter than {MIN_STEWARD_KEY_CHARS} chars "
                        "(generate one: python3 -c 'import secrets;print(secrets.token_urlsafe(32))')")
    if settings.allow_local_sources:
        problems.append("AGENTDAO_ALLOW_LOCAL_SOURCES=1 is a dev/test-only SSRF escape hatch")
    if settings.dev_allow_same_ip:
        problems.append("AGENTDAO_DEV_ALLOW_SAME_IP=1 disables the same-IP self-verification block and the "
                        "GitHub requirement for verify tasks (dev only)")
    return problems
