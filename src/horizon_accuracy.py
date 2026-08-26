"""Append-only horizon snapshots and outcome evaluation.

The live horizon table is a current-state comparison.  This module preserves
what that comparison said at each refresh and, when later nflverse usage is
available, evaluates the next-game and rest-of-season lanes against realized
production.  It deliberately does not turn a percentile into a probability
or claim that dynasty/career fit has been calibrated: those require different
longitudinal labels.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


HORIZON_SCORE_FIELDS = (
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
    "contender_fit_score",
    "rebuilder_fit_score",
)

HORIZON_MARKET_DELTA_FIELDS = (
    "next_game_minus_market_delta",
    "rest_of_season_minus_market_delta",
    "dynasty_minus_market_delta",
    "career_minus_market_delta",
)

HORIZON_MOVEMENT_SCORE_FIELDS = (
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
)

HORIZON_MOVEMENT_COLUMNS = [
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
]

SNAPSHOT_COLUMNS = [
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
]

ACCURACY_COLUMNS = [
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
]


def append_horizon_snapshot(
    history_path: Path,
    horizon_df: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append the current horizon rows using a dated, idempotent key.

    The history file is intentionally outside the overwrite-every-refresh
    export loop.  A rerun for the same scope/season/week/player/model replaces
    its prior row, while a later week creates a new observation.  Snapshot rows
    contain only deterministic horizon evidence; no generated prose is stored.
    """

    if horizon_df is None or horizon_df.empty:
        return {"written": 0, "row_count": _existing_row_count(history_path), "scope": ""}

    config = config or {}
    context = config.get("context") if isinstance(config.get("context"), dict) else {}
    scope = _snapshot_scope(config, context)
    scoped_league_id = str(
        config.get("league_id") or context.get("league_id") or ""
    ).strip()
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for _, row in horizon_df.fillna("").iterrows():
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            continue
        output = {
            "snapshot_at": now,
            "snapshot_scope": scope,
            "season": str(row.get("season") or config.get("current_season") or ""),
            "league_id": str(row.get("league_id") or scoped_league_id).strip(),
            "as_of_week": str(row.get("as_of_week") or config.get("current_week") or ""),
            "player_id": player_id,
            "player_name": str(row.get("player_name") or ""),
            "position": str(row.get("position") or "").upper(),
            "horizon_model_version": str(row.get("horizon_model_version") or ""),
            "market_value": _blank_or_value(row.get("market_value")),
            "market_percentile": _blank_or_value(row.get("market_percentile")),
            "market_source_count": _blank_or_value(row.get("market_source_count")),
            "market_disagreement_score": _blank_or_value(row.get("market_disagreement_score")),
            "market_source_confidence": str(row.get("market_source_confidence") or ""),
            "fit_coverage": str(row.get("fit_coverage") or ""),
            "value_lane": str(row.get("value_lane") or ""),
            "source_trace": str(row.get("source_trace") or ""),
        }
        output.update({field: _blank_or_value(row.get(field)) for field in HORIZON_SCORE_FIELDS})
        output.update({field: _blank_or_value(row.get(field)) for field in HORIZON_MARKET_DELTA_FIELDS})
        rows.append(output)

    if not rows:
        return {"written": 0, "row_count": _existing_row_count(history_path), "scope": scope}

    snapshot = pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_history(history_path)
    combined = pd.concat([existing, snapshot], ignore_index=True, sort=False)
    for column in SNAPSHOT_COLUMNS:
        if column not in combined.columns:
            combined[column] = ""
    # The first deployed snapshot schema did not include league_id, but its
    # scope key did. Backfill that durable identity during the additive schema
    # migration instead of discarding the historical belief log.
    combined["league_id"] = combined.apply(
        lambda row: str(row.get("league_id") or _league_from_scope(row.get("snapshot_scope"))).strip(),
        axis=1,
    )
    combined = combined[SNAPSHOT_COLUMNS].fillna("")
    key_columns = [
        "snapshot_scope",
        "season",
        "as_of_week",
        "player_id",
        "position",
        "horizon_model_version",
    ]
    combined = combined.drop_duplicates(subset=key_columns, keep="last")
    combined.to_csv(history_path, index=False)
    return {"written": len(snapshot), "row_count": len(combined), "scope": scope}


