from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import DATA_DIR


DB_PATH = DATA_DIR / "app.db"


def init_db(path: Path | None = None) -> None:
    conn = _connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                clerk_user_id TEXT UNIQUE NOT NULL,
                sleeper_username TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_leagues (
                user_id INTEGER,
                league_id TEXT,
                season TEXT,
                league_type TEXT,
                name TEXT,
                roster_id INTEGER,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY(user_id, league_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_or_create_user(clerk_user_id: str) -> dict[str, Any]:
    conn = _connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO users(clerk_user_id, created_at) VALUES (?, ?)",
            (clerk_user_id, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, clerk_user_id, sleeper_username, created_at FROM users WHERE clerk_user_id = ?",
            (clerk_user_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("user provisioning failed")
        return _row(row)
    finally:
        conn.close()


def set_sleeper_username(user_id: int, sleeper_username: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET sleeper_username = ? WHERE id = ?",
            (sleeper_username, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_user_league(user_id: int, entry: dict[str, Any]) -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO user_leagues(user_id, league_id, season, league_type, name, roster_id, enabled)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id, league_id) DO UPDATE SET
                season = excluded.season,
                league_type = excluded.league_type,
                name = excluded.name,
                roster_id = excluded.roster_id
            """,
            (
                user_id,
                str(entry.get("league_id") or ""),
                str(entry.get("season") or ""),
                str(entry.get("league_type") or ""),
                str(entry.get("name") or ""),
                entry.get("roster_id"),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT user_id, league_id, season, league_type, name, roster_id, enabled
            FROM user_leagues
            WHERE user_id = ? AND league_id = ?
            """,
            (user_id, str(entry.get("league_id") or "")),
        ).fetchone()
        if row is None:
            raise RuntimeError("league upsert failed")
        return _row(row)
    finally:
        conn.close()


def list_user_leagues(user_id: int) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT user_id, league_id, season, league_type, name, roster_id, enabled
            FROM user_leagues
            WHERE user_id = ?
            ORDER BY enabled DESC, name COLLATE NOCASE, league_id
            """,
            (user_id,),
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        conn.close()


def list_users_with_sleeper() -> list[dict[str, Any]]:
    """Every user who has linked a Sleeper account -- the scheduler's refresh population."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, clerk_user_id, sleeper_username, created_at
            FROM users
            WHERE sleeper_username IS NOT NULL AND sleeper_username != ''
            ORDER BY id
            """
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        conn.close()


def toggle_league(user_id: int, league_id: str, enabled: bool | None = None) -> dict[str, Any] | None:
    conn = _connect()
    try:
        current = conn.execute(
            """
            SELECT user_id, league_id, season, league_type, name, roster_id, enabled
            FROM user_leagues
            WHERE user_id = ? AND league_id = ?
            """,
            (user_id, str(league_id)),
        ).fetchone()
        if current is None:
            return None
        next_enabled = int(bool(enabled)) if enabled is not None else (0 if int(current["enabled"]) else 1)
        conn.execute(
            "UPDATE user_leagues SET enabled = ? WHERE user_id = ? AND league_id = ?",
            (next_enabled, user_id, str(league_id)),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT user_id, league_id, season, league_type, name, roster_id, enabled
            FROM user_leagues
            WHERE user_id = ? AND league_id = ?
            """,
            (user_id, str(league_id)),
        ).fetchone()
        return _row(row) if row is not None else None
    finally:
        conn.close()


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)
