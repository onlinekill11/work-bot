"""Хранилище на два бэкенда.

- Локально (без DATABASE_URL) — SQLite, файл work.db.
- На хостинге (есть DATABASE_URL) — PostgreSQL (Neon), история переживает
  любые рестарты и передеплои.

Наружу оба бэкенда выглядят одинаково: функции возвращают строки,
у которых поля берутся по имени — row["user_id"].
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from typing import Any, Iterator

from config import DATABASE_URL, DB_PATH

IS_PG = bool(DATABASE_URL)

if IS_PG:  # pragma: no cover - зависит от окружения
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    _pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        max_idle=120,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=True,
    )
else:
    _lock = threading.Lock()
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row


def backend_name() -> str:
    return "PostgreSQL (Neon)" if IS_PG else f"SQLite ({DB_PATH})"


def _q(sql: str) -> str:
    """Плейсхолдеры: пишем '?', для Postgres превращаем в '%s'."""
    return sql.replace("?", "%s") if IS_PG else sql


@contextlib.contextmanager
def _cur() -> Iterator[Any]:
    if IS_PG:  # pragma: no cover
        with _pool.connection() as conn, conn.cursor() as cur:
            yield cur
    else:
        with _lock:
            cur = _conn.cursor()
            try:
                yield cur
                _conn.commit()
            finally:
                cur.close()


def execute(sql: str, params: tuple = ()) -> None:
    """Служебное: выполнить произвольный запрос (используется в тестах)."""
    with _cur() as cur:
        cur.execute(_q(sql), params)


def _fetchone(sql: str, params: tuple = ()) -> Any:
    with _cur() as cur:
        cur.execute(_q(sql), params)
        return cur.fetchone()


def _fetchall(sql: str, params: tuple = ()) -> list[Any]:
    with _cur() as cur:
        cur.execute(_q(sql), params)
        return list(cur.fetchall())


def _insert(sql: str, params: tuple) -> int:
    with _cur() as cur:
        if IS_PG:  # pragma: no cover
            cur.execute(_q(sql) + " RETURNING id", params)
            return int(cur.fetchone()["id"])
        cur.execute(_q(sql), params)
        return int(cur.lastrowid)


# --- схема ----------------------------------------------------------------
_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    full_name  TEXT,
    first_seen INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    started_at    INTEGER NOT NULL,
    accumulated   INTEGER NOT NULL DEFAULT 0,
    running_since INTEGER,
    status        TEXT NOT NULL,
    finished_at   INTEGER,
    msg_id        INTEGER,
    pauses        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    session_id   INTEGER,
    created_at   INTEGER NOT NULL,
    start_bal    REAL,
    end_bal      REAL,
    disputes     REAL,
    profit       REAL,
    percent      REAL,
    percent_pay  REAL,
    hours        REAL,
    has_blocks   INTEGER,
    blocks_text  TEXT,
    fix_pay      REAL,
    total        REAL,
    difficulties TEXT,
    plans        TEXT,
    paid         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_PG_DDL = """
CREATE TABLE IF NOT EXISTS users (
    user_id    BIGINT PRIMARY KEY,
    username   TEXT,
    full_name  TEXT,
    first_seen BIGINT
);
CREATE TABLE IF NOT EXISTS sessions (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    started_at    BIGINT NOT NULL,
    accumulated   BIGINT NOT NULL DEFAULT 0,
    running_since BIGINT,
    status        TEXT NOT NULL,
    finished_at   BIGINT,
    msg_id        BIGINT,
    pauses        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reports (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL,
    session_id   BIGINT,
    created_at   BIGINT NOT NULL,
    start_bal    DOUBLE PRECISION,
    end_bal      DOUBLE PRECISION,
    disputes     DOUBLE PRECISION,
    profit       DOUBLE PRECISION,
    percent      DOUBLE PRECISION,
    percent_pay  DOUBLE PRECISION,
    hours        DOUBLE PRECISION,
    has_blocks   INTEGER,
    blocks_text  TEXT,
    fix_pay      DOUBLE PRECISION,
    total        DOUBLE PRECISION,
    difficulties TEXT,
    plans        TEXT,
    paid         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def init() -> None:
    ddl = _PG_DDL if IS_PG else _SQLITE_DDL
    with _cur() as cur:
        for statement in filter(None, (s.strip() for s in ddl.split(";"))):
            cur.execute(statement)
    _migrate()


def _migrate() -> None:
    """Догоняем схему на уже существующих базах (боевая Neon живёт с первого дня)."""
    _add_column("reports", "blocks_sum", "DOUBLE PRECISION" if IS_PG else "REAL")


def _add_column(table: str, column: str, coltype: str) -> None:
    if IS_PG:  # pragma: no cover
        execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}")
        return
    existing = {r["name"] for r in _fetchall(f"PRAGMA table_info({table})")}
    if column not in existing:
        execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


# --- settings -------------------------------------------------------------
def get_setting(key: str) -> str | None:
    row = _fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )


