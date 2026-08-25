from __future__ import annotations

import sqlite3
import json
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
    "content_interactions",
    "refresh_runs",
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
            """
        )
        _ensure_column(conn, "users", "sleeper_user_id", "TEXT")
        _ensure_column(conn, "users", "selected_league_id", "TEXT")
        _ensure_column(conn, "user_leagues", "identity_status", "TEXT NOT NULL DEFAULT 'unverified'")
        _ensure_column(conn, "user_leagues", "identity_checked_at", "TEXT")
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
            SELECT user_id, league_id, season, league_type, name, roster_id,
                   identity_status, identity_checked_at, enabled
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
            SELECT user_id, league_id, season, league_type, name, roster_id,
                   identity_status, identity_checked_at, enabled
            FROM user_leagues
            WHERE user_id = ?
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


def upsert_team_profile(user_id: int, league_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Persist customization that belongs to one user's team in one league."""

    strategy = profile.get("strategy_profile", profile.get("strategy", {}))
    writer_preferences = normalize_writer_preferences(profile.get("writer_preferences", {}))
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


def content_artifact_status(
    user_id: int,
    league_id: str,
    season: str,
    artifact_type: str = "article",
    current_receipts: dict[str, dict[str, Any]] | None = None,
    current_bundle_revision: str = "",
) -> dict[str, Any]:
    """Return a safe, user-scoped receipt for generated writer output.

    The deterministic edition is always available, so the absence of an API
    artifact is not an error. It is still important to distinguish that
    fallback from a completed reporter run in the headquarters UI.
    """

    expected_keys = ("team_report", "market_watch", "trade_desk", "manager_intel", "daily_brief")
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT artifact_key, status, generated_at, updated_at, content_hash,
                   reporter_id, writer_mode, evidence_fingerprint, bundle_revision
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
        if current_receipts is None:
            return True
        receipt = current_receipts.get(str(row[0])) or {}
        return (
            str(receipt.get("mode") or "").lower() == "automatic_llm"
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
    generated_count = len(generated_keys)
    expected_count = len(expected_keys)
    if generated_count == expected_count:
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
        "last_generated_at": max(timestamps, default=""),
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
) -> dict[str, Any]:
    """Summarize deliberate feedback for one authenticated league scope."""

    rows = list_content_interactions(user_id, league_id, roster_id)
    feedback_types = {"useful", "not_useful", "evidence_opened", "saved", "pursued"}
    outcome_types = {"open", "confirmed", "missed", "unclear"}
    feedback = {name: 0 for name in sorted(feedback_types)}
    outcomes = {name: 0 for name in sorted(outcome_types)}
    artifacts: set[tuple[str, str]] = set()
    latest_recorded_at = ""

    for row in rows:
        interaction_type = str(row.get("interaction_type") or "")
        if interaction_type in feedback:
            feedback[interaction_type] += 1
        elif interaction_type == "outcome":
            outcome = str((row.get("payload") or {}).get("outcome") or "").strip().lower()
            if outcome in outcomes:
                outcomes[outcome] += 1
        artifacts.add((str(row.get("artifact_type") or ""), str(row.get("artifact_key") or "")))
        latest_recorded_at = max(latest_recorded_at, str(row.get("created_at") or ""))

    resolved = outcomes["confirmed"] + outcomes["missed"]
    return {
        "league_id": str(league_id),
        "roster_id": int(roster_id) if roster_id is not None else None,
        "interaction_count": len(rows),
        "artifact_count": len(artifacts),
        "feedback_counts": feedback,
        "outcome_counts": outcomes,
        "resolved_outcomes": resolved,
        "confirmed_rate": round(outcomes["confirmed"] / resolved, 3) if resolved else None,
        "latest_recorded_at": latest_recorded_at,
    }


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


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _decode_json(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
