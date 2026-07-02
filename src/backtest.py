from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.opportunity import score_players_from_weekly


DEFAULT_SCORES = [
    "opportunity_score",
    "production_score",
    "xfp_regression_score",
    "role_trend_score",
    "fragility_score",
]
SUMMARY_COLUMNS = [
    "score",
    "mean_auc_top_finish",
    "mean_spearman_ros_ppg",
    "n_snapshots",
    "n_player_snapshots",
]


def run_score_backtest(
    weekly_stats_df: pd.DataFrame,
    seasons: list[int],
    snapshot_weeks: list[int],
    scores: list[str] | None = None,
) -> pd.DataFrame:
    if weekly_stats_df.empty or not seasons or not snapshot_weeks:
        return _empty_summary()

    selected_scores = scores or DEFAULT_SCORES
    stats = _prepare_weekly_frame(weekly_stats_df)
    records: list[dict[str, Any]] = []

    for season in seasons:
        season_rows = stats[(stats["season"] == int(season)) & (stats["season_type"] == "REG")].copy()
        if season_rows.empty:
            continue

        for week in snapshot_weeks:
            snapshot = season_rows[season_rows["week"] <= int(week)].copy()
            future = season_rows[season_rows["week"] > int(week)].copy()
            if snapshot.empty or future.empty:
                continue

            scored = score_players_from_weekly(snapshot)
            outcomes = _future_outcomes(future)
            if scored.empty or outcomes.empty or "player_id" not in scored:
                continue

            scored = scored.copy()
            scored["player_id"] = scored["player_id"].fillna("").astype(str)
            joined = scored.merge(outcomes, on="player_id", how="inner")
            joined = joined[joined["future_games"] >= 1].copy()
            if len(joined) < 20:
                continue

            joined["is_top_finisher"] = False
            top_index = joined.sort_values("future_ppr_pg", ascending=False).head(24).index
            joined.loc[top_index, "is_top_finisher"] = True

            for score in selected_scores:
                if score not in joined:
                    continue
                metric_frame = joined[[score, "future_ppr_pg", "is_top_finisher"]].copy()
                metric_frame[score] = pd.to_numeric(metric_frame[score], errors="coerce")
                metric_frame["future_ppr_pg"] = pd.to_numeric(metric_frame["future_ppr_pg"], errors="coerce")
                metric_frame = metric_frame.dropna(subset=[score, "future_ppr_pg"])
                if len(metric_frame) < 20:
                    continue

                labels = metric_frame["is_top_finisher"].astype(bool)
                auc = _auc_rank(metric_frame[score], labels)
                if auc is None:
                    continue

                records.append(
                    {
                        "score": score,
                        "auc": auc,
                        "spearman": _spearman(metric_frame[score], metric_frame["future_ppr_pg"]),
                        "pool_size": int(len(metric_frame)),
                    }
                )

    if not records:
        return _empty_summary()

    result = (
        pd.DataFrame(records)
        .groupby("score", as_index=False)
        .agg(
            mean_auc_top_finish=("auc", "mean"),
            mean_spearman_ros_ppg=("spearman", "mean"),
            n_snapshots=("auc", "size"),
            n_player_snapshots=("pool_size", "sum"),
        )
    )
    result["mean_auc_top_finish"] = result["mean_auc_top_finish"].round(3)
    result["mean_spearman_ros_ppg"] = result["mean_spearman_ros_ppg"].round(3)
    result["n_snapshots"] = result["n_snapshots"].astype(int)
    result["n_player_snapshots"] = result["n_player_snapshots"].astype(int)
    return result[SUMMARY_COLUMNS].sort_values("mean_auc_top_finish", ascending=False).reset_index(drop=True)


def _prepare_weekly_frame(frame: pd.DataFrame) -> pd.DataFrame:
    stats = frame.copy()
    stats["season"] = pd.to_numeric(stats.get("season"), errors="coerce").fillna(0).astype(int)
    stats["week"] = pd.to_numeric(stats.get("week"), errors="coerce").fillna(0).astype(int)
    stats["season_type"] = stats.get("season_type", "").fillna("").astype(str)
    for column in ["attempts", "carries", "targets", "fantasy_points_ppr"]:
        stats[column] = pd.to_numeric(stats.get(column), errors="coerce").fillna(0.0)
    if "player_id" not in stats:
        stats["player_id"] = ""
    stats["player_id"] = stats["player_id"].fillna("").astype(str)
    return stats


def _future_outcomes(future: pd.DataFrame) -> pd.DataFrame:
    if future.empty or "player_id" not in future:
        return pd.DataFrame(columns=["player_id", "future_games", "future_ppr_total", "future_ppr_pg"])

    frame = future.copy()
    frame["player_id"] = frame["player_id"].fillna("").astype(str)
    frame["week"] = pd.to_numeric(frame.get("week"), errors="coerce").fillna(0).astype(int)
    for column in ["attempts", "carries", "targets", "fantasy_points_ppr"]:
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce").fillna(0.0)
    frame["activity"] = (frame["attempts"] > 0) | (frame["carries"] > 0) | (frame["targets"] > 0)

    active_games = (
        frame.loc[frame["activity"], ["player_id", "week"]]
        .drop_duplicates()
        .groupby("player_id")
        .size()
        .rename("future_games")
    )
    totals = frame.groupby("player_id")["fantasy_points_ppr"].sum().rename("future_ppr_total")
    outcomes = pd.concat([active_games, totals], axis=1).fillna({"future_games": 0, "future_ppr_total": 0.0})
    outcomes = outcomes.reset_index()
    outcomes["future_games"] = outcomes["future_games"].astype(int)
    outcomes = outcomes[outcomes["future_games"] >= 1].copy()
    outcomes["future_ppr_pg"] = outcomes["future_ppr_total"] / outcomes["future_games"].clip(lower=1)
    return outcomes[["player_id", "future_games", "future_ppr_total", "future_ppr_pg"]]


def _auc_rank(scores: pd.Series, labels: pd.Series) -> float | None:
    frame = pd.DataFrame({"score": pd.to_numeric(scores, errors="coerce"), "label": labels.astype(bool)}).dropna()
    n_pos = int(frame["label"].sum())
    n_neg = int(len(frame) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return None

    ranks = frame["score"].rank(method="average")
    sum_ranks_positives = float(ranks[frame["label"]].sum())
    auc = (sum_ranks_positives - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    if pd.isna(auc) or np.isinf(auc):
        return None
    return float(max(0.0, min(1.0, auc)))


def _spearman(scores: pd.Series, outcomes: pd.Series) -> float:
    frame = pd.DataFrame(
        {
            "score": pd.to_numeric(scores, errors="coerce"),
            "future_ppr_pg": pd.to_numeric(outcomes, errors="coerce"),
        }
    ).dropna()
    if len(frame) < 2:
        return 0.0

    correlation = frame["score"].rank(method="average").corr(frame["future_ppr_pg"].rank(method="average"))
    if pd.isna(correlation) or np.isinf(correlation):
        return 0.0
    return float(max(-1.0, min(1.0, correlation)))


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SUMMARY_COLUMNS)
