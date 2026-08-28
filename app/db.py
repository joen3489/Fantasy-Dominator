from __future__ import annotations

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.personas import normalize_writer_preferences
from src.utils import DATA_DIR


DB_PATH = DATA_DIR / "app.db"

REQUIRED_TABLES = {
    "users",
    "user_leagues",
    "team_profiles",
    "manager_trade_profiles",
    "content_artifacts",
    "content_artifact_history",
    "content_interactions",
    "refresh_runs",
    "edition_runs",
    "edition_jobs",
    "publication_edges",
    "newsroom_workers",
}


def init_db(path: Path | None = None) -> None:
    conn = _connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                clerk_user_id TEXT UNIQUE NOT NULL,
                sleeper_username TEXT,
                sleeper_user_id TEXT,
                selected_league_id TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_leagues (
                user_id INTEGER,
                league_id TEXT,
                season TEXT,
                league_type TEXT,
                name TEXT,
                roster_id INTEGER,
                identity_status TEXT NOT NULL DEFAULT 'unverified',
                identity_checked_at TEXT,
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

            CREATE TABLE IF NOT EXISTS manager_trade_profiles (
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                roster_id INTEGER NOT NULL,
                manager_name TEXT NOT NULL DEFAULT '',
                trade_style TEXT NOT NULL DEFAULT '',
                preferred_assets TEXT NOT NULL DEFAULT '',
                protected_assets TEXT NOT NULL DEFAULT '',
                editor_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT,
                PRIMARY KEY(user_id, league_id, roster_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS content_artifacts (
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                season TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_key TEXT NOT NULL,
                article_id TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '',
                roster_id INTEGER,
                path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'generated',
                source_json TEXT NOT NULL DEFAULT '{}',
                source_receipt_json TEXT NOT NULL DEFAULT '{}',
                generation_metadata_json TEXT NOT NULL DEFAULT '{}',
                generated_at TEXT,
                updated_at TEXT,
                evidence_fingerprint TEXT NOT NULL DEFAULT '',
                bundle_revision TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                reporter_id TEXT NOT NULL DEFAULT '',
                writer_mode TEXT NOT NULL DEFAULT '',
                fallback_reason TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS content_interactions (
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                roster_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_key TEXT NOT NULL,
                interaction_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, league_id, roster_id, artifact_type, artifact_key, interaction_type),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS content_artifact_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                season TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_key TEXT NOT NULL,
                roster_id INTEGER,
                status TEXT NOT NULL,
                evidence_fingerprint TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                reporter_id TEXT NOT NULL DEFAULT '',
                writer_mode TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                fallback_reason TEXT NOT NULL DEFAULT '',
                source_receipt_json TEXT NOT NULL DEFAULT '{}',
                generation_metadata_json TEXT NOT NULL DEFAULT '{}',
                change_type TEXT NOT NULL DEFAULT 'updated',
                recorded_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS edition_runs (
                run_id TEXT PRIMARY KEY,
                operator_run_id TEXT NOT NULL DEFAULT '',
                user_id INTEGER NOT NULL,
                league_id TEXT NOT NULL,
                season TEXT NOT NULL,
                roster_id INTEGER,
                requested_article_keys_json TEXT NOT NULL DEFAULT '[]',
                state TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT 'queued',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                last_heartbeat_at TEXT,
                lease_until TEXT,
                worker_id TEXT NOT NULL DEFAULT '',
                bundle_revision TEXT NOT NULL DEFAULT '',
                completed_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 2,
                cancel_requested_at TEXT,
                edition_fingerprint TEXT NOT NULL DEFAULT '',
                source_receipt_json TEXT NOT NULL DEFAULT '{}',
                failure_class TEXT NOT NULL DEFAULT '',
                failure_message TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS edition_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                article_key TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT 'writer',
                state TEXT NOT NULL DEFAULT 'queued',
                attempt INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                evidence_fingerprint TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                lease_until TEXT,
                worker_id TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                reasoning_effort TEXT NOT NULL DEFAULT '',
                provider_request_id TEXT NOT NULL DEFAULT '',
                client_request_id TEXT NOT NULL DEFAULT '',
                usage_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                error_class TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                UNIQUE(run_id, article_key, phase),
                FOREIGN KEY(run_id) REFERENCES edition_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS publication_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_article_key TEXT NOT NULL,
                target_article_key TEXT NOT NULL,
                relationship TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                source_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'visible',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, source_article_key, target_article_key, relationship),
                FOREIGN KEY(run_id) REFERENCES edition_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS newsroom_workers (
                worker_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                last_heartbeat_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'idle',
                run_id TEXT NOT NULL DEFAULT ''
            );
            """
        )
        _ensure_column(conn, "users", "sleeper_user_id", "TEXT")
        _ensure_column(conn, "users", "selected_league_id", "TEXT")
        _ensure_column(conn, "user_leagues", "identity_status", "TEXT NOT NULL DEFAULT 'unverified'")
        _ensure_column(conn, "user_leagues", "identity_checked_at", "TEXT")
        for column, definition in (
            ("lease_until", "TEXT"),
            ("worker_id", "TEXT NOT NULL DEFAULT ''"),
            ("max_attempts", "INTEGER NOT NULL DEFAULT 2"),
            ("cancel_requested_at", "TEXT"),
            ("edition_fingerprint", "TEXT NOT NULL DEFAULT ''"),
            ("source_receipt_json", "TEXT NOT NULL DEFAULT '{}'"),
        ):
            _ensure_column(conn, "edition_runs", column, definition)
        for column, definition in (
            ("lease_until", "TEXT"),
            ("worker_id", "TEXT NOT NULL DEFAULT ''"),
            ("client_request_id", "TEXT NOT NULL DEFAULT ''"),
        ):
            _ensure_column(conn, "edition_jobs", column, definition)
        for column, definition in (
            ("article_id", "TEXT NOT NULL DEFAULT ''"),
            ("section", "TEXT NOT NULL DEFAULT ''"),
            ("roster_id", "INTEGER"),
            ("source_receipt_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("generation_metadata_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("evidence_fingerprint", "TEXT NOT NULL DEFAULT ''"),
            ("bundle_revision", "TEXT NOT NULL DEFAULT ''"),
            ("content_hash", "TEXT NOT NULL DEFAULT ''"),
            ("reporter_id", "TEXT NOT NULL DEFAULT ''"),
            ("writer_mode", "TEXT NOT NULL DEFAULT ''"),
            ("fallback_reason", "TEXT NOT NULL DEFAULT ''"),
            ("model", "TEXT NOT NULL DEFAULT ''"),
        ):
            _ensure_column(conn, "content_artifacts", column, definition)
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
            "SELECT id, clerk_user_id, sleeper_username, sleeper_user_id, selected_league_id, created_at FROM users WHERE clerk_user_id = ?",
            (clerk_user_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("user provisioning failed")
        return _row(row)
    finally:
        conn.close()


def set_sleeper_username(user_id: int, sleeper_username: str) -> None:
    set_sleeper_account(user_id, sleeper_username, None)


def set_sleeper_account(user_id: int, sleeper_username: str, sleeper_user_id: str | None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET sleeper_username = ?, sleeper_user_id = ? WHERE id = ?",
            (sleeper_username, sleeper_user_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_user_league(user_id: int, entry: dict[str, Any]) -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO user_leagues(
                user_id, league_id, season, league_type, name, roster_id,
                identity_status, identity_checked_at, enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id, league_id) DO UPDATE SET
                season = excluded.season,
                league_type = excluded.league_type,
                name = excluded.name,
                roster_id = excluded.roster_id,
                identity_status = excluded.identity_status,
                identity_checked_at = excluded.identity_checked_at
            """,
            (
                user_id,
                str(entry.get("league_id") or ""),
                str(entry.get("season") or ""),
                str(entry.get("league_type") or ""),
                str(entry.get("name") or ""),
                entry.get("roster_id"),
                str(entry.get("identity_status") or ("verified_roster_match" if entry.get("roster_id") not in (None, "") else "unverified")),
                str(entry.get("identity_checked_at") or datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT leagues.user_id, league_id, season, league_type, name, roster_id,
                   users.sleeper_user_id AS sleeper_user_id,
                   identity_status, identity_checked_at, enabled
            FROM user_leagues AS leagues
            JOIN users ON users.id = leagues.user_id
            WHERE leagues.user_id = ? AND leagues.league_id = ?
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
            SELECT leagues.user_id, league_id, season, league_type, name, roster_id,
                   users.sleeper_user_id AS sleeper_user_id,
                   identity_status, identity_checked_at, enabled
            FROM user_leagues AS leagues
            JOIN users ON users.id = leagues.user_id
            WHERE leagues.user_id = ?
            ORDER BY enabled DESC, name COLLATE NOCASE, league_id
            """,
            (user_id,),
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        conn.close()


def get_selected_league_id(user_id: int) -> str:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT selected_league_id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0] or "") if row is not None else ""


def set_selected_league_id(user_id: int, league_id: str | None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET selected_league_id = ? WHERE id = ?",
            (str(league_id or ""), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def storage_health(path: Path | None = None) -> dict[str, Any]:
    """Return non-sensitive evidence that the application store is usable.

    This deliberately reports schema shape rather than user rows.  It lets a
    deployment health check distinguish a mounted, initialized SQLite store
    from a fresh empty file without leaking identities or league names.
    """

    db_path = path or DB_PATH
    if not db_path.is_file():
        return {"database_schema_ready": False, "database_table_count": 0}
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {"database_schema_ready": False, "database_table_count": 0}
    tables = {str(row[0]) for row in rows}
    return {
        "database_schema_ready": REQUIRED_TABLES.issubset(tables),
        "database_table_count": len(tables),
    }


def heartbeat_newsroom_worker(
    worker_id: str,
    *,
    state: str = "idle",
    run_id: str = "",
) -> dict[str, Any]:
    """Persist a safe liveness receipt for the separate newsroom worker."""

    worker = str(worker_id or "").strip()
    if not worker:
        raise ValueError("worker_id is required")
    now = datetime.now(timezone.utc).isoformat()
    normalized_state = str(state or "idle").strip().lower()
    if normalized_state not in {"idle", "working", "stopping"}:
        normalized_state = "working"
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO newsroom_workers(worker_id, started_at, last_heartbeat_at, state, run_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                last_heartbeat_at = excluded.last_heartbeat_at,
                state = excluded.state,
                run_id = excluded.run_id
            """,
            (worker, now, now, normalized_state, str(run_id or "")),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "worker_id": worker,
        "last_heartbeat_at": now,
        "state": normalized_state,
        "run_id": str(run_id or ""),
    }


def newsroom_worker_health(*, max_age_seconds: int = 300, path: Path | None = None) -> dict[str, Any]:
    """Summarize worker liveness without exposing worker or league identities."""

    db_path = path or DB_PATH
    if not db_path.is_file():
        return {
            "heartbeat_schema_ready": False,
            "worker_count": 0,
            "active_worker_count": 0,
            "active": False,
            "last_heartbeat_at": "",
        }
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT last_heartbeat_at, state FROM newsroom_workers ORDER BY last_heartbeat_at DESC"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {
            "heartbeat_schema_ready": False,
            "worker_count": 0,
            "active_worker_count": 0,
            "active": False,
            "last_heartbeat_at": "",
        }

    now = datetime.now(timezone.utc)
    age_limit = max(1, min(int(max_age_seconds), 3600))
    active_count = 0
    latest = str(rows[0]["last_heartbeat_at"] or "") if rows else ""
    for row in rows:
        try:
            heartbeat_at = datetime.fromisoformat(str(row["last_heartbeat_at"]).replace("Z", "+00:00"))
            if heartbeat_at.tzinfo is None:
                heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
            if (now - heartbeat_at).total_seconds() <= age_limit:
                active_count += 1
        except (TypeError, ValueError, OverflowError):
            continue
    return {
        "heartbeat_schema_ready": True,
        "worker_count": len(rows),
        "active_worker_count": active_count,
        "active": bool(active_count),
        "last_heartbeat_at": latest,
        "max_age_seconds": age_limit,
    }


def storage_audit(current_user_id: int | None = None, path: Path | None = None) -> dict[str, Any]:
    """Return operator-safe counts for diagnosing identity/storage continuity.

    The audit intentionally omits Clerk subjects, league IDs, and league names.
    It answers the operational question that matters after a deployment: does
    this identity see the preserved rows, and are there rows under another
    identity that indicate a Clerk-instance mismatch?
    """

    db_path = path or DB_PATH
    result = storage_health(db_path)
    if not result["database_schema_ready"]:
        return result | {
            "current_user_present": False,
            "current_user_leagues": 0,
            "other_users": 0,
            "other_user_leagues": 0,
            "team_profiles": 0,
            "manager_trade_profiles": 0,
            "content_artifacts": 0,
            "refresh_runs": 0,
            "edition_runs": 0,
            "edition_jobs": 0,
            "publication_edges": 0,
            "orphan_user_leagues": 0,
            "orphan_team_profiles": 0,
            "orphan_manager_trade_profiles": 0,
        }

    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA query_only = ON")

            def count(query: str, params: tuple[Any, ...] = ()) -> int:
                row = conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0

            current_present = bool(
                current_user_id is not None
                and count("SELECT COUNT(*) FROM users WHERE id = ?", (current_user_id,))
            )
            current_leagues = count(
                "SELECT COUNT(*) FROM user_leagues WHERE user_id = ?", (current_user_id,)
            ) if current_user_id is not None else 0
            total_users = count("SELECT COUNT(*) FROM users")
            total_leagues = count("SELECT COUNT(*) FROM user_leagues")
            orphan_leagues = count(
                """
                SELECT COUNT(*)
                FROM user_leagues AS leagues
                LEFT JOIN users ON users.id = leagues.user_id
                WHERE users.id IS NULL
                """
            )
            orphan_profiles = count(
                """
                SELECT COUNT(*)
                FROM team_profiles AS profiles
                LEFT JOIN users ON users.id = profiles.user_id
                WHERE users.id IS NULL
                """
            )
            orphan_manager_profiles = count(
                """
                SELECT COUNT(*)
                FROM manager_trade_profiles AS profiles
                LEFT JOIN users ON users.id = profiles.user_id
                WHERE users.id IS NULL
                """
            )
            return result | {
                "current_user_present": current_present,
                "current_user_leagues": current_leagues,
                "other_users": max(0, total_users - (1 if current_present else 0)),
                "other_user_leagues": max(0, total_leagues - current_leagues),
                "team_profiles": count("SELECT COUNT(*) FROM team_profiles"),
                "manager_trade_profiles": count("SELECT COUNT(*) FROM manager_trade_profiles"),
                "content_artifacts": count("SELECT COUNT(*) FROM content_artifacts"),
                "refresh_runs": count("SELECT COUNT(*) FROM refresh_runs"),
                "edition_runs": count("SELECT COUNT(*) FROM edition_runs"),
                "edition_jobs": count("SELECT COUNT(*) FROM edition_jobs"),
                "publication_edges": count("SELECT COUNT(*) FROM publication_edges"),
                "orphan_user_leagues": orphan_leagues,
                "orphan_team_profiles": orphan_profiles,
                "orphan_manager_trade_profiles": orphan_manager_profiles,
            }
        finally:
            conn.close()
    except sqlite3.Error:
        return result | {
            "current_user_present": False,
            "current_user_leagues": 0,
            "other_users": 0,
            "other_user_leagues": 0,
            "team_profiles": 0,
            "manager_trade_profiles": 0,
            "content_artifacts": 0,
            "refresh_runs": 0,
            "edition_runs": 0,
            "edition_jobs": 0,
            "publication_edges": 0,
            "orphan_user_leagues": 0,
            "orphan_team_profiles": 0,
            "orphan_manager_trade_profiles": 0,
        }


def another_user_has_leagues(user_id: int) -> bool:
    """Return whether another authenticated identity has a stored league.

    This is intentionally a boolean. It helps diagnose a Clerk identity
    mismatch without exposing another user's league names, IDs, or counts.
    """

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM user_leagues WHERE user_id != ? LIMIT 1",
            (user_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_user_league(user_id: int, league_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT leagues.user_id, league_id, season, league_type, name, roster_id,
                   users.sleeper_user_id AS sleeper_user_id,
                   identity_status, identity_checked_at, enabled
            FROM user_leagues AS leagues
            JOIN users ON users.id = leagues.user_id
            WHERE leagues.user_id = ? AND leagues.league_id = ?
            """,
            (user_id, str(league_id)),
        ).fetchone()
        return _row(row) if row is not None else None
    finally:
        conn.close()


def upsert_team_profile(user_id: int, league_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Persist customization that belongs to one user's team in one league."""

    # The browser sends only the editable strategy fields.  Merge those fields
    # into the existing league-scoped JSON so saving a team name or horizon
    # weight cannot erase core holds, tracked picks, or other private notes.
    existing_profile = get_team_profile(user_id, str(league_id))
    existing_strategy = (
        existing_profile.get("strategy_profile", {})
        if isinstance(existing_profile, dict)
        else {}
    )
    incoming_strategy = profile.get("strategy_profile", profile.get("strategy", {}))
    if not isinstance(existing_strategy, dict):
        existing_strategy = {}
    if not isinstance(incoming_strategy, dict):
        incoming_strategy = {}
    strategy = dict(existing_strategy)
    strategy.update(incoming_strategy)
    writer_preferences = normalize_writer_preferences(profile.get("writer_preferences", {}))
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


def upsert_manager_trade_profile(
    user_id: int,
    league_id: str,
    roster_id: int,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Persist private, user-authored trade context for one league manager."""

    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO manager_trade_profiles(
                user_id, league_id, roster_id, manager_name, trade_style,
                preferred_assets, protected_assets, editor_note, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, league_id, roster_id) DO UPDATE SET
                manager_name = excluded.manager_name,
                trade_style = excluded.trade_style,
                preferred_assets = excluded.preferred_assets,
                protected_assets = excluded.protected_assets,
                editor_note = excluded.editor_note,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                str(league_id),
                int(roster_id),
                str(profile.get("manager_name") or "")[:160],
                str(profile.get("trade_style") or "")[:400],
                str(profile.get("preferred_assets") or "")[:400],
                str(profile.get("protected_assets") or "")[:400],
                str(profile.get("editor_note") or "")[:800],
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    result = get_manager_trade_profile(user_id, league_id, int(roster_id))
    if result is None:
        raise RuntimeError("manager trade profile upsert failed")
    return result


def get_manager_trade_profile(
    user_id: int,
    league_id: str,
    roster_id: int,
) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT user_id, league_id, roster_id, manager_name, trade_style,
                   preferred_assets, protected_assets, editor_note, updated_at
            FROM manager_trade_profiles
            WHERE user_id = ? AND league_id = ? AND roster_id = ?
            """,
            (user_id, str(league_id), int(roster_id)),
        ).fetchone()
        return _row(row) if row is not None else None
    finally:
        conn.close()


def list_manager_trade_profiles(user_id: int, league_id: str) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT user_id, league_id, roster_id, manager_name, trade_style,
                   preferred_assets, protected_assets, editor_note, updated_at
            FROM manager_trade_profiles
            WHERE user_id = ? AND league_id = ?
            ORDER BY manager_name COLLATE NOCASE, roster_id
            """,
            (user_id, str(league_id)),
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        conn.close()


def migrate_legacy_team_profile(
    user_id: int,
    league: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Idempotently copy strategy settings into one authenticated scope.

    The legacy YAML contains a singleton team name and display identity. Those
    labels are not safe to migrate into an authenticated league because the
    current Sleeper roster and name are the source of truth. Strategy settings
    are useful defaults; identity labels must come from the linked roster (or
    be entered as an explicit league customization later).
    """

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
            "team_name": "",
            "display_name": "",
            "strategy_profile": strategy if isinstance(strategy, dict) else {},
            "writer_preferences": {},
        },
    )


def reconcile_team_profile_identity(
    user_id: int,
    league: dict[str, Any],
    previous_league: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """Re-key a profile after Sleeper proves the league's owned roster.

    A profile is private customization, not an identity source. When an old
    row was unverified or pointed at a different roster, preserve its strategy
    and writer notes but clear the stale team/display labels. An explicit
    identity recheck may force the same cleanup when a legacy row was falsely
    marked verified. The next scoped refresh derives the current Sleeper name
    from the exact roster ID.
    """

    league_id = str(league.get("league_id") or "")
    profile = get_team_profile(user_id, league_id)
    if profile is None:
        return None

    expected_roster_id = league.get("roster_id")
    if expected_roster_id in (None, ""):
        return profile

    previous = previous_league or {}
    previous_status = str(previous.get("identity_status") or "unverified").lower()
    previous_roster_id = previous.get("roster_id")
    profile_roster_id = profile.get("roster_id")

    def _same_roster(left: Any, right: Any) -> bool:
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return False

    identity_changed = force or (
        previous_status not in {"verified", "verified_roster_match"}
        or not _same_roster(previous_roster_id, expected_roster_id)
        or not _same_roster(profile_roster_id, expected_roster_id)
    )
    if not identity_changed:
        return profile

    return upsert_team_profile(
        user_id,
        league_id,
        {
            **profile,
            "roster_id": expected_roster_id,
            "season": league.get("season") or profile.get("season") or "",
            "team_name": "",
            "display_name": "",
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
    article_id: str = "",
    section: str = "",
    roster_id: int | str | None = None,
    source_receipt: dict[str, Any] | None = None,
    generation_metadata: dict[str, Any] | None = None,
    status: str = "generated",
    evidence_fingerprint: str = "",
    bundle_revision: str = "",
    content_hash: str = "",
    reporter_id: str = "",
    writer_mode: str = "",
    fallback_reason: str = "",
    model: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        previous = conn.execute(
            """
            SELECT status, evidence_fingerprint, content_hash, reporter_id,
                   writer_mode, model, fallback_reason
            FROM content_artifacts
            WHERE user_id = ? AND league_id = ? AND season = ?
              AND artifact_type = ? AND artifact_key = ?
            """,
            (user_id, str(league_id), str(season), str(artifact_type), str(artifact_key)),
        ).fetchone()
        current_signature = (
            str(status), str(evidence_fingerprint or ""), str(content_hash or ""),
            str(reporter_id or ""), str(writer_mode or ""), str(model or ""),
            str(fallback_reason or ""),
        )
        previous_signature = tuple(str(value or "") for value in previous) if previous else None
        if previous_signature != current_signature:
            change_type = "new" if previous is None else ("failed" if str(status).lower() == "failed" else "updated")
            conn.execute(
                """
                INSERT INTO content_artifact_history(
                    user_id, league_id, season, artifact_type, artifact_key,
                    roster_id, status, evidence_fingerprint, content_hash,
                    reporter_id, writer_mode, model, fallback_reason,
                    source_receipt_json, generation_metadata_json, change_type,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    str(league_id),
                    str(season),
                    str(artifact_type),
                    str(artifact_key),
                    int(roster_id) if str(roster_id or "").strip().isdigit() else None,
                    str(status),
                    str(evidence_fingerprint or ""),
                    str(content_hash or ""),
                    str(reporter_id or ""),
                    str(writer_mode or ""),
                    str(model or ""),
                    str(fallback_reason or ""),
                    json.dumps(source_receipt or {}, sort_keys=True),
                    json.dumps(generation_metadata or {}, sort_keys=True),
                    change_type,
                    now,
                ),
            )
        conn.execute(
            """
            INSERT INTO content_artifacts(
                user_id, league_id, season, artifact_type, artifact_key, article_id,
                section, roster_id, path, status, source_json, source_receipt_json,
                generation_metadata_json, generated_at, updated_at, evidence_fingerprint,
                bundle_revision, content_hash, reporter_id, writer_mode, fallback_reason, model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, league_id, season, artifact_type, artifact_key) DO UPDATE SET
                article_id = excluded.article_id,
                section = excluded.section,
                roster_id = excluded.roster_id,
                path = excluded.path,
                status = excluded.status,
                source_json = excluded.source_json,
                source_receipt_json = excluded.source_receipt_json,
                generation_metadata_json = excluded.generation_metadata_json,
                generated_at = excluded.generated_at,
                updated_at = excluded.updated_at,
                evidence_fingerprint = excluded.evidence_fingerprint,
                bundle_revision = excluded.bundle_revision,
                content_hash = excluded.content_hash,
                reporter_id = excluded.reporter_id,
                writer_mode = excluded.writer_mode,
                fallback_reason = excluded.fallback_reason,
                model = excluded.model
            """,
            (
                user_id,
                str(league_id),
                str(season),
                str(artifact_type),
                str(artifact_key),
                str(article_id or f"{artifact_type}:{artifact_key}:{season}"),
                str(section or artifact_key),
                int(roster_id) if str(roster_id or "").strip().isdigit() else None,
                str(path),
                str(status),
                json.dumps(source or {}, sort_keys=True),
                json.dumps(source_receipt or {}, sort_keys=True),
                json.dumps(generation_metadata or {}, sort_keys=True),
                now,
                now,
                str(evidence_fingerprint or ""),
                str(bundle_revision or ""),
                str(content_hash or ""),
                str(reporter_id or ""),
                str(writer_mode or ""),
                str(fallback_reason or ""),
                str(model or ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_content_artifact(
    user_id: int,
    league_id: str,
    season: str,
    artifact_key: str,
    artifact_type: str = "article",
) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT artifact_key, article_id, section, roster_id, path, status, source_json,
                   source_receipt_json, generation_metadata_json, generated_at, updated_at,
                   evidence_fingerprint, bundle_revision, content_hash, reporter_id,
                   writer_mode, fallback_reason, model
            FROM content_artifacts
            WHERE user_id = ? AND league_id = ? AND season = ?
              AND artifact_type = ? AND artifact_key = ?
            """,
            (user_id, str(league_id), str(season), str(artifact_type), str(artifact_key)),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        source = json.loads(row[6] or "{}")
    except (TypeError, json.JSONDecodeError):
        source = {}
    return {
        "artifact_key": str(row[0] or ""),
        "article_id": str(row[1] or ""),
        "section": str(row[2] or ""),
        "roster_id": row[3],
        "path": str(row[4] or ""),
        "status": str(row[5] or ""),
        "source": source if isinstance(source, dict) else {},
        "source_receipt": _decode_json(row[7]),
        "generation_metadata": _decode_json(row[8]),
        "generated_at": str(row[9] or ""),
        "updated_at": str(row[10] or ""),
        "evidence_fingerprint": str(row[11] or ""),
        "bundle_revision": str(row[12] or ""),
        "content_hash": str(row[13] or ""),
        "reporter_id": str(row[14] or ""),
        "writer_mode": str(row[15] or ""),
        "fallback_reason": str(row[16] or ""),
        "model": str(row[17] or ""),
    }


def stamp_content_artifact_bundle(
    user_id: int,
    league_id: str,
    season: str,
    bundle_revision: str,
    artifact_type: str = "article",
) -> None:
    """Bind persisted article receipts to the exact browser bundle that published them."""
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE content_artifacts
            SET bundle_revision = ?, updated_at = ?
            WHERE user_id = ? AND league_id = ? AND season = ? AND artifact_type = ?
            """,
            (
                str(bundle_revision or ""),
                datetime.now(timezone.utc).isoformat(),
                user_id,
                str(league_id),
                str(season),
                str(artifact_type),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_content_artifact_changes(
    user_id: int,
    league_id: str,
    season: str,
    roster_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return current publication artifacts with their last prior receipt."""

    conn = _connect()
    try:
        query = """
            SELECT artifact_type, artifact_key, roster_id, status,
                   evidence_fingerprint, content_hash, reporter_id,
                   writer_mode, model, fallback_reason, updated_at,
                   generation_metadata_json
            FROM content_artifacts
            WHERE user_id = ? AND league_id = ? AND season = ?
        """
        params: list[Any] = [user_id, str(league_id), str(season)]
        if roster_id is not None:
            query += " AND roster_id = ?"
            params.append(int(roster_id))
        current_rows = conn.execute(query, tuple(params)).fetchall()
        history_rows = conn.execute(
            """
            SELECT artifact_type, artifact_key, roster_id, status,
                   evidence_fingerprint, content_hash, reporter_id,
                   writer_mode, model, fallback_reason, change_type, recorded_at
            FROM content_artifact_history
            WHERE user_id = ? AND league_id = ? AND season = ?
            ORDER BY id DESC
            """,
            (user_id, str(league_id), str(season)),
        ).fetchall()
    finally:
        conn.close()

    history_by_key: dict[tuple[str, str, str], list[tuple[Any, ...]]] = {}
    for row in history_rows:
        key = (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""))
        history_by_key.setdefault(key, []).append(row)

    output: list[dict[str, Any]] = []
    for row in current_rows:
        key = (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""))
        history = history_by_key.get(key, [])
        prior = history[1] if len(history) > 1 else None
        current = {
            "artifact_type": str(row[0] or ""),
            "artifact_key": str(row[1] or ""),
            "roster_id": row[2],
            "status": str(row[3] or ""),
            "evidence_fingerprint": str(row[4] or ""),
            "content_hash": str(row[5] or ""),
            "reporter_id": str(row[6] or ""),
            "writer_mode": str(row[7] or ""),
            "model": str(row[8] or ""),
            "fallback_reason": str(row[9] or ""),
            "updated_at": str(row[10] or ""),
            "change_type": str(history[0][10] if history else "untracked"),
            "recorded_at": str(history[0][11] if history else ""),
            "prior_evidence_fingerprint": str(prior[4] or "") if prior else "",
            "prior_content_hash": str(prior[5] or "") if prior else "",
        }
        metadata = _decode_json(row[11])
        usage = metadata.get("usage") if isinstance(metadata, dict) and isinstance(metadata.get("usage"), dict) else {}
        current["usage"] = usage
        current["cost_known"] = bool(metadata.get("cost_known")) if isinstance(metadata, dict) else False
        if prior is None and history:
            current["change_type"] = "new"
        elif prior and current["evidence_fingerprint"] == current["prior_evidence_fingerprint"] and current["content_hash"] == current["prior_content_hash"]:
            current["change_type"] = "unchanged"
        output.append(current)
    return sorted(output, key=lambda item: (str(item.get("change_type")), str(item.get("artifact_key"))))


def content_artifact_status(
    user_id: int,
    league_id: str,
    season: str,
    artifact_type: str = "article",
    current_receipts: dict[str, dict[str, Any]] | None = None,
    current_bundle_revision: str = "",
    expected_model: str = "",
) -> dict[str, Any]:
    """Return a safe, user-scoped receipt for generated writer output.

    The deterministic edition is always available, so the absence of an API
    artifact is not an error. It is still important to distinguish that
    fallback from a completed reporter run in the headquarters UI.
    """

    expected_keys = ("team_report", "market_watch", "horizon_watch", "trade_desk", "manager_intel", "daily_brief")
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT artifact_key, status, generated_at, updated_at, content_hash,
                   reporter_id, writer_mode, evidence_fingerprint, bundle_revision, model
            FROM content_artifacts
            WHERE user_id = ? AND league_id = ? AND season = ? AND artifact_type = ?
            """,
            (user_id, str(league_id), str(season), str(artifact_type)),
        ).fetchall()
    finally:
        conn.close()

    def is_current_generated(row: tuple[Any, ...]) -> bool:
        if str(row[1] or "").lower() != "generated":
            return False
        # A database artifact is not proof that the reader is serving it. The
        # manifest is the publication seam, so fail closed when it is absent.
        # This keeps a stale/private DB receipt from making the headquarters
        # call content "published" while its bundle is missing or rebuilding.
        if current_receipts is None:
            return False
        receipt = current_receipts.get(str(row[0])) or {}
        if not isinstance(receipt, dict):
            return False
        if expected_model and str(receipt.get("model") or "") != str(expected_model):
            return False
        editorial_review = receipt.get("editorial_review")
        if isinstance(editorial_review, dict) and editorial_review:
            if str(editorial_review.get("status") or "").lower() != "approved":
                return False
        return (
            str(receipt.get("mode") or "").lower() in {"automatic_llm", "codex_task"}
            and str(row[4] or "")
            and str(row[4] or "") == str(receipt.get("content_hash") or "")
            and (
                not current_bundle_revision
                or str(row[8] or "") == str(current_bundle_revision)
            )
        )

    generated_keys = {
        str(row[0])
        for row in rows
        if str(row[0]) in expected_keys and is_current_generated(row)
    }
    timestamps = [
        str(row[2] or row[3] or "")
        for row in rows
        if str(row[2] or row[3] or "") and is_current_generated(row)
    ]
    generated_rows = [row for row in rows if str(row[1] or "").lower() == "generated"]
    unverified_keys = {
        str(row[0])
        for row in generated_rows
        if str(row[0]) in expected_keys
    } if current_receipts is None else set()
    latest_generated_row = max(
        generated_rows,
        key=lambda row: str(row[3] or row[2] or ""),
        default=None,
    )
    last_generated_model = str(latest_generated_row[9] or "") if latest_generated_row else ""
    model_mismatch_count = (
        sum(1 for row in generated_rows if str(row[9] or "") != str(expected_model))
        if expected_model
        else 0
    )
    if not generated_rows:
        model_reconciliation = "no prior writer run"
    elif expected_model and model_mismatch_count:
        model_reconciliation = "prior run needs regeneration"
    elif expected_model:
        model_reconciliation = "prior runs match configured model"
    else:
        model_reconciliation = "configured model not supplied"
    generated_count = len(generated_keys)
    expected_count = len(expected_keys)
    if current_receipts is None and unverified_keys:
        state = "unverified"
        label = f"{len(unverified_keys)}/{expected_count} reporter articles · reader receipt unavailable"
    elif generated_count == expected_count:
        state = "complete"
        label = f"{generated_count}/{expected_count} reporter articles"
    elif generated_count:
        state = "partial"
        label = f"{generated_count}/{expected_count} reporter articles"
    else:
        state = "fallback"
        label = f"0/{expected_count} reporter articles · evidence-led fallback"
    return {
        "state": state,
        "label": label,
        "generated_count": generated_count,
        "expected_count": expected_count,
        "generated_keys": sorted(generated_keys),
        "unverified_keys": sorted(unverified_keys),
        "last_generated_at": max(timestamps, default=""),
        "last_generated_model": last_generated_model,
        "expected_model": str(expected_model or ""),
        "model_mismatch_count": model_mismatch_count,
        "model_reconciliation": model_reconciliation,
        "bundle_revision": str(current_bundle_revision or ""),
        "receipt_verified": current_receipts is not None,
    }


def record_content_interaction(
    user_id: int,
    league_id: str,
    roster_id: int,
    artifact_type: str,
    artifact_key: str,
    interaction_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store an explicit manager feedback signal for one scoped artifact."""

    created_at = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO content_interactions(
                user_id, league_id, roster_id, artifact_type, artifact_key,
                interaction_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, league_id, roster_id, artifact_type, artifact_key, interaction_type)
            DO UPDATE SET payload_json = excluded.payload_json, created_at = excluded.created_at
            """,
            (
                user_id,
                str(league_id),
                int(roster_id),
                str(artifact_type),
                str(artifact_key),
                str(interaction_type),
                json.dumps(payload or {}, sort_keys=True),
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "user_id": user_id,
        "league_id": str(league_id),
        "roster_id": int(roster_id),
        "artifact_type": str(artifact_type),
        "artifact_key": str(artifact_key),
        "interaction_type": str(interaction_type),
        "payload": payload or {},
        "created_at": created_at,
    }


def list_content_interactions(
    user_id: int,
    league_id: str,
    roster_id: int | None = None,
) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        query = """
            SELECT league_id, roster_id, artifact_type, artifact_key,
                   interaction_type, payload_json, created_at
            FROM content_interactions
            WHERE user_id = ? AND league_id = ?
        """
        params: list[Any] = [user_id, str(league_id)]
        if roster_id is not None:
            query += " AND roster_id = ?"
            params.append(int(roster_id))
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
    finally:
        conn.close()
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "league_id": str(row[0] or ""),
                "roster_id": row[1],
                "artifact_type": str(row[2] or ""),
                "artifact_key": str(row[3] or ""),
                "interaction_type": str(row[4] or ""),
                "payload": _decode_json(row[5]),
                "created_at": str(row[6] or ""),
            }
        )
    return output


def content_learning_summary(
    user_id: int,
    league_id: str,
    roster_id: int | None = None,
    season: str = "",
) -> dict[str, Any]:
    """Summarize deliberate feedback for one authenticated league scope."""

    rows = list_content_interactions(user_id, league_id, roster_id)
    artifact_rows = (
        list_content_artifact_changes(user_id, league_id, str(season), roster_id)
        if str(season or "").strip()
        else []
    )
    feedback_types = {"useful", "not_useful", "evidence_opened", "saved", "pursued"}
    outcome_types = {"open", "confirmed", "missed", "unclear"}
    feedback = {name: 0 for name in sorted(feedback_types)}
    outcomes = {name: 0 for name in sorted(outcome_types)}
    recommendation_outcomes = {name: 0 for name in sorted(outcome_types)}
    artifacts: set[tuple[str, str]] = set()
    recommendation_artifacts: set[tuple[str, str]] = set()
    latest_recorded_at = ""

    artifact_by_key = {
        (str(row.get("artifact_type") or ""), str(row.get("artifact_key") or "")): row
        for row in artifact_rows
    }
    reporter_groups: dict[tuple[str, str], dict[str, Any]] = {}

    def reporter_group(reporter_id: str, writer_mode: str) -> dict[str, Any]:
        key = (str(reporter_id or "unassigned"), str(writer_mode or ""))
        if key not in reporter_groups:
            reporter_groups[key] = {
                "reporter_id": key[0] or "unassigned",
                "writer_mode": key[1],
                "article_keys": [],
                "artifact_count": 0,
                "interaction_count": 0,
                "useful": 0,
                "not_useful": 0,
                "evidence_opened": 0,
                "saved": 0,
                "pursued": 0,
                "open": 0,
                "confirmed": 0,
                "missed": 0,
                "unclear": 0,
            }
        return reporter_groups[key]

    for artifact in artifact_rows:
        group = reporter_group(
            str(artifact.get("reporter_id") or "unassigned"),
            str(artifact.get("writer_mode") or ""),
        )
        group["artifact_count"] += 1
        key = str(artifact.get("artifact_key") or "")
        if key and key not in group["article_keys"]:
            group["article_keys"].append(key)

    for row in rows:
        interaction_type = str(row.get("interaction_type") or "")
        payload = row.get("payload") or {}
        artifact_type = str(row.get("artifact_type") or "")
        if interaction_type in feedback:
            feedback[interaction_type] += 1
        elif interaction_type == "outcome":
            outcome = str(payload.get("outcome") or "").strip().lower()
            if outcome in outcomes:
                outcomes[outcome] += 1
        elif interaction_type == "decision_outcome":
            outcome = str(payload.get("outcome") or "").strip().lower()
            if outcome in recommendation_outcomes:
                recommendation_outcomes[outcome] += 1
            recommendation_artifacts.add((artifact_type, str(row.get("artifact_key") or "")))

        artifact = artifact_by_key.get((artifact_type, str(row.get("artifact_key") or "")), {})
        if artifact_type == "article":
            group = reporter_group(
                str(artifact.get("reporter_id") or "unassigned"),
                str(artifact.get("writer_mode") or ""),
            )
            group["interaction_count"] += 1
            if interaction_type in feedback:
                group[interaction_type] += 1
            elif interaction_type == "outcome":
                outcome = str(payload.get("outcome") or "").strip().lower()
                if outcome in outcomes:
                    group[outcome] += 1
        artifacts.add((str(row.get("artifact_type") or ""), str(row.get("artifact_key") or "")))
        latest_recorded_at = max(latest_recorded_at, str(row.get("created_at") or ""))

    resolved = outcomes["confirmed"] + outcomes["missed"]
    recommendation_resolved = recommendation_outcomes["confirmed"] + recommendation_outcomes["missed"]
    reporter_breakdown = []
    for group in reporter_groups.values():
        group_resolved = group["confirmed"] + group["missed"]
        group["resolved_outcomes"] = group_resolved
        group["confirmed_rate"] = round(group["confirmed"] / group_resolved, 3) if group_resolved else None
        reporter_breakdown.append(group)
    reporter_breakdown.sort(key=lambda item: (str(item.get("reporter_id")), str(item.get("writer_mode"))))
    return {
        "league_id": str(league_id),
        "roster_id": int(roster_id) if roster_id is not None else None,
        "interaction_count": len(rows),
        "artifact_count": len(artifacts),
        "feedback_counts": feedback,
        "outcome_counts": outcomes,
        "resolved_outcomes": resolved,
        "confirmed_rate": round(outcomes["confirmed"] / resolved, 3) if resolved else None,
        "recommendation_count": len(recommendation_artifacts),
        "recommendation_outcome_counts": recommendation_outcomes,
        "recommendation_resolved_outcomes": recommendation_resolved,
        "recommendation_confirmed_rate": round(recommendation_outcomes["confirmed"] / recommendation_resolved, 3) if recommendation_resolved else None,
        "latest_recorded_at": latest_recorded_at,
        "reporter_breakdown": reporter_breakdown,
    }


def start_edition_run(
    user_id: int,
    league_id: str,
    season: str,
    roster_id: int | str | None = None,
    operator_run_id: str = "",
    article_keys: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
    edition_fingerprint: str = "",
    source_receipt: dict[str, Any] | None = None,
    initial_state: str = "running",
    initial_stage: str = "refreshing",
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Create the durable receipt for one league newsroom edition.

    This is deliberately separate from ``content_artifacts``.  An artifact is
    the last published result; an edition run is the execution ledger that
    explains what was attempted, reused, held, or interrupted on the way
    there.  Keeping both lets a retry resume without pretending a partial run
    was a complete publication.
    """

    now = datetime.now(timezone.utc).isoformat()
    run_id = uuid.uuid4().hex
    requested = [str(key) for key in (article_keys or []) if str(key).strip()]
    state = str(initial_state or "running").strip().lower()
    stage = str(initial_stage or ("queued" if state == "queued" else "refreshing")).strip().lower()
    if state not in {"queued", "running"}:
        raise ValueError("initial_state must be queued or running")
    attempts = max(1, min(int(max_attempts), 5))
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO edition_runs(
                run_id, operator_run_id, user_id, league_id, season, roster_id,
                requested_article_keys_json, state, stage, started_at, updated_at,
                last_heartbeat_at, total_count, max_attempts, edition_fingerprint,
                source_receipt_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(operator_run_id or ""),
                int(user_id),
                str(league_id),
                str(season),
                int(roster_id) if str(roster_id or "").strip().isdigit() else None,
                json.dumps(requested, sort_keys=True),
                state,
                stage,
                now,
                now,
                now,
                len(requested),
                attempts,
                str(edition_fingerprint or ""),
                json.dumps(source_receipt or {}, sort_keys=True),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_edition_run(run_id) or {"run_id": run_id, "state": state}


def update_edition_run(
    run_id: str,
    *,
    state: str | None = None,
    stage: str | None = None,
    completed_count: int | None = None,
    total_count: int | None = None,
    bundle_revision: str | None = None,
    edition_fingerprint: str | None = None,
    source_receipt: dict[str, Any] | None = None,
    failure_class: str | None = None,
    failure_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    complete: bool = False,
    worker_id: str | None = None,
) -> dict[str, Any] | None:
    """Checkpoint a newsroom run without accepting arbitrary SQL fields."""

    assignments = ["updated_at = ?", "last_heartbeat_at = ?"]
    values: list[Any] = [datetime.now(timezone.utc).isoformat()] * 2
    for column, value in (
        ("state", state),
        ("stage", stage),
        ("completed_count", completed_count),
        ("total_count", total_count),
        ("bundle_revision", bundle_revision),
        ("edition_fingerprint", edition_fingerprint),
        ("failure_class", failure_class),
        ("failure_message", failure_message),
    ):
        if value is not None:
            assignments.append(f"{column} = ?")
            values.append(value)
    if metadata is not None:
        assignments.append("metadata_json = ?")
        values.append(json.dumps(metadata, sort_keys=True))
    if source_receipt is not None:
        assignments.append("source_receipt_json = ?")
        values.append(json.dumps(source_receipt, sort_keys=True))
    if complete:
        assignments.extend(["completed_at = ?", "lease_until = NULL", "worker_id = ''"])
        values.append(datetime.now(timezone.utc).isoformat())
    where = "run_id = ?"
    where_values: list[Any] = [str(run_id)]
    if worker_id is not None:
        now = datetime.now(timezone.utc).isoformat()
        where += " AND worker_id = ? AND state NOT IN ('complete', 'completed', 'failed', 'cancelled', 'dead_letter') AND cancel_requested_at IS NULL AND (lease_until IS NULL OR lease_until > ?)"
        where_values.extend([str(worker_id), now])
    values.extend(where_values)
    conn = _connect()
    try:
        cursor = conn.execute(f"UPDATE edition_runs SET {', '.join(assignments)} WHERE {where}", tuple(values))
        if worker_id is not None and cursor.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
    finally:
        conn.close()
    return get_edition_run(str(run_id))


def start_edition_job(
    run_id: str,
    article_key: str,
    *,
    phase: str = "writer",
    evidence_fingerprint: str = "",
    prompt_version: str = "",
    provider: str = "",
    model: str = "",
    reasoning_effort: str = "",
    client_request_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Start or retry one desk phase, incrementing its durable attempt count."""

    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        run = conn.execute(
            "SELECT state, max_attempts, cancel_requested_at FROM edition_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if run is None:
            conn.rollback()
            return None
        existing = conn.execute(
            "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
            (str(run_id), str(article_key), str(phase)),
        ).fetchone()
        run_state = str(run[0] or "").strip().lower()
        if run_state != "running":
            conn.rollback()
            return _edition_job_row(existing) if existing is not None else {"state": run_state or "unavailable"}
        if bool(run[2]):
            conn.rollback()
            return _edition_job_row(existing) if existing is not None else {"state": "cancelled"}
        if existing is not None:
            existing_state = str(existing["state"] or "").lower()
            if existing_state in {"published", "reused", "skipped", "reviewed", "held", "dead_letter", "cancelled"}:
                conn.rollback()
                return _edition_job_row(existing)
            if existing_state in {"failed", "interrupted"} and int(existing["attempt"] or 0) >= max(1, int(run[1] or 2)):
                conn.execute(
                    """
                    UPDATE edition_jobs
                    SET state = 'dead_letter', updated_at = ?, completed_at = ?,
                        lease_until = NULL, worker_id = '', error_class = 'retry_budget_exhausted',
                        error_message = ?
                    WHERE run_id = ? AND article_key = ? AND phase = ?
                    """,
                    (now, now, f"Retry budget exhausted after {max(1, int(run[1] or 2))} attempts.", str(run_id), str(article_key), str(phase)),
                )
                conn.commit()
                return _edition_job_row(conn.execute(
                    "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
                    (str(run_id), str(article_key), str(phase)),
                ).fetchone())
        conn.execute(
            """
            INSERT INTO edition_jobs(
                run_id, article_key, phase, state, attempt, started_at, updated_at,
                evidence_fingerprint, prompt_version, provider, model, reasoning_effort,
                client_request_id, metadata_json
            ) VALUES (?, ?, ?, 'running', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, article_key, phase) DO UPDATE SET
                state = 'running', attempt = edition_jobs.attempt + 1,
                started_at = excluded.started_at, updated_at = excluded.updated_at,
                completed_at = NULL, evidence_fingerprint = excluded.evidence_fingerprint,
                prompt_version = excluded.prompt_version, provider = excluded.provider,
                model = excluded.model, reasoning_effort = excluded.reasoning_effort,
                client_request_id = CASE WHEN excluded.client_request_id = ''
                    THEN edition_jobs.client_request_id ELSE excluded.client_request_id END,
                lease_until = NULL, worker_id = '', provider_request_id = '', usage_json = '{}', metadata_json = excluded.metadata_json,
                error_class = '', error_message = ''
            """,
            (
                str(run_id), str(article_key), str(phase), now, now,
                str(evidence_fingerprint or ""), str(prompt_version or ""),
                str(provider or ""), str(model or ""), str(reasoning_effort or ""),
                str(client_request_id or ""),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
            (str(run_id), str(article_key), str(phase)),
        ).fetchone()
    finally:
        conn.close()
    return _edition_job_row(row) if row is not None else None


def claim_edition_run(
    run_id: str,
    worker_id: str,
    *,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    """Atomically claim a queued, interrupted, or expired edition run.

    This is the seam a future Railway worker can use.  The current inline
    operator path remains compatible, while a second worker cannot claim a
    live run until its lease expires or it is the same worker renewing it.
    """

    worker = str(worker_id or "").strip()
    if not worker:
        raise ValueError("worker_id is required")
    seconds = max(1, min(int(lease_seconds), 3600))
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    lease_until = (now_dt.timestamp() + seconds)
    lease = datetime.fromtimestamp(lease_until, timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, stage, worker_id, lease_until, metadata_json FROM edition_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        state = str(row[0] or "").strip().lower()
        owner = str(row[2] or "").strip()
        expired = _lease_is_expired(row[3], now_dt)
        if state in {"complete", "completed", "failed"} or (
            state in {"running", "cancel_requested"} and owner and owner != worker and not expired
        ) or state not in {"queued", "interrupted", "running", "cancel_requested"}:
            conn.rollback()
            return None
        stage = str(row[1] or "").strip()
        if state in {"queued", "interrupted"} or stage in {"", "queued", "interrupted"}:
            metadata = _decode_json(row[4])
            stage = str(metadata.get("resume_stage") or "refreshing").strip() or "refreshing"
        conn.execute(
            """
            UPDATE edition_runs
            SET state = 'running', stage = ?, updated_at = ?, last_heartbeat_at = ?,
                lease_until = ?, worker_id = ?,
                cancel_requested_at = CASE WHEN ? = 'cancel_requested' THEN cancel_requested_at ELSE NULL END,
                failure_class = '', failure_message = ''
            WHERE run_id = ?
            """,
            (stage, now, now, lease, worker, state, str(run_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return get_edition_run(str(run_id))


def claim_next_edition_run(
    worker_id: str,
    *,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    """Atomically claim the oldest queued or recoverable edition run.

    A worker should use this instead of selecting a run and claiming it in two
    separate requests.  The transaction closes the race where two Railway
    worker instances wake up on the same queue row.
    """

    worker = str(worker_id or "").strip()
    if not worker:
        raise ValueError("worker_id is required")
    seconds = max(1, min(int(lease_seconds), 3600))
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    lease = datetime.fromtimestamp(now_dt.timestamp() + seconds, timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT run_id, state, stage, worker_id, lease_until, metadata_json
            FROM edition_runs
            WHERE completed_at IS NULL
              AND (
                state IN ('queued', 'interrupted')
                OR (state IN ('running', 'cancel_requested') AND worker_id <> '' AND (lease_until IS NULL OR lease_until <= ?))
              )
            ORDER BY started_at, rowid
            LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        state = str(row[1] or "").strip().lower()
        stage = str(row[2] or "").strip()
        if state in {"queued", "interrupted"} or stage in {"", "queued", "interrupted"}:
            metadata = _decode_json(row[5])
            stage = str(metadata.get("resume_stage") or "refreshing").strip() or "refreshing"
        conn.execute(
            """
            UPDATE edition_runs
            SET state = 'running', stage = ?, updated_at = ?, last_heartbeat_at = ?,
                lease_until = ?, worker_id = ?,
                cancel_requested_at = CASE WHEN ? = 'cancel_requested' THEN cancel_requested_at ELSE NULL END,
                failure_class = '', failure_message = ''
            WHERE run_id = ?
            """,
            (stage, now, now, lease, worker, state, str(row[0])),
        )
        conn.commit()
        run_id = str(row[0])
    finally:
        conn.close()
    return get_edition_run(run_id)


def heartbeat_edition_run(
    run_id: str,
    worker_id: str,
    *,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    """Extend a run lease only when the caller still owns the run."""

    worker = str(worker_id or "").strip()
    if not worker:
        raise ValueError("worker_id is required")
    seconds = max(1, min(int(lease_seconds), 3600))
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    lease = datetime.fromtimestamp(now_dt.timestamp() + seconds, timezone.utc).isoformat()
    conn = _connect()
    try:
        cursor = conn.execute(
            """
            UPDATE edition_runs
            SET updated_at = ?, last_heartbeat_at = ?, lease_until = ?
            WHERE run_id = ? AND state IN ('running', 'cancel_requested') AND worker_id = ?
              AND (lease_until IS NULL OR lease_until > ?)
            """,
            (now, now, lease, str(run_id), worker, now),
        )
        conn.commit()
        if cursor.rowcount != 1:
            return None
    finally:
        conn.close()
    return get_edition_run(str(run_id))


def edition_run_cancel_requested(run_id: str) -> bool:
    """Return whether a non-terminal edition has a cancellation request."""

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT state, cancel_requested_at FROM edition_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    return str(row[0] or "").strip().lower() in {"cancel_requested", "cancelled"} or bool(row[1])


def request_edition_cancellation(run_id: str) -> dict[str, Any] | None:
    """Request cancellation without stealing a live worker's lease.

    Queued work can be cancelled immediately.  Running work is marked for
    cooperative cancellation so the current provider call can finish safely;
    the worker then closes the run and suppresses publication.
    """

    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state FROM edition_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        state = str(row[0] or "").strip().lower()
        if state in {"complete", "completed", "failed", "cancelled", "dead_letter"}:
            conn.rollback()
        elif state in {"queued", "interrupted"}:
            conn.execute(
                """
                UPDATE edition_runs
                SET state = 'cancelled', stage = 'cancelled', updated_at = ?,
                    last_heartbeat_at = ?, completed_at = ?, cancel_requested_at = ?,
                    lease_until = NULL, worker_id = '', failure_class = 'cancelled',
                    failure_message = 'Cancellation requested before the newsroom started.'
                WHERE run_id = ?
                """,
                (now, now, now, now, str(run_id)),
            )
            conn.execute(
                """
                UPDATE edition_jobs
                SET state = 'cancelled', updated_at = ?, completed_at = ?,
                    lease_until = NULL, worker_id = '', error_class = 'cancelled',
                    error_message = 'Edition cancelled before this desk phase ran.'
                WHERE run_id = ? AND state NOT IN ('published', 'reused', 'skipped', 'reviewed', 'held', 'dead_letter', 'cancelled')
                """,
                (now, now, str(run_id)),
            )
            conn.commit()
        else:
            conn.execute(
                """
                UPDATE edition_runs
                SET state = 'cancel_requested', updated_at = ?, last_heartbeat_at = ?,
                    cancel_requested_at = ?, failure_class = 'cancel_requested',
                    failure_message = 'Cancellation requested; the active desk will stop before publication.'
                WHERE run_id = ? AND completed_at IS NULL
                """,
                (now, now, now, str(run_id)),
            )
            conn.commit()
    finally:
        conn.close()
    return get_edition_run(str(run_id))


def cancel_edition_run(
    run_id: str,
    *,
    worker_id: str | None = None,
    message: str = "Edition cancelled before publication.",
) -> dict[str, Any] | None:
    """Close a cancellation request and suppress every in-flight job."""

    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        where = "run_id = ? AND completed_at IS NULL"
        values: list[Any] = [str(run_id)]
        if worker_id is not None:
            where += " AND worker_id = ? AND state IN ('running', 'cancel_requested')"
            values.append(str(worker_id))
        cursor = conn.execute(
            f"""
            UPDATE edition_runs
            SET state = 'cancelled', stage = 'cancelled', updated_at = ?,
                last_heartbeat_at = ?, completed_at = ?, lease_until = NULL,
                worker_id = '', failure_class = 'cancelled', failure_message = ?
            WHERE {where}
            """,
            (now, now, now, str(message), *values),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return get_edition_run(str(run_id))
        conn.execute(
            """
            UPDATE edition_jobs
            SET state = 'cancelled', updated_at = ?, completed_at = ?,
                lease_until = NULL, worker_id = '', error_class = 'cancelled',
                error_message = ?
            WHERE run_id = ? AND state NOT IN ('published', 'reused', 'skipped', 'reviewed', 'held', 'dead_letter', 'cancelled')
            """,
            (now, now, str(message), str(run_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return get_edition_run(str(run_id))


def claim_edition_job(
    run_id: str,
    article_key: str,
    worker_id: str,
    *,
    phase: str = "writer",
    evidence_fingerprint: str = "",
    prompt_version: str = "",
    provider: str = "",
    model: str = "",
    reasoning_effort: str = "",
    client_request_id: str = "",
    lease_seconds: int = 300,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Atomically claim one desk phase for the owner of an edition run."""

    worker = str(worker_id or "").strip()
    if not worker:
        raise ValueError("worker_id is required")
    seconds = max(1, min(int(lease_seconds), 3600))
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    lease = datetime.fromtimestamp(now_dt.timestamp() + seconds, timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute(
            "SELECT state, worker_id, lease_until, max_attempts, cancel_requested_at FROM edition_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if (
            run is None
            or str(run[0] or "").lower() != "running"
            or str(run[1] or "") != worker
            or _lease_is_expired(run[2], now_dt)
            or bool(run[4])
        ):
            conn.rollback()
            return None
        row = conn.execute(
            "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
            (str(run_id), str(article_key), str(phase)),
        ).fetchone()
        if row is not None:
            state = str(row["state"] or "").lower()
            current_owner = str(row["worker_id"] or "")
            expired = _lease_is_expired(row["lease_until"], now_dt)
            if state in {"dead_letter", "cancelled"}:
                conn.rollback()
                return _edition_job_row(row)
            if state in {"published", "reused", "skipped", "reviewed", "held"} or (state == "running" and current_owner != worker and not expired):
                conn.rollback()
                return None
            if state == "running" and current_owner == worker and not expired:
                conn.rollback()
                return _edition_job_row(row)
            max_attempts = max(1, int(run[3] or 2))
            if int(row["attempt"] or 0) >= max_attempts:
                conn.execute(
                    """
                    UPDATE edition_jobs
                    SET state = 'dead_letter', updated_at = ?, completed_at = ?,
                        lease_until = NULL, worker_id = '', error_class = 'retry_budget_exhausted',
                        error_message = ?
                    WHERE run_id = ? AND article_key = ? AND phase = ?
                    """,
                    (
                        now,
                        now,
                        f"Retry budget exhausted after {max_attempts} attempts.",
                        str(run_id),
                        str(article_key),
                        str(phase),
                    ),
                )
                conn.commit()
                return _edition_job_row(
                    conn.execute(
                        "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
                        (str(run_id), str(article_key), str(phase)),
                    ).fetchone()
                )
            conn.execute(
                """
                UPDATE edition_jobs
                SET state = 'running', attempt = attempt + 1, started_at = ?, updated_at = ?,
                    completed_at = NULL, lease_until = ?, worker_id = ?,
                    evidence_fingerprint = ?, prompt_version = ?, provider = ?, model = ?,
                    reasoning_effort = ?, client_request_id = COALESCE(NULLIF(?, ''), client_request_id), provider_request_id = '', usage_json = '{}',
                    metadata_json = ?, error_class = '', error_message = ''
                WHERE run_id = ? AND article_key = ? AND phase = ?
                """,
                (
                    now, now, lease, worker, str(evidence_fingerprint or ""),
                    str(prompt_version or ""), str(provider or ""), str(model or ""),
                    str(reasoning_effort or ""), str(client_request_id or ""),
                    json.dumps(metadata or {}, sort_keys=True),
                    str(run_id), str(article_key), str(phase),
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO edition_jobs(
                    run_id, article_key, phase, state, attempt, started_at, updated_at,
                    evidence_fingerprint, prompt_version, lease_until, worker_id,
                    provider, model, reasoning_effort, client_request_id, metadata_json
                ) VALUES (?, ?, ?, 'running', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id), str(article_key), str(phase), now, now,
                    str(evidence_fingerprint or ""), str(prompt_version or ""), lease, worker,
                    str(provider or ""), str(model or ""), str(reasoning_effort or ""),
                    str(client_request_id or ""),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
            (str(run_id), str(article_key), str(phase)),
        ).fetchone()
    finally:
        conn.close()
    return _edition_job_row(row) if row is not None else None


def finish_edition_job(
    run_id: str,
    article_key: str,
    *,
    phase: str = "writer",
    state: str,
    provider_request_id: str = "",
    usage: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    error_class: str = "",
    error_message: str = "",
    worker_id: str | None = None,
) -> dict[str, Any] | None:
    """Close a desk receipt while retaining safe provider telemetry."""

    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        where = "run_id = ? AND article_key = ? AND phase = ?"
        where_values: list[Any] = [str(run_id), str(article_key), str(phase)]
        if worker_id is not None:
            where += " AND worker_id = ? AND state = 'running'"
            where_values.append(str(worker_id))
        cursor = conn.execute(
            f"""
            UPDATE edition_jobs
            SET state = ?, updated_at = ?, completed_at = ?, provider_request_id = ?,
                lease_until = NULL, worker_id = '', usage_json = ?, metadata_json = ?,
                error_class = ?, error_message = ?
            WHERE {where}
            """,
            (
                str(state), now, now, str(provider_request_id or ""),
                json.dumps(usage or {}, sort_keys=True), json.dumps(metadata or {}, sort_keys=True),
                str(error_class or ""), str(error_message or ""),
                *where_values,
            ),
        )
        if worker_id is not None and cursor.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        row = conn.execute(
            "SELECT * FROM edition_jobs WHERE run_id = ? AND article_key = ? AND phase = ?",
            (str(run_id), str(article_key), str(phase)),
        ).fetchone()
    finally:
        conn.close()
    return _edition_job_row(row) if row is not None else None


def interrupt_edition_run(
    run_id: str,
    *,
    resume_stage: str = "",
    failure_message: str = "The worker stopped before the edition run reached a terminal publication state.",
    worker_id: str | None = None,
) -> dict[str, Any] | None:
    """Mark a run and only its in-flight jobs recoverable after a worker exit.

    When a worker supplies its identity, recovery is conditional on still
    owning the run.  A stale worker must not interrupt a run that another
    worker reclaimed after its lease expired.
    """

    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT metadata_json FROM edition_runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            return None
        try:
            metadata = json.loads(row[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        if resume_stage:
            metadata["resume_stage"] = str(resume_stage)
        where = "run_id = ? AND completed_at IS NULL"
        where_values: list[Any] = [str(run_id)]
        if worker_id is not None:
            where += " AND worker_id = ? AND state IN ('running', 'cancel_requested')"
            where_values.append(str(worker_id))
        cursor = conn.execute(
            """
            UPDATE edition_runs
            SET state = 'interrupted', stage = 'interrupted', updated_at = ?,
                last_heartbeat_at = ?, failure_class = 'worker_restart',
                failure_message = ?, metadata_json = ?, lease_until = NULL, worker_id = ''
            WHERE """ + where,
            (
                now,
                now,
                str(failure_message),
                json.dumps(metadata, sort_keys=True),
                *where_values,
            ),
        )
        if worker_id is not None and cursor.rowcount != 1:
            conn.rollback()
            return get_edition_run(str(run_id))
        job_where = "run_id = ? AND state = 'running'"
        job_values: list[Any] = [str(run_id)]
        if worker_id is not None:
            job_where += " AND worker_id = ?"
            job_values.append(str(worker_id))
        conn.execute(
            """
            UPDATE edition_jobs
            SET state = 'interrupted', updated_at = ?, completed_at = NULL,
                lease_until = NULL, worker_id = '',
                error_class = 'worker_restart', error_message = ?
            WHERE """ + job_where,
            (now, str(failure_message), *job_values),
        )
        conn.commit()
    finally:
        conn.close()
    return get_edition_run(str(run_id))


def replace_publication_edges(run_id: str, edges: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Persist the deterministic editorial graph for one private edition."""

    allowed_relationships = {"supports", "disputes", "extends", "asks", "supersedes", "held_because"}
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("DELETE FROM publication_edges WHERE run_id = ?", (str(run_id),))
        for raw in edges or []:
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("source_article_key") or "").strip()
            target = str(raw.get("target_article_key") or "").strip()
            relationship = str(raw.get("relationship") or "").strip().lower()
            if not source or not target or source == target or relationship not in allowed_relationships:
                continue
            evidence_ids = [
                str(value).strip()
                for value in (raw.get("source_evidence_ids") or [])
                if str(value).strip()
            ]
            conn.execute(
                """
                INSERT OR REPLACE INTO publication_edges(
                    run_id, source_article_key, target_article_key, relationship,
                    summary, source_evidence_ids_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    source,
                    target,
                    relationship,
                    str(raw.get("summary") or "")[:500],
                    json.dumps(evidence_ids[:40], sort_keys=True),
                    str(raw.get("status") or "visible") if str(raw.get("status") or "visible") in {"visible", "held", "stale"} else "visible",
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return list_publication_edges(str(run_id))


def list_publication_edges(run_id: str) -> list[dict[str, Any]]:
    """Read the private editorial graph without exposing another league's rows."""

    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM publication_edges WHERE run_id = ? ORDER BY id",
            (str(run_id),),
        ).fetchall()
    finally:
        conn.close()
    output: list[dict[str, Any]] = []
    for row in rows:
        payload = _row(row)
        raw = payload.pop("source_evidence_ids_json", "[]")
        try:
            evidence_ids = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            evidence_ids = []
        payload["source_evidence_ids"] = [str(value) for value in evidence_ids] if isinstance(evidence_ids, list) else []
        output.append(payload)
    return output


def get_edition_run(run_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM edition_runs WHERE run_id = ?", (str(run_id),)).fetchone()
        if row is None:
            return None
        payload = _edition_run_row(row)
        jobs = conn.execute(
            "SELECT * FROM edition_jobs WHERE run_id = ? ORDER BY id",
            (str(run_id),),
        ).fetchall()
        payload["jobs"] = [_edition_job_row(job) for job in jobs]
        payload["publication_edges"] = list_publication_edges(str(run_id))
        return payload
    finally:
        conn.close()


def latest_edition_run(user_id: int, league_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT run_id FROM edition_runs
            WHERE user_id = ? AND league_id = ?
            ORDER BY started_at DESC, rowid DESC LIMIT 1
            """,
            (int(user_id), str(league_id)),
        ).fetchone()
    finally:
        conn.close()
    return get_edition_run(str(row[0])) if row is not None else None


def _edition_run_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _row(row)
    for key in ("requested_article_keys_json", "metadata_json", "source_receipt_json"):
        raw = payload.pop(key, "{}")
        try:
            decoded = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            decoded = [] if key.endswith("keys_json") else {}
        payload[key.removesuffix("_json")] = decoded
    return payload


def _edition_job_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _row(row)
    for source, target in (("usage_json", "usage"), ("metadata_json", "metadata")):
        raw = payload.pop(source, "{}")
        try:
            decoded = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            decoded = {}
        payload[target] = decoded if isinstance(decoded, dict) else {}
    return payload


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
            SELECT id, clerk_user_id, sleeper_username, sleeper_user_id, created_at
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
            SELECT user_id, league_id, season, league_type, name, roster_id,
                   identity_status, identity_checked_at, enabled
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
            SELECT user_id, league_id, season, league_type, name, roster_id,
                   identity_status, identity_checked_at, enabled
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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Apply additive schema migrations without disturbing the durable store."""

    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _lease_is_expired(value: Any, now: datetime | None = None) -> bool:
    if not value:
        return True
    try:
        lease = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return True
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=timezone.utc)
    return lease <= (now or datetime.now(timezone.utc))


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _decode_json(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
