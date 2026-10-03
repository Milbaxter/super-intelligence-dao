"""Numbered migrations tracked by PRAGMA user_version (db.MIGRATIONS)."""

from __future__ import annotations

import pytest

from agentdao import db

# contributors / invites / leases as first shipped, before any of migration 1's columns.
OLD_SCHEMA = """
CREATE TABLE contributors (id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE, model_family TEXT NOT NULL,
    api_key_hash TEXT NOT NULL UNIQUE, invite_code TEXT, contact TEXT, joined_at TEXT NOT NULL,
    is_steward INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE invites (code TEXT PRIMARY KEY, created_at TEXT NOT NULL, used_by TEXT REFERENCES contributors(id), note TEXT);
CREATE TABLE leases (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, contributor_id TEXT NOT NULL REFERENCES contributors(id),
    model_family TEXT, model TEXT, created_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    hard_deadline TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', progress_note TEXT);
INSERT INTO contributors (id, handle, model_family, api_key_hash, joined_at)
    VALUES ('c_old', 'old-one', 'claude', 'h1', '2026-01-01T00:00:00Z');
INSERT INTO invites (code, created_at, used_by) VALUES ('inv-a', '2026-01-01T00:00:00Z', 'c_old');
INSERT INTO leases (id, task_id, contributor_id, created_at, heartbeat_at, expires_at, hard_deadline)
    VALUES ('l_old', 't_x', 'c_old', 'a', 'b', 'c', 'd');
"""
M1_COLUMNS = {
    "contributors": {"registered_ip_hash", "person", "github_login", "github_id", "github_created_at",
                     "github_linked_at", "github_challenge", "github_challenge_at"},
    "leases": {"released_at", "release_reason"},
    "invites": {"person"},
}


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _snapshot(conn):
    return (db.user_version(conn), conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall(),
            conn.execute("SELECT id, person FROM contributors ORDER BY id").fetchall(),
            conn.execute("SELECT code, person FROM invites ORDER BY code").fetchall())


def _make(path, script):
    c = db.connect(path)
    c.executescript(script)
    c.close()


def _check_m1(conn):
    for table, cols in M1_COLUMNS.items():
        assert cols <= _cols(conn, table), table
    assert db.scalar(conn, "SELECT count(*) FROM sqlite_master WHERE name='ux_contributors_github_id'") == 1


def test_fresh_db_is_at_latest_version(tmp_path):
    path = str(tmp_path / "fresh.db")
    db.init_db(path)
    c = db.connect(path)
    assert db.user_version(c) == db.SCHEMA_VERSION == len(db.MIGRATIONS) >= 1
    _check_m1(c)
    c.close()


def test_old_db_migrates(tmp_path):
    path = str(tmp_path / "old.db")
    _make(path, OLD_SCHEMA)
    db.init_db(path)
    c = db.connect(path)
    assert db.user_version(c) == db.SCHEMA_VERSION
    _check_m1(c)
    persons = [r[0] for r in c.execute("SELECT person FROM contributors UNION ALL SELECT person FROM invites")]
    assert len(persons) == 2 and all(p.startswith("p_") for p in persons)
    assert db.one(c, "SELECT handle FROM contributors")["handle"] == "old-one"
    assert db.one(c, "SELECT released_at FROM leases WHERE id='l_old'") == {"released_at": None}
    c.close()


def test_init_db_twice_is_noop(tmp_path):
    path = str(tmp_path / "old.db")
    _make(path, OLD_SCHEMA)
    db.init_db(path)
    c = db.connect(path)
    before = _snapshot(c)
    c.close()
    db.init_db(path)
    c = db.connect(path)
    assert _snapshot(c) == before
    c.close()


def test_production_db_columns_present_but_version_zero(tmp_path):
    """Prod ran the pre-versioning _migrate: every column + index exists, user_version is still 0."""
    path = str(tmp_path / "prod.db")
    db.init_db(path)
    c = db.connect(path)
    with db.tx(c):
        c.execute("INSERT INTO contributors (id, handle, model_family, api_key_hash, joined_at, person) "
                  "VALUES ('c_1', 'h', 'claude', 'k', '2026-01-01T00:00:00Z', 'op:alice')")
    c.execute("PRAGMA user_version = 0")
    c.close()
    db.init_db(path)
    c = db.connect(path)
    assert db.user_version(c) == db.SCHEMA_VERSION
    _check_m1(c)
    assert db.one(c, "SELECT person FROM contributors WHERE id='c_1'") == {"person": "op:alice"}
    c.close()


def test_later_migrations_run_once_in_order_and_roll_back_on_failure(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    calls = []

    def m_ok(conn):
        calls.append("ok")
        conn.execute("ALTER TABLE layers ADD COLUMN extra TEXT")

    def m_bad(conn):
        conn.execute("ALTER TABLE layers ADD COLUMN doomed TEXT")
        raise RuntimeError("boom")

    base = db.SCHEMA_VERSION
    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, m_ok, m_bad])
    monkeypatch.setattr(db, "SCHEMA_VERSION", base + 2)
    with pytest.raises(RuntimeError, match="boom"):
        db.init_db(path)
    c = db.connect(path)
    assert db.user_version(c) == base + 1  # m_ok committed, m_bad rolled back
    assert "extra" in _cols(c, "layers") and "doomed" not in _cols(c, "layers")
    c.close()

    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS[:-1]])
    monkeypatch.setattr(db, "SCHEMA_VERSION", base + 1)
    db.init_db(path)
    assert calls == ["ok"]  # not re-run


def test_db_newer_than_code_is_left_alone(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    c = db.connect(path)
    c.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    c.close()
    db.init_db(path)  # rollback deploy: no error, no downgrade
    c = db.connect(path)
    assert db.user_version(c) == db.SCHEMA_VERSION + 1
    c.close()


def test_reset_db(tmp_path):
    path = str(tmp_path / "t.db")
    _make(path, OLD_SCHEMA)
    db.reset_db(path)
    c = db.connect(path)
    assert db.user_version(c) == db.SCHEMA_VERSION
    assert db.scalar(c, "SELECT count(*) FROM contributors") == 0
    c.close()
