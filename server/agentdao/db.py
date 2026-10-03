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
from typing import Any, Iterator

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
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)
    finally:
        conn.close()


# Columns added after the first release: (table, column, type). CREATE TABLE IF NOT EXISTS won't add them to old DBs.
_ADDED_COLUMNS = [
    ("contributors", "registered_ip_hash", "TEXT"),
    ("leases", "released_at", "TEXT"),
    ("leases", "release_reason", "TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, typ in _ADDED_COLUMNS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


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
