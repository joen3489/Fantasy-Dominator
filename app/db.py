from __future__ import annotations

import sqlite3
import json
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

            CREATE TABLE IF NOT EXISTS team_profiles (
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                roster_id INTEGER,
                season TEXT NOT NULL,
                team_name TEXT,
                display_name TEXT,
                strategy_name TEXT,
                team_direction TEXT,
                contention_window TEXT,
                strategy_json TEXT NOT NULL DEFAULT '{}',
                writer_preferences_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT,
                PRIMARY KEY(user_id, league_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS content_artifacts (
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                season TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_key TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'generated',
                source_json TEXT NOT NULL DEFAULT '{}',
                generated_at TEXT,
                updated_at TEXT,
                PRIMARY KEY(user_id, league_id, season, artifact_type, artifact_key),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS refresh_runs (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                season TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
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


def get_user_league(user_id: int, league_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
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


def upsert_team_profile(user_id: int, league_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Persist customization that belongs to one user's team in one league."""

    strategy = profile.get("strategy_profile", profile.get("strategy", {}))
    writer_preferences = profile.get("writer_preferences", {})
    if not isinstance(strategy, dict):
        strategy = {}
    if not isinstance(writer_preferences, dict):
        writer_preferences = {}
    if profile.get("strategy_name"):
        strategy.setdefault("name", profile["strategy_name"])
    if profile.get("team_direction"):
        strategy.setdefault("team_direction", profile["team_direction"])
    if profile.get("contention_window"):
        strategy.setdefault("contention_window", profile["contention_window"])
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO team_profiles(
                user_id, league_id, roster_id, season, team_name, display_name,
                strategy_name, team_direction, contention_window, strategy_json,
                writer_preferences_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, league_id) DO UPDATE SET
                roster_id = excluded.roster_id,
                season = excluded.season,
                team_name = excluded.team_name,
                display_name = excluded.display_name,
                strategy_name = excluded.strategy_name,
                team_direction = excluded.team_direction,
                contention_window = excluded.contention_window,
                strategy_json = excluded.strategy_json,
                writer_preferences_json = excluded.writer_preferences_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                str(league_id),
                profile.get("roster_id"),
                str(profile.get("season") or ""),
                str(profile.get("team_name") or ""),
                str(profile.get("display_name") or ""),
                str(profile.get("strategy_name") or strategy.get("name") or ""),
                str(profile.get("team_direction") or strategy.get("team_direction") or ""),
                str(profile.get("contention_window") or strategy.get("contention_window") or ""),
                json.dumps(strategy, sort_keys=True),
                json.dumps(writer_preferences, sort_keys=True),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    result = get_team_profile(user_id, str(league_id))
    if result is None:
        raise RuntimeError("team profile upsert failed")
    return result


def get_team_profile(user_id: int, league_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT user_id, league_id, roster_id, season, team_name, display_name,
                   strategy_name, team_direction, contention_window, strategy_json,
                   writer_preferences_json, updated_at
            FROM team_profiles
            WHERE user_id = ? AND league_id = ?
            """,
            (user_id, str(league_id)),
        ).fetchone()
        if row is None:
            return None
        result = _row(row)
        result["strategy_profile"] = _decode_json(result.pop("strategy_json", "{}"))
        result["writer_preferences"] = _decode_json(
            result.pop("writer_preferences_json", "{}")
        )
        return result
    finally:
        conn.close()


def migrate_legacy_team_profile(
    user_id: int,
    league: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Idempotently copy the old single-team YAML settings into one scope."""

    league_id = str(league.get("league_id") or "")
    existing = get_team_profile(user_id, league_id)
    if existing is not None:
        return existing

    current_team = config.get("current_team") or {}
    configured_roster_id = current_team.get("roster_id")
    league_roster_id = league.get("roster_id")
    if configured_roster_id not in (None, "") and league_roster_id not in (None, ""):
        if str(configured_roster_id) != str(league_roster_id):
            return None

    strategy = config.get("strategy_profile") or {}
    return upsert_team_profile(
        user_id,
        league_id,
        {
            "roster_id": league_roster_id or configured_roster_id,
            "season": league.get("season") or config.get("current_season") or "",
            "team_name": current_team.get("team_name") or "",
            "display_name": current_team.get("display_name") or "",
            "strategy_profile": strategy if isinstance(strategy, dict) else {},
            "writer_preferences": {},
        },
    )


def record_content_artifact(
    user_id: int,
    league_id: str,
    season: str,
    artifact_type: str,
    artifact_key: str,
    path: str,
    source: dict[str, Any] | None = None,
    status: str = "generated",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO content_artifacts(
                user_id, league_id, season, artifact_type, artifact_key, path,
                status, source_json, generated_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, league_id, season, artifact_type, artifact_key) DO UPDATE SET
                path = excluded.path,
                status = excluded.status,
                source_json = excluded.source_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                str(league_id),
                str(season),
                str(artifact_type),
                str(artifact_key),
                str(path),
                str(status),
                json.dumps(source or {}, sort_keys=True),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def start_refresh_run(user_id: int, league_id: str, season: str) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO refresh_runs(user_id, league_id, season, status, started_at)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (user_id, str(league_id), str(season), started_at),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def finish_refresh_run(
    run_id: int,
    status: str,
    error: str | None = None,
) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE refresh_runs
            SET status = ?, finished_at = ?, error = ?
            WHERE id = ?
            """,
            (str(status), datetime.now(timezone.utc).isoformat(), error, run_id),
        )
        conn.commit()
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


def latest_refresh_run(user_id: int, league_id: str) -> dict[str, Any] | None:
    """Return the latest durable refresh receipt for one user's league."""

    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, user_id, league_id, season, status, started_at, finished_at, error
            FROM refresh_runs
            WHERE user_id = ? AND league_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, str(league_id)),
        ).fetchone()
        return _row(row) if row is not None else None
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


def _decode_json(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
