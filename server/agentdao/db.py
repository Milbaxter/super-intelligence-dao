"""Thin stdlib sqlite3 layer: connections, transactions, ids, time, JSON helpers.

Connections run in autocommit mode (`isolation_level=None`); writes are grouped with
`tx(conn)`, which takes the write lock up front (BEGIN IMMEDIATE) so read-then-write
sequences such as "pick a task, then lease it" are race-free across threads/processes.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"

# Overridable clock (tests monkeypatch `db.utcnow`).
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ts() -> str:
    return ts(utcnow())


def ts_in(seconds: float = 0, days: float = 0) -> str:
    return ts(utcnow() + timedelta(seconds=seconds, days=days))


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def new_id(prefix: str, n: int = 8) -> str:
    return f"{prefix}_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(n))


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(path: str) -> None:
    """Create missing tables/indexes (schema.sql), then apply pending numbered migrations."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)
    finally:
        conn.close()


# ----------------------------------------------------------------------------------------------------------------
# Numbered migrations, tracked by `PRAGMA user_version` (0 = none applied; N = MIGRATIONS[:N] applied).
#
# schema.sql always describes the *current* full schema and runs first (CREATE ... IF NOT EXISTS), so a fresh DB
# already has every column; migrations exist to bring *old* DBs up to date. Every migration must therefore also be
# safe on a fresh DB (use `_add_column`, which skips columns that already exist).
#
# To add one:
#   1. Update schema.sql to the new shape (for fresh DBs). Don't put indexes on brand-new columns there: on an old
#      DB schema.sql runs before the column exists. Create such indexes in the migration instead.
#   2. Write `def _m00N_short_name(conn)` below and APPEND it to MIGRATIONS. Append, never edit, reorder or remove
#      a shipped migration: deployed DBs have already recorded it as applied and will never run it again.
#   3. Use only `conn.execute(...)`, never `conn.executescript(...)` (it COMMITs, breaking the per-migration
#      transaction). Each migration runs once, inside BEGIN IMMEDIATE, together with its user_version bump.
# ----------------------------------------------------------------------------------------------------------------


def _add_column(conn: sqlite3.Connection, table: str, col: str, typ: str) -> None:
    """ALTER TABLE ... ADD COLUMN unless the column already exists (fresh DBs get it from schema.sql)."""
    if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def _m001_post_release_columns(conn: sqlite3.Connection) -> None:
    """Baseline = the pre-versioning `_migrate`: columns added after the first release, person backfill, GitHub index.
    Production DBs that ran the old `_migrate` already have all of this at user_version 0, so it is idempotent."""
    for table, col, typ in [
        ("contributors", "registered_ip_hash", "TEXT"),
        ("leases", "released_at", "TEXT"),
        ("leases", "release_reason", "TEXT"),
        ("contributors", "person", "TEXT"),
        ("contributors", "github_login", "TEXT"),
        ("contributors", "github_id", "INTEGER"),
        ("contributors", "github_created_at", "TEXT"),
        ("contributors", "github_linked_at", "TEXT"),
        ("contributors", "github_challenge", "TEXT"),
        ("contributors", "github_challenge_at", "TEXT"),
        ("invites", "person", "TEXT"),
    ]:
        _add_column(conn, table, col, typ)
    # Pre-existing contributors/invites: each gets its own person id (= separate people, as before person labels).
    for table in ("contributors", "invites"):
        conn.execute(f"UPDATE {table} SET person = 'p_' || lower(hex(randomblob(6))) WHERE person IS NULL")
    # One GitHub account links to at most one contributor (ALTER TABLE can't add UNIQUE, so a partial index).
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_contributors_github_id ON contributors(github_id) "
                 "WHERE github_id IS NOT NULL")


# Append-only. MIGRATIONS[i] takes a DB from user_version i to i + 1.
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _m001_post_release_columns,
]
SCHEMA_VERSION = len(MIGRATIONS)


def user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _migrate(conn: sqlite3.Connection) -> None:
    # A DB newer than this code (rollback deploy) is left alone: migrations are additive, so old code still runs.
    for version in range(user_version(conn) + 1, SCHEMA_VERSION + 1):
        with tx(conn):
            if user_version(conn) >= version:  # another process applied it while we waited for the write lock
                continue
            MIGRATIONS[version - 1](conn)
            conn.execute(f"PRAGMA user_version = {version}")


def reset_db(path: str) -> None:
    """Delete all data (used by `agentdao seed --reset`)."""
    for suffix in ("", "-wal", "-shm"):
        p = Path(path + suffix)
        if p.exists():
            p.unlink()
    init_db(path)


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Write transaction. Nested use is allowed (inner blocks join the outer one)."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def one(conn: sqlite3.Connection, sql: str, params: Any = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def all_(conn: sqlite3.Connection, sql: str, params: Any = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def scalar(conn: sqlite3.Connection, sql: str, params: Any = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def insert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    cols = list(row)
    vals = [jdump(v) if isinstance(v, (dict, list)) else v for v in row.values()]
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", vals
    )


def update(conn: sqlite3.Connection, table: str, id_: str, fields: dict) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = [jdump(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*vals, id_])


def jdump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def jload(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
