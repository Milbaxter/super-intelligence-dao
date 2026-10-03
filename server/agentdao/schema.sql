-- Super Intelligence DAO schema (CONTRACT §4). Timestamps are ISO-8601 UTC strings "YYYY-MM-DDTHH:MM:SSZ",
-- which sort lexicographically. JSON columns hold JSON text.

CREATE TABLE IF NOT EXISTS contributors (
    id            TEXT PRIMARY KEY,
    handle        TEXT NOT NULL UNIQUE,
    model_family  TEXT NOT NULL,
    api_key_hash  TEXT NOT NULL UNIQUE,
    invite_code   TEXT,
    registered_ip_hash TEXT,
    person        TEXT,                 -- operator label inherited from the invite (never public)
    github_login  TEXT,
    github_id     INTEGER,
    github_created_at TEXT,
    github_linked_at  TEXT,
    github_challenge  TEXT,
    github_challenge_at TEXT,
    contact       TEXT,
    joined_at     TEXT NOT NULL,
    is_steward    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS invites (
    code        TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    used_by     TEXT REFERENCES contributors(id),
    note        TEXT,
    person      TEXT                    -- operator label; codes minted in one call share it
);

CREATE TABLE IF NOT EXISTS layers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS artifacts (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    layer               TEXT NOT NULL REFERENCES layers(id),
    kind                TEXT NOT NULL,
    url                 TEXT,
    repo_url            TEXT,
    license             TEXT,
    description         TEXT,
    latest_version      TEXT,
    latest_release_date TEXT,
    homepage            TEXT,
    open_weights        INTEGER,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'seed'
);
CREATE INDEX IF NOT EXISTS ix_artifacts_layer ON artifacts(layer);

CREATE TABLE IF NOT EXISTS benchmarks (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    layer       TEXT,
    url         TEXT,
    description TEXT,
    measures    TEXT,
    saturated   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    lease_id        TEXT REFERENCES leases(id),
    contributor_id  TEXT NOT NULL REFERENCES contributors(id),
    model_family    TEXT,
    model           TEXT,
    payload         TEXT NOT NULL,
    tokens_estimate INTEGER NOT NULL DEFAULT 0,
    minutes_spent   REAL NOT NULL DEFAULT 0,
    notes           TEXT,
    checks          TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_submissions_task ON submissions(task_id);
CREATE INDEX IF NOT EXISTS ix_submissions_contrib ON submissions(contributor_id);

CREATE TABLE IF NOT EXISTS claims (
    id               TEXT PRIMARY KEY,
    artifact_id      TEXT NOT NULL REFERENCES artifacts(id),
    benchmark_id     TEXT NOT NULL REFERENCES benchmarks(id),
    metric           TEXT NOT NULL,
    value            REAL NOT NULL,
    unit             TEXT,
    higher_is_better INTEGER NOT NULL DEFAULT 1,
    conditions       TEXT NOT NULL DEFAULT '{}',
    source_url       TEXT NOT NULL,
    quote            TEXT,
    reported_by      TEXT,
    tier             TEXT NOT NULL DEFAULT 'reported',
    special_status   TEXT,
    created_at       TEXT NOT NULL,
    tier_changed_at  TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    submission_id    TEXT REFERENCES submissions(id),
    check_result     TEXT,
    seed             INTEGER NOT NULL DEFAULT 0,
    retrieved_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_claims_artifact ON claims(artifact_id);
CREATE INDEX IF NOT EXISTS ix_claims_benchmark ON claims(benchmark_id);

CREATE TABLE IF NOT EXISTS gaps (
    id            TEXT PRIMARY KEY,
    layer         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    evidence_urls TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'proposed',
    created_by    TEXT,
    created_at    TEXT NOT NULL,
    task_ids      TEXT NOT NULL DEFAULT '[]',
    submission_id TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    workstream   TEXT NOT NULL,
    phase        TEXT NOT NULL,
    summary      TEXT,
    why          TEXT,
    verification TEXT,
    weight       INTEGER NOT NULL DEFAULT 3,
    sort         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id                     TEXT PRIMARY KEY,
    type                   TEXT NOT NULL,
    track_id               TEXT,
    title                  TEXT NOT NULL,
    spec_md                TEXT,
    inputs                 TEXT NOT NULL DEFAULT '{}',
    allowed_model_families TEXT NOT NULL DEFAULT '["any"]',
    budget_minutes         INTEGER NOT NULL DEFAULT 30,
    status                 TEXT NOT NULL DEFAULT 'open',
    priority               REAL NOT NULL DEFAULT 1,
    attempts               INTEGER NOT NULL DEFAULT 0,
    max_attempts           INTEGER NOT NULL DEFAULT 3,
    parent_submission_id   TEXT,
    target_claim_id        TEXT,
    created_by             TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS ix_tasks_claim ON tasks(target_claim_id);

CREATE TABLE IF NOT EXISTS leases (
    id             TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    contributor_id TEXT NOT NULL REFERENCES contributors(id),
    model_family   TEXT,
    model          TEXT,
    created_at     TEXT NOT NULL,
    heartbeat_at   TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    hard_deadline  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    progress_note  TEXT,
    released_at    TEXT,
    release_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_leases_status ON leases(status, expires_at);
CREATE INDEX IF NOT EXISTS ix_leases_contrib ON leases(contributor_id);

CREATE TABLE IF NOT EXISTS verifications (
    id                     TEXT PRIMARY KEY,
    submission_id          TEXT REFERENCES submissions(id),
    claim_id               TEXT REFERENCES claims(id),
    verifier_submission_id TEXT REFERENCES submissions(id),
    verdict                TEXT NOT NULL,
    detail                 TEXT NOT NULL DEFAULT '{}',
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    contributor_id TEXT NOT NULL REFERENCES contributors(id),
    kind           TEXT NOT NULL,
    amount         INTEGER NOT NULL,
    ref_type       TEXT,
    ref_id         TEXT,
    ts             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_contrib ON ledger(contributor_id);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    actor_handle TEXT,
    summary      TEXT NOT NULL,
    ref_type     TEXT,
    ref_id       TEXT,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ref ON events(ref_type, ref_id);
