from __future__ import annotations

"""Read-only audit for the local processed facts and analyst artifacts.

This deliberately does not refresh anything.  It is the cheap check to run
after a refresh and before trusting the browser edition for draft decisions.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_TABLES = {
    "refresh_metadata": ("generated_at", "current_season", "analysis_artifacts_status"),
    "matchup_player_points": (
        "season", "league_id", "week", "matchup_id", "roster_id", "player_id",
        "player_name", "position", "team_name", "opponent_roster_id",
        "is_starter", "player_points", "matchup_status", "source_trace", "evidence",
    ),
    "news_events": ("source", "event_id", "published_at", "source_trace"),
    "news_source_freshness": ("source", "dataset", "status", "checked_at"),
    "source_freshness": ("source", "dataset", "status", "checked_at"),
    "projection_source_freshness": ("source", "dataset", "status", "checked_at"),
    "today_priority_board": ("source_trace",),
    "player_dossiers": ("source_trace",),
    "league_news_impact": ("source_trace",),
    "player_signal_scores": ("source_trace",),
    "player_opportunity_scores": ("league_id", "player_id", "roster_id", "source_trace"),
    "player_projection_season": (
        "season", "player_id", "player_name", "position", "team",
        "availability_scope", "current_availability_status", "availability_note",
        "projected_ppg", "projection_method", "projection_confidence",
        "source_trace", "projection_note",
    ),
    "player_projection_weekly": (
        "season", "week", "player_id", "player_name", "position", "team",
        "availability_scope", "current_availability_status", "availability_note",
        "projected_fantasy_points", "projection_method", "projection_confidence",
        "source_trace",
    ),
    "projection_source_components": (
        "season", "player_id", "player_name", "position", "team",
        "availability_scope", "current_availability_status", "availability_note",
        "source", "projected_fantasy_points", "projected_ppg", "source_confidence",
        "source_trace", "checked_at",
    ),
    "player_horizon_market_scores": ("league_id", "horizon_model_version", "horizon_score_basis", "market_value", "market_percentile", "next_game_status", "next_game_matchup_adjustment_status", "next_game_minus_market_delta", "rest_of_season_status", "rest_of_season_minus_market_delta", "rest_of_season_minus_next_game_delta", "dynasty_status", "dynasty_minus_market_delta", "dynasty_minus_rest_of_season_delta", "career_projection_status", "career_projection_basis", "career_history_join_method", "career_history_source_player_id", "career_history_status", "career_history_seasons", "career_history_games", "career_history_ppg", "career_history_latest_season", "career_minus_market_delta", "career_minus_dynasty_delta", "fit_coverage", "fit_basis", "evidence", "risk", "confidence", "source_trace"),
}

REQUIRED_ANALYSIS = "analysis_validation.json"
CURRENT_STATUSES = {"refreshed", "cached"}
PROJECTION_AVAILABILITY_SCOPES = {"current_season_snapshot", "historical_unavailable"}
PROJECTION_AVAILABILITY_STATUSES = {
    "available",
    "injury_out",
    "injury_doubtful",
    "injury_questionable",
    "injury_flagged",
    "no_current_nfl_team",
    "historical_unavailable",
    "unknown",
}
PLAYER_HISTORY_IDENTITY_METHODS = {"source_id", "normalized_name", "ambiguous_name", "unmatched_name"}
HORIZON_SCORE_FIELDS = (
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
    "contender_fit_score",
    "rebuilder_fit_score",
)
HORIZON_DELTA_FIELDS = {
    "rest_of_season_minus_next_game_delta": ("next_game_market_score", "rest_of_season_market_score"),
    "dynasty_minus_rest_of_season_delta": ("rest_of_season_market_score", "dynasty_market_score"),
    "career_minus_dynasty_delta": ("dynasty_market_score", "career_projection_score"),
}
HORIZON_MARKET_DELTA_FIELDS = {
    "next_game_minus_market_delta": "next_game_market_score",
    "rest_of_season_minus_market_delta": "rest_of_season_market_score",
    "dynasty_minus_market_delta": "dynasty_market_score",
    "career_minus_market_delta": "career_projection_score",
}
COUNTERPARTY_HORIZON_SCORE_FIELDS = {
    "next_game_market_score": "next_game_market_score",
    "rest_of_season_market_score": "rest_of_season_market_score",
    "dynasty_market_score": "dynasty_market_score",
    "career_projection_score": "career_projection_score",
}
COUNTERPARTY_HORIZON_MARKET_FIELDS = {
    "horizon_market_percentile": "market_percentile",
    "next_game_minus_market_delta": "next_game_minus_market_delta",
    "rest_of_season_minus_market_delta": "rest_of_season_minus_market_delta",
    "dynasty_minus_market_delta": "dynasty_minus_market_delta",
    "career_minus_market_delta": "career_minus_market_delta",
    "rest_of_season_minus_next_game_delta": "rest_of_season_minus_next_game_delta",
    "dynasty_minus_rest_of_season_delta": "dynasty_minus_rest_of_season_delta",
    "career_minus_dynasty_delta": "career_minus_dynasty_delta",
}
COUNTERPARTY_HORIZON_CONTEXT_COLUMNS = (
    *COUNTERPARTY_HORIZON_SCORE_FIELDS,
    *COUNTERPARTY_HORIZON_MARKET_FIELDS,
    "horizon_market_disagreement_window",
    "horizon_market_disagreement_delta",
    "horizon_market_disagreement_magnitude",
    "horizon_market_disagreement_read",
)
HORIZON_VALUE_LANES = {"rebuilder_edge", "contender_edge", "balanced_window", "insufficient_context"}
HORIZON_SNAPSHOT_COLUMNS = {
    "snapshot_at",
    "snapshot_scope",
    "season",
    "league_id",
    "as_of_week",
    "player_id",
    "player_name",
    "position",
    "horizon_model_version",
    "market_value",
    "market_percentile",
    "market_source_count",
    "market_disagreement_score",
    "market_source_confidence",
    *HORIZON_SCORE_FIELDS,
    *HORIZON_MARKET_DELTA_FIELDS,
    "fit_coverage",
    "value_lane",
    "source_trace",
}
HORIZON_ACCURACY_COLUMNS = {
    "horizon_model_version",
    "horizon",
    "score_field",
    "position",
    "outcome",
    "n_snapshots",
    "n_player_snapshots",
    "spearman_rank_correlation",
    "cohort_mean_outcome",
    "top_quartile_mean_outcome",
    "top_quartile_lift",
    "evaluation_status",
    "confidence",
    "evidence",
    "source_trace",
}
HORIZON_ACCURACY_SCORE_FIELDS = {
    "next_game_market_score",
    "rest_of_season_market_score",
}
HORIZON_MOVEMENT_COLUMNS = {
    "snapshot_scope",
    "league_id",
    "season",
    "player_id",
    "player_name",
    "position",
    "horizon_model_version",
    "prior_snapshot_at",
    "current_snapshot_at",
    "prior_as_of_week",
    "current_as_of_week",
    "prior_market_value",
    "market_value",
    "market_value_delta",
    "prior_market_percentile",
    "market_percentile",
    "market_percentile_delta",
    "prior_next_game_market_score",
    "next_game_market_score",
    "next_game_score_delta",
    "prior_rest_of_season_market_score",
    "rest_of_season_market_score",
    "rest_of_season_score_delta",
    "prior_dynasty_market_score",
    "dynasty_market_score",
    "dynasty_score_delta",
    "prior_career_projection_score",
    "career_projection_score",
    "career_score_delta",
    "prior_contender_fit_score",
    "contender_fit_score",
    "contender_fit_delta",
    "prior_rebuilder_fit_score",
    "rebuilder_fit_score",
    "rebuilder_fit_delta",
    "prior_rebuilder_contender_spread",
    "rebuilder_contender_spread",
    "rebuilder_contender_spread_delta",
    "prior_value_lane",
    "value_lane",
    "value_lane_change",
    "largest_clock_movement_window",
    "largest_clock_movement_delta",
    "largest_clock_movement_magnitude",
    "movement_status",
    "evidence",
    "source_trace",
}
HORIZON_MOVEMENT_STATUS = {"changed", "unchanged"}
HORIZON_MOVEMENT_WINDOWS = {"this_week", "rest_of_season", "dynasty", "career_window"}
HORIZON_MOVEMENT_DELTAS = (
    ("market_value", "market_value_delta"),
    ("market_percentile", "market_percentile_delta"),
    ("next_game_market_score", "next_game_score_delta"),
    ("rest_of_season_market_score", "rest_of_season_score_delta"),
    ("dynasty_market_score", "dynasty_score_delta"),
    ("career_projection_score", "career_score_delta"),
    ("contender_fit_score", "contender_fit_delta"),
    ("rebuilder_fit_score", "rebuilder_fit_delta"),
    ("rebuilder_contender_spread", "rebuilder_contender_spread_delta"),
)

REQUIRED_TABLES["player_horizon_market_scores"] = REQUIRED_TABLES["player_horizon_market_scores"] + (
    "market_source_count",
    "market_disagreement_score",
    "market_source_confidence",
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
    "contender_fit_score",
    "rebuilder_fit_score",
    "value_lane",
)


def _audit_matchup_player_points(rows: list[dict[str, str]], errors: list[str]) -> None:
    """Check player receipts stay unique and reconcile played/unplayed state."""

    keys = [
        (
            str(row.get("season") or "").strip(),
            str(row.get("league_id") or "").strip(),
            str(row.get("week") or "").strip(),
            str(row.get("matchup_id") or "").strip(),
            str(row.get("roster_id") or "").strip(),
            str(row.get("player_id") or "").strip(),
        )
        for row in rows
    ]
    duplicate_keys = sorted({key for key in keys if key[-1] and keys.count(key) > 1})
    if duplicate_keys:
        errors.append(
            "matchup_player_points.csv contains duplicate source keys: "
            + ", ".join("/".join(key) for key in duplicate_keys[:5])
        )
    allowed_statuses = {"played", "unplayed"}
    invalid_statuses = sorted({str(row.get("matchup_status") or "").strip() for row in rows if str(row.get("matchup_status") or "").strip() not in allowed_statuses})
    if invalid_statuses:
        errors.append(
            "matchup_player_points.csv contains unsupported matchup_status values: "
            + ", ".join(invalid_statuses[:5])
        )
    inconsistent_rows = [
        row for row in rows
        if str(row.get("matchup_status") or "").strip() == "unplayed"
        and str(row.get("player_points") or "").strip() not in {"", "0", "0.0", "0.00"}
    ]
    if inconsistent_rows:
        errors.append("matchup_player_points.csv has non-zero player points on unplayed matchup rows")


def _audit_projection_availability(
    tables: dict[str, list[dict[str, str]]],
    errors: list[str],
) -> None:
    """Keep projection availability status and reader caveats semantically aligned."""

    for table in ("player_projection_season", "player_projection_weekly", "projection_source_components"):
        for row in tables.get(table, []):
            player = str(row.get("player_name") or row.get("player_id") or "unknown player")
            scope = str(row.get("availability_scope") or "").strip().lower()
            status = str(row.get("current_availability_status") or "").strip().lower()
            note = str(row.get("availability_note") or "").strip().lower()
            if not scope:
                errors.append(f"{table}.csv has no availability_scope for {player}")
            elif scope not in PROJECTION_AVAILABILITY_SCOPES:
                errors.append(f"{table}.csv has unknown availability_scope {scope!r} for {player}")
            if not status:
                errors.append(f"{table}.csv has no current_availability_status for {player}")
            elif status not in PROJECTION_AVAILABILITY_STATUSES:
                errors.append(f"{table}.csv has unknown current_availability_status {status!r} for {player}")
            if not note:
                errors.append(f"{table}.csv has no availability_note for {player}")
            if status == "no_current_nfl_team" and "conditional on signing" not in note:
                errors.append(
                    f"{table}.csv marks {player} as no_current_nfl_team without a signing caveat"
                )
            if (
                table == "player_projection_season"
                and status == "no_current_nfl_team"
                and "historical production evidence" not in str(row.get("projection_note") or "").lower()
            ):
                errors.append(
                    f"player_projection_season.csv marks {player} as no_current_nfl_team without historical-production context"
                )


def audit_local_data(
    processed_dir: Path,
    analysis_dir: Path,
    *,
    now: datetime | None = None,
    max_age_hours: float = 36.0,
) -> dict[str, Any]:
    """Return a machine-readable audit without changing any project data."""

    processed_dir = Path(processed_dir)
    analysis_dir = Path(analysis_dir)
    errors: list[str] = []
    warnings: list[str] = []
    tables: dict[str, list[dict[str, str]]] = {}
    table_counts: dict[str, int] = {}

    for table, required_columns in REQUIRED_TABLES.items():
        path = processed_dir / f"{table}.csv"
        rows, read_error = _read_csv(path)
        if read_error:
            errors.append(read_error)
            continue
        tables[table] = rows
        table_counts[table] = len(rows)
        missing = [column for column in required_columns if column not in (rows[0].keys() if rows else ())]
        if missing:
            errors.append(f"{table}.csv is missing columns: {', '.join(missing)}")
        if not rows:
            errors.append(f"{table}.csv has no rows")

    _audit_projection_availability(tables, errors)
    _audit_matchup_player_points(tables.get("matchup_player_points", []), errors)
    _audit_opportunity_scope(tables.get("player_opportunity_scores", []), tables.get("refresh_metadata", []), errors)

    player_history_identity = _audit_player_history(processed_dir / "player_transaction_history.csv", errors, warnings)
    if player_history_identity is not None:
        table_counts["player_transaction_history"] = player_history_identity["row_count"]
    horizon_history_identity = _audit_horizon_history(tables.get("player_horizon_market_scores", []), errors, warnings)
    horizon_score_quality = _audit_horizon_scores(tables.get("player_horizon_market_scores", []), errors, warnings)
    transaction_lane_quality = _audit_manager_transaction_preferences(
        processed_dir / "manager_transaction_preferences.csv",
        errors,
        warnings,
    )
    if transaction_lane_quality is not None:
        table_counts["manager_transaction_preferences"] = transaction_lane_quality["row_count"]
    counterparty_interest_quality = _audit_counterparty_asset_interest(
        processed_dir / "counterparty_asset_interest.csv",
        errors,
        warnings,
    )
    if counterparty_interest_quality is not None:
        table_counts["counterparty_asset_interest"] = counterparty_interest_quality["row_count"]
    counterparty_edge_quality = _audit_counterparty_horizon_context(
        processed_dir / "counterparty_trade_edges.csv",
        processed_dir / "player_horizon_market_scores.csv",
        errors,
        warnings,
        roster_column="target_roster_id",
        player_column="player_id",
    )
    if counterparty_edge_quality is not None:
        table_counts["counterparty_trade_edges"] = counterparty_edge_quality["row_count"]
    counterparty_interest_horizon_quality = _audit_counterparty_horizon_context(
        processed_dir / "counterparty_asset_interest.csv",
        processed_dir / "player_horizon_market_scores.csv",
        errors,
        warnings,
        roster_column="active_roster_id",
        player_column="asset_id",
    )
    available_horizon_quality = _audit_available_horizon(
        processed_dir / "available_player_horizon_scores.csv",
        errors,
        warnings,
    )
    if available_horizon_quality is not None:
        table_counts["available_player_horizon_scores"] = available_horizon_quality["row_count"]
    horizon_snapshot_quality = _audit_horizon_snapshot_history(
        processed_dir / "horizon_snapshot_history.csv",
        errors,
        warnings,
    )
    if horizon_snapshot_quality is not None:
        table_counts["horizon_snapshot_history"] = horizon_snapshot_quality["row_count"]
    horizon_accuracy_quality = _audit_horizon_accuracy(
        processed_dir / "horizon_score_accuracy.csv",
        errors,
        warnings,
    )
    if horizon_accuracy_quality is not None:
        table_counts["horizon_score_accuracy"] = horizon_accuracy_quality["row_count"]
    horizon_movement_quality = _audit_horizon_movements(
        processed_dir / "horizon_market_movements.csv",
        errors,
        warnings,
    )
    if horizon_movement_quality is not None:
        table_counts["horizon_market_movements"] = horizon_movement_quality["row_count"]

    metadata = (tables.get("refresh_metadata") or [{}])[0]
    generated_at = str(metadata.get("generated_at") or "")
    age_hours = _age_hours(generated_at, now=now)
    freshness_margin_hours = None
    if not generated_at:
        errors.append("refresh_metadata.csv has no generated_at timestamp")
    elif age_hours is None:
        errors.append(f"refresh_metadata.generated_at is not parseable: {generated_at}")
    else:
        freshness_margin_hours = max_age_hours - age_hours
        if freshness_margin_hours < 0:
            errors.append(f"processed data is {age_hours:.1f} hours old; maximum is {max_age_hours:g} hours")
        elif freshness_margin_hours < max_age_hours * 0.25:
            warnings.append(
                f"processed data freshness margin is only {freshness_margin_hours:.1f} hours; "
                f"warning floor is {max_age_hours * 0.25:.1f} hours"
            )

    if str(metadata.get("analysis_artifacts_status") or "").lower() not in {"generated", "complete"}:
        errors.append("refresh metadata does not report generated analysis artifacts")

    news_rows = tables.get("news_events", [])
    if not news_rows:
        errors.append("news_events.csv has no imported news rows")
    event_ids = [str(row.get("event_id") or "").strip() for row in news_rows]
    duplicate_ids = sorted({event_id for event_id in event_ids if event_id and event_ids.count(event_id) > 1})
    if duplicate_ids:
        errors.append(f"news_events.csv contains duplicate event IDs: {', '.join(duplicate_ids[:5])}")
    if news_rows and not any(str(row.get("source_trace") or "").strip() for row in news_rows):
        errors.append("news_events.csv has rows but no source traces")

    # Design source: docs/data_contract.md; current news may fan out across
    # current leagues, but it cannot become evidence for a completed season.
    current_season = str(metadata.get("current_season") or "").strip()
    impact_rows = tables.get("league_news_impact", [])
    historical_news_seasons = sorted(
        {
            str(row.get("season") or "").strip()
            for row in impact_rows
            if current_season
            and str(row.get("season") or "").strip()
            and str(row.get("season") or "").strip() != current_season
        }
    )
    if historical_news_seasons:
        errors.append(
            "league_news_impact.csv attaches current news to non-current season(s): "
            + ", ".join(historical_news_seasons[:5])
        )

    source_summary: list[dict[str, Any]] = []
    for table in ("source_freshness", "news_source_freshness", "projection_source_freshness"):
        rows = tables.get(table, [])
        current = 0
        limited: list[str] = []
        for row in rows:
            status = str(row.get("status") or "").strip().lower()
            if status in CURRENT_STATUSES:
                current += 1
            elif status.startswith("disabled"):
                warnings.append(f"{table}: {row.get('source') or 'source'} is explicitly disabled ({status})")
                limited.append(str(row.get("source") or "source"))
            else:
                limited.append(str(row.get("source") or "source"))
                warnings.append(f"{table}: {row.get('source') or 'source'} is limited ({status or 'unknown'})")
        if rows and current == 0:
            errors.append(f"{table} has no current or cached source")
        source_summary.append({"table": table, "current": current, "total": len(rows), "limited": limited})

    for table in ("today_priority_board", "player_dossiers", "league_news_impact", "player_signal_scores", "player_opportunity_scores", "player_horizon_market_scores", "available_player_horizon_scores", "nfl_schedule", "nfl_team_defense_factors"):
        rows = tables.get(table, [])
        if rows and not all(str(row.get("source_trace") or "").strip() for row in rows):
            errors.append(f"{table}.csv contains rows without source_trace")

    analysis_path = analysis_dir / REQUIRED_ANALYSIS
    analysis: dict[str, Any] = {}
    if not analysis_path.is_file():
        errors.append(f"missing {analysis_path.name}")
    else:
        try:
            payload = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"could not read {analysis_path.name}: {exc}")
        else:
            if not isinstance(payload, dict):
                errors.append(f"{analysis_path.name} is not a JSON object")
            else:
                items = payload.get("items")
                valid_items = (
                    isinstance(items, list)
                    and bool(items)
                    and all(bool(item.get("valid")) and not item.get("errors") for item in items if isinstance(item, dict))
                    and all(isinstance(item, dict) for item in items)
                )
                analysis = {
                    "valid": payload.get("generation_mode") == "deterministic_template" and valid_items,
                    "generation_mode": payload.get("generation_mode", ""),
                    "item_count": len(items) if isinstance(items, list) else 0,
                }
                if not analysis["valid"]:
                    errors.append(f"{analysis_path.name} reports invalid analysis artifacts")

    return {
        "ok": not errors,
        "processed_dir": str(processed_dir),
        "analysis_dir": str(analysis_dir),
        "generated_at": generated_at,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "freshness_margin_hours": round(freshness_margin_hours, 2)
        if freshness_margin_hours is not None
        else None,
        "freshness_warning_floor_hours": round(max_age_hours * 0.25, 2),
        "table_counts": table_counts,
        "player_history_identity": player_history_identity,
        "horizon_history_identity": horizon_history_identity,
        "horizon_score_quality": horizon_score_quality,
        "manager_transaction_preferences": transaction_lane_quality,
        "counterparty_asset_interest": counterparty_interest_quality,
        "counterparty_trade_edges": counterparty_edge_quality,
        "counterparty_asset_interest_horizon": counterparty_interest_horizon_quality,
        "available_player_horizon_scores": available_horizon_quality,
        "horizon_snapshot_history": horizon_snapshot_quality,
        "horizon_score_accuracy": horizon_accuracy_quality,
        "horizon_market_movements": horizon_movement_quality,
        "news_event_count": len(news_rows),
        "source_summary": source_summary,
        "analysis": analysis,
        "errors": errors,
        "warnings": warnings,
    }


def _audit_manager_transaction_preferences(
    path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    """Check the optional manager transaction-lane receipt when generated."""

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False}
    required = {
        "owner_id",
        "roster_id",
        "position_group",
        "acquired_count",
        "sold_count",
        "horizon_coverage",
        "history_status",
        "confidence",
        "evidence",
        "source_trace",
    }
    missing = sorted(required - set(rows[0].keys() if rows else ()))
    if missing:
        errors.append(f"manager_transaction_preferences.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False}
    if not rows:
        warnings.append("manager_transaction_preferences.csv has no rows; manager dossiers have no resolved transaction lanes")
        return {"row_count": 0, "valid": True}
    invalid_status = sorted({str(row.get("history_status") or "") for row in rows} - {"supported", "sparse"})
    if invalid_status:
        errors.append(
            "manager_transaction_preferences.csv has invalid history_status values: "
            + ", ".join(value or "blank" for value in invalid_status)
        )
    if any(not str(row.get("source_trace") or "").strip() for row in rows):
        errors.append("manager_transaction_preferences.csv contains rows without source_trace")
    return {
        "row_count": len(rows),
        "valid": not invalid_status and all(str(row.get("source_trace") or "").strip() for row in rows),
        "history_status_counts": {
            status: sum(1 for row in rows if str(row.get("history_status") or "") == status)
            for status in sorted({str(row.get("history_status") or "") for row in rows})
        },
    }


def _audit_counterparty_asset_interest(
    path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    """Check the optional active-asset audience receipt when generated."""

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False}
    required = {
        "active_roster_id",
        "asset_id",
        "target_roster_id",
        "transaction_lane_read",
        "conversation_fit_score",
        "conversation_fit_label",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    }
    missing = sorted(required - set(rows[0].keys() if rows else ()))
    if missing:
        errors.append(f"counterparty_asset_interest.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False}
    if not rows:
        warnings.append("counterparty_asset_interest.csv has no rows; no active-asset audience is supported")
        return {"row_count": 0, "valid": True, "confidence_counts": {}}

    invalid_labels = sorted(
        {
            str(row.get("conversation_fit_label") or "")
            for row in rows
        }
        - {"strong_conversation_fit", "watch_conversation_fit", "limited_conversation_fit"}
    )
    if invalid_labels:
        errors.append(
            "counterparty_asset_interest.csv has invalid conversation_fit_label values: "
            + ", ".join(value or "blank" for value in invalid_labels)
        )
    for row in rows:
        try:
            score = float(str(row.get("conversation_fit_score") or ""))
        except (TypeError, ValueError):
            errors.append("counterparty_asset_interest.csv contains a non-numeric conversation_fit_score")
            break
        if not 0 <= score <= 100:
            errors.append("counterparty_asset_interest.csv contains a conversation_fit_score outside 0-100")
            break
        if str(row.get("active_roster_id") or "") == str(row.get("target_roster_id") or ""):
            errors.append("counterparty_asset_interest.csv contains the active roster as its own target")
            break
    if any(not str(row.get("source_trace") or "").strip() for row in rows):
        errors.append("counterparty_asset_interest.csv contains rows without source_trace")
    return {
        "row_count": len(rows),
        "valid": not invalid_labels
        and all(str(row.get("source_trace") or "").strip() for row in rows)
        and not any(
            str(row.get("active_roster_id") or "") == str(row.get("target_roster_id") or "")
            for row in rows
        ),
        "confidence_counts": {
            confidence: sum(1 for row in rows if str(row.get("confidence") or "") == confidence)
            for confidence in sorted({str(row.get("confidence") or "") for row in rows})
        },
    }


def _audit_counterparty_horizon_context(
    path: Path,
    horizon_path: Path,
    errors: list[str],
    warnings: list[str],
    *,
    roster_column: str,
    player_column: str,
) -> dict[str, Any] | None:
    """Verify copied counterparty clocks still match the canonical horizon row.

    Counterparty tables are downstream projections.  They may add audience or
    manager context, but their copied horizon fields must not become a second
    source of truth through hand-edits, stale joins, or accidental recompute.
    Older fixtures without these optional columns remain valid; generated
    tables that expose the seam are checked fail-closed.
    """

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False, "status": "read_error"}
    if not rows:
        return {"row_count": 0, "valid": True, "status": "empty"}
    present = set(rows[0].keys())
    if not any(field in present for field in COUNTERPARTY_HORIZON_CONTEXT_COLUMNS):
        return {"row_count": len(rows), "valid": True, "status": "not_present"}
    missing = sorted(set(COUNTERPARTY_HORIZON_CONTEXT_COLUMNS) - present)
    if missing:
        errors.append(f"{path.name} is missing copied horizon columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False, "status": "missing_columns"}

    horizon_rows, horizon_error = _read_csv(horizon_path)
    if horizon_error:
        errors.append(horizon_error)
        return {"row_count": len(rows), "valid": False, "status": "horizon_unavailable"}
    horizon_by_key = {
        (str(row.get("player_id") or "").strip(), str(row.get("roster_id") or "").strip()): row
        for row in horizon_rows
        if str(row.get("player_id") or "").strip() and str(row.get("roster_id") or "").strip()
    }
    invalid_rows = 0
    joined_rows = 0
    for row in rows:
        populated = any(str(row.get(field) or "").strip() for field in COUNTERPARTY_HORIZON_CONTEXT_COLUMNS)
        if not populated:
            continue
        player = str(row.get(player_column) or "").strip()
        roster = str(row.get(roster_column) or "").strip()
        canonical = horizon_by_key.get((player, roster))
        if canonical is None:
            errors.append(
                f"{path.name} has copied horizon context without a canonical player/roster join: {player or 'blank'} / {roster or 'blank'}"
            )
            invalid_rows += 1
            continue
        joined_rows += 1
        row_invalid = False

        def compare_numeric(output_field: str, canonical_field: str) -> None:
            nonlocal row_invalid
            actual_raw = str(row.get(output_field) or "").strip()
            expected_raw = str(canonical.get(canonical_field) or "").strip()
            actual = _float_or_none(actual_raw) if actual_raw else None
            expected = _float_or_none(expected_raw) if expected_raw else None
            if (actual is None) != (expected is None) or (
                actual is not None and expected is not None and abs(actual - expected) > 0.011
            ):
                errors.append(
                    f"{path.name} {output_field} does not match canonical horizon evidence for {player}: {actual_raw or 'blank'} vs {expected_raw or 'blank'}"
                )
                row_invalid = True

        for output_field, canonical_field in COUNTERPARTY_HORIZON_SCORE_FIELDS.items():
            compare_numeric(output_field, canonical_field)
        for output_field, canonical_field in COUNTERPARTY_HORIZON_MARKET_FIELDS.items():
            compare_numeric(output_field, canonical_field)

        comparable = []
        for window, delta_field in (
            ("this_week", "next_game_minus_market_delta"),
            ("rest_of_season", "rest_of_season_minus_market_delta"),
            ("dynasty", "dynasty_minus_market_delta"),
            ("career_window", "career_minus_market_delta"),
        ):
            delta = _float_or_none(canonical.get(delta_field))
            if delta is not None:
                comparable.append((window, round(delta, 2)))
        expected_window = ""
        expected_delta: float | None = None
        expected_read = ""
        if comparable:
            expected_window, expected_delta = max(comparable, key=lambda item: abs(item[1]))
            expected_read = "clock_leads_market" if expected_delta > 0 else "market_leads_clock" if expected_delta < 0 else "near_market"
        actual_window = str(row.get("horizon_market_disagreement_window") or "").strip()
        actual_delta = _float_or_none(row.get("horizon_market_disagreement_delta"))
        actual_magnitude = _float_or_none(row.get("horizon_market_disagreement_magnitude"))
        actual_read = str(row.get("horizon_market_disagreement_read") or "").strip()
        if actual_window != expected_window or (
            (actual_delta is None) != (expected_delta is None)
            or (actual_delta is not None and expected_delta is not None and abs(actual_delta - expected_delta) > 0.011)
            or (actual_magnitude is None) != (expected_delta is None)
            or (actual_magnitude is not None and expected_delta is not None and abs(actual_magnitude - abs(expected_delta)) > 0.011)
            or actual_read != expected_read
        ):
            errors.append(
                f"{path.name} horizon_market_disagreement summary does not reconcile for {player}"
            )
            row_invalid = True
        if row_invalid:
            invalid_rows += 1

    if rows and joined_rows == 0 and any(
        any(str(row.get(field) or "").strip() for field in COUNTERPARTY_HORIZON_CONTEXT_COLUMNS)
        for row in rows
    ):
        warnings.append(f"{path.name} has no usable canonical horizon joins")
    return {
        "row_count": len(rows),
        "joined_rows": joined_rows,
        "invalid_rows": invalid_rows,
        "valid": invalid_rows == 0,
        "status": "validated",
    }


def _audit_available_horizon(
    path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    """Check the optional available-market clock table and its seam receipts."""

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False}
    required = {
        "league_id",
        "availability_status",
        "identity_status",
        "market_value",
        "market_source_count",
        "market_disagreement_score",
        "market_source_confidence",
        "fit_coverage",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    }
    missing = sorted(required - set(rows[0].keys() if rows else ()))
    if missing:
        errors.append(f"available_player_horizon_scores.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False}
    if not rows:
        warnings.append("available_player_horizon_scores.csv has no rows; no canonical market names were proven available")
        return {"row_count": 0, "valid": True}

    receipt_invalid = 0
    receipt_counts = {"complete": 0, "unavailable": 0, "invalid": 0}
    for row in rows:
        player = row.get("player_name") or row.get("player_id") or "unnamed player"
        receipt_status = _audit_market_quality_receipt(
            row, "available_player_horizon_scores.csv", player, errors
        )
        receipt_counts[receipt_status] += 1
        if receipt_status != "complete":
            receipt_invalid += 1

    allowed_identity = {"sleeper_id", "sleeper_unique_name_match"}
    invalid_identity = sorted({str(row.get("identity_status") or "") for row in rows} - allowed_identity)
    invalid_availability = sorted(
        {
            str(row.get("availability_status") or "")
            for row in rows
        }
        - {"not_rostered_in_selected_league"}
    )
    if invalid_identity:
        errors.append(
            "available_player_horizon_scores.csv has unresolved identity rows: "
            + ", ".join(value or "blank" for value in invalid_identity)
        )
    if invalid_availability:
        errors.append(
            "available_player_horizon_scores.csv has invalid availability status: "
            + ", ".join(value or "blank" for value in invalid_availability)
        )
    if any(not str(row.get("league_id") or "").strip() for row in rows):
        errors.append("available_player_horizon_scores.csv contains rows without league_id")
    if any(not str(row.get("player_id") or "").strip() for row in rows):
        errors.append("available_player_horizon_scores.csv contains rows without Sleeper player_id")
    if any(not str(row.get("source_trace") or "").strip() for row in rows):
        errors.append("available_player_horizon_scores.csv contains rows without source_trace")
    return {
        "row_count": len(rows),
        "valid": not invalid_identity
        and not invalid_availability
        and receipt_invalid == 0
        and all(str(row.get("league_id") or "").strip() for row in rows)
        and all(str(row.get("player_id") or "").strip() for row in rows)
        and all(str(row.get("source_trace") or "").strip() for row in rows),
        "identity_status_counts": {
            status: sum(1 for row in rows if str(row.get("identity_status") or "") == status)
            for status in sorted({str(row.get("identity_status") or "") for row in rows})
        },
        "market_receipt_counts": receipt_counts,
    }


def _audit_horizon_snapshot_history(
    path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    """Check the append-only record that makes horizon evaluation possible."""

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False}
    columns = set(rows[0].keys() if rows else _csv_header(path))
    missing = sorted(HORIZON_SNAPSHOT_COLUMNS - columns)
    if missing:
        errors.append(f"horizon_snapshot_history.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False}
    if not rows:
        warnings.append("horizon_snapshot_history.csv has no rows; no dated horizon beliefs are retained")
        return {"row_count": 0, "valid": True, "duplicate_keys": 0}

    key_columns = (
        "snapshot_scope",
        "season",
        "as_of_week",
        "player_id",
        "position",
        "horizon_model_version",
    )
    keys = [tuple(str(row.get(column) or "").strip() for column in key_columns) for row in rows]
    duplicate_keys = len(keys) - len(set(keys))
    if duplicate_keys:
        errors.append(f"horizon_snapshot_history.csv contains {duplicate_keys} duplicate dated player keys")
    receipt_invalid = False
    for row in rows:
        player = row.get("player_name") or row.get("player_id") or "unnamed player"
        for field in ("season", "league_id", "as_of_week", "player_id", "position", "horizon_model_version"):
            if not str(row.get(field) or "").strip():
                errors.append(f"horizon_snapshot_history.csv contains a row without {field} for {player}")
                receipt_invalid = True
        if not str(row.get("snapshot_at") or "").strip():
            errors.append(f"horizon_snapshot_history.csv contains a row without snapshot_at for {player}")
            receipt_invalid = True
        if not str(row.get("snapshot_scope") or "").strip():
            errors.append(f"horizon_snapshot_history.csv contains a row without snapshot_scope for {player}")
            receipt_invalid = True
        if not str(row.get("source_trace") or "").strip():
            errors.append(f"horizon_snapshot_history.csv contains a row without source_trace for {player}")
            receipt_invalid = True
        if _audit_market_quality_receipt(
            row, "horizon_snapshot_history.csv", player, errors
        ) == "invalid":
            receipt_invalid = True
        for field in HORIZON_SCORE_FIELDS:
            raw = str(row.get(field) or "").strip()
            if not raw:
                continue
            value = _float_or_none(raw)
            if value is None or not 0 <= value <= 100:
                errors.append(
                    f"horizon_snapshot_history.csv has {field} outside the 0-100 percentile scale for {player}: {raw}"
                )
                receipt_invalid = True
    return {
        "row_count": len(rows),
        "duplicate_keys": duplicate_keys,
        "valid": duplicate_keys == 0
        and not receipt_invalid
        and all(str(row.get("snapshot_at") or "").strip() for row in rows)
        and all(str(row.get("snapshot_scope") or "").strip() for row in rows)
        and all(str(row.get("source_trace") or "").strip() for row in rows),
    }


def _audit_horizon_accuracy(
    path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    """Check the optional realized-outcome evaluation artifact."""

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False}
    missing = sorted(HORIZON_ACCURACY_COLUMNS - set(rows[0].keys() if rows else _csv_header(path)))
    if missing:
        errors.append(f"horizon_score_accuracy.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False}
    if not rows:
        warnings.append("horizon_score_accuracy.csv has no graded rows; outcome evaluation is still at cold start")
        return {"row_count": 0, "valid": True, "status_counts": {}}

    allowed_horizons = {"next_game", "rest_of_season"}
    allowed_statuses = {"insufficient_history", "descriptive_evaluation"}
    invalid_horizons = sorted({str(row.get("horizon") or "") for row in rows} - allowed_horizons)
    invalid_statuses = sorted({str(row.get("evaluation_status") or "") for row in rows} - allowed_statuses)
    invalid_score_fields = sorted({str(row.get("score_field") or "") for row in rows} - HORIZON_ACCURACY_SCORE_FIELDS)
    if invalid_horizons:
        errors.append("horizon_score_accuracy.csv has unsupported horizon values: " + ", ".join(invalid_horizons))
    if invalid_statuses:
        errors.append("horizon_score_accuracy.csv has unsupported evaluation statuses: " + ", ".join(invalid_statuses))
    if invalid_score_fields:
        errors.append("horizon_score_accuracy.csv has unsupported score fields: " + ", ".join(invalid_score_fields))
    numeric_invalid = False
    for row in rows:
        row_player = row.get("position") or "unknown position"
        for field in ("evidence", "source_trace", "confidence"):
            if not str(row.get(field) or "").strip():
                errors.append(f"horizon_score_accuracy.csv contains a row without {field} for {row_player}")
                numeric_invalid = True
        for field in ("n_snapshots", "n_player_snapshots"):
            count = _float_or_none(row.get(field))
            if count is None or count < 1:
                errors.append(f"horizon_score_accuracy.csv contains an invalid {field} for {row_player}")
                numeric_invalid = True
        correlation = _float_or_none(row.get("spearman_rank_correlation"))
        if correlation is None or not -1 <= correlation <= 1:
            errors.append("horizon_score_accuracy.csv contains a rank correlation outside -1 to 1")
            numeric_invalid = True
            break
        for field in ("top_quartile_lift", "cohort_mean_outcome", "top_quartile_mean_outcome"):
            raw = str(row.get(field) or "").strip()
            if raw and _float_or_none(raw) is None:
                errors.append(f"horizon_score_accuracy.csv contains a non-numeric {field}")
                numeric_invalid = True
                break
    return {
        "row_count": len(rows),
        "valid": not invalid_horizons and not invalid_statuses and not invalid_score_fields and not numeric_invalid,
        "status_counts": {
            status: sum(1 for row in rows if str(row.get("evaluation_status") or "") == status)
            for status in sorted({str(row.get("evaluation_status") or "") for row in rows})
        },
    }


def _audit_horizon_movements(
    path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any] | None:
    """Check the current-vs-prior horizon movement receipt.

    The artifact is optional for older generated bundles, but when present it
    must reconcile to its endpoints. This keeps a reader-facing movement label
    from becoming an untraceable second valuation formula.
    """

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return {"row_count": 0, "valid": False}
    columns = set(rows[0].keys() if rows else _csv_header(path))
    missing = sorted(HORIZON_MOVEMENT_COLUMNS - columns)
    if missing:
        errors.append(f"horizon_market_movements.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False}
    if not rows:
        warnings.append("horizon_market_movements.csv has no prior comparisons; the current snapshot is the baseline")
        return {"row_count": 0, "valid": True, "status_counts": {}}

    invalid = False
    status_counts: dict[str, int] = {}
    for row in rows:
        player = row.get("player_name") or row.get("player_id") or "unnamed player"
        status = str(row.get("movement_status") or "").strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        if status not in HORIZON_MOVEMENT_STATUS:
            errors.append(f"horizon_market_movements.csv has unsupported movement_status for {player}: {status or 'blank'}")
            invalid = True
        for field in (
            "snapshot_scope", "league_id", "season", "player_id", "position",
            "horizon_model_version", "prior_snapshot_at", "current_snapshot_at",
            "prior_as_of_week", "current_as_of_week", "evidence", "source_trace",
        ):
            if not str(row.get(field) or "").strip():
                errors.append(f"horizon_market_movements.csv contains a row without {field} for {player}")
                invalid = True
        prior_week = _float_or_none(row.get("prior_as_of_week"))
        current_week = _float_or_none(row.get("current_as_of_week"))
        if prior_week is None or current_week is None or prior_week >= current_week:
            errors.append(f"horizon_market_movements.csv does not compare an earlier week for {player}")
            invalid = True

        meaningful_change = False
        for endpoint_field, delta_field in HORIZON_MOVEMENT_DELTAS:
            prior = _float_or_none(row.get(f"prior_{endpoint_field}"))
            current = _float_or_none(row.get(endpoint_field))
            delta = _float_or_none(row.get(delta_field))
            if prior is None or current is None:
                if delta is not None:
                    errors.append(f"horizon_market_movements.csv has {delta_field} without both endpoints for {player}")
                    invalid = True
                continue
            if delta is None or abs((current - prior) - delta) > 0.02:
                errors.append(f"horizon_market_movements.csv has {delta_field} that does not reconcile for {player}")
                invalid = True
            if abs(current - prior) >= 0.01:
                meaningful_change = True

        lane_change = str(row.get("value_lane_change") or "").strip()
        if lane_change not in {"", "changed", "unchanged"}:
            errors.append(f"horizon_market_movements.csv has unsupported value_lane_change for {player}: {lane_change}")
            invalid = True
        prior_lane = str(row.get("prior_value_lane") or "")
        current_lane = str(row.get("value_lane") or "")
        if prior_lane and current_lane and lane_change != ("unchanged" if prior_lane == current_lane else "changed"):
            errors.append(f"horizon_market_movements.csv has value_lane_change that does not reconcile for {player}")
            invalid = True
        if lane_change == "changed":
            meaningful_change = True
        if status == "changed" and not meaningful_change:
            errors.append(f"horizon_market_movements.csv marks {player} changed without a tracked change")
            invalid = True

        magnitude = _float_or_none(row.get("largest_clock_movement_magnitude"))
        clock_deltas = [
            _float_or_none(row.get(field))
            for field in ("next_game_score_delta", "rest_of_season_score_delta", "dynasty_score_delta", "career_score_delta")
        ]
        available_clock_deltas = [abs(value) for value in clock_deltas if value is not None]
        if available_clock_deltas:
            expected_magnitude = max(available_clock_deltas)
            if magnitude is None or abs(magnitude - expected_magnitude) > 0.02:
                errors.append(f"horizon_market_movements.csv has an unreconciled largest clock movement for {player}")
                invalid = True
            window = str(row.get("largest_clock_movement_window") or "").strip()
            if window not in HORIZON_MOVEMENT_WINDOWS:
                errors.append(f"horizon_market_movements.csv has unsupported largest clock window for {player}: {window or 'blank'}")
                invalid = True
        elif magnitude is not None or str(row.get("largest_clock_movement_window") or "").strip():
            errors.append(f"horizon_market_movements.csv has a largest clock movement without a clock delta for {player}")
            invalid = True

    return {"row_count": len(rows), "valid": not invalid, "status_counts": status_counts}


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.is_file():
        return [], f"missing {path.name}"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle)), None
    except (OSError, csv.Error) as exc:
        return [], f"could not read {path.name}: {exc}"


def _csv_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, csv.Error):
        return []


def _audit_opportunity_scope(
    rows: list[dict[str, str]],
    refresh_metadata: list[dict[str, str]],
    errors: list[str],
) -> None:
    """Keep the global usage join inside one current league publication scope."""

    if not rows:
        return
    missing_identity = [
        row.get("player_name") or row.get("player_id") or "unnamed player"
        for row in rows
        if not str(row.get("league_id") or "").strip()
        or not str(row.get("player_id") or "").strip()
        or not str(row.get("roster_id") or "").strip()
    ]
    if missing_identity:
        errors.append(
            "player_opportunity_scores.csv contains rows without league_id, player_id, or roster_id: "
            + ", ".join(str(value) for value in missing_identity[:5])
        )

    scoped_leagues = {
        str(row.get("league_id") or "").strip()
        for row in rows
        if str(row.get("league_id") or "").strip()
    }
    if len(scoped_leagues) > 1:
        errors.append(
            "player_opportunity_scores.csv mixes league scopes: "
            + ", ".join(sorted(scoped_leagues)[:5])
        )
    metadata_scope = ""
    for row in refresh_metadata:
        metadata_scope = str(row.get("league_id") or "").strip()
        if metadata_scope:
            break
    if metadata_scope and scoped_leagues and metadata_scope not in scoped_leagues:
        errors.append(
            "player_opportunity_scores.csv does not match refresh_metadata.league_id: "
            f"{metadata_scope}"
        )

    keys = [
        (
            str(row.get("league_id") or "").strip(),
            str(row.get("player_id") or "").strip(),
        )
        for row in rows
    ]
    duplicate_keys = sorted({key for key in keys if key[0] and key[1] and keys.count(key) > 1})
    if duplicate_keys:
        errors.append(
            "player_opportunity_scores.csv contains duplicate league/player joins: "
            + ", ".join(f"{league}/{player}" for league, player in duplicate_keys[:5])
        )


def _audit_player_history(path: Path, errors: list[str], warnings: list[str]) -> dict[str, Any] | None:
    """Check the join seam that makes a historical player dossier trustworthy."""

    if not path.is_file():
        return None
    rows, read_error = _read_csv(path)
    if read_error:
        errors.append(read_error)
        return None
    required = {"player_id", "identity_method", "player_name", "event_type", "direction", "source_trace"}
    missing = sorted(required - set(rows[0].keys() if rows else ()))
    if missing:
        errors.append(f"player_transaction_history.csv is missing columns: {', '.join(missing)}")
        return {"row_count": len(rows), "valid": False, "identity_method_counts": {}, "trade_direction_counts": {}}
    if not rows:
        warnings.append("player_transaction_history.csv has no rows; player dossiers have no historical transaction evidence")
        return {"row_count": 0, "valid": True, "identity_method_counts": {}, "trade_direction_counts": {}}

    identity_method_counts: dict[str, int] = {}
    trade_direction_counts: dict[str, int] = {}
    resolved_rows = 0
    unresolved_rows = 0
    for row in rows:
        method = str(row.get("identity_method") or "").strip()
        player_id = str(row.get("player_id") or "").strip()
        event_type = str(row.get("event_type") or "").strip()
        direction = str(row.get("direction") or "").strip()
        identity_method_counts[method] = identity_method_counts.get(method, 0) + 1
        if method not in PLAYER_HISTORY_IDENTITY_METHODS:
            errors.append(f"player_transaction_history.csv has unsupported identity_method: {method or 'blank'}")
        if method in {"source_id", "normalized_name"}:
            resolved_rows += 1
            if not player_id:
                errors.append(
                    f"player_transaction_history.csv marks {method} without player_id for {row.get('player_name') or 'unnamed player'}"
                )
        else:
            unresolved_rows += 1
        if event_type == "trade":
            trade_direction_counts[direction] = trade_direction_counts.get(direction, 0) + 1
            if direction not in {"acquired", "sold"}:
                errors.append(
                    f"player_transaction_history.csv has invalid trade direction: {direction or 'blank'}"
                )
        if not str(row.get("player_name") or "").strip():
            errors.append("player_transaction_history.csv contains a row without player_name")
        if not str(row.get("source_trace") or "").strip():
            errors.append("player_transaction_history.csv contains a row without source_trace")

    if unresolved_rows:
        warnings.append(
            f"player_transaction_history.csv has {unresolved_rows}/{len(rows)} unresolved name matches; inspect identity_method before relying on history"
        )
    if trade_direction_counts and trade_direction_counts.get("acquired", 0) != trade_direction_counts.get("sold", 0):
        warnings.append(
            "player_transaction_history.csv trade directions are asymmetric; source transactions may be incomplete"
        )
    return {
        "row_count": len(rows),
        "valid": not any("player_transaction_history.csv" in error for error in errors),
        "identity_method_counts": dict(sorted(identity_method_counts.items())),
        "resolved_rows": resolved_rows,
        "unresolved_rows": unresolved_rows,
        "unresolved_rate": round(unresolved_rows / len(rows), 4) if rows else 0.0,
        "trade_direction_counts": dict(sorted(trade_direction_counts.items())),
    }


def _audit_horizon_history(
    rows: list[dict[str, str]], errors: list[str], warnings: list[str]
) -> dict[str, Any]:
    """Fail closed when a career history status disagrees with its identity receipt."""

    status_counts: dict[str, int] = {}
    matched_rows = 0
    ambiguous_rows = 0
    for row in rows:
        status = str(row.get("career_history_status") or "").strip().lower()
        source_player_id = str(row.get("career_history_source_player_id") or "").strip()
        join_method = str(row.get("career_history_join_method") or "").strip()
        if not status:
            continue
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "matched":
            matched_rows += 1
            if not source_player_id:
                errors.append(
                    f"player_horizon_market_scores.csv marks matched career history without career_history_source_player_id for {row.get('player_name') or 'unnamed player'}"
                )
            if join_method != "normalized_name_position_unique_source_id":
                errors.append(
                    f"player_horizon_market_scores.csv marks matched career history with unsupported join method: {join_method or 'blank'}"
                )
            if not _positive_number(row.get("career_history_games")):
                errors.append(
                    f"player_horizon_market_scores.csv marks matched career history without positive games for {row.get('player_name') or 'unnamed player'}"
                )
            if not _positive_number(row.get("career_history_seasons")):
                errors.append(
                    f"player_horizon_market_scores.csv marks matched career history without positive seasons for {row.get('player_name') or 'unnamed player'}"
                )
            if not _number(row.get("career_history_ppg")):
                errors.append(
                    f"player_horizon_market_scores.csv marks matched career history without numeric PPG for {row.get('player_name') or 'unnamed player'}"
                )
        elif status == "ambiguous":
            ambiguous_rows += 1
            if source_player_id:
                errors.append(
                    f"player_horizon_market_scores.csv marks ambiguous career history with a source player ID for {row.get('player_name') or 'unnamed player'}"
                )
    return {
        "row_count": len(rows),
        "matched_rows": matched_rows,
        "ambiguous_rows": ambiguous_rows,
        "status_counts": dict(sorted(status_counts.items())),
        "valid": not any("player_horizon_market_scores.csv marks" in error for error in errors),
    }


def _audit_horizon_scores(
    rows: list[dict[str, str]], errors: list[str], warnings: list[str]
) -> dict[str, Any]:
    """Check the horizon seam without pretending percentiles are forecasts.

    The horizon model is intentionally a position-relative comparison, so the
    most important local gate is structural: scores stay on the documented
    scale, transition deltas reconcile to their component scores, and fit
    coverage tells the reader exactly how many clocks were usable.
    """

    invalid_rows = 0
    score_counts = {field: 0 for field in HORIZON_SCORE_FIELDS}
    market_receipt_counts = {"complete": 0, "unavailable": 0, "invalid": 0}
    clock_fields = HORIZON_SCORE_FIELDS[:4]
    for row in rows:
        player = row.get("player_name") or row.get("player_id") or "unnamed player"
        row_invalid = False
        if not str(row.get("league_id") or "").strip():
            errors.append(
                f"player_horizon_market_scores.csv has no league_id for {player}"
            )
            row_invalid = True
        if "position-relative" not in str(row.get("horizon_score_basis") or "").lower():
            errors.append(
                f"player_horizon_market_scores.csv is missing the position-relative score basis for {player}"
            )
            row_invalid = True
        if not str(row.get("horizon_model_version") or "").strip():
            errors.append(
                f"player_horizon_market_scores.csv has no horizon_model_version for {player}"
            )
            row_invalid = True

        score_values: dict[str, float | None] = {}
        for field in HORIZON_SCORE_FIELDS:
            raw = str(row.get(field) or "").strip()
            if not raw:
                score_values[field] = None
                continue
            value = _float_or_none(raw)
            if value is None or not 0 <= value <= 100:
                errors.append(
                    f"player_horizon_market_scores.csv has {field} outside the 0-100 percentile scale for {player}: {raw or 'blank'}"
                )
                row_invalid = True
                score_values[field] = None
                continue
            score_values[field] = value
            score_counts[field] += 1

        raw_coverage = str(row.get("fit_coverage") or "").strip()
        expected_coverage = f"{sum(score_values[field] is not None for field in clock_fields)}/4"
        if raw_coverage != expected_coverage:
            errors.append(
                f"player_horizon_market_scores.csv fit_coverage disagrees with clock availability for {player}: {raw_coverage or 'blank'} vs {expected_coverage}"
            )
            row_invalid = True

        raw_market_percentile = str(row.get("market_percentile") or "").strip()
        market_percentile = _float_or_none(raw_market_percentile) if raw_market_percentile else None
        if raw_market_percentile and (market_percentile is None or not 0 <= market_percentile <= 100):
            errors.append(
                f"player_horizon_market_scores.csv has market_percentile outside the 0-100 position scale for {player}: {raw_market_percentile}"
            )
            row_invalid = True

        receipt_status = _audit_market_quality_receipt(
            row, "player_horizon_market_scores.csv", player, errors
        )
        market_receipt_counts[receipt_status] += 1
        if receipt_status == "invalid":
            row_invalid = True

        for delta_field, (earlier_field, later_field) in HORIZON_DELTA_FIELDS.items():
            raw_delta = str(row.get(delta_field) or "").strip()
            delta = _float_or_none(raw_delta) if raw_delta else None
            earlier = score_values[earlier_field]
            later = score_values[later_field]
            if earlier is not None and later is not None:
                expected_delta = round(later - earlier, 2)
                if delta is None or abs(delta - expected_delta) > 0.011:
                    errors.append(
                        f"player_horizon_market_scores.csv {delta_field} does not reconcile for {player}: {raw_delta or 'blank'} vs {expected_delta:g}"
                    )
                    row_invalid = True
            elif raw_delta:
                errors.append(
                    f"player_horizon_market_scores.csv {delta_field} is populated without both clock scores for {player}"
                )
                row_invalid = True

        for delta_field, score_field in HORIZON_MARKET_DELTA_FIELDS.items():
            raw_delta = str(row.get(delta_field) or "").strip()
            if not raw_delta:
                continue
            delta = _float_or_none(raw_delta)
            score = score_values[score_field]
            if delta is None or not -100 <= delta <= 100:
                errors.append(
                    f"player_horizon_market_scores.csv has {delta_field} outside -100 to 100 for {player}: {raw_delta}"
                )
                row_invalid = True
            elif score is None or market_percentile is None:
                errors.append(
                    f"player_horizon_market_scores.csv {delta_field} is populated without its clock score and market_percentile for {player}"
                )
                row_invalid = True
            else:
                expected_delta = round(score - market_percentile, 2)
                if abs(delta - expected_delta) > 0.011:
                    errors.append(
                        f"player_horizon_market_scores.csv {delta_field} does not reconcile to the market percentile for {player}: {raw_delta} vs {expected_delta:g}"
                    )
                    row_invalid = True

        lane = str(row.get("value_lane") or "").strip()
        if lane and lane not in HORIZON_VALUE_LANES:
            errors.append(
                f"player_horizon_market_scores.csv has unsupported value_lane for {player}: {lane}"
            )
            row_invalid = True
        if row_invalid:
            invalid_rows += 1

    return {
        "row_count": len(rows),
        "invalid_rows": invalid_rows,
        "score_counts": score_counts,
        "market_receipt_counts": market_receipt_counts,
        "valid": invalid_rows == 0,
    }


def _number(value: Any) -> bool:
    try:
        return value not in (None, "") and float(str(value).strip()) == float(str(value).strip())
    except (TypeError, ValueError):
        return False


def _audit_market_quality_receipt(
    row: dict[str, str], filename: str, player: str, errors: list[str]
) -> str:
    """Validate the all-or-nothing receipt attached to an external market row."""

    fields = (
        "market_source_count",
        "market_disagreement_score",
        "market_source_confidence",
    )
    values = {field: str(row.get(field) or "").strip() for field in fields}
    present = [field for field, value in values.items() if value]
    if not present:
        return "unavailable"
    if len(present) != len(fields):
        errors.append(
            f"{filename} has an incomplete market quality receipt for {player}: "
            f"present={','.join(present)}"
        )
        return "invalid"

    source_count = _float_or_none(values["market_source_count"])
    disagreement = _float_or_none(values["market_disagreement_score"])
    confidence = values["market_source_confidence"].lower()
    valid = True
    if source_count is None or source_count < 1 or source_count != int(source_count):
        errors.append(
            f"{filename} has invalid market_source_count for {player}: "
            f"{values['market_source_count']}"
        )
        valid = False
    if disagreement is None or disagreement < 0:
        errors.append(
            f"{filename} has invalid market_disagreement_score for {player}: "
            f"{values['market_disagreement_score']}"
        )
        valid = False
    if confidence not in {"high", "medium", "low", "single_source"}:
        errors.append(
            f"{filename} has unsupported market_source_confidence for {player}: "
            f"{values['market_source_confidence']}"
        )
        valid = False
    return "complete" if valid else "invalid"


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _positive_number(value: Any) -> bool:
    try:
        return _number(value) and float(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


def _age_hours(value: str, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (reference - parsed).total_seconds() / 3600)


def _format_report(audit: dict[str, Any]) -> str:
    lines = [
        f"Local data audit: {'PASS' if audit['ok'] else 'FAIL'}",
        f"Refresh: {audit.get('generated_at') or 'not recorded'} "
        f"({audit.get('age_hours') if audit.get('age_hours') is not None else 'unknown'} hours old; "
        f"margin {audit.get('freshness_margin_hours') if audit.get('freshness_margin_hours') is not None else 'unknown'} hours)",
        f"News rows: {audit.get('news_event_count', 0)}",
        f"Analysis: {'valid' if audit.get('analysis', {}).get('valid') else 'invalid or missing'}",
    ]
    history = audit.get("player_history_identity") or {}
    if history:
        lines.append(
            "Player history: "
            f"{history.get('row_count', 0)} rows; "
            f"{history.get('resolved_rows', 0)} resolved; "
            f"{history.get('unresolved_rows', 0)} unresolved"
        )
    horizon_history = audit.get("horizon_history_identity") or {}
    if horizon_history:
        lines.append(
            "Career history joins: "
            f"{horizon_history.get('matched_rows', 0)} matched; "
            f"{horizon_history.get('ambiguous_rows', 0)} ambiguous"
        )
    horizon_scores = audit.get("horizon_score_quality") or {}
    if horizon_scores:
        lines.append(
            "Horizon scores: "
            f"{horizon_scores.get('row_count', 0)} rows; "
            f"{horizon_scores.get('invalid_rows', 0)} structural errors"
        )
        market_receipts = horizon_scores.get("market_receipt_counts") or {}
        lines.append(
            "Market receipts: "
            f"{market_receipts.get('complete', 0)} complete; "
            f"{market_receipts.get('unavailable', 0)} unavailable; "
            f"{market_receipts.get('invalid', 0)} invalid"
        )
    for error in audit.get("errors", []):
        lines.append(f"ERROR: {error}")
    for warning in audit.get("warnings", []):
        lines.append(f"WARN: {warning}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument("--analysis-dir", type=Path, default=None)
    parser.add_argument("--max-age-hours", type=float, default=36.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    audit = audit_local_data(
        args.processed_dir or root / "data" / "processed",
        args.analysis_dir or root / "data" / "analysis",
        max_age_hours=args.max_age_hours,
    )
    print(json.dumps(audit, indent=2) if args.as_json else _format_report(audit))
    return 0 if audit["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