def build_horizon_accuracy_table(
    history_path: Path,
    usage_df: pd.DataFrame,
    config: dict[str, Any] | None = None,
    *,
    minimum_sample: int = 30,
) -> pd.DataFrame:
    """Evaluate realized next-game and rest-of-season outcomes.

    Player IDs differ between Sleeper and nflverse, so the join uses a
    normalized name plus position and fails closed when that key maps to more
    than one nflverse player ID.  Next-game grading requires an observed usage
    row in the following week; missing rows are not silently converted to a
    zero because they may be a bye or an unavailable source.  Dynasty and
    career scores remain ungraded here because a single season's PPR output is
    not a valid label for those horizons.
    """

    empty = pd.DataFrame(columns=ACCURACY_COLUMNS)
    history = _read_history(history_path)
    if history.empty or usage_df is None or usage_df.empty:
        return empty

    stats = _prepare_usage(usage_df)
    if stats.empty:
        return empty
    identity = _usage_identity(stats)
    records: list[dict[str, Any]] = []
    for _, snapshot in history.iterrows():
        season = _integer(snapshot.get("season"))
        as_of_week = _integer(snapshot.get("as_of_week"))
        position = str(snapshot.get("position") or "").upper().strip()
        name_key = _name_key(snapshot.get("player_name"))
        if not season or not position or not name_key:
            continue
        source_ids = identity.get((name_key, position), set())
        if len(source_ids) != 1:
            continue
        source_id = next(iter(source_ids))
        player_rows = stats[
            (stats["season"] == season)
            & (stats["position"] == position)
            & (stats["player_id"] == source_id)
        ].copy()
        if player_rows.empty:
            continue

        next_rows = player_rows[player_rows["week"] == as_of_week + 1]
        if not next_rows.empty:
            _append_observation(
                records,
                snapshot,
                "next_game",
                "next_game_market_score",
                "next_game_ppr",
                float(next_rows["fantasy_points_ppr"].sum()),
                minimum_sample,
            )

        ros_rows = player_rows[player_rows["week"] > as_of_week]
        active_rows = ros_rows[ros_rows["activity"]]
        if not active_rows.empty:
            _append_observation(
                records,
                snapshot,
                "rest_of_season",
                "rest_of_season_market_score",
                "rest_of_season_active_game_ppr",
                float(active_rows["fantasy_points_ppr"].sum() / len(active_rows)),
                minimum_sample,
            )

    if not records:
        return empty
    observations = pd.DataFrame(records)
    rows: list[dict[str, Any]] = []
    for (model, horizon, score_field, outcome, position), group in observations.groupby(
        ["horizon_model_version", "horizon", "score_field", "outcome", "position"], dropna=False
    ):
        scores = pd.to_numeric(group["score"], errors="coerce")
        outcomes = pd.to_numeric(group["outcome_value"], errors="coerce")
        valid = pd.DataFrame({"score": scores, "outcome": outcomes}).dropna()
        if valid.empty:
            continue
        cohort_mean = float(valid["outcome"].mean())
        quartile_cut = float(valid["score"].quantile(0.75))
        top_quartile = valid[valid["score"] >= quartile_cut]
        top_mean = float(top_quartile["outcome"].mean()) if not top_quartile.empty else None
        lift = (top_mean / cohort_mean) if top_mean is not None and cohort_mean else None
        rows.append(
            {
                "horizon_model_version": str(model or ""),
                "horizon": str(horizon),
                "score_field": str(score_field),
                "position": str(position),
                "outcome": str(outcome),
                "n_snapshots": int(len(valid)),
                "n_player_snapshots": int(group["snapshot_key"].nunique()),
                "spearman_rank_correlation": round(_spearman(valid["score"], valid["outcome"]), 3),
                "cohort_mean_outcome": round(cohort_mean, 3),
                "top_quartile_mean_outcome": round(top_mean, 3) if top_mean is not None else "",
                "top_quartile_lift": round(lift, 3) if lift is not None else "",
                "evaluation_status": "descriptive_evaluation" if len(valid) >= minimum_sample else "insufficient_history",
                "confidence": _confidence(len(valid)),
                "evidence": (
                    f"{len(valid)} dated horizon observations joined by normalized player name and position; "
                    f"top quartile uses the score distribution within {position}"
                ),
                "source_trace": "horizon_snapshot_history.csv; player_usage_weekly",
            }
        )
    return pd.DataFrame(rows, columns=ACCURACY_COLUMNS).sort_values(
        ["horizon", "position"], kind="stable"
    ).reset_index(drop=True)