# --- users ----------------------------------------------------------------
def upsert_user(user_id: int, username: str | None, full_name: str) -> None:
    execute(
        "INSERT INTO users(user_id, username, full_name, first_seen) VALUES(?,?,?,?) "
        "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, "
        "full_name = EXCLUDED.full_name",
        (user_id, username, full_name, int(time.time())),
    )


def get_user(user_id: int) -> Any:
    return _fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))


# --- sessions -------------------------------------------------------------
def active_session(user_id: int) -> Any:
    return _fetchone(
        "SELECT * FROM sessions WHERE user_id = ? AND status IN ('running','paused') "
        "ORDER BY id DESC LIMIT 1",
        (user_id,),
    )


def start_session(user_id: int) -> int:
    now = int(time.time())
    return _insert(
        "INSERT INTO sessions(user_id, started_at, accumulated, running_since, status) "
        "VALUES(?,?,0,?,'running')",
        (user_id, now, now),
    )


def pause_session(session_id: int) -> None:
    now = int(time.time())
    row = get_session(session_id)
    if not row or row["status"] != "running":
        return
    acc = row["accumulated"] + (now - (row["running_since"] or now))
    execute(
        "UPDATE sessions SET accumulated = ?, running_since = NULL, "
        "status = 'paused', pauses = pauses + 1 WHERE id = ?",
        (acc, session_id),
    )


def resume_session(session_id: int) -> None:
    execute(
        "UPDATE sessions SET running_since = ?, status = 'running' "
        "WHERE id = ? AND status = 'paused'",
        (int(time.time()), session_id),
    )


def finish_session(session_id: int) -> int:
    """Завершает смену и возвращает отработанные секунды."""
    now = int(time.time())
    row = get_session(session_id)
    if not row:
        return 0
    acc = row["accumulated"]
    if row["status"] == "running" and row["running_since"]:
        acc += now - row["running_since"]
    execute(
        "UPDATE sessions SET accumulated = ?, running_since = NULL, "
        "status = 'finished', finished_at = ? WHERE id = ?",
        (acc, now, session_id),
    )
    return int(acc)


def set_session_msg(session_id: int, msg_id: int) -> None:
    execute("UPDATE sessions SET msg_id = ? WHERE id = ?", (msg_id, session_id))


def get_session(session_id: int) -> Any:
    return _fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))


def all_live_sessions() -> list[Any]:
    return _fetchall("SELECT * FROM sessions WHERE status IN ('running','paused')")


def elapsed_seconds(row: Any) -> int:
    acc = row["accumulated"]
    if row["status"] == "running" and row["running_since"]:
        acc += int(time.time()) - row["running_since"]
    return int(acc)


# --- reports --------------------------------------------------------------
_REPORT_FIELDS = (
    "user_id", "session_id", "created_at", "start_bal", "end_bal", "disputes",
    "profit", "percent", "percent_pay", "hours", "has_blocks", "blocks_text",
    "fix_pay", "total", "difficulties", "plans", "blocks_sum",
)


def save_report(data: dict[str, Any]) -> int:
    columns = ", ".join(_REPORT_FIELDS)
    placeholders = ", ".join("?" for _ in _REPORT_FIELDS)
    return _insert(
        "INSERT INTO reports(" + columns + ") VALUES(" + placeholders + ")",
        tuple(data.get(k) for k in _REPORT_FIELDS),
    )


def mark_paid(report_id: int) -> None:
    execute("UPDATE reports SET paid = 1 WHERE id = ?", (report_id,))


def get_report(report_id: int) -> Any:
    return _fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))


def user_reports(user_id: int, limit: int = 10) -> list[Any]:
    return _fetchall(
        "SELECT * FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )


def user_stats(user_id: int) -> Any:
    return _fetchone(
        "SELECT COUNT(*) AS days, COALESCE(SUM(hours),0) AS hours, "
        "COALESCE(SUM(profit),0) AS profit, COALESCE(SUM(total),0) AS total "
        "FROM reports WHERE user_id = ?",
        (user_id,),
    )


def last_reports(limit: int = 15) -> list[Any]:
    return _fetchall(
        "SELECT r.*, u.username, u.full_name FROM reports r "
        "LEFT JOIN users u ON u.user_id = r.user_id "
        "ORDER BY r.id DESC LIMIT ?",
        (limit,),
    )