def build_horizon_movement_table(
    history_path: Path,
    current_df: pd.DataFrame,
    config: dict[str, Any] | None = None,
    *,
    change_threshold: float = 0.01,
) -> pd.DataFrame:
    """Compare the current horizon snapshot with the latest prior week.

    This is a movement receipt, not a valuation model.  It compares exact
    scope/season/player/position/model observations already stored in the
    append-only history and leaves a field blank when either endpoint is
    unavailable.  A rerun for the same week therefore does not manufacture a
    movement row; the comparison begins when a genuinely later snapshot is
    recorded.
    """

    empty = pd.DataFrame(columns=HORIZON_MOVEMENT_COLUMNS)
    if current_df is None or current_df.empty:
        return empty
    history = _read_history(history_path)
    if history.empty:
        return empty

    config = config or {}
    context = config.get("context") if isinstance(config.get("context"), dict) else {}
    current_scope = _snapshot_scope(config, context)
    current_season = str(config.get("current_season") or context.get("season") or "").strip()
    output: list[dict[str, Any]] = []

    for _, current in current_df.fillna("").iterrows():
        player_id = str(current.get("player_id") or "").strip()
        position = str(current.get("position") or "").strip().upper()
        if not player_id or not position:
            continue
        season = str(current.get("season") or current_season).strip()
        model = str(current.get("horizon_model_version") or "").strip()
        league_id = str(current.get("league_id") or config.get("league_id") or context.get("league_id") or "").strip()
        as_of_week = _integer(current.get("as_of_week") or config.get("current_week"))

        candidates = history[
            (history["snapshot_scope"].astype(str) == current_scope)
            & (history["season"].astype(str) == season)
            & (history["player_id"].astype(str).str.strip() == player_id)
            & (history["position"].astype(str).str.upper().str.strip() == position)
            & (history["horizon_model_version"].astype(str).str.strip() == model)
        ].copy()
        if league_id and "league_id" in candidates.columns:
            candidates = candidates[
                candidates["league_id"].astype(str).str.strip().isin({"", league_id})
            ]
        if as_of_week:
            candidates["_as_of_week_num"] = pd.to_numeric(candidates["as_of_week"], errors="coerce").fillna(0).astype(int)
            candidates = candidates[candidates["_as_of_week_num"] < as_of_week]
        if candidates.empty:
            continue
        candidates = candidates.sort_values(
            ["_as_of_week_num", "snapshot_at"], ascending=[False, False], kind="stable"
        )
        prior = candidates.iloc[0]
        current_week = str(current.get("as_of_week") or as_of_week or "")
        row: dict[str, Any] = {
            "snapshot_scope": current_scope,
            "league_id": league_id or str(current.get("league_id") or prior.get("league_id") or "").strip(),
            "season": season,
            "player_id": player_id,
            "player_name": str(current.get("player_name") or prior.get("player_name") or ""),
            "position": position,
            "horizon_model_version": model,
            "prior_snapshot_at": str(prior.get("snapshot_at") or ""),
            "current_snapshot_at": str(current.get("snapshot_at") or "") or _now_iso(),
            "prior_as_of_week": str(prior.get("as_of_week") or ""),
            "current_as_of_week": current_week,
            "prior_value_lane": str(prior.get("value_lane") or ""),
            "value_lane": str(current.get("value_lane") or ""),
            "source_trace": _join_trace(
                "horizon_snapshot_history.csv",
                str(current.get("source_trace") or "player_horizon_market_scores"),
                str(prior.get("source_trace") or ""),
            ),
        }
        changed_fields: list[str] = []
        for current_field, prior_field, delta_field in (
            ("market_value", "market_value", "market_value_delta"),
            ("market_percentile", "market_percentile", "market_percentile_delta"),
            ("contender_fit_score", "contender_fit_score", "contender_fit_delta"),
            ("rebuilder_fit_score", "rebuilder_fit_score", "rebuilder_fit_delta"),
            ("rebuilder_contender_spread", "rebuilder_contender_spread", "rebuilder_contender_spread_delta"),
        ):
            current_value = _float_or_none(current.get(current_field))
            prior_value = _float_or_none(prior.get(prior_field))
            row[f"prior_{current_field}"] = _blank_or_value(prior_value)
            row[current_field] = _blank_or_value(current_value)
            delta = _delta(current_value, prior_value)
            row[delta_field] = _blank_or_value(delta)
            if delta is not None and abs(delta) >= change_threshold:
                changed_fields.append(delta_field)

        clock_movements: list[tuple[str, float]] = []
        for field in HORIZON_MOVEMENT_SCORE_FIELDS:
            current_value = _float_or_none(current.get(field))
            prior_value = _float_or_none(prior.get(field))
            row[f"prior_{field}"] = _blank_or_value(prior_value)
            row[field] = _blank_or_value(current_value)
            delta = _delta(current_value, prior_value)
            delta_field = _movement_delta_field(field)
            row[delta_field] = _blank_or_value(delta)
            if delta is not None:
                clock_movements.append((field, delta))
                if abs(delta) >= change_threshold:
                    changed_fields.append(delta_field)

        prior_lane = str(prior.get("value_lane") or "")
        current_lane = str(current.get("value_lane") or "")
        lane_change = ""
        if prior_lane or current_lane:
            lane_change = "unchanged" if prior_lane == current_lane else "changed"
            if lane_change == "changed":
                changed_fields.append("value_lane")
        row["value_lane_change"] = lane_change
        if clock_movements:
            largest_field, largest_delta = max(clock_movements, key=lambda item: abs(item[1]))
            row["largest_clock_movement_window"] = _movement_window_label(largest_field)
            row["largest_clock_movement_delta"] = round(largest_delta, 2)
            row["largest_clock_movement_magnitude"] = round(abs(largest_delta), 2)
        else:
            row["largest_clock_movement_window"] = ""
            row["largest_clock_movement_delta"] = ""
            row["largest_clock_movement_magnitude"] = ""
        row["movement_status"] = "changed" if changed_fields else "unchanged"
        changed_text = ", ".join(dict.fromkeys(changed_fields)) or "no tracked field"
        row["evidence"] = (
            f"prior_as_of_week={row['prior_as_of_week'] or 'unknown'}; "
            f"current_as_of_week={row['current_as_of_week'] or 'unknown'}; "
            f"movement_status={row['movement_status']}; changed_fields={changed_text}; "
            "comparison uses the latest earlier exact-scope snapshot; missing endpoints remain unavailable"
        )
        output.append(row)

    if not output:
        return empty
    return pd.DataFrame(output, columns=HORIZON_MOVEMENT_COLUMNS).sort_values(
        ["movement_status", "largest_clock_movement_magnitude", "player_name"],
        ascending=[True, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _append_observation(
    records: list[dict[str, Any]],
    snapshot: pd.Series,
    horizon: str,
    score_field: str,
    outcome: str,
    outcome_value: float,
    minimum_sample: int,
) -> None:
    score = _float_or_none(snapshot.get(score_field))
    if score is None:
        return
    records.append(
        {
            "horizon_model_version": str(snapshot.get("horizon_model_version") or ""),
            "horizon": horizon,
            "score_field": score_field,
            "outcome": outcome,
            "position": str(snapshot.get("position") or ""),
            "score": score,
            "outcome_value": outcome_value,
            "snapshot_key": _snapshot_key(snapshot),
        }
    )


def _prepare_usage(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"season", "week", "player_id", "position", "fantasy_points_ppr"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    output = frame.copy().fillna("")
    output["season"] = pd.to_numeric(output["season"], errors="coerce").fillna(0).astype(int)
    output["week"] = pd.to_numeric(output["week"], errors="coerce").fillna(0).astype(int)
    output["player_id"] = output["player_id"].astype(str).str.strip()
    output["position"] = output["position"].astype(str).str.upper().str.strip()
    output["fantasy_points_ppr"] = pd.to_numeric(output["fantasy_points_ppr"], errors="coerce").fillna(0.0)
    activity_columns = [column for column in ("targets", "carries", "passing_attempts", "attempts") if column in output.columns]
    if activity_columns:
        activity = pd.Series(False, index=output.index)
        for column in activity_columns:
            activity = activity | (pd.to_numeric(output[column], errors="coerce").fillna(0) > 0)
        output["activity"] = activity
    else:
        output["activity"] = True
    if "player_name" not in output.columns:
        output["player_name"] = ""
    output["name_key"] = output["player_name"].map(_name_key)
    return output[(output["season"] > 0) & output["week"].between(1, 18) & output["player_id"].ne("")]


def _usage_identity(stats: pd.DataFrame) -> dict[tuple[str, str], set[str]]:
    identity: dict[tuple[str, str], set[str]] = {}
    for row in stats[["name_key", "position", "player_id"]].drop_duplicates().itertuples(index=False):
        if row.name_key and row.position and row.player_id:
            identity.setdefault((row.name_key, row.position), set()).add(row.player_id)
    return identity


def _read_history(path: Path) -> pd.DataFrame:
    if not Path(path).is_file():
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    try:
        frame = pd.read_csv(path, dtype=object).fillna("")
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    for column in SNAPSHOT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[SNAPSHOT_COLUMNS]


def _existing_row_count(path: Path) -> int:
    return len(_read_history(path))


def _snapshot_scope(config: dict[str, Any], context: dict[str, Any]) -> str:
    league_id = str(config.get("league_id") or context.get("league_id") or "legacy").strip()
    season = str(config.get("current_season") or context.get("season") or "").strip()
    roster = str(context.get("roster_id") or "all").strip()
    return f"league:{league_id}:season:{season}:roster:{roster}"


def _league_from_scope(value: Any) -> str:
    match = re.match(r"^league:([^:]+):", str(value or "").strip())
    return match.group(1) if match else ""


def _snapshot_key(row: pd.Series) -> str:
    return ":".join(
        str(row.get(column) or "")
        for column in ("snapshot_scope", "season", "as_of_week", "player_id", "position", "horizon_model_version")
    )


def _name_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def _blank_or_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return value


def _integer(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _delta(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None:
        return None
    return round(current - prior, 2)


def _movement_delta_field(field: str) -> str:
    return {
        "next_game_market_score": "next_game_score_delta",
        "rest_of_season_market_score": "rest_of_season_score_delta",
        "dynasty_market_score": "dynasty_score_delta",
        "career_projection_score": "career_score_delta",
    }.get(field, f"{field}_delta")


def _movement_window_label(field: str) -> str:
    return {
        "next_game_market_score": "this_week",
        "rest_of_season_market_score": "rest_of_season",
        "dynasty_market_score": "dynasty",
        "career_projection_score": "career_window",
    }.get(field, field)


def _join_trace(*values: Any) -> str:
    output: list[str] = []
    for value in values:
        for item in str(value or "").split(";"):
            text = item.strip()
            if text and text not in output:
                output.append(text)
    return "; ".join(output)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spearman(scores: pd.Series, outcomes: pd.Series) -> float:
    if len(scores) < 2:
        return 0.0
    correlation = scores.rank(method="average").corr(outcomes.rank(method="average"))
    if pd.isna(correlation):
        return 0.0
    return float(max(-1.0, min(1.0, correlation)))


def _confidence(sample_size: int) -> str:
    if sample_size < 10:
        return "low"
    if sample_size < 30:
        return "medium"
    return "high"
