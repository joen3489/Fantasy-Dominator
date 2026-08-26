from __future__ import annotations

import hashlib
import json
import os
from html import escape
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from .analysis import (
    build_manager_dossier_items,
    rewrite_source_team_labels_in_articles,
    upgrade_deterministic_article_receipts,
)
from .editorial import build_editorial_issue
from .editorial_ui import inject_editorial_facade
from .draft_room import build_draft_room
from .media_assets import build_media_manifest, materialize_media_assets, media_manifest_json
from .manager_profiles import build_manager_season_history
from .economics import build_league_standings
from .personas import reporter_lineup
from .team_identity import resolve_team_name
from .team_identity import historical_sleeper_team_names

from .utils import ANALYSIS_DIR, PROCESSED_DIR, load_config, load_json


def build_browser_site(
    output_dir: Path,
    processed_dir: Path = PROCESSED_DIR,
    analysis_dir: Path = ANALYSIS_DIR,
    league_type: str = "dynasty",
    league_id: str = "",
    config: Mapping[str, Any] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "teams": _records(processed_dir / "teams.csv"),
        "players": _records(processed_dir / "players.csv"),
        "roster_players": _records(processed_dir / "roster_players.csv"),
        "manager_profiles": _records(processed_dir / "manager_profiles.csv"),
        "pick_ownership": _records(processed_dir / "pick_ownership.csv"),
        "trades": _records(processed_dir / "trades.csv"),
        "waivers": _records(processed_dir / "waivers.csv"),
        "matchups": _records(processed_dir / "matchups.csv"),
        "drafts": _records(processed_dir / "drafts.csv"),
        "draft_picks": _records(processed_dir / "draft_picks.csv"),
        "refresh_metadata": _records(processed_dir / "refresh_metadata.csv"),
        "player_usage_weekly": _records(processed_dir / "player_usage_weekly.csv"),
        "nfl_schedule": _records(processed_dir / "nfl_schedule.csv"),
        "nfl_team_defense_factors": _records(processed_dir / "nfl_team_defense_factors.csv"),
        "market_value_sources": _records(processed_dir / "market_value_sources.csv"),
        "market_consensus_values": _records(processed_dir / "market_consensus_values.csv"),
        "player_market_values": _records(processed_dir / "player_market_values.csv"),
        "pick_market_values": _records(processed_dir / "pick_market_values.csv"),
        "team_asset_inventory": _records(processed_dir / "team_asset_inventory.csv"),
        "manager_event_log": _records(processed_dir / "manager_event_log.csv"),
        "team_needs_matrix": _records(processed_dir / "team_needs_matrix.csv"),
        "manager_behavior_signals": _records(processed_dir / "manager_behavior_signals.csv"),
        "manager_valuation_profiles": _records(processed_dir / "manager_valuation_profiles.csv"),
        "manager_transaction_preferences": _records(processed_dir / "manager_transaction_preferences.csv"),
        "liquidity_scores": _records(processed_dir / "liquidity_scores.csv"),
        "asset_market_gaps": _records(processed_dir / "asset_market_gaps.csv"),
        "opportunity_board": _records(processed_dir / "opportunity_board.csv"),
        "counterparty_trade_edges": _records(processed_dir / "counterparty_trade_edges.csv"),
        "counterparty_asset_interest": _records(processed_dir / "counterparty_asset_interest.csv"),
        "source_freshness": _records(processed_dir / "source_freshness.csv", safe_cache_paths=True),
        "news_events": _records(processed_dir / "news_events.csv"),
        "player_news_matches": _records(processed_dir / "player_news_matches.csv"),
        "league_news_impact": _records(processed_dir / "league_news_impact.csv"),
        "news_source_freshness": _records(processed_dir / "news_source_freshness.csv", safe_cache_paths=True),
        "player_projection_season": _records(processed_dir / "player_projection_season.csv"),
        "player_projection_weekly": _records(processed_dir / "player_projection_weekly.csv"),
        "player_horizon_market_scores": _records(processed_dir / "player_horizon_market_scores.csv"),
        "available_player_horizon_scores": _records(processed_dir / "available_player_horizon_scores.csv"),
        "horizon_score_accuracy": _records(processed_dir / "horizon_score_accuracy.csv"),
        "horizon_market_movements": _records(processed_dir / "horizon_market_movements.csv"),
        "projection_source_freshness": _records(processed_dir / "projection_source_freshness.csv", safe_cache_paths=True),
        "player_signal_scores": _records(processed_dir / "player_signal_scores.csv"),
        "breakout_candidates": _records(processed_dir / "breakout_candidates.csv"),
        "sell_candidates": _records(processed_dir / "sell_candidates.csv"),
        "projection_market_gaps": _records(processed_dir / "projection_market_gaps.csv"),
        "news_market_edges": _records(processed_dir / "news_market_edges.csv"),
        "team_fit_scores": _records(processed_dir / "team_fit_scores.csv"),
        "action_recommendations": _records(processed_dir / "action_recommendations.csv"),
        "today_priority_board": _records(processed_dir / "today_priority_board.csv"),
        "manager_profile_tags": _records(processed_dir / "manager_profile_tags.csv"),
        "manager_cycle_profiles": _records(processed_dir / "manager_cycle_profiles.csv"),
        "player_dossiers": _records(processed_dir / "player_dossiers.csv"),
        "player_transaction_history": _records(processed_dir / "player_transaction_history.csv"),
        "player_profile_tags": _records(processed_dir / "player_profile_tags.csv"),
        "player_opportunity_scores": _records(processed_dir / "player_opportunity_scores.csv"),
    }
    tables["manager_season_history"] = _manager_season_history_records(processed_dir, tables)
    tables["league_standings"] = _league_standings_records(processed_dir, tables)
    config = dict(config) if config is not None else load_config()
    my_roster = [row for row in tables["roster_players"] if _is_true(row.get("is_my_team"))]
    context = config.get("context") if isinstance(config, Mapping) and isinstance(config.get("context"), Mapping) else {}
    configured_roster_id = context.get("roster_id")
    if configured_roster_id not in (None, ""):
        try:
            my_roster_id = int(configured_roster_id)
        except (TypeError, ValueError):
            my_roster_id = None
    else:
        my_roster_id = int(my_roster[0]["roster_id"]) if my_roster else None
    my_team_name = _my_team_name(tables["teams"], my_roster_id)
    # A private profile may carry a deliberate Front Office label, but an old
    # Sleeper name must follow the current exact league/season/roster row.
    configured_team = config.get("current_team") or {}
    configured_name = configured_team.get("team_name") if isinstance(configured_team, Mapping) else ""
    resolved_name = resolve_team_name(
        configured_name,
        tables["teams"],
        league_id=str(league_id or ""),
        season=str(config.get("current_season") or ""),
        roster_id=my_roster_id,
    )
    if resolved_name:
        my_team_name = resolved_name
    analysis = _analysis_artifacts(analysis_dir)
    analysis = rewrite_source_team_labels_in_articles(
        analysis_dir,
        analysis,
        historical_sleeper_team_names(
            tables["teams"],
            league_id=str(league_id or ""),
            season=str(config.get("current_season") or ""),
            roster_id=my_roster_id,
        ),
        my_team_name,
    )
    analysis = _upgrade_manager_dossier_payload(analysis, tables)
    analysis = upgrade_deterministic_article_receipts(
        analysis_dir,
        analysis,
        tables,
        my_roster_id,
        my_team_name,
        dict(config.get("writer_preferences") or {}),
    )
    manifest = _write_data_chunks(data_dir, tables, my_roster_id, my_team_name, config, analysis, league_id)
    target = output_dir / "index.html"
    target.write_text(inject_editorial_facade(_page(my_team_name, manifest, league_type)), encoding="utf-8")
    return target


def rebuild_browser_shell(
    output_dir: Path,
    league_type: str = "dynasty",
    analysis_dir: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> Path:
    """Rebuild only the generated shell from a preserved complete bundle.

    Durable deployments can retain the browser bundle after processed CSV
    intermediates have been pruned or moved. A source deploy still needs to
    refresh the HTML and JavaScript in that case, without inventing facts or
    starting a data refresh or LLM generation.
    """

    data_dir = output_dir / "data"
    manifest = load_json(data_dir / "manifest.json")
    app_payload = load_json(data_dir / "app_bundle.json")
    if not isinstance(manifest, dict) or not isinstance(app_payload, dict):
        raise ValueError("complete browser bundle payloads are required")
    identity = app_payload.get("identityReceipt") if isinstance(app_payload.get("identityReceipt"), dict) else {}
    my_team_name = str(app_payload.get("myTeamName") or identity.get("team_name") or "Unknown team")
    raw_roster_id = app_payload.get("myRosterId")
    try:
        my_roster_id = int(raw_roster_id) if raw_roster_id not in (None, "") else None
    except (TypeError, ValueError):
        my_roster_id = None
    writer_preferences = dict(
        (config or {}).get("writer_preferences")
        or app_payload.get("writerPreferences")
        or {}
    )
    tables = app_payload.get("tables") if isinstance(app_payload.get("tables"), dict) else {}
    current_league_id = str(app_payload.get("leagueId") or manifest.get("leagueId") or "")
    current_season = str(app_payload.get("currentSeason") or "")
    resolved_name = resolve_team_name(
        my_team_name,
        tables.get("teams", []),
        league_id=current_league_id,
        season=current_season,
        roster_id=my_roster_id,
    )
    if resolved_name:
        my_team_name = resolved_name
    app_payload["myTeamName"] = my_team_name
    if isinstance(identity, dict):
        identity = dict(identity)
        identity["team_name"] = my_team_name
        app_payload["identityReceipt"] = identity
    tables["manager_season_history"] = _manager_season_history_records(output_dir / "processed", tables)
    tables["league_standings"] = _league_standings_records(output_dir / "processed", tables)
    analysis = dict(app_payload.get("analysis") or {}) if isinstance(app_payload.get("analysis"), dict) else {}
    analysis = rewrite_source_team_labels_in_articles(
        analysis_dir,
        analysis,
        historical_sleeper_team_names(
            tables.get("teams", []),
            league_id=current_league_id,
            season=current_season,
            roster_id=my_roster_id,
        ),
        my_team_name,
    )
    analysis = upgrade_deterministic_article_receipts(
        analysis_dir,
        analysis,
        tables,
        my_roster_id,
        my_team_name,
        writer_preferences,
    )
    analysis = _upgrade_manager_dossier_payload(analysis, tables)
    app_payload["analysis"] = analysis
    app_payload["teamLabelContract"] = "source_label_v1"
    app_payload["tables"] = tables
    app_payload["dataQuality"] = _data_quality_receipt(tables)
    shell_config = dict(config or {})
    shell_config.setdefault("current_season", app_payload.get("currentSeason") or "")
    current_team = dict(shell_config.get("current_team") or {})
    current_team.update({"team_name": my_team_name, "roster_id": my_roster_id})
    shell_config["current_team"] = current_team
    shell_config.setdefault("strategy_profile", app_payload.get("strategyProfile") or {})
    shell_config.setdefault("writer_preferences", writer_preferences)
    shell_config.setdefault("manager_trade_profiles", app_payload.get("managerTradeProfiles") or [])
    editorial = build_editorial_issue(
        tables,
        analysis,
        league_id=current_league_id,
        my_roster_id=my_roster_id,
        my_team_name=my_team_name,
        config=shell_config,
    )
    app_payload["editorial"] = editorial
    app_payload["reporterPersona"] = editorial.get("reporter_persona") or app_payload.get("reporterPersona") or {}
    app_payload["reporterLineup"] = editorial.get("reporter_lineup") or app_payload.get("reporterLineup") or []
    _refresh_preserved_media(output_dir, app_payload, manifest)
    if not isinstance(app_payload.get("mediaManifest"), dict):
        app_payload["mediaManifest"] = build_media_manifest(
            [],
            user_id=identity.get("user_id"),
            league_id=str(app_payload.get("leagueId") or manifest.get("leagueId") or ""),
        )
    source_revision = _source_revision()
    _clear_runtime_revisions(app_payload)
    app_payload.pop("bundleRevision", None)
    app_payload.pop("sourceRevision", None)
    bundle_revision = _bundle_revision(app_payload)
    app_payload["bundleRevision"] = bundle_revision
    app_payload["sourceRevision"] = source_revision
    editorial["bundle_revision"] = bundle_revision
    app_payload["mediaManifest"]["bundle_revision"] = bundle_revision
    for asset in app_payload["mediaManifest"].get("assets", []):
        asset["bundle_revision"] = bundle_revision
    manifest["bundleRevision"] = bundle_revision
    manifest["sourceRevision"] = source_revision
    manifest["reporterPersona"] = app_payload["reporterPersona"]
    manifest["reporterLineup"] = app_payload["reporterLineup"]
    manifest["dataQuality"] = app_payload["dataQuality"]
    manifest["dataRoomDelta"] = app_payload.get("dataRoomDelta") or manifest.get("dataRoomDelta") or {}
    manifest["articleReceipts"] = analysis.get("articleReceipts") or {}
    manifest["mediaManifest"] = app_payload.get("mediaManifest") or manifest.get("mediaManifest") or {}
    manifest["teamLabelContract"] = "source_label_v1"
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2).replace("</", "<\\/"),
        encoding="utf-8",
    )
    (data_dir / "app_bundle.json").write_text(
        json.dumps(app_payload, ensure_ascii=False).replace("</", "<\\/"),
        encoding="utf-8",
    )
    (data_dir / "editorial_issue.json").write_text(
        json.dumps(editorial, ensure_ascii=False).replace("</", "<\\/"),
        encoding="utf-8",
    )
    (data_dir / "media_manifest.json").write_text(
        media_manifest_json(app_payload["mediaManifest"]),
        encoding="utf-8",
    )
    target = output_dir / "index.html"
    target.write_text(inject_editorial_facade(_page(my_team_name, manifest, league_type)), encoding="utf-8")
    return target


def _clear_runtime_revisions(value: Any) -> None:
    """Remove generated revision fields before hashing a preserved payload."""

    if isinstance(value, dict):
        value.pop("bundle_revision", None)
        value.pop("bundleRevision", None)
        for nested in value.values():
            _clear_runtime_revisions(nested)
    elif isinstance(value, list):
        for nested in value:
            _clear_runtime_revisions(nested)


def _refresh_preserved_media(output_dir: Path, app_payload: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Refresh configured decorative media while preserving the durable fact bundle.

    A shell-only deployment rebuild intentionally skips processed data and LLM
    work. It must still be able to ship a new versioned, non-factual asset;
    otherwise a durable bundle would silently keep the old media contract after
    a source deploy. The existing app payload remains the fallback if config or
    an asset is unavailable.
    """
    try:
        configured = load_config().get("media_assets") or []
        if not configured:
            return
        identity = app_payload.get("identityReceipt") if isinstance(app_payload.get("identityReceipt"), dict) else {}
        league_id = str(app_payload.get("leagueId") or manifest.get("leagueId") or identity.get("league_id") or "")
        user_id = identity.get("user_id")
        bundle_revision = str(app_payload.get("bundleRevision") or manifest.get("bundleRevision") or "")
        materialized = materialize_media_assets(output_dir, configured)
        media_manifest = build_media_manifest(
            materialized,
            user_id=user_id,
            league_id=league_id,
            bundle_revision=bundle_revision,
        )
        app_payload["mediaManifest"] = media_manifest
        manifest["mediaManifest"] = media_manifest
        (output_dir / "data" / "media_manifest.json").write_text(
            media_manifest_json(media_manifest),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError):
        # Decorative media is optional. Preserve the durable payload and let
        # the browser use its text/gradient fallback when this refresh is not
        # possible.
        return


def _data_quality_receipt(tables: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return deterministic semantic-quality receipts for the reader bundle.

    Freshness only says when a table was produced. The reader also needs to
    show whether the historical rows can be joined to canonical Sleeper
    players. Keep this receipt derived from the same rows that the browser
    renders so a green source timestamp cannot hide a broken identity seam.
    """

    rows = tables.get("player_transaction_history") or []
    method_counts: dict[str, int] = {}
    trade_direction_counts: dict[str, int] = {}
    errors: list[str] = []
    resolved_rows = 0
    unresolved_rows = 0
    supported_methods = {"source_id", "normalized_name", "ambiguous_name", "unmatched_name"}

    for row in rows:
        method = str(row.get("identity_method") or "").strip()
        player_id = str(row.get("player_id") or "").strip()
        event_type = str(row.get("event_type") or "").strip()
        direction = str(row.get("direction") or "").strip()
        method_counts[method or "missing"] = method_counts.get(method or "missing", 0) + 1
        if method not in supported_methods:
            errors.append(f"unsupported identity method for {row.get('player_name') or 'unnamed player'}")
        if method in {"source_id", "normalized_name"}:
            resolved_rows += 1
            if not player_id:
                errors.append(f"{method} row has no player_id for {row.get('player_name') or 'unnamed player'}")
        else:
            unresolved_rows += 1
        if event_type == "trade":
            trade_direction_counts[direction or "missing"] = trade_direction_counts.get(direction or "missing", 0) + 1
            if direction not in {"acquired", "sold"}:
                errors.append(f"invalid trade direction for {row.get('player_name') or 'unnamed player'}")
        if not str(row.get("player_name") or "").strip():
            errors.append("history row has no player_name")
        if not str(row.get("source_trace") or "").strip():
            errors.append(f"history row has no source_trace for {row.get('player_name') or 'unnamed player'}")

    acquired = trade_direction_counts.get("acquired", 0)
    sold = trade_direction_counts.get("sold", 0)
    trade_direction_status = "not_applicable"
    if trade_direction_counts:
        trade_direction_status = "balanced" if acquired == sold and not errors else "unbalanced"
    if not rows:
        status = "empty"
    elif errors:
        status = "contract_error"
    elif unresolved_rows:
        status = "partial"
    else:
        status = "verified"
    return {
        "player_history_identity": {
            "status": status,
            "valid": not errors,
            "row_count": len(rows),
            "resolved_rows": resolved_rows,
            "unresolved_rows": unresolved_rows,
            "resolved_rate": round(resolved_rows / len(rows), 4) if rows else 0.0,
            "identity_method_counts": dict(sorted(method_counts.items())),
            "trade_direction_counts": dict(sorted(trade_direction_counts.items())),
            "trade_direction_status": trade_direction_status,
            "errors": errors[:8],
        }
    }


def browser_bundle_missing(site_dir: Path) -> list[str]:
    """Return the generated files required for a readable league edition.

    ``index.html`` alone is not a usable edition: the shell loads its facts and
    lazy audit tables from the sibling data bundle. Keeping this check next to
    the builder prevents the server from calling an incomplete shell "ready".
    """

    site_dir = site_dir.resolve()
    missing: list[str] = []
    for relative in (
        "index.html",
        "data/manifest.json",
        "data/app_bundle.json",
        "data/editorial_issue.json",
        "data/draft_room.json",
        "data/media_manifest.json",
    ):
        if not (site_dir / relative).is_file():
            missing.append(relative)

    manifest_path = site_dir / "data" / "manifest.json"
    if not manifest_path.is_file():
        return missing
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if "data/manifest.json" not in missing:
            missing.append("data/manifest.json")
        return missing

    for relative in (manifest.get("auditTables") or {}).values():
        candidate = (site_dir / str(relative)).resolve()
        if not candidate.is_relative_to(site_dir) or not candidate.is_file():
            missing.append(str(relative))
    return list(dict.fromkeys(missing))


def browser_bundle_is_complete(site_dir: Path) -> bool:
    return not browser_bundle_missing(site_dir)


def _records(path: Path, safe_cache_paths: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_csv(path).fillna("")
    records = frame.to_dict(orient="records")
    if safe_cache_paths:
        for row in records:
            row["cache_path"] = _safe_cache_path(row.get("cache_path"))
    return records


def _manager_season_history_records(
    processed_dir: Path,
    tables: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Load or deterministically derive the historical manager ledger.

    A source-only deploy may have preserved the canonical CSVs from before
    this table existed. Deriving the ledger from preserved Sleeper tables keeps
    the new dossier entry path available without refreshing facts or invoking
    an LLM.
    """

    path = processed_dir / "manager_season_history.csv"
    if path.exists():
        return _records(path)
    frames = {
        name: pd.DataFrame(rows)
        for name, rows in tables.items()
        if name in {"teams", "trades", "waivers", "roster_players", "matchups"}
    }
    history = build_manager_season_history(
        frames.get("teams", pd.DataFrame()),
        frames.get("trades", pd.DataFrame()),
        frames.get("waivers", pd.DataFrame()),
        frames.get("roster_players", pd.DataFrame()),
        frames.get("matchups", pd.DataFrame()),
    )
    return history.to_dict(orient="records")


def _league_standings_records(
    processed_dir: Path,
    tables: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Keep the League surface useful when a deploy preserved matchups only."""

    path = processed_dir / "league_standings.csv"
    if path.exists():
        return _records(path)
    standings = build_league_standings(
        pd.DataFrame(tables.get("matchups", [])),
        pd.DataFrame(tables.get("teams", [])),
    )
    return standings.to_dict(orient="records")


def _upgrade_manager_dossier_payload(
    analysis: dict[str, Any],
    tables: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Attach the current deterministic season ledger to durable dossiers.

    Dossier markdown/JSON can outlive the processed CSV intermediates on the
    durable volume. Rebuilding this deterministic envelope at shell time keeps
    a source-only deploy from serving a shallow historical view, while leaving
    any expensive writer workflow untouched.
    """

    if not isinstance(analysis, dict):
        return analysis
    required = {"manager_profiles", "manager_cycle_profiles"}
    if not required.issubset(tables):
        return analysis
    frames = {name: pd.DataFrame(rows) for name, rows in tables.items()}
    refresh_rows = frames.get("refresh_metadata", pd.DataFrame()).to_dict(orient="records")
    generated_at = str(refresh_rows[0].get("generated_at") or "browser-shell-migration") if refresh_rows else "browser-shell-migration"
    try:
        rebuilt = build_manager_dossier_items(
            frames,
            generated_at,
            previous_items=analysis.get("managerDossierItems") or [],
        )
    except (KeyError, TypeError, ValueError):
        return analysis
    if rebuilt:
        # This function runs during a source-only shell migration, not a new
        # analytical refresh. Preserve the prior receipt state so enriching an
        # older dossier (for example, adding season timing) is idempotent and
        # does not oscillate the bundle between ``updated`` and ``unchanged``
        # on repeated shell rebuilds.
        previous_by_roster = {
            str(item.get("roster_id")): item
            for item in (analysis.get("managerDossierItems") or [])
            if isinstance(item, dict) and item.get("roster_id") not in (None, "")
        }
        for item in rebuilt:
            previous = previous_by_roster.get(str(item.get("roster_id")))
            if previous and previous.get("update_status"):
                item["update_status"] = previous["update_status"]
        analysis["managerDossierItems"] = rebuilt
    return analysis


def _safe_cache_path(value: Any) -> str:
    """Keep audit paths useful without leaking the host filesystem layout."""

    normalized = str(value or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    lowered = normalized.lower()
    marker = "/data/"
    marker_index = lowered.find(marker)
    if marker_index >= 0:
        return normalized[marker_index + 1 :]
    if lowered.startswith("data/"):
        return normalized
    return "cached payload"


def _analysis_artifacts(analysis_dir: Path) -> dict[str, Any]:
    return {
        "status": "available" if analysis_dir.exists() else "missing",
        "targetTheses": _json_items(analysis_dir / "target_theses.json"),
        "sellTheses": _json_items(analysis_dir / "sell_theses.json"),
        "tradeTheses": _json_items(analysis_dir / "trade_theses.json"),
        "managerDossierItems": _json_items(analysis_dir / "manager_dossiers.json"),
        "managerDossierReceipt": _json_receipt(analysis_dir / "manager_dossiers.json"),
        "playerDossierItems": _json_items(analysis_dir / "player_dossiers.json"),
        "contextPackets": _json_items(analysis_dir / "analysis_context_packets.json"),
        "validation": _json_items(analysis_dir / "analysis_validation.json"),
        "dailyGmBrief": _text_or_empty(analysis_dir / "daily_gm_brief.md"),
        "dailyGmBriefMode": _front_matter_field(analysis_dir / "daily_gm_brief.md", "model_mode"),
        "managerDossiers": _text_or_empty(analysis_dir / "manager_dossiers.md"),
        "newsImpactBrief": _text_or_empty(analysis_dir / "news_impact_brief.md"),
        # Sprint 17 per-section articles (each with its LLM-written / Deterministic mode marker).
        "teamReport": _text_or_empty(analysis_dir / "team_report.md"),
        "teamReportMode": _front_matter_field(analysis_dir / "team_report.md", "model_mode"),
        "marketWatch": _text_or_empty(analysis_dir / "market_watch.md"),
        "marketWatchMode": _front_matter_field(analysis_dir / "market_watch.md", "model_mode"),
        "horizonWatch": _text_or_empty(analysis_dir / "horizon_watch.md"),
        "horizonWatchMode": _front_matter_field(analysis_dir / "horizon_watch.md", "model_mode"),
        "tradeDeskRead": _text_or_empty(analysis_dir / "trade_desk.md"),
        "tradeDeskReadMode": _front_matter_field(analysis_dir / "trade_desk.md", "model_mode"),
        "managerIntel": _text_or_empty(analysis_dir / "manager_intel.md"),
        "managerIntelMode": _front_matter_field(analysis_dir / "manager_intel.md", "model_mode"),
        "insightCards": _json_items(analysis_dir / "validated_insight_cards.json"),
        "insightValidation": _json_items(analysis_dir / "insight_card_validation.json"),
        "articleReceipts": _article_receipts(analysis_dir),
    }


def _front_matter_field(path: Path, key: str) -> str:
    text = _text_or_empty(path)
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _front_matter_json(path: Path, key: str) -> dict[str, Any]:
    raw = _front_matter_field(path, key)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _article_receipts(analysis_dir: Path) -> dict[str, dict[str, Any]]:
    files = {
        "daily_brief": "daily_gm_brief.md",
        "team_report": "team_report.md",
        "market_watch": "market_watch.md",
        "horizon_watch": "horizon_watch.md",
        "trade_desk": "trade_desk.md",
        "manager_intel": "manager_intel.md",
    }
    receipts: dict[str, dict[str, Any]] = {}
    for key, filename in files.items():
        path = analysis_dir / filename
        if not path.is_file():
            continue
        try:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            content_hash = ""
        structured = _front_matter_json(path, "article_payload_json")
        source_receipt = _front_matter_json(path, "source_receipt_json")
        if not source_receipt and structured.get("source_ids"):
            # Older LLM articles embedded their source IDs in the structured
            # story but omitted the dedicated receipt line. Preserve the
            # evidence path in the reader until those artifacts are refreshed.
            source_ids = [str(value) for value in structured.get("source_ids", []) if str(value).strip()]
            source_receipt = {
                "scope": "legacy_structured_article_evidence",
                "source_count": len(source_ids),
                "source_ids": source_ids,
            }
        receipts[key] = {
            "mode": _front_matter_field(path, "model_mode") or "deterministic_template",
            "model": _front_matter_field(path, "model"),
            "reporter_id": _front_matter_field(path, "reporter_persona"),
            "reporter_name": _front_matter_field(path, "reporter_name"),
            "generated_at": _front_matter_field(path, "generated_at"),
            "evidence_fingerprint": _front_matter_field(path, "evidence_fingerprint"),
            "fallback_reason": _front_matter_field(path, "fallback_reason"),
            "source_receipt": source_receipt,
            "content_hash": content_hash,
            "structured": structured,
            "editorial_review": _front_matter_json(path, "editorial_review_json"),
            "path": filename,
        }
    return receipts


def _bundle_revision(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _source_revision() -> str:
    """Return the deployed source revision used to invalidate persisted shells."""

    for key in ("RAILWAY_GIT_COMMIT_SHA", "SOURCE_VERSION", "COMMIT_SHA", "GIT_COMMIT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value[:80]
    return ""


def _json_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        items = payload.get("items", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _json_receipt(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        key: payload.get(key)
        for key in ("update_mode", "item_count", "new_count", "updated_count", "unchanged_count", "fingerprint")
        if key in payload
    } if isinstance(payload, dict) else {}


def _text_or_empty(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _is_true(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _my_team_name(teams: list[dict[str, Any]], my_roster_id: int | None) -> str:
    for team in teams:
        if my_roster_id is not None and int(team.get("roster_id", -1)) == my_roster_id:
            return str(team.get("team_name", "Unknown team"))
    return "Unknown team"


def _data_room_delta(
    previous_payload: Mapping[str, Any] | None,
    current_tables: Mapping[str, list[dict[str, Any]]],
    generated_at: str = "",
) -> dict[str, Any]:
    """Compare event tables with the prior durable reader bundle.

    This receipt is deliberately limited to immutable-ish event evidence. It
    does not infer that an event is strategically important, and it fails to a
    visible unavailable state when the prior bundle did not carry the complete
    comparison scope. The current pulse remains available in that state.
    """

    specs = {
        "news": ("league_news_impact", "event_id", "published_at"),
        "trades": ("trades", "transaction_id", "created_datetime"),
        "waivers": ("waivers", "transaction_id", "created_datetime"),
    }
    scope = list(specs)
    prior_revision = str(previous_payload.get("bundleRevision") or "") if isinstance(previous_payload, Mapping) else ""

    def unavailable(reason: str) -> dict[str, Any]:
        return {
            "status": "not_available",
            "reason": reason,
            "scope": scope,
            "generated_at": generated_at,
            "from_bundle_revision": prior_revision,
            "added_events": [],
            "categories": {},
        }

    previous_tables = previous_payload.get("tables") if isinstance(previous_payload, Mapping) else None
    if not isinstance(previous_tables, Mapping):
        return unavailable("No prior reader bundle contains a comparison receipt yet.")
    missing = [
        table
        for table, _, _ in specs.values()
        if table not in previous_tables or table not in current_tables or not isinstance(previous_tables.get(table), list) or not isinstance(current_tables.get(table), list)
    ]
    if missing:
        return unavailable(f"The comparison scope lacks complete event tables: {', '.join(missing)}.")

    categories: dict[str, dict[str, Any]] = {}
    added_events: list[dict[str, Any]] = []
    for category, (table_name, key_field, timestamp_field) in specs.items():
        previous_rows = [row for row in previous_tables.get(table_name, []) if isinstance(row, Mapping)]
        current_rows = [row for row in current_tables.get(table_name, []) if isinstance(row, Mapping)]
        if any(not str(row.get(key_field) or "").strip() for row in [*previous_rows, *current_rows]):
            return unavailable(f"The {category} comparison contains a row without its source key {key_field}.")
        previous_by_key = {_delta_row_key(row, key_field): row for row in previous_rows}
        current_by_key = {_delta_row_key(row, key_field): row for row in current_rows}
        added_rows = [row for key, row in current_by_key.items() if key not in previous_by_key]
        updated_rows = [
            row
            for key, row in current_by_key.items()
            if key in previous_by_key and _bundle_revision(row) != _bundle_revision(previous_by_key[key])
        ]
        categories[category] = {
            "table": table_name,
            "prior_rows": len(previous_rows),
            "current_rows": len(current_rows),
            "added_rows": len(added_rows),
            "updated_rows": len(updated_rows),
            "removed_rows": sum(1 for key in previous_by_key if key not in current_by_key),
            "source_trace": table_name,
        }
        added_events.extend(_data_room_event_view(category, row, key_field, timestamp_field) for row in added_rows)

    added_events.sort(key=lambda row: str(row.get("recorded_at") or ""), reverse=True)
    return {
        "status": "verified",
        "reason": "Compared with the prior durable reader bundle.",
        "scope": list(specs),
        "generated_at": generated_at,
        "from_bundle_revision": str(previous_payload.get("bundleRevision") or ""),
        "added_events": added_events[:20],
        "categories": categories,
    }


def _delta_row_key(row: Mapping[str, Any], key_field: str) -> str:
    value = str(row.get(key_field) or "").strip()
    return value


def _data_room_event_view(
    category: str,
    row: Mapping[str, Any],
    key_field: str,
    timestamp_field: str,
) -> dict[str, Any]:
    if category == "news":
        headline = f"News · {row.get('player_name') or 'League signal'}"
        detail = str(row.get("evidence") or row.get("impact_type") or "event recorded")
    elif category == "trades":
        headline = f"Trade · {row.get('team_a_name') or 'Roster A'} ↔ {row.get('team_b_name') or 'Roster B'}"
        detail = str(
            row.get("team_a_players_received")
            or row.get("team_a_picks_received")
            or row.get("team_b_players_received")
            or row.get("team_b_picks_received")
            or "assets recorded"
        )
    else:
        headline = f"Waiver · {row.get('team_name') or 'Roster'}"
        detail = f"added {row.get('player_added') or 'an unknown player'}"
        if row.get("player_dropped"):
            detail += f" and dropped {row.get('player_dropped')}"
    return {
        "category": category,
        "event_id": str(row.get(key_field) or ""),
        "recorded_at": str(row.get(timestamp_field) or row.get("week") or ""),
        "headline": headline,
        "detail": detail,
        "evidence": str(row.get("evidence") or ""),
        "source_trace": str(row.get("source_trace") or category),
    }


def _write_data_chunks(
    data_dir: Path,
    tables: dict[str, list[dict[str, Any]]],
    my_roster_id: int | None,
    my_team_name: str,
    config: dict[str, Any],
    analysis: dict[str, Any],
    league_id: str = "",
) -> dict[str, Any]:
    audit_only_tables = {
        "players",
        "player_usage_weekly",
        "player_projection_weekly",
    }
    table_counts = {name: len(rows) for name, rows in tables.items()}
    app_tables = {name: rows for name, rows in tables.items() if name not in audit_only_tables}
    try:
        previous_payload = load_json(data_dir / "app_bundle.json")
    except (OSError, ValueError):
        previous_payload = {}
    generated_at = str((tables.get("refresh_metadata") or [{}])[0].get("generated_at") or "")
    data_room_delta = _data_room_delta(previous_payload, tables, generated_at)
    editorial = build_editorial_issue(
        tables,
        analysis,
        league_id=league_id,
        my_roster_id=my_roster_id,
        my_team_name=my_team_name,
        config=config,
    )
    context = config.get("context") if isinstance(config.get("context"), Mapping) else {}
    identity_receipt = {
        "status": "verified" if context.get("user_id") and context.get("roster_id") not in (None, "") else "unverified",
        "user_id": context.get("user_id"),
        "league_id": str(league_id or context.get("league_id") or ""),
        "season": str(context.get("season") or config.get("current_season") or ""),
        "roster_id": context.get("roster_id"),
        "team_name": my_team_name,
        "display_name": context.get("display_name", ""),
        "source": "verified_roster_scope" if context.get("roster_id") not in (None, "") else "legacy_or_unassigned",
    }
    draft_room = build_draft_room(
        tables,
        config,
        league_id=league_id,
        my_roster_id=my_roster_id,
        my_team_name=my_team_name,
    )
    materialized_assets = materialize_media_assets(
        data_dir.parent,
        config.get("media_assets") or [],
    )
    media_manifest = build_media_manifest(
        materialized_assets,
        user_id=context.get("user_id"),
        league_id=str(league_id or ""),
    )
    source_revision = _source_revision()
    app_payload = {
        "tables": app_tables,
        "editorial": editorial,
        "draftRoom": draft_room,
        "myRosterId": my_roster_id,
        "myTeamName": my_team_name,
        "strategyProfile": config.get("strategy_profile") or {},
        "writerPreferences": config.get("writer_preferences") or {},
        "managerTradeProfiles": config.get("manager_trade_profiles") or [],
        "reporterPersona": editorial.get("reporter_persona") or {},
        "reporterLineup": editorial.get("reporter_lineup") or reporter_lineup(config.get("writer_preferences") or {}),
        "identityReceipt": identity_receipt,
        "trackedPicks": config.get("tracked_picks") or [],
        "currentSeason": config.get("current_season", ""),
        "configuredLeagues": config.get("leagues") or {},
        "leagueId": str(league_id or ""),
        "analysis": analysis,
        "dataQuality": _data_quality_receipt(tables),
        "dataRoomDelta": data_room_delta,
        "tableCounts": table_counts,
        "mediaManifest": media_manifest,
        "teamLabelContract": "source_label_v1",
    }
    bundle_revision = _bundle_revision(app_payload)
    editorial["bundle_revision"] = bundle_revision
    app_payload["bundleRevision"] = bundle_revision
    # This is deliberately separate from bundleRevision. The latter describes
    # reader content and publication receipts; sourceRevision only tells the
    # server whether a persisted shell needs to be rebuilt after a deploy.
    app_payload["sourceRevision"] = source_revision
    app_payload["mediaManifest"]["bundle_revision"] = bundle_revision
    for asset in app_payload["mediaManifest"].get("assets", []):
        asset["bundle_revision"] = bundle_revision
    (data_dir / "app_bundle.json").write_text(
        json.dumps(app_payload, ensure_ascii=False).replace("</", "<\\/"),
        encoding="utf-8",
    )
    (data_dir / "editorial_issue.json").write_text(
        json.dumps(editorial, ensure_ascii=False).replace("</", "<\\/"),
        encoding="utf-8",
    )
    (data_dir / "media_manifest.json").write_text(
        media_manifest_json(app_payload["mediaManifest"]),
        encoding="utf-8",
    )
    (data_dir / "draft_room.json").write_text(
        json.dumps(draft_room, ensure_ascii=False).replace("</", "<\\/"),
        encoding="utf-8",
    )

    audit_dir = data_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted(audit_only_tables):
        (audit_dir / f"{name}.json").write_text(
            json.dumps(tables.get(name, []), ensure_ascii=False).replace("</", "<\\/"),
            encoding="utf-8",
        )

    manifest = {
        "appName": "The Front Office",
        "bundlePath": "data/app_bundle.json",
        "editorialPath": "data/editorial_issue.json",
        "draftRoomPath": "data/draft_room.json",
        "mediaPath": "data/media_manifest.json",
        "auditTables": {name: f"data/audit/{name}.json" for name in sorted(audit_only_tables)},
        "tableCounts": table_counts,
        "initialTables": sorted(app_tables),
        "payloadPolicy": "initial_shell_plus_fact_bundle; audit_only_tables_lazy_loaded",
        "leagueId": str(league_id or ""),
        "editorialSchema": editorial.get("schema_version", "issue_v1"),
        "reporterPersona": editorial.get("reporter_persona") or {},
        "reporterLineup": editorial.get("reporter_lineup") or reporter_lineup(config.get("writer_preferences") or {}),
        "identityReceipt": identity_receipt,
        "dataQuality": app_payload["dataQuality"],
        "dataRoomDelta": data_room_delta,
        "bundleRevision": bundle_revision,
        "sourceRevision": source_revision,
        "teamLabelContract": "source_label_v1",
        "articleReceipts": analysis.get("articleReceipts") or {},
        "mediaManifest": app_payload["mediaManifest"],
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2).replace("</", "<\\/"),
        encoding="utf-8",
    )
    return manifest


def _page(
    my_team_name: str,
    manifest: dict[str, Any],
    league_type: str = "dynasty",
) -> str:
    manifest_json = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    # Per-type experience gating (v2): redraft leagues get the same generated site with the
    # dynasty-only surfaces hidden via a body class + CSS, keeping one template instead of
    # forking the giant page string. Best-ball leagues never generate a site at all.
    body_class = f"league-{league_type}" if league_type in ("dynasty", "redraft") else "league-dynasty"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The Front Office</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f4ef;
      --panel: #ffffff;
      --ink: #15171a;
      --muted: #626a73;
      --line: #d8ddd2;
      --accent: #0f5c4a;
      --accent-2: #a23f2d;
      --rail: #202722;
      --gold: #c49b44;

      --buy: var(--accent);
      --buy-bg: #e4efe9;
      --sell: var(--accent-2);
      --sell-bg: #f4e3dd;
      --watch: var(--gold);
      --watch-bg: #f6ecd8;
      --hold: #35506b;
      --hold-bg: #e2e8ee;
      --info: var(--muted);
      --info-bg: #eceeec;
      --alert: #8a2f5c;
      --alert-bg: #f1e0ea;

      --rank-size-lg: 28px;
      --rank-size-md: 22px;
      --rank-weight: 800;
      --rank-color: var(--ink);
      --rank-muted: var(--muted);

      --headshot-size: 44px;
      --headshot-radius: 6px;
      --headshot-fallback-bg: var(--rail);
      --headshot-fallback-ink: #f8f4ea;

      --tile-size: 30px;
      --tile-radius: 6px;
      --tile-font-size: 12px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }}
    .app-shell {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 232px minmax(0, 1fr);
    }}
    .side-rail {{
      background: var(--rail);
      color: #f8f4ea;
      padding: 22px 16px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    .brand-kicker {{
      color: var(--gold);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .side-rail h1 {{ margin: 4px 0 8px; font-size: 25px; line-height: 1.05; }}
    .side-rail p {{ margin: 0 0 18px; color: #cbd4cc; font-size: 13px; line-height: 1.4; }}
    .nav-group {{ margin: 0 0 18px; }}
    .nav-group-title {{ color: #96a89d; font-size: 11px; font-weight: 800; text-transform: uppercase; margin: 0 0 7px; }}
    nav {{
      display: grid;
      gap: 5px;
    }}
    nav a {{
      color: #f8f4ea;
      text-decoration: none;
      padding: 8px 9px;
      border-radius: 6px;
      font-size: 14px;
    }}
    nav a:hover {{ background: rgba(255,255,255,0.08); }}
    nav a.active {{ background: var(--accent); color: #fff; }}
    header {{
      border-bottom: 1px solid var(--line);
      background: #fbfcf8;
      padding: 22px 28px 16px;
      position: sticky;
      top: 0;
      z-index: 3;
    }}
    h1 {{ margin: 0; font-size: 26px; line-height: 1.15; }}
    header p {{ margin: 6px 0 0; color: var(--muted); }}
    button, select, input {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      font: inherit;
      font-size: 14px;
    }}
    main {{ padding: 22px 28px 48px; max-width: 1440px; margin: 0 auto; }}
    section {{ margin: 0 0 28px; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; }}
    h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin: 0 0 14px;
    }}
    .controls label {{
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
    }}
    select, input {{ min-height: 34px; padding: 6px 9px; min-width: 150px; }}
    textarea {{
      width: 100%;
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
      color: var(--ink);
      font: 13px/1.45 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      resize: vertical;
    }}
    input[type="search"] {{ min-width: min(420px, 100%); }}
    button {{ min-height: 34px; padding: 6px 10px; cursor: pointer; }}
    button.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .button-link {{ display: inline-block; padding: 8px 11px; border: 1px solid var(--accent); border-radius: 6px; color: var(--accent); font-size: 13px; font-weight: 800; text-decoration: none; white-space: nowrap; }}
    .button-link:hover {{ background: var(--accent); color: #fff; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px 14px;
      min-height: 82px;
    }}
    .metric strong {{ display: block; font-size: 24px; margin-bottom: 3px; }}
    .metric span {{ color: var(--muted); font-size: 13px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 14px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      overflow: hidden;
    }}
    .brief-list {{
      display: grid;
      gap: 10px;
    }}
    .article-panel {{ border-left: 4px solid var(--accent); }}
    .article-body {{ display: grid; gap: 8px; }}
    .article-h {{ margin: 6px 0 0; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent); }}
    .article-p {{ margin: 0; font-size: 14px; line-height: 1.5; color: var(--ink); }}
    .article-list {{ margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.5; }}
    .brief-card {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--info);
      border-radius: 8px;
      background: #fbfcf8;
      padding: 11px 12px;
      display: grid;
      grid-template-columns: minmax(0, auto) 1fr;
      gap: 10px;
      align-items: start;
    }}
    .brief-card.cat-buy {{ border-left-color: var(--buy); }}
    .brief-card.cat-sell {{ border-left-color: var(--sell); }}
    .brief-card.cat-hold {{ border-left-color: var(--hold); }}
    .brief-card.cat-watch {{ border-left-color: var(--watch); }}
    .brief-card.cat-info {{ border-left-color: var(--info); }}
    .brief-card.cat-alert {{ border-left-color: var(--alert); }}
    .manager-trajectory {{
      display: grid;
      gap: 9px;
      margin-top: 12px;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-left: 4px solid var(--watch);
      border-radius: 8px;
      background: #f7f4e7;
    }}
    .manager-trajectory-heading {{ display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }}
    .manager-trajectory-heading strong {{ font-size: 13px; }}
    .manager-trajectory-heading span {{ color: var(--muted); font-size: 11px; }}
    .manager-trajectory-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .manager-trajectory-window {{ padding: 8px 9px; border-radius: 7px; background: #fffdf7; }}
    .manager-trajectory-window strong {{ display: block; font-size: 13px; }}
    .manager-trajectory-window span {{ display: block; margin-top: 3px; color: var(--muted); font-size: 11px; line-height: 1.35; }}
    .manager-trajectory-read {{ margin: 0; color: var(--accent); font-size: 12px; line-height: 1.4; }}
    @media (max-width: 620px) {{ .manager-trajectory-grid {{ grid-template-columns: 1fr; }} }}
    .brief-card-media {{
      display: grid;
      gap: 6px;
      justify-items: center;
      align-content: start;
    }}
    .brief-card-body {{
      display: grid;
      gap: 7px;
      min-width: 0;
    }}
    .brief-card-rank {{
      font-size: var(--rank-size-md);
      font-weight: var(--rank-weight);
      color: var(--rank-muted);
      line-height: 1;
      text-align: center;
    }}
    .brief-card-rank.brief-card-rank-top {{
      font-size: var(--rank-size-lg);
      color: var(--rank-color);
    }}
    .brief-card-headshot {{
      width: var(--headshot-size);
      height: var(--headshot-size);
    }}
    .headshot-img {{
      width: var(--headshot-size);
      height: var(--headshot-size);
      object-fit: cover;
      border-radius: var(--headshot-radius);
      background: var(--headshot-fallback-bg);
      display: block;
    }}
    .headshot-fallback {{
      width: var(--headshot-size);
      height: var(--headshot-size);
      border-radius: var(--headshot-radius);
      background: var(--headshot-fallback-bg);
      color: var(--headshot-fallback-ink);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 800;
    }}
    .delta-cell {{ font-variant-numeric: tabular-nums; }}
    .delta-up {{ color: var(--buy); font-weight: 700; }}
    .delta-down {{ color: var(--sell); font-weight: 700; }}
    .delta-flat {{ color: var(--muted); }}
    .score-tile {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: var(--tile-size);
      height: var(--tile-size);
      border-radius: var(--tile-radius);
      padding: 0 6px;
      font-size: var(--tile-font-size);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}
    .score-tile.score-high {{ background: var(--buy-bg); color: var(--buy); }}
    .score-tile.score-mid {{ background: var(--watch-bg); color: #7a5f28; }}
    .score-tile.score-low {{ background: var(--sell-bg); color: var(--sell); }}
    .brief-card-title {{
      font-weight: 700;
      line-height: 1.25;
    }}
    .brief-card-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .brief-chip {{
      border: 1px solid var(--line);
      background: #ffffff;
      border-radius: 999px;
      padding: 2px 7px;
      font-size: 12px;
      color: #34403b;
      line-height: 1.35;
    }}
    .brief-card-evidence {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }}
    .brief-card-summary {{
      font-size: 14px;
      line-height: 1.45;
      color: var(--ink);
    }}
    .decision-outcome {{
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: end;
    }}
    .decision-outcome label {{
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .evidence-drawer {{
      border-top: 1px solid var(--line);
      margin-top: 4px;
      padding-top: 7px;
    }}
    .evidence-drawer summary {{
      cursor: pointer;
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
    }}
    .manager-event-list {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}
    .manager-event-row {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcf8;
      padding: 10px;
    }}
    .manager-event-row p {{
      margin: 6px 0 0;
    }}
    .lens-preset-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .lens-weight-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .lens-weight {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcf8;
      padding: 10px;
      display: grid;
      gap: 7px;
    }}
    .lens-weight-label {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: #34403b;
      font-size: 13px;
      font-weight: 700;
    }}
    input[type="range"] {{
      width: 100%;
      min-width: 0;
      padding: 0;
      accent-color: var(--accent);
    }}
    .scenario-status {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 10px 12px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: #34403b; background: #f1f3ed; font-weight: 700; position: sticky; top: 0; }}
    .table-wrap {{ overflow: auto; max-height: 520px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); }}
    .tag {{ display: inline-block; color: #fff; background: var(--accent); border-radius: 4px; padding: 2px 6px; font-size: 12px; }}
    .warn {{ background: var(--accent-2); }}
    .note {{ color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .view-block {{ margin: 0 0 34px; }}
    /* Per-type gating (v2): redraft leagues hide the dynasty-only surfaces -- future-pick
       tooling and dynasty-cycle framing have no meaning in a one-season league. */
    body.league-redraft #pick-ledger,
    body.league-redraft nav a[href="#pick-ledger"],
    body.league-redraft #manager-map,
    body.league-redraft .dynasty-only {{ display: none; }}
    .entity-header {{ display: flex; gap: 16px; align-items: flex-start; margin: 0 0 16px; }}
    .entity-header h2 {{ margin: 0 0 8px; }}
    .entity-headshot .headshot-img, .entity-headshot .headshot-fallback {{ width: 72px; height: 72px; font-size: 20px; }}
    .tile-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 16px; }}
    .horizon-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 12px 0; }}
    .horizon-card {{ background: #f7f8f4; border: 1px solid var(--line); border-radius: 10px; padding: 12px; min-width: 0; }}
    .horizon-card .brief-card-evidence {{ margin: 8px 0 4px; }}
    .horizon-card-meter {{ height: 7px; margin: 10px 0 8px; overflow: hidden; border-radius: 99px; background: #dce4dc; }}
    .horizon-card-meter-fill {{ display: block; height: 100%; border-radius: inherit; background: var(--accent); }}
    .horizon-card-meter-na {{ background: repeating-linear-gradient(135deg, #dce4dc 0 4px, #f2f4ee 4px 8px); }}
    .horizon-basis summary {{ color: var(--accent); cursor: pointer; font-size: 0.82rem; }}
    .horizon-market-list {{ display: grid; gap: 10px; }}
    .horizon-market-card {{ border: 1px solid var(--line); border-radius: 10px; background: #fbfcf8; padding: 12px; }}
    .horizon-market-card .brief-card-title {{ margin-bottom: 5px; }}
    .horizon-market-card .brief-card-title a {{ color: var(--ink); text-decoration: none; }}
    .horizon-market-card .brief-card-title a:hover {{ color: var(--accent); text-decoration: underline; }}
    .horizon-market-score-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin: 9px 0; }}
    .horizon-market-fit-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .horizon-market-delta-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .horizon-market-score {{ border-left: 3px solid var(--accent); background: #f2f4ee; padding: 7px 8px; min-width: 0; }}
    .horizon-market-score strong {{ display: block; font-size: 17px; }}
    .horizon-market-score span {{ color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .horizon-market-score-top {{ display: flex; justify-content: space-between; gap: 6px; align-items: baseline; }}
    .horizon-market-score-top strong {{ flex: 0 0 auto; }}
    .horizon-market-score-top span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .horizon-market-meter {{ height: 6px; margin: 7px 0 4px; overflow: hidden; border-radius: 99px; background: #dce4dc; }}
    .horizon-market-meter-fill {{ display: block; height: 100%; min-width: 0; border-radius: inherit; background: var(--accent); }}
    .horizon-market-meter-na {{ background: repeating-linear-gradient(135deg, #dce4dc 0 4px, #f2f4ee 4px 8px); }}
    .horizon-market-scale {{ display: block; color: var(--muted); font-size: 9px; letter-spacing: 0; text-transform: none; }}
    .horizon-market-delta {{ border-left-color: var(--gold); background: #fbf7e9; }}
    .horizon-market-card .evidence-drawer {{ margin-top: 8px; }}
    .horizon-view-row {{ display: flex; gap: 7px; overflow-x: auto; padding: 2px 0 4px; margin: 4px 0 8px; scrollbar-width: thin; }}
    .horizon-view {{ flex: 0 0 auto; min-height: 36px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); background: var(--panel); font-size: 12px; font-weight: 800; }}
    .horizon-view.active {{ color: var(--panel); border-color: var(--accent); background: var(--accent); }}
    .horizon-view-note {{ margin: 0 0 10px; padding: 9px 10px; border-left: 3px solid var(--gold); color: #4c514a; background: #fbf7e9; font-size: 12px; line-height: 1.4; }}
    .horizon-market-primary {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; margin: 10px 0; padding: 10px; border: 1px solid #c8d2c5; border-radius: 8px; background: #f2f4ee; }}
    .horizon-market-primary strong {{ display: block; font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }}
    .horizon-market-primary p {{ margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .horizon-market-primary-score {{ color: var(--accent); font-size: 25px; font-weight: 900; font-variant-numeric: tabular-nums; text-align: right; }}
    .horizon-market-primary-score small {{ display: block; color: var(--muted); font-size: 9px; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }}
    .horizon-market-card.is-focused {{ border-color: #a8c4b1; box-shadow: 0 2px 0 rgba(15, 92, 74, .08); }}
    .horizon-position-section {{ margin: 16px 0; }}
    .horizon-position-section h4 {{ margin: 0 0 8px; color: var(--accent); font-size: 13px; letter-spacing: .06em; text-transform: uppercase; }}
    .horizon-position-section h4 .note {{ color: var(--muted); font-size: 10px; font-weight: 600; letter-spacing: 0; text-transform: none; }}
    @media (max-width: 900px) {{ .horizon-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 700px) {{ .horizon-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 900px) {{ .horizon-market-score-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .horizon-market-fit-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
    @media (max-width: 700px) {{ .horizon-market-score-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    .entity-tile {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; min-width: 96px; text-align: center; }}
    .entity-tile-value {{ font-size: 20px; font-weight: 800; }}
    .entity-tile-value.score-high {{ color: var(--buy); }}
    .entity-tile-value.score-mid {{ color: #7a5f28; }}
    .entity-tile-value.score-low {{ color: var(--sell); }}
    .entity-tile-label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 2px; }}
    .entity-link {{ color: var(--accent); text-decoration: none; font-weight: 700; }}
    .entity-link:hover {{ text-decoration: underline; }}
    .back-link {{ display: inline-block; color: var(--muted); text-decoration: none; font-size: 13px; margin: 0 0 12px; }}
    .back-link:hover {{ color: var(--ink); }}
    .data-drawer {{ border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 10px 14px; margin: 0 0 14px; }}
    .data-drawer summary {{ cursor: pointer; color: var(--accent); font-size: 13px; font-weight: 700; }}
    .data-drawer[open] summary {{ margin-bottom: 10px; }}
    #entity-search {{ width: 100%; min-width: 0; margin-bottom: 4px; }}
    #entity-search-results a {{ display: block; color: #f8f4ea; text-decoration: none; padding: 5px 9px; border-radius: 6px; font-size: 13px; }}
    #entity-search-results a:hover {{ background: rgba(255,255,255,0.08); }}
    #entity-search-results .entity-kind {{ color: #96a89d; font-size: 11px; margin-left: 5px; }}
    .joke {{ color: #53635b; font-size: 13px; font-style: italic; }}
    .loading {{ padding: 22px 28px; color: var(--muted); }}
    .list {{ margin: 0; padding-left: 20px; font-size: 13px; }}
    @media (max-width: 720px) {{
      .app-shell {{ display: block; }}
      .side-rail {{ position: static; height: auto; padding: 14px 14px 10px; }}
      .side-rail h1 {{ font-size: 21px; margin-bottom: 4px; }}
      .side-rail p {{ display: none; }}
      .side-rail .nav-group {{ margin-bottom: 10px; }}
      .side-rail .nav-group .nav-group-title {{ display: none; }}
      .side-rail .section-nav {{ display: flex; gap: 6px; overflow-x: auto; padding-bottom: 3px; scrollbar-width: thin; }}
      .side-rail .section-nav a {{ flex: 0 0 auto; padding: 7px 10px; font-size: 12px; white-space: nowrap; }}
      .side-rail .find-nav {{ margin-bottom: 0; }}
      header {{ padding: 10px 14px; }}
      header h1 {{ display: none; }}
      header p {{ margin: 0; font-size: 12px; }}
      header, main {{ padding-left: 14px; padding-right: 14px; }}
      main {{ padding-top: 14px; }}
      .grid {{ grid-template-columns: 1fr; }}
      th {{ position: static; }}
      select, input {{ width: 100%; }}
    }}
  </style>
</head>
<body class="{body_class}">
  <script id="front-office-manifest" type="application/json">{manifest_json}</script>
  <div class="app-shell">
    <aside class="side-rail">
      <div class="brand-kicker">Dynasty Command</div>
      <h1>The Front Office</h1>
      <p>Find the market leak, then pretend it was obvious all along.</p>
      <div class="nav-group">
        <div class="nav-group-title">Where To</div>
        <nav class="section-nav">
          <a href="#view-today">Today</a>
          <a href="#view-draft-room">Draft Room</a>
          <a href="#view-my-team">My Team</a>
          <a href="#view-players">Players</a>
          <a href="#view-league">League</a>
          <a href="#view-trade-desk">Trade Desk</a>
          <a href="#view-news">News</a>
          <a href="#view-data-room">Data Room</a>
        </nav>
      </div>
      <div class="nav-group">
        <div class="nav-group-title">Find</div>
        <nav class="find-nav">
          <input id="entity-search" type="search" placeholder="player or team..." autocomplete="off">
          <div id="entity-search-results"></div>
        </nav>
      </div>
    </aside>
    <div>
      <header>
        <h1>The Front Office</h1>
        <p><span id="active-team-label">{escape(my_team_name)}</span> weekly command surface. Read-only, because the league chat already has enough chaos.</p>
      </header>
      <div id="loading-state" class="loading">Opening the binder, checking the cap table, and pretending future picks are a real currency...</div>
      <main hidden>
    <section id="view-today">
    <div id="todays-board" class="view-block">
      <h2>Today</h2>
      <div class="panel article-panel"><h3>Daily GM Brief <span id="daily-gm-brief-mode" class="tag"></span></h3><div id="daily-gm-brief"></div></div>
      <h3>Today's Board</h3>
      <p class="note">One ranked list, highest priority first. Each player/pick/manager appears once, whichever signal ranked it highest.</p>
      <div class="panel"><div id="today-priority-board"></div></div>
    </div>

    <div id="decision-board" class="view-block">
      <h2>Decision Board</h2>
      <div class="controls">
        <label>Active team<select id="team-filter"></select></label>
        <label>Search<input id="global-search" type="search" placeholder="player, team, pick, manager"></label>
        <button id="reset-filters" type="button">Reset</button>
      </div>
      <div class="metrics">
        <div class="metric"><strong id="metric-roster">0</strong><span>rostered players</span></div>
        <div class="metric"><strong id="metric-qb">0</strong><span>quarterbacks</span></div>
        <div class="metric"><strong id="metric-rb">0</strong><span>running backs</span></div>
        <div class="metric"><strong id="metric-pass">0</strong><span>pass catchers</span></div>
        <div class="metric"><strong id="metric-my-picks-away">0</strong><span>my original picks elsewhere</span></div>
        <div class="metric"><strong id="metric-team-trades">0</strong><span>team trades</span></div>
      </div>
      <div class="grid">
        <div class="panel">
          <h3>My Original Picks Elsewhere</h3>
          <div id="my-pick-alerts"></div>
        </div>
        <div class="panel">
          <h3>Likely Trade Counterparties</h3>
          <div id="likely-traders"></div>
        </div>
      </div>
    </div>
    </section>

    <section id="view-draft-room">
    <div id="draft-room" class="view-block">
      <h2>Draft Room</h2>
      <p class="note">A league-scoped draft-season read: what to circle, what to move, and where your draft capital gives you leverage. Every card shows the evidence behind the read.</p>
      <div id="draft-room-status" class="panel article-panel"></div>
      <div class="metrics">
        <div class="metric"><strong id="draft-room-available">0</strong><span>available market names</span></div>
        <div class="metric"><strong id="draft-room-targets">0</strong><span>trade targets</span></div>
        <div class="metric"><strong id="draft-room-fades">0</strong><span>roster fades</span></div>
        <div class="metric"><strong id="draft-room-picks">0</strong><span>future picks in scope</span></div>
      </div>
      <div class="grid">
        <div class="panel"><h3>Circle These Names</h3><div id="draft-room-board"></div></div>
        <div class="panel"><h3>Acquire Before the Draft</h3><div id="draft-room-target-list"></div></div>
        <div class="panel"><h3>Fades / Price Traps</h3><div id="draft-room-fade-list"></div></div>
      </div>
      <h3>Pick Leverage</h3>
      <div id="draft-room-pick-list"></div>
      <details class="data-drawer">
        <summary>Draft Room data notes</summary>
        <div id="draft-room-data-quality" class="brief-card-evidence"></div>
      </details>
    </div>
    </section>

    <section id="view-my-team">
    <div id="team-overview" class="view-block">
      <h2>My Team</h2>
      <div class="grid">
        <div class="panel"><h3>Team Overview</h3><div id="team-overview-panel"></div></div>
        <div class="panel"><h3>Strategy Overlay</h3><div id="strategy-panel"></div></div>
      </div>
    </div>

    <div id="roster-value" class="view-block">
      <h2>Roster Value Board</h2>
      <div class="panel article-panel"><h3>Your Team Report <span id="team-report-mode" class="tag"></span></h3><div id="team-report"></div></div>
      <div class="controls">
        <label>Position<select id="position-filter"></select></label>
        <label>Status<select id="status-filter"></select></label>
      </div>
      <p class="note">Strategy tags are deterministic evidence labels from the selected roster's fit, need, liquidity, and action rows. Open a player dossier or the Data Room to inspect the underlying evidence.</p>
      <div id="roster-table"></div>
    </div>
    </section>

    <section id="view-players">
    <div id="player-room" class="view-block">
      <h2>Players</h2>
      <p class="note">Player tags combine roster status, market value, projections, news, signals, and league transaction history. A tag is a research prompt with evidence, not a parade route. Click any player card to open their page.</p>
      <div id="player-browser"></div>
      <div class="grid">
        <div class="panel"><h3>Active Team Player Cards</h3><div id="player-dossier-cards"></div></div>
        <div class="panel"><h3>Player Tag Board</h3><div id="player-tag-cards"></div></div>
      </div>
      <h3>Player Dossiers</h3>
      <div id="player-dossier-table"></div>
      <h3>Player Transaction History</h3>
      <div id="player-transaction-history-table"></div>
    </div>

    <div id="projection-board" class="view-block">
      <h2>Projection Board</h2>
      <div class="controls">
        <button class="projection-scope active" data-projection-scope="team" type="button">Active Team</button>
        <button class="projection-scope" data-projection-scope="league" type="button">League</button>
        <label>Confidence<select id="projection-confidence-filter"></select></label>
      </div>
      <div id="projection-table"></div>
    </div>
    </section>

    <section id="view-league">
    <div id="manager-room" class="view-block">
      <h2>League</h2>
      <div class="panel article-panel"><h3>Manager Intel <span id="manager-intel-mode" class="tag"></span></h3><div id="manager-intel"></div></div>
      <div class="panel"><h3>Standings &amp; outcome coverage</h3><div id="league-standings" data-testid="standings-panel"></div></div>
      <h3>Manager Room</h3>
      <p class="note">Manager tags are deterministic reads from observed trades, waivers, FAAB, picks, roster shape, and recency. They estimate tendencies; they do not read minds, sadly. Click a manager card to open their page.</p>
      <div id="manager-grid"></div>
      <div class="grid">
        <div class="panel"><h3>Active Manager Dossier</h3><div id="active-manager-dossier"></div></div>
        <div class="panel"><h3>League Manager Tags</h3><div id="manager-tag-cards"></div></div>
      </div>
      <div class="panel"><h3>Personal Trade Profiles</h3><p class="note">Your private notes shape reporter emphasis; they are never presented as observed league evidence.</p><div id="manager-trade-profiles"></div></div>
      <h3>Manager Cycle Profiles</h3>
      <div id="manager-cycle-table"></div>
      <h3>Manager Tag Evidence</h3>
      <div id="manager-profile-tag-table"></div>
      <div class="panel"><h3>Manager Dossiers</h3><div id="manager-dossier-receipt" class="note"></div><div id="manager-dossiers"></div></div>
    </div>

    <div id="manager-map" class="view-block">
      <h2>Manager Map</h2>
      <div class="grid">
        <div class="panel"><h3>Manager Valuation Profiles</h3><div id="manager-valuation-table"></div></div>
        <div class="panel"><h3>Observed Transaction Lanes</h3><p class="note">Identity-resolved acquisitions and disposals by position. The clock averages are current context for historically moved players, not historical prices or proof of intent.</p><div id="manager-transaction-preferences-table"></div></div>
        <div class="panel"><h3>Behavior Signals</h3><div id="manager-signal-table"></div></div>
        <div class="panel"><h3>Manager Event Log</h3><div id="manager-event-table"></div></div>
      </div>
    </div>

    <div id="manager-behavior" class="view-block">
      <h2>Manager Behavior</h2>
      <div id="active-manager-profile"></div>
      <h3>League Manager Profiles</h3>
      <div id="manager-table"></div>
    </div>
    </section>

    <section id="view-trade-desk">
    <div id="signal-board" class="view-block">
      <h2>Trade Desk</h2>
      <div class="panel article-panel"><h3>Market Watch <span id="market-watch-mode" class="tag"></span></h3><div id="market-watch"></div></div>
      <h3>Four-Window Market Board</h3>
      <p class="note">This is the deterministic market underneath the articles. The four scores—next game, rest of season, dynasty, and career window—are position-relative percentiles from 0–100, not dollar market values or cross-position price rankings, and are not yet outcome-calibrated forecasts. Use the clock-versus-market deltas to find same-position repricing leads, then compare immediate utility, remaining-season value, and dynasty value before deciding whether an asset fits a contender, a rebuilder, or neither. Every row links to the player dossier and keeps its evidence receipt one click away.</p>
      <div class="horizon-view-row" role="tablist" aria-label="Market decision view">
        <button class="horizon-view active" data-horizon-view="all" type="button">All clocks</button>
        <button class="horizon-view" data-horizon-view="this_week" type="button">This week</button>
        <button class="horizon-view" data-horizon-view="rest_of_season" type="button">Rest of season</button>
        <button class="horizon-view" data-horizon-view="dynasty" type="button">Dynasty / career</button>
        <button class="horizon-view" data-horizon-view="fit" type="button">Contender vs rebuilder</button>
        <button class="horizon-view" data-horizon-view="repricing" type="button">Repricing leads</button>
      </div>
      <p id="horizon-view-note" class="horizon-view-note">All clocks: use this when you want the full player card. Scores remain position-relative percentiles; market value is the cross-position price anchor.</p>
      <div class="controls">
        <button class="horizon-scope active" data-horizon-scope="team" type="button">Active Team</button>
        <button class="horizon-scope" data-horizon-scope="league" type="button">League</button>
        <label>Value lane<select id="horizon-lane-filter"></select></label>
        <label>Sort by<select id="horizon-sort-filter"></select></label>
      </div>
      <div id="horizon-market-summary" class="tile-row"></div>
      <div id="horizon-market-board"></div>
      <h3>Signal Board</h3>
      <div class="controls">
        <button class="signal-scope active" data-signal-scope="team" type="button">Active Team</button>
        <button class="signal-scope" data-signal-scope="league" type="button">League</button>
        <label>Label<select id="signal-label-filter"></select></label>
        <label>Confidence<select id="signal-confidence-filter"></select></label>
      </div>
      <div class="grid">
        <div class="panel"><h3>Breakout Candidates</h3><div id="signal-breakouts"></div></div>
        <div class="panel"><h3>Sell Candidates</h3><div id="signal-sells"></div></div>
      </div>
      <h3>Projection Market Gaps</h3>
      <div id="signal-gap-table"></div>
      <h3>News-Market Dislocations</h3>
      <p class="note">These rows connect a current scoped catalyst to a deterministic price or sell-pressure gap. They are research leads, not proof that the market is wrong.</p>
      <div id="news-market-edge-table"></div>
      <h3>Team Fit Scores</h3>
      <div id="team-fit-table"></div>
    </div>

    <div id="analyst-brief" class="view-block">
      <h2>Analyst Brief</h2>
      <p class="note">Analysis is interpretation generated from deterministic tables. It does not send, accept, or execute transactions.</p>
      <div class="controls">
        <button class="analysis-scope active" data-analysis-scope="team" type="button">Active Team</button>
        <button class="analysis-scope" data-analysis-scope="league" type="button">League</button>
        <label>Confidence<select id="analysis-confidence-filter"></select></label>
      </div>
      <div class="grid">
        <div class="panel"><h3>Target Theses</h3><div id="target-theses"></div></div>
        <div class="panel"><h3>Sell Theses</h3><div id="sell-theses"></div></div>
        <div class="panel"><h3>Trade Theses</h3><div id="trade-theses"></div></div>
      </div>
    </div>

    <div id="market-gaps" class="view-block">
      <h2>Market Gaps</h2>
      <div class="controls">
        <button class="gap-scope active" data-gap-scope="targets" type="button">Targets</button>
        <button class="gap-scope" data-gap-scope="team" type="button">My Assets</button>
        <button class="gap-scope" data-gap-scope="league" type="button">League</button>
      </div>
      <div id="market-gap-table"></div>
    </div>

    <div id="counterparty-edges" class="view-block">
      <h2>Counterparty Edges</h2>
      <div class="panel article-panel"><h3>Trade Desk Read <span id="trade-desk-read-mode" class="tag"></span></h3><div id="trade-desk-read"></div></div>
      <p class="note">These are estimated value disagreements, not trade quotes. Nobody has accepted anything. The commissioner can breathe.</p>
      <div class="grid">
        <div class="panel"><h3>We May Value More Than Owner</h3><div id="edge-we-value-more"></div></div>
        <div class="panel"><h3>Owner May Overvalue</h3><div id="edge-owner-overvalues"></div></div>
        <div class="panel"><h3>Do Not Chase</h3><div id="edge-do-not-chase"></div></div>
       <div class="panel"><h3>Best Manager Fits</h3><div id="edge-mutual-fit"></div></div>
      </div>
      <h3>Who Might Value Our Assets?</h3>
      <p class="note">These are audience signals for players on the active roster. They combine an identity-resolved historical position lane, current team need, and available horizon fit. A conversation-fit score is a research priority, not intent, willingness, or a generated offer.</p>
      <div id="counterparty-asset-interest" data-testid="counterparty-interest-board"></div>
      <div id="counterparty-asset-interest-table"></div>
      <h3>Counterparty Edge Table</h3>
      <div id="counterparty-edge-table"></div>
    </div>

    <div id="market-lens-lab" class="view-block">
      <h2>Market Lens Lab</h2>
      <p class="note">Scenario rankings are browser-only exploration. They do not change canonical tables, default recommendations, or anyone's actual asking price.</p>
      <div class="lens-preset-row" id="market-lens-presets"></div>
      <div class="lens-weight-grid">
        <div class="lens-weight">
          <div class="lens-weight-label"><span>Market Consensus</span><span id="lens-market-value">25</span></div>
          <input id="lens-market" data-lens="market" type="range" min="0" max="100" value="25">
        </div>
        <div class="lens-weight">
          <div class="lens-weight-label"><span>Projection Value</span><span id="lens-projection-value">25</span></div>
          <input id="lens-projection" data-lens="projection" type="range" min="0" max="100" value="25">
        </div>
        <div class="lens-weight">
          <div class="lens-weight-label"><span>Manager Preference</span><span id="lens-manager-value">20</span></div>
          <input id="lens-manager" data-lens="manager" type="range" min="0" max="100" value="20">
        </div>
        <div class="lens-weight">
          <div class="lens-weight-label"><span>Timeline / Team Fit</span><span id="lens-timeline-value">20</span></div>
          <input id="lens-timeline" data-lens="timeline" type="range" min="0" max="100" value="20">
        </div>
        <div class="lens-weight">
          <div class="lens-weight-label"><span>News Heat</span><span id="lens-news-value">10</span></div>
          <input id="lens-news" data-lens="news" type="range" min="0" max="100" value="10">
        </div>
      </div>
      <div id="market-lens-status" class="scenario-status"></div>
      <div class="grid">
        <div class="panel"><h3>Scenario Targets</h3><div id="scenario-targets"></div></div>
        <div class="panel"><h3>Scenario Sells</h3><div id="scenario-sells"></div></div>
        <div class="panel"><h3>Biggest Movers</h3><div id="scenario-movers"></div></div>
      </div>
      <h3>Scenario Detail</h3>
      <div id="scenario-table"></div>
    </div>

    <div id="asset-ledger" class="view-block">
      <h2>Asset Ledger</h2>
      <div id="asset-ledger-table"></div>
    </div>

    <div id="opportunity-board" class="view-block">
      <h2>Opportunity Board</h2>
      <div id="opportunity-table"></div>
    </div>

    <div id="pick-ledger" class="view-block">
      <h2>Pick Ledger</h2>
      <div class="controls">
        <button class="pick-filter active" data-pick-filter="all" type="button">All Picks</button>
        <button class="pick-filter" data-pick-filter="my-original-away" type="button">My Original Elsewhere</button>
        <button class="pick-filter" data-pick-filter="currently-owned" type="button">Currently Owned</button>
        <button class="pick-filter" data-pick-filter="active-original" type="button">Active Team Original</button>
      </div>
      <div id="pick-table"></div>
    </div>

    <div id="trade-market" class="view-block">
      <h2>Trade Market</h2>
      <div class="controls">
        <button class="scope-filter active" data-scope="team" type="button">Active Team</button>
        <button class="scope-filter" data-scope="league" type="button">League</button>
      </div>
      <div id="trade-table"></div>
    </div>

    <div id="waiver-market" class="view-block">
      <h2>Waiver Market</h2>
      <div class="controls">
        <button class="waiver-scope active" data-waiver-scope="team" type="button">Active Team</button>
        <button class="waiver-scope" data-waiver-scope="league" type="button">League</button>
        <label>Status<select id="waiver-status-filter"></select></label>
      </div>
      <div id="waiver-table"></div>
    </div>
    </section>

    <section id="view-news">
    <div id="news-desk" class="view-block">
      <h2>News Desk</h2>
      <div class="panel article-panel"><h3>News Impact Brief</h3><div id="news-impact-brief"></div></div>
      <div class="controls">
        <button class="news-scope active" data-news-scope="league-impact" type="button">League Impact</button>
        <button class="news-scope" data-news-scope="watchlist" type="button">Watchlist / Waiver</button>
        <button class="news-scope" data-news-scope="unmatched" type="button">Unmatched Feed Items</button>
      </div>
      <div id="news-impact-table"></div>
      <h3>Player News Matches</h3>
      <div id="news-match-table"></div>
    </div>
    </section>

    <section id="view-data-room">
    <div id="question-led-data-room" class="view-block">
      <div class="data-room-intro question-led-intro">
        <div>
          <span class="section-kicker">Question-led data room</span>
          <h2>Ask the room a useful question.</h2>
          <p class="note">These summaries answer one decision question at a time, then leave the underlying tables and source receipts one click away.</p>
        </div>
        <span class="tag">Sleeper facts first</span>
      </div>
      <div class="data-room-question-grid" role="tablist" aria-label="Data Room questions">
        <button type="button" class="data-room-question active" data-data-question="changed">What changed?</button>
        <button type="button" class="data-room-question" data-data-question="matters">Why does it matter to my team?</button>
        <button type="button" class="data-room-question" data-data-question="mispriced">Which players are mispriced?</button>
        <button type="button" class="data-room-question" data-data-question="traders">Who is most likely to trade?</button>
        <button type="button" class="data-room-question" data-data-question="disagree">Which signals disagree?</button>
        <button type="button" class="data-room-question" data-data-question="weak">What evidence is weak or stale?</button>
        <button type="button" class="data-room-question" data-data-question="next">What should I investigate next?</button>
      </div>
      <div id="data-room-answer" class="question-answer" role="status"></div>
      <div id="data-room-visuals" class="decision-visual-grid"></div>
    </div>
    <div class="panel article-panel learning-ledger" id="learning-ledger">
      <h3>Decision ledger</h3>
      <p class="note">Only deliberate signals appear here. Reading an article is not treated as approval, and a tracked call remains unresolved until you record what happened.</p>
      <div id="learning-ledger-body"><p class="note">No explicit feedback recorded for this edition yet.</p></div>
    </div>
    <div class="panel article-panel edition-changes" id="edition-changes">
      <h3>Since the last edition</h3>
      <p class="note">This compares the current article receipts with the last recorded publication state. A changed evidence fingerprint means the underlying packet changed; it is not a claim that the recommendation improved.</p>
      <div id="edition-changes-body"><p class="note">No prior publication receipt is available yet.</p></div>
    </div>
    <div class="panel article-panel media-ledger" id="media-ledger">
      <h3>Editorial media receipt</h3>
      <p class="note">Artwork is atmosphere, not evidence. This receipt shows its scope and responsive delivery without allowing an image to carry a fantasy claim.</p>
      <div id="media-ledger-body"><p class="note">No media receipt is available yet.</p></div>
    </div>
    <div class="panel article-panel data-quality-receipt" id="data-quality-receipt">
      <h3>Historical identity receipt</h3>
      <p class="note">Freshness tells us when the bundle was built. This receipt tells us whether historical player rows can be joined to canonical Sleeper players before a dossier or story relies on them.</p>
      <div id="data-quality-receipt-body"><p class="note">No historical identity receipt is available yet.</p></div>
    </div>
    <div id="operator-mode" class="view-block">
      <h2>Data Room</h2>
      <h3>Operator Mode</h3>
      <p class="note">Personal-use update loop. These controls refresh facts, build Codex packets, validate insight output, and rebuild the browser. They require the operator token and never execute league transactions.</p>
      <div class="panel">
        <div class="controls">
          <label>Operator token<input id="operator-token" type="password" placeholder="FRONT_OFFICE_OPERATOR_TOKEN"></label>
          <button id="operator-refresh" type="button">Refresh Data</button>
          <button id="operator-build-packet" type="button">Build Insight Packet</button>
          <button id="operator-generate-insights" type="button">Update &amp; Write Analysis (LLM)</button>
          <button id="operator-generation-plan" type="button">Preview Writer Plan (no call)</button>
          <button id="operator-import" type="button">Import Insight JSON</button>
          <button id="operator-validate" type="button">Validate Insights</button>
          <button id="operator-rebuild" type="button">Rebuild Browser</button>
          <button id="operator-reload" type="button">Reload Latest</button>
          <button id="operator-copy-chat-context" type="button">Copy Chat Context</button>
        </div>
      <p class="note">Update &amp; Write Analysis refreshes the data, then has the configured writer provider write one focused article per section (Team Report, Market Watch, Four-Window Market Read, Trade Desk Read, Manager Intel) plus the Daily GM Brief, and rebuilds the site. Each article has its own reporter lens and falls back to its deterministic version if its own call fails. Copy Chat Context copies clean markdown, ready to paste into any chat, instead of raw JSON.</p>
        <textarea id="operator-insight-json" rows="8" placeholder="Paste Codex/ChatGPT insight JSON here when you want the app to validate and import it."></textarea>
        <div id="operator-status-panel"></div>
        <div id="operator-generation-plan-panel"></div>
        <div id="operator-chat-context-status"></div>
      </div>
    </div>

    <div id="diagnostics" class="view-block">
      <h2>Diagnostics</h2>
      <p class="note">Data Diagnostics, source freshness, and audit payloads. This is where the facts live before anyone starts doing victory laps.</p>
      <div class="panel article-panel"><h3>Model Verification <span class="tag">backtested</span></h3>
        <p class="note">Rolling-origin backtest on nflverse 1999-2024 (30 snapshots, 12,263 player-snapshots, <code>scripts/backtest.py</code>) for predicting rest-of-season top finishes: <strong>production_score AUC 0.85</strong>, <strong>opportunity_score AUC 0.80</strong> -- both strong, confirming opportunity (target share, air yards, carries) is a real forward-looking signal. xfp_regression / role_trend / fragility score below 0.55 standalone, so they are used only as buy-low / role / risk <em>flags</em>, never as ranking scores.</p>
      </div>
      <div id="diagnostics-panel"></div>
    </div>

    <div id="draft" class="view-block"><h2>Draft Results</h2><div id="draft-table"></div></div>
    </section>

    <section id="player-page">
      <div id="player-page-body"><p class="note">Pick a player from any card, table, or the search box to open their page.</p></div>
    </section>

    <section id="team-page">
      <div id="team-page-body"><p class="note">Pick a manager from the League view to open their page.</p></div>
    </section>
      </main>
    </div>
  </div>
  <script>
    const manifest = JSON.parse(document.getElementById('front-office-manifest').textContent);
    let app = null;
    let tables = {{}};
    let analysis = {{}};
    let draftRoom = {{}};
    const state = {{
      activeSection: 'view-today',
      teamId: 0,
      query: '',
      position: 'ALL',
      status: 'ALL',
      pickFilter: 'all',
      tradeScope: 'team',
      waiverScope: 'team',
      waiverStatus: 'ALL',
      gapScope: 'targets',
      newsScope: 'league-impact'
      , projectionScope: 'team',
      projectionConfidence: 'ALL',
      signalScope: 'team',
      signalLabel: 'ALL',
      signalConfidence: 'ALL',
      horizonScope: 'team',
      horizonLane: 'ALL',
      horizonSort: 'team_fit',
      horizonView: 'all',
      analysisScope: 'team',
      analysisConfidence: 'ALL',
      dataQuestion: 'changed',
      lensPreset: 'Balanced Market',
      lensWeights: {{ market: 25, projection: 25, manager: 20, timeline: 20, news: 10 }},
      operatorToken: '',
      operatorStatus: null,
      writerPlan: null
    }};

    const marketLensPresets = {{
      'Balanced Market': {{ market: 25, projection: 25, manager: 20, timeline: 20, news: 10 }},
      'Projection Contrarian': {{ market: 10, projection: 45, manager: 15, timeline: 20, news: 10 }},
      'Counterparty Exploit': {{ market: 15, projection: 20, manager: 40, timeline: 15, news: 10 }},
      'Contender Trade Market': {{ market: 30, projection: 25, manager: 20, timeline: 15, news: 10 }},
      'Rebuild Asset Bank': {{ market: 20, projection: 20, manager: 15, timeline: 35, news: 10 }},
      'News Heat Check': {{ market: 20, projection: 15, manager: 15, timeline: 10, news: 40 }}
    }};

    const strategyRosterColumns = ['player_name', 'position', 'nfl_team', 'roster_status', 'age', 'strategy_fit', 'strategy_action', {{ field: 'timeline_fit_score', kind: 'score' }}, {{ field: 'liquidity_fit_score', kind: 'score' }}];
    const managerColumns = ['team_name', 'owner_id', 'seasons_covered', 'roster_ids_by_season', 'total_trades', 'future_1sts_acquired', 'future_1sts_sold', 'faab_spent_on_waivers', 'number_of_waiver_claims', 'contender_rebuilder_indicator'];
    const pickColumns = ['pick_season', 'round', 'original_team', 'current_owner', 'previous_owner', 'is_my_original_pick', 'i_currently_own_it'];
    const tradeColumns = ['week', 'created_datetime', 'team_a_name', 'team_a_players_received', 'team_a_picks_received', 'team_a_faab_received', 'team_b_name', 'team_b_players_received', 'team_b_picks_received', 'team_b_faab_received'];
    const waiverColumns = ['week', 'team_name', 'player_added', 'player_dropped', 'waiver_bid', 'status', 'failure_reason'];
    const draftColumns = ['pick_no', 'round', 'roster_id', 'player_name', 'position', 'nfl_team'];
    const marketGapColumns = ['opportunity_type', 'target_team', 'asset_type', 'asset_name', 'position', 'current_availability_status', 'availability_note', 'market_value', {{ field: 'market_gap_score', kind: 'delta' }}, 'timeline_fit', 'evidence', 'risk', 'confidence'];
    const counterpartyColumns = ['edge_type', 'target_team', 'player_name', 'position', 'target_team_lens', {{ field: 'target_horizon_fit_score', label: 'Target fit percentile', kind: 'score' }}, {{ field: 'active_horizon_fit_score', label: 'Active fit percentile', kind: 'score' }}, {{ field: 'horizon_fit_edge', label: 'Fit spread', kind: 'delta' }}, 'horizon_fit_read', 'horizon_market_disagreement_window', {{ field: 'horizon_market_disagreement_delta', label: 'Clock / market delta', kind: 'delta' }}, {{ field: 'next_game_market_score', label: 'This-week percentile', kind: 'score' }}, {{ field: 'rest_of_season_market_score', label: 'Season percentile', kind: 'score' }}, {{ field: 'dynasty_market_score', label: 'Dynasty percentile', kind: 'score' }}, {{ field: 'career_projection_score', label: 'Career-window percentile', kind: 'score' }}, {{ field: 'our_value_score', kind: 'score' }}, {{ field: 'market_consensus_value', label: 'Market price anchor', kind: 'score' }}, {{ field: 'estimated_owner_value_score', kind: 'score' }}, {{ field: 'trade_edge_score', kind: 'delta' }}, 'evidence', 'risk', 'confidence'];
    const counterpartyInterestColumns = ['asset_name', 'position', 'target_team', 'target_team_lens', 'transaction_lane_read', 'transaction_acquired_count', 'transaction_sold_count', 'target_need', {{ field: 'target_need_fit_score', label: 'Need-fit percentile', kind: 'score' }}, {{ field: 'target_horizon_fit_score', label: 'Target fit percentile', kind: 'score' }}, {{ field: 'conversation_fit_score', label: 'Conversation priority', kind: 'score' }}, 'conversation_fit_label', 'horizon_market_disagreement_window', {{ field: 'horizon_market_disagreement_delta', label: 'Clock / market delta', kind: 'delta' }}, {{ field: 'next_game_market_score', label: 'This-week percentile', kind: 'score' }}, {{ field: 'rest_of_season_market_score', label: 'Season percentile', kind: 'score' }}, {{ field: 'dynasty_market_score', label: 'Dynasty percentile', kind: 'score' }}, {{ field: 'career_projection_score', label: 'Career-window percentile', kind: 'score' }}, 'horizon_fit_read', 'confidence', 'evidence', 'risk'];
    const scenarioColumns = ['scenario_label', 'target_team', 'player_name', 'position', {{ field: 'scenario_score', kind: 'score' }}, 'canonical_model', {{ field: 'market_component', kind: 'score' }}, {{ field: 'projection_component', kind: 'score' }}, {{ field: 'manager_component', kind: 'score' }}, {{ field: 'timeline_component', kind: 'score' }}, {{ field: 'news_component', kind: 'score' }}, 'scenario_warning', 'confidence'];
    const assetLedgerColumns = ['asset_type', 'asset_name', 'position', 'market_value', 'liquidity_tier', 'timeline_fit', 'source_trace'];
    const opportunityColumns = ['action_type', 'target_team', 'asset_in', 'asset_out', 'manager_signal', 'evidence', 'risk', 'confidence', 'source_trace'];
    const marketConsensusColumns = ['player_name', 'position', 'consensus_value', 'source_count', 'disagreement_score', 'best_source', 'confidence', 'source_trace'];
    const managerSignalColumns = ['team_name', {{ field: 'trade_activity_score', kind: 'score' }}, {{ field: 'pick_buyer_score', kind: 'score' }}, {{ field: 'pick_seller_score', kind: 'score' }}, {{ field: 'faab_aggression_score', kind: 'score' }}, {{ field: 'waiver_activity_score', kind: 'score' }}, 'plain_language_label', 'evidence'];
    const managerValuationColumns = ['team_name', 'asset_type', 'position_group', 'preference_score', 'evidence_count', 'confidence', 'label', 'evidence'];
    const managerTransactionPreferenceColumns = ['team_name', 'position_group', 'transaction_read', 'acquired_count', 'sold_count', 'net_acquired_count', 'current_roster_acquired_count', 'current_roster_sold_count', {{ field: 'acquired_next_game_market_score', label: 'Acquired this-week percentile' }}, {{ field: 'sold_next_game_market_score', label: 'Sold this-week percentile' }}, {{ field: 'acquired_rest_of_season_market_score', label: 'Acquired season percentile' }}, {{ field: 'sold_rest_of_season_market_score', label: 'Sold season percentile' }}, {{ field: 'acquired_dynasty_market_score', label: 'Acquired dynasty percentile' }}, {{ field: 'sold_dynasty_market_score', label: 'Sold dynasty percentile' }}, {{ field: 'acquired_career_projection_score', label: 'Acquired career-window percentile' }}, {{ field: 'sold_career_projection_score', label: 'Sold career-window percentile' }}, {{ field: 'acquired_rebuilder_fit_score', label: 'Acquired rebuilder-fit percentile' }}, {{ field: 'sold_rebuilder_fit_score', label: 'Sold rebuilder-fit percentile' }}, 'horizon_coverage', {{ field: 'horizon_coverage_detail', label: 'Coverage by clock' }}, 'history_status', 'confidence', 'evidence'];
    const managerEventColumns = ['season', 'league_id', 'owner_id', 'event_type', 'week', 'team_name', 'counterparty', 'players_in', 'picks_in', 'faab_in', 'players_out', 'picks_out', 'faab_out', 'evidence'];
    const leagueStandingsColumns = ['team_name', 'record', 'wins', 'losses', 'ties', 'points_for', 'points_against', 'point_diff', 'outcome_status'];
    const sourceColumns = ['source', 'dataset', 'status', 'row_count', 'checked_at', 'source_url', 'cache_path'];
    const newsImpactColumns = ['published_at', 'source', 'player_name', 'league_id', 'season', 'roster_id', 'team_name', 'impact_type', 'evidence', 'risk', 'confidence', 'source_trace'];
    const newsMatchColumns = ['source', 'input_player_name', 'matched_player_name', 'match_method', 'match_confidence', 'is_ambiguous', 'source_trace'];
    const todayOpportunityColumns = ['opportunity_type', 'target_team', 'asset_name', 'position', 'market_gap_score', 'evidence', 'risk', 'confidence'];
    const todayNewsColumns = ['published_at', 'source', 'player_name', 'league_id', 'season', 'roster_id', 'team_name', 'impact_type', 'evidence', 'risk', 'confidence'];
    const todayManagerColumns = ['team_name', 'plain_language_label', 'trade_activity_score', 'pick_seller_score', 'faab_aggression_score', 'evidence'];
    const projectionColumns = ['player_name', 'position', 'team', 'team_name', 'current_availability_status', 'availability_note', {{ field: 'projected_fantasy_points', label: 'Projected fantasy points (availability-aware)', kind: 'score' }}, {{ field: 'projected_ppg', label: 'Baseline PPG (availability-aware)', kind: 'score' }}, 'projected_games', 'projection_confidence', 'projection_method', 'projection_note'];
    const signalGapColumns = ['player_name', 'position', 'current_availability_status', {{ field: 'projected_fantasy_points', label: 'Projected fantasy points (availability-aware)', kind: 'score' }}, {{ field: 'projected_ppg', label: 'Baseline PPG (availability-aware)' }}, {{ field: 'market_value', label: 'Market price anchor' }}, {{ field: 'projection_percentile', label: 'Projection percentile (position)' }}, {{ field: 'market_percentile', label: 'Market percentile (position)' }}, 'market_gap_status', {{ field: 'gap_score', label: 'Projection minus market percentile', kind: 'delta' }}, 'gap_label', 'risk', 'confidence', 'evidence'];
    const newsMarketEdgeColumns = ['player_name', 'position', 'team_name', 'news_direction', 'edge_type', 'news_impact', 'news_event_count', 'market_value', {{ field: 'projected_ppg', label: 'Baseline PPG (availability-aware)' }}, {{ field: 'news_market_edge_score', kind: 'score' }}, 'risk', 'confidence', 'evidence'];
    const teamFitColumns = ['team_name', 'player_name', 'position', 'fit_label', {{ field: 'timeline_fit_score', kind: 'score' }}, {{ field: 'need_fit_score', kind: 'score' }}, {{ field: 'liquidity_fit_score', kind: 'score' }}, 'risk', 'confidence', 'evidence'];
    const actionColumns = ['consumer_label', 'player_name', 'position', 'team_name', 'current_availability_status', 'action_score', {{ field: 'projected_ppg', label: 'Baseline PPG (availability-aware)' }}, 'market_value', 'why', 'risk', 'confidence'];
    const managerCycleColumns = ['team_name', 'dynasty_cycle', 'trade_temperature', 'pick_posture', 'waiver_posture', 'likely_needs', 'likely_sells', 'confidence', 'evidence'];
    const profileTagColumns = ['entity_name', 'tag', 'score', 'confidence', 'evidence', 'risk'];
    const playerDossierColumns = ['player_name', 'position', 'team_name', 'roster_status', {{ field: 'availability_scope', label: 'Availability source' }}, 'current_availability_status', 'market_value', {{ field: 'projected_ppg', label: 'Baseline PPG (availability-aware)' }}, 'projection_confidence', 'availability_note', 'signal_label', 'breakout_score', 'sell_score', 'news_impact', 'transaction_count', 'last_transaction'];
    const playerHistoryColumns = ['player_name', 'event_type', 'season', 'week', 'team_name', 'counterparty', 'direction', 'identity_method', 'evidence'];
    async function init() {{
      try {{
        app = await fetchJson(manifest.bundlePath);
      }} catch (error) {{
        document.getElementById('loading-state').textContent = `The Front Office could not load its data bundle: ${{error.message}}`;
        return;
      }}
      tables = app.tables || {{}};
      analysis = app.analysis || {{}};
      draftRoom = app.draftRoom || {{}};
      state.teamId = Number(app.myRosterId);
      ensureTables();
      populateTeamFilter();
      populateSelect('position-filter', ['ALL', ...unique(tables.roster_players.map(row => row.position)).sort()]);
      populateSelect('status-filter', ['ALL', ...unique(tables.roster_players.map(row => row.roster_status)).sort()]);
      populateSelect('waiver-status-filter', ['ALL', ...unique(tables.waivers.map(row => row.status)).sort()]);
      populateSelect('projection-confidence-filter', ['ALL', ...unique(tables.player_projection_season.map(row => row.projection_confidence)).sort()]);
      populateSelect('signal-label-filter', ['ALL', ...unique(tables.player_signal_scores.map(row => row.signal_label)).sort()]);
      populateSelect('signal-confidence-filter', ['ALL', ...unique(tables.player_signal_scores.map(row => row.confidence)).sort()]);
      populateSelect('horizon-lane-filter', ['ALL', ...unique(tables.player_horizon_market_scores.map(row => row.value_lane)).sort()]);
      populateSelect('horizon-sort-filter', ['team_fit', 'rebuilder_contender_spread', 'market_disagreement', 'market_lead', 'market_lag', 'next_game_market_score', 'rest_of_season_market_score', 'dynasty_market_score', 'career_projection_score']);
      populateSelect('analysis-confidence-filter', ['ALL', ...unique([...(analysis.targetTheses || []), ...(analysis.sellTheses || []), ...(analysis.tradeTheses || [])].map(row => row.confidence)).sort()]);
      renderMarketLensPresetButtons();
      bindControls();
      await refreshOperatorStatus();
      document.getElementById('loading-state').hidden = true;
      document.querySelector('main').hidden = false;
      render();
      hydrateLearningLedger();
      hydrateEditionChanges();
      showSection(location.hash.replace('#', ''));
    }}

    async function fetchJson(path) {{
      const response = await fetch(path, {{ cache: 'no-store' }});
      if (!response.ok) throw new Error(`${{response.status}} ${{response.statusText}}`);
      return response.json();
    }}

    async function refreshOperatorStatus() {{
      try {{
        const statusPath = manifest.leagueId
          ? `/api/operator/status?league_id=${{encodeURIComponent(manifest.leagueId)}}`
          : '/api/operator/status';
        state.operatorStatus = await fetchJson(statusPath);
      }} catch (error) {{
        overlayOperatorStatus({{ state: 'unavailable', message: `Operator API unavailable: ${{error.message}}`, operator_enabled: false }});
      }}
    }}

    function overlayOperatorStatus(patch) {{
      // Keep the live writer/readiness receipt visible when an action is blocked
      // or fails; a small status replacement must not erase provider evidence.
      state.operatorStatus = {{ ...(state.operatorStatus || {{}}), ...patch }};
    }}

    async function runOperatorAction(path) {{
      if (!state.operatorToken) {{
        overlayOperatorStatus({{ state: 'blocked', message: 'Enter the operator token before running write actions.' }});
        render();
        return;
      }}
      if (path.includes('/generate-insights')) state.writerPlan = null;
      try {{
        const response = await fetch(path, {{
          method: 'POST',
          cache: 'no-store',
          headers: {{
            'Content-Type': 'application/json',
            'X-Front-Office-Token': state.operatorToken
          }},
          body: JSON.stringify({{ league_id: manifest.leagueId || '' }})
        }});
        state.operatorStatus = await response.json();
      }} catch (error) {{
        overlayOperatorStatus({{ state: 'failed', message: `Operator action failed: ${{error.message}}` }});
      }}
      render();
      pollOperatorStatus();
    }}

    async function previewWriterPlan() {{
      const panel = document.getElementById('operator-generation-plan-panel');
      if (!state.operatorToken) {{
        panel.innerHTML = '<p class="note">Enter the operator token before previewing the writer plan.</p>';
        return;
      }}
      panel.innerHTML = '<p class="note">Inspecting scoped evidence and publication receipts. No provider request will be made.</p>';
      try {{
        const response = await fetch('/api/operator/generation-plan?league_id=' + encodeURIComponent(manifest.leagueId || ''), {{
          method: 'GET',
          cache: 'no-store',
          headers: {{ 'X-Front-Office-Token': state.operatorToken }}
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'writer plan failed (' + response.status + ')');
        state.writerPlan = payload;
        render();
      }} catch (error) {{
        state.writerPlan = {{ state: 'failed', message: `Writer plan failed: ${{error.message}}`, articles: {{}} }};
        render();
      }}
    }}

    async function copyChatContext() {{
      const statusEl = document.getElementById('operator-chat-context-status');
      if (!state.operatorToken) {{
        statusEl.textContent = 'Enter the operator token before copying chat context.';
        return;
      }}
      statusEl.textContent = 'Building chat context...';
      try {{
        const response = await fetch('/api/operator/chat-context?league_id=' + encodeURIComponent(manifest.leagueId || ''), {{
          method: 'GET',
          cache: 'no-store',
          headers: {{ 'X-Front-Office-Token': state.operatorToken }}
        }});
        const payload = await response.json();
        if (!response.ok || payload.state !== 'complete') {{
          statusEl.textContent = `Chat context failed: ${{payload.message || response.statusText}}`;
          return;
        }}
        await navigator.clipboard.writeText(payload.markdown || '');
        statusEl.textContent = 'Chat context copied to clipboard.';
      }} catch (error) {{
        statusEl.textContent = `Chat context failed: ${{error.message}}`;
      }}
    }}

    async function runOperatorImport() {{
      if (!state.operatorToken) {{
        overlayOperatorStatus({{ state: 'blocked', message: 'Enter the operator token before importing insights.' }});
        render();
        return;
      }}
      let payload = {{}};
      try {{
        payload = JSON.parse(document.getElementById('operator-insight-json').value || '{{}}');
      }} catch (error) {{
        overlayOperatorStatus({{ state: 'failed', message: `Insight JSON is invalid: ${{error.message}}` }});
        render();
        return;
      }}
      try {{
        const response = await fetch('/api/operator/import-insights', {{
          method: 'POST',
          cache: 'no-store',
          headers: {{
            'Content-Type': 'application/json',
            'X-Front-Office-Token': state.operatorToken
          }},
          body: JSON.stringify({{ ...payload, league_id: manifest.leagueId || '' }})
        }});
        state.operatorStatus = await response.json();
      }} catch (error) {{
        overlayOperatorStatus({{ state: 'failed', message: `Insight import failed: ${{error.message}}` }});
      }}
      render();
      pollOperatorStatus();
    }}

    async function pollOperatorStatus() {{
      // Luna plus an explicit editor pass can legitimately take several
      // minutes. Keep the receipt visible long enough to observe completion;
      // the durable status endpoint remains the authority if this tab sleeps.
      // Six Luna calls at the configured timeout can outlive the old five
      // minute window. Keep polling for a bounded 30 minutes; the durable
      // receipt remains authoritative if this tab sleeps.
      for (let index = 0; index < 900; index += 1) {{
        await sleep(2000);
        await refreshOperatorStatus();
        render();
        if (!state.operatorStatus || state.operatorStatus.state !== 'running') return;
      }}
    }}

    function sleep(ms) {{
      return new Promise(resolve => setTimeout(resolve, ms));
    }}

    function ensureTables() {{
      [
        'teams', 'players', 'roster_players', 'manager_profiles', 'pick_ownership', 'trades', 'waivers', 'matchups', 'league_standings',
        'draft_picks', 'refresh_metadata', 'player_usage_weekly', 'nfl_schedule', 'nfl_team_defense_factors', 'market_value_sources', 'market_consensus_values',
        'player_market_values', 'pick_market_values', 'team_asset_inventory', 'manager_event_log', 'manager_season_history', 'team_needs_matrix', 'manager_behavior_signals',
        'manager_valuation_profiles', 'manager_transaction_preferences', 'liquidity_scores', 'asset_market_gaps', 'opportunity_board', 'counterparty_trade_edges', 'counterparty_asset_interest', 'source_freshness', 'news_events',
        'player_news_matches', 'league_news_impact', 'news_source_freshness', 'player_projection_season',
        'player_projection_weekly', 'projection_source_freshness', 'player_signal_scores', 'breakout_candidates',
        'sell_candidates', 'projection_market_gaps', 'news_market_edges', 'team_fit_scores', 'action_recommendations',
        'manager_profile_tags', 'manager_cycle_profiles', 'player_dossiers', 'player_transaction_history', 'player_profile_tags',
        'player_horizon_market_scores', 'available_player_horizon_scores', 'horizon_score_accuracy', 'horizon_market_movements'
      ].forEach(name => {{
        if (!Array.isArray(tables[name])) tables[name] = [];
      }});
    }}

    function populateTeamFilter() {{
      const select = document.getElementById('team-filter');
      select.innerHTML = currentSeasonTeams()
        .slice()
        .sort((a, b) => String(a.team_name).localeCompare(String(b.team_name)))
        .map(team => `<option value="${{escapeHtml(team.roster_id)}}">${{escapeHtml(team.team_name || team.display_name)}}</option>`)
        .join('');
      select.value = String(state.teamId);
    }}

    function populateSelect(id, values) {{
      const select = document.getElementById(id);
      select.innerHTML = values.map(value => `<option value="${{escapeHtml(value)}}">${{escapeHtml(label(value))}}</option>`).join('');
    }}

    function bindControls() {{
      document.getElementById('team-filter').addEventListener('change', event => {{
        state.teamId = Number(event.target.value);
        render();
      }});
      document.getElementById('global-search').addEventListener('input', event => {{
        state.query = event.target.value.trim().toLowerCase();
        render();
      }});
      document.getElementById('position-filter').addEventListener('change', event => {{
        state.position = event.target.value;
        render();
      }});
      document.getElementById('status-filter').addEventListener('change', event => {{
        state.status = event.target.value;
        render();
      }});
      document.getElementById('waiver-status-filter').addEventListener('change', event => {{
        state.waiverStatus = event.target.value;
        render();
      }});
      document.getElementById('projection-confidence-filter').addEventListener('change', event => {{
        state.projectionConfidence = event.target.value;
        render();
      }});
      document.getElementById('signal-label-filter').addEventListener('change', event => {{
        state.signalLabel = event.target.value;
        render();
      }});
      document.getElementById('signal-confidence-filter').addEventListener('change', event => {{
        state.signalConfidence = event.target.value;
        render();
      }});
      document.getElementById('horizon-lane-filter').addEventListener('change', event => {{
        state.horizonLane = event.target.value;
        render();
      }});
      document.getElementById('horizon-sort-filter').addEventListener('change', event => {{
        state.horizonSort = event.target.value;
        render();
      }});
      document.querySelectorAll('.horizon-view').forEach(button => {{
        button.addEventListener('click', () => {{
          state.horizonView = button.dataset.horizonView || 'all';
          const defaultSort = {{
            all: 'team_fit',
            this_week: 'next_game_market_score',
            rest_of_season: 'rest_of_season_market_score',
            dynasty: 'dynasty_market_score',
            fit: 'team_fit',
            repricing: 'market_disagreement'
          }}[state.horizonView] || 'team_fit';
          state.horizonSort = defaultSort;
          syncControls();
          render();
        }});
      }});
      document.getElementById('analysis-confidence-filter').addEventListener('change', event => {{
        state.analysisConfidence = event.target.value;
        render();
      }});
      document.getElementById('reset-filters').addEventListener('click', () => {{
        state.teamId = Number(app.myRosterId);
        state.query = '';
        state.position = 'ALL';
        state.status = 'ALL';
        state.pickFilter = 'all';
        state.tradeScope = 'team';
        state.waiverScope = 'team';
        state.waiverStatus = 'ALL';
        state.gapScope = 'targets';
        state.newsScope = 'league-impact';
        state.projectionScope = 'team';
        state.projectionConfidence = 'ALL';
        state.signalScope = 'team';
        state.signalLabel = 'ALL';
        state.signalConfidence = 'ALL';
        state.horizonScope = 'team';
        state.horizonLane = 'ALL';
        state.horizonSort = 'team_fit';
        state.horizonView = 'all';
        state.analysisScope = 'team';
        state.analysisConfidence = 'ALL';
        syncControls();
        render();
      }});
      document.querySelectorAll('.pick-filter').forEach(button => {{
        button.addEventListener('click', () => {{
          state.pickFilter = button.dataset.pickFilter;
          setActive('.pick-filter', button);
          render();
        }});
      }});
      document.querySelectorAll('.scope-filter').forEach(button => {{
        button.addEventListener('click', () => {{
          state.tradeScope = button.dataset.scope;
          setActive('.scope-filter', button);
          render();
        }});
      }});
      document.querySelectorAll('.waiver-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.waiverScope = button.dataset.waiverScope;
          setActive('.waiver-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.gap-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.gapScope = button.dataset.gapScope;
          setActive('.gap-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.news-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.newsScope = button.dataset.newsScope;
          setActive('.news-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.projection-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.projectionScope = button.dataset.projectionScope;
          setActive('.projection-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.signal-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.signalScope = button.dataset.signalScope;
          setActive('.signal-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.horizon-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.horizonScope = button.dataset.horizonScope;
          setActive('.horizon-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.analysis-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.analysisScope = button.dataset.analysisScope;
          setActive('.analysis-scope', button);
          render();
        }});
      }});
      document.querySelectorAll('.data-room-question').forEach(button => {{
        button.addEventListener('click', () => {{
          state.dataQuestion = button.dataset.dataQuestion || 'changed';
          setActive('.data-room-question', button);
          renderDataRoomQuestions();
        }});
      }});
      document.querySelectorAll('.lens-preset').forEach(button => {{
        button.addEventListener('click', () => {{
          state.lensPreset = button.dataset.preset;
          state.lensWeights = {{ ...marketLensPresets[state.lensPreset] }};
          syncLensControls();
          render();
        }});
      }});
      document.querySelectorAll('[data-lens]').forEach(input => {{
        input.addEventListener('input', () => {{
          state.lensWeights[input.dataset.lens] = Number(input.value);
          state.lensPreset = 'Custom';
          syncLensControls();
          render();
        }});
      }});
      document.getElementById('operator-token').addEventListener('input', event => {{
        state.operatorToken = event.target.value.trim();
      }});
      document.addEventListener('click', event => {{
        const button = event.target.closest('[data-content-interaction]');
        if (button) recordContentInteraction(button);
      }});
      document.getElementById('operator-refresh').addEventListener('click', () => runOperatorAction('/api/operator/refresh'));
      document.getElementById('operator-build-packet').addEventListener('click', () => runOperatorAction('/api/operator/build-packet'));
      document.getElementById('operator-generate-insights').addEventListener('click', () => runOperatorAction('/api/operator/generate-insights'));
      document.getElementById('operator-generation-plan').addEventListener('click', () => previewWriterPlan());
      document.getElementById('operator-import').addEventListener('click', () => runOperatorImport());
      document.getElementById('operator-validate').addEventListener('click', () => runOperatorAction('/api/operator/validate-insights'));
      document.getElementById('operator-rebuild').addEventListener('click', () => runOperatorAction('/api/operator/rebuild-browser'));
      document.getElementById('operator-reload').addEventListener('click', () => window.location.reload());
      document.getElementById('operator-copy-chat-context').addEventListener('click', () => copyChatContext());
      document.querySelectorAll('.side-rail nav a').forEach(link => {{
        link.addEventListener('click', event => {{
          event.preventDefault();
          showSection(link.getAttribute('href').slice(1));
        }});
      }});
      // Entity links (#player-..., #team-...) created dynamically in cards, search results, and
      // entity pages need no listeners: native anchor navigation changes the hash and the
      // hashchange listener below routes it.
      window.addEventListener('hashchange', () => showSection(location.hash.replace('#', '')));
      const entitySearch = document.getElementById('entity-search');
      entitySearch.addEventListener('input', () => renderEntitySearch(entitySearch.value));
      document.getElementById('entity-search-results').addEventListener('click', () => {{
        document.getElementById('entity-search-results').innerHTML = '';
        entitySearch.value = '';
      }});
    }}

    async function recordContentInteraction(button) {{
      const interactionType = button.dataset.contentInteraction;
      const artifactKey = button.dataset.artifactKey;
      if (!interactionType || !artifactKey || !manifest.leagueId) return;
      const decisionNode = interactionType === 'decision_outcome' ? button.closest('[data-decision-key]') : null;
      const outcomeSelect = interactionType === 'outcome'
        ? button.closest('[data-article-key]')?.querySelector('[data-outcome-select]')
        : decisionNode?.querySelector('[data-decision-outcome-select]');
      const outcome = outcomeSelect ? String(outcomeSelect.value || 'open') : '';
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Saving...';
      try {{
        const response = await fetch(`/api/leagues/${{encodeURIComponent(manifest.leagueId)}}/content-interactions`, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            artifact_type: interactionType === 'decision_outcome' ? 'recommendation' : 'article',
            artifact_key: artifactKey,
            interaction_type: interactionType,
            payload: {{
              bundle_revision: manifest.bundleRevision || '',
              mode: interactionType === 'decision_outcome' ? 'explicit_recommendation_outcome' : interactionType === 'outcome' ? 'explicit_article_outcome' : 'explicit_reader_feedback',
              ...(outcome ? {{
                outcome,
                prediction_key: `${{interactionType === 'decision_outcome' ? 'recommendation' : 'article'}}:${{artifactKey}}:${{manifest.bundleRevision || 'unbound'}}`,
                ...(decisionNode ? {{
                  decision_type: decisionNode.dataset.decisionType || '',
                  subject_id: decisionNode.dataset.decisionSubjectId || '',
                  subject_name: decisionNode.dataset.decisionSubjectName || '',
                  confidence: decisionNode.dataset.decisionConfidence || '',
                  risk: decisionNode.dataset.decisionRisk || '',
                  evidence: decisionNode.dataset.decisionEvidence || ''
                }} : {{}})
              }} : {{}})
            }}
          }})
        }});
        if (!response.ok) throw new Error(`${{response.status}}`);
        button.textContent = interactionType === 'outcome' ? 'Outcome saved' : 'Saved';
        hydrateLearningLedger();
      }} catch (error) {{
        button.textContent = original;
        button.disabled = false;
        console.warn('Could not save article feedback', error);
      }}
    }}

    function managerGridCards() {{
      const cycles = tables.manager_cycle_profiles || [];
      if (!cycles.length) return '<p class="note">No manager profiles yet.</p>';
      return `<div class="brief-list">${{cycles.map(row => briefCard({{
        title: row.team_name || `Roster ${{row.roster_id}}`,
        category: categoryFor('dynasty_cycle', row.dynasty_cycle),
        entityHash: `team-${{num(row.roster_id)}}`,
        chips: [label(row.dynasty_cycle || ''), row.trade_temperature, row.pick_posture],
        summary: row.likely_needs ? `Needs: ${{row.likely_needs}}` : ''
      }})).join('')}}</div>`;
    }}

    function leagueStandingsMarkup() {{
      const rows = currentLeagueStandings();
      if (!rows.length) return '<p class="note">No team rows are available for the current league snapshot.</p>';
      const recorded = rows.filter(row => ['recorded', 'partial'].includes(String(row.outcome_status || ''))).length;
      const coverage = `${{recorded}} of ${{rows.length}} teams have scored matchup evidence for ${{escapeHtml(String(app.currentSeason || 'the current season'))}}.`;
      return `<p class="note"><strong>Outcome coverage:</strong> ${{coverage}} Results come from exact Sleeper matchup rows; teams without scored rows remain <em>not recorded</em>.</p>${{table(rows, leagueStandingsColumns)}}`;
    }}

    function currentLeagueStandings() {{
      const rows = scopedCurrentRows(tables.league_standings || []);
      return rows.slice().sort((a, b) => {{
        const statusRank = row => String(row.outcome_status || '') === 'not_recorded' ? 1 : 0;
        return statusRank(a) - statusRank(b)
          || Number(b.wins || 0) - Number(a.wins || 0)
          || Number(b.point_diff || -Infinity) - Number(a.point_diff || -Infinity)
          || Number(b.points_for || -Infinity) - Number(a.points_for || -Infinity)
          || String(a.team_name || '').localeCompare(String(b.team_name || ''));
      }});
    }}

    function managerTradeProfileCards() {{
      const profiles = (app.managerTradeProfiles || []).filter(row => row.customized);
      if (!profiles.length) return '<p class="note">No personal trade profiles saved yet. Add them from headquarters when you want a reporter to remember the room.</p>';
      return `<div class="brief-list">${{profiles.map(row => `<article class="brief-card">
        <div class="brief-card-top"><strong>${{escapeHtml(row.manager_name || `Roster ${{row.roster_id}}`)}}</strong><span class="tag">Private editor note</span></div>
        ${{row.trade_style ? `<p><strong>Approach:</strong> ${{escapeHtml(row.trade_style)}}</p>` : ''}}
        ${{row.preferred_assets ? `<p><strong>Will chase:</strong> ${{escapeHtml(row.preferred_assets)}}</p>` : ''}}
        ${{row.protected_assets ? `<p><strong>Protects:</strong> ${{escapeHtml(row.protected_assets)}}</p>` : ''}}
        ${{row.editor_note ? `<p class="note">${{escapeHtml(row.editor_note)}}</p>` : ''}}
      </article>`).join('')}}</div>`;
    }}

    function playerBrowserCards() {{
      const rows = sortRows(applySearch(tables.player_dossiers), ['market_value']).reverse().slice(0, 24);
      if (!rows.length) return '<p class="note">No player dossiers yet.</p>';
      return `<h3>Top of the Player Pool</h3><div class="brief-list">${{rows.map((row, index) => briefCard({{
        title: row.player_name || 'Unknown',
        category: categoryFor('signal_label', row.signal_label),
        rank: index + 1,
        playerId: row.player_id,
        entityHash: `player-${{row.player_id}}`,
        chips: [row.position, row.team_name, row.market_value ? `market ${{row.market_value}}` : '', row.projected_ppg !== undefined && row.projected_ppg !== '' ? projectionPpgText(row, row.projected_ppg) : '', row.injury_status ? `availability ${{row.injury_status}}` : '']
      }})).join('')}}</div>`;
    }}

    function renderEntitySearch(query) {{
      const box = document.getElementById('entity-search-results');
      const needle = String(query || '').trim().toLowerCase();
      if (needle.length < 2) {{ box.innerHTML = ''; return; }}
      const players = (tables.player_dossiers || [])
        .filter(row => String(row.player_name || '').toLowerCase().includes(needle))
        .slice(0, 6)
        .map(row => `<a href="#player-${{escapeHtml(String(row.player_id))}}">${{escapeHtml(row.player_name)}}<span class="entity-kind">${{escapeHtml(row.position || 'player')}}</span></a>`);
      const teams = currentSeasonTeams()
        .filter(row => String(row.team_name || row.display_name || '').toLowerCase().includes(needle))
        .slice(0, 4)
        .map(row => `<a href="#team-${{Number(row.roster_id)}}">${{escapeHtml(row.team_name || row.display_name)}}<span class="entity-kind">team</span></a>`);
      const results = [...players, ...teams];
      box.innerHTML = results.length ? results.join('') : '<a href="javascript:void(0)"><span class="entity-kind">no matches</span></a>';
    }}

    function renderMarketLensPresetButtons() {{
      const target = document.getElementById('market-lens-presets');
      if (!target) return;
      target.innerHTML = Object.keys(marketLensPresets)
        .map(name => `<button class="lens-preset${{name === state.lensPreset ? ' active' : ''}}" data-preset="${{escapeHtml(name)}}" type="button">${{escapeHtml(name)}}</button>`)
        .join('');
    }}

    function syncControls() {{
      document.getElementById('team-filter').value = String(state.teamId);
      document.getElementById('global-search').value = state.query;
      document.getElementById('position-filter').value = state.position;
      document.getElementById('status-filter').value = state.status;
      document.getElementById('waiver-status-filter').value = state.waiverStatus;
      document.getElementById('projection-confidence-filter').value = state.projectionConfidence;
      document.getElementById('signal-label-filter').value = state.signalLabel;
      document.getElementById('signal-confidence-filter').value = state.signalConfidence;
      document.getElementById('horizon-lane-filter').value = state.horizonLane;
      document.getElementById('horizon-sort-filter').value = state.horizonSort;
      document.querySelectorAll('.horizon-view').forEach(button => button.classList.toggle('active', button.dataset.horizonView === state.horizonView));
      document.getElementById('analysis-confidence-filter').value = state.analysisConfidence;
      document.querySelectorAll('.pick-filter').forEach(button => button.classList.toggle('active', button.dataset.pickFilter === state.pickFilter));
      document.querySelectorAll('.scope-filter').forEach(button => button.classList.toggle('active', button.dataset.scope === state.tradeScope));
      document.querySelectorAll('.waiver-scope').forEach(button => button.classList.toggle('active', button.dataset.waiverScope === state.waiverScope));
      document.querySelectorAll('.gap-scope').forEach(button => button.classList.toggle('active', button.dataset.gapScope === state.gapScope));
      document.querySelectorAll('.news-scope').forEach(button => button.classList.toggle('active', button.dataset.newsScope === state.newsScope));
      document.querySelectorAll('.projection-scope').forEach(button => button.classList.toggle('active', button.dataset.projectionScope === state.projectionScope));
      document.querySelectorAll('.signal-scope').forEach(button => button.classList.toggle('active', button.dataset.signalScope === state.signalScope));
      document.querySelectorAll('.horizon-scope').forEach(button => button.classList.toggle('active', button.dataset.horizonScope === state.horizonScope));
      document.querySelectorAll('.analysis-scope').forEach(button => button.classList.toggle('active', button.dataset.analysisScope === state.analysisScope));
      syncLensControls();
    }}

    function syncLensControls() {{
      for (const [key, value] of Object.entries(state.lensWeights)) {{
        const input = document.getElementById(`lens-${{key}}`);
        const label = document.getElementById(`lens-${{key}}-value`);
        if (input) input.value = String(value);
        if (label) label.textContent = String(value);
      }}
      document.querySelectorAll('.lens-preset').forEach(button => button.classList.toggle('active', button.dataset.preset === state.lensPreset));
    }}

    function render() {{
      const activeTeam = currentSeasonTeams().find(team => Number(team.roster_id) === state.teamId) || tables.teams.find(team => Number(team.roster_id) === state.teamId) || {{}};
      const teamName = activeTeam.team_name || activeTeam.display_name || 'Unknown team';
      document.getElementById('active-team-label').textContent = teamName;

      let roster = currentSeasonRoster().filter(row => Number(row.roster_id) === state.teamId);
      if (state.position !== 'ALL') roster = roster.filter(row => row.position === state.position);
      if (state.status !== 'ALL') roster = roster.filter(row => row.roster_status === state.status);
      roster = applySearch(roster);

      const allTeamRoster = currentSeasonRoster().filter(row => Number(row.roster_id) === state.teamId);
      const qbCount = allTeamRoster.filter(row => row.position === 'QB').length;
      const rbCount = allTeamRoster.filter(row => row.position === 'RB').length;
      const passCount = allTeamRoster.filter(row => row.position === 'WR' || row.position === 'TE').length;
      const teamTrades = tables.trades.filter(row => Number(row.team_a_roster_id) === state.teamId || Number(row.team_b_roster_id) === state.teamId);
      const myPicksAway = tables.pick_ownership.filter(row => truthy(row.is_my_original_pick) && !truthy(row.i_currently_own_it));
      const priorityRows = sortRows(applySearch(tables.today_priority_board), ['priority_score']).reverse().slice(0, 15);

      setText('metric-roster', allTeamRoster.length);
      setText('metric-qb', qbCount);
      setText('metric-rb', rbCount);
      setText('metric-pass', passCount);
      setText('metric-my-picks-away', myPicksAway.length);
      setText('metric-team-trades', teamTrades.length);

      document.getElementById('my-pick-alerts').innerHTML = list(myPicksAway.map(row => `${{row.pick_season}} round ${{row.round}}: ${{row.current_owner}}`));
      document.getElementById('today-priority-board').innerHTML = priorityCards(priorityRows);
      document.getElementById('team-overview-panel').innerHTML = teamOverview(activeTeam, allTeamRoster, teamTrades);
      document.getElementById('strategy-panel').innerHTML = strategyOverlay(activeTeam, allTeamRoster);
      document.getElementById('likely-traders').innerHTML = table(
        applySearch(tables.manager_profiles.slice().sort((a, b) => Number(b.total_trades) - Number(a.total_trades)).slice(0, 8)),
        managerColumns
      );
      document.getElementById('roster-table').innerHTML = table(sortRows(strategyRosterRows(roster), ['position', 'player_name']), strategyRosterColumns);
      document.getElementById('active-manager-profile').innerHTML = table(
        tables.manager_behavior_signals.filter(row => Number(row.roster_id) === state.teamId),
        managerSignalColumns
      );
      document.getElementById('projection-table').innerHTML = table(filteredProjections(), projectionColumns);
      document.getElementById('signal-breakouts').innerHTML = signalCards(signalBreakoutRows(), 'breakout');
      document.getElementById('signal-sells').innerHTML = signalCards(signalSellRows(), 'sell');
      renderHorizonMarketBoard();
      document.getElementById('signal-gap-table').innerHTML = table(filteredSignalGaps(), signalGapColumns);
      document.getElementById('news-market-edge-table').innerHTML = table(filteredNewsMarketEdges(), newsMarketEdgeColumns);
      document.getElementById('team-fit-table').innerHTML = table(filteredTeamFits(), teamFitColumns);
      document.getElementById('daily-gm-brief').innerHTML = articleBody(analysis.dailyGmBrief);
      document.getElementById('daily-gm-brief-mode').textContent = articleModeLabel(analysis.dailyGmBriefMode);
      document.getElementById('team-report').innerHTML = articleBody(analysis.teamReport);
      document.getElementById('team-report-mode').textContent = articleModeLabel(analysis.teamReportMode);
      document.getElementById('market-watch').innerHTML = articleBody(analysis.marketWatch);
      document.getElementById('market-watch-mode').textContent = articleModeLabel(analysis.marketWatchMode);
      document.getElementById('trade-desk-read').innerHTML = articleBody(analysis.tradeDeskRead);
      document.getElementById('trade-desk-read-mode').textContent = articleModeLabel(analysis.tradeDeskReadMode);
      document.getElementById('manager-intel').innerHTML = articleBody(analysis.managerIntel);
      document.getElementById('manager-intel-mode').textContent = articleModeLabel(analysis.managerIntelMode);
      document.getElementById('league-standings').innerHTML = leagueStandingsMarkup();
      document.getElementById('target-theses').innerHTML = thesisCards(filteredTargetTheses(), 'target');
      document.getElementById('sell-theses').innerHTML = thesisCards(filteredSellTheses(), 'sell');
      document.getElementById('trade-theses').innerHTML = thesisCards(filteredTradeTheses(), 'trade');
      document.getElementById('manager-dossiers').innerHTML = markdownBrief(analysis.managerDossiers);
      const dossierReceipt = analysis.managerDossierReceipt || {{}};
      document.getElementById('manager-dossier-receipt').textContent = dossierReceipt.item_count
        ? `${{dossierReceipt.item_count}} dossiers · ${{dossierReceipt.updated_count || 0}} updated · ${{dossierReceipt.unchanged_count || 0}} unchanged this refresh`
        : 'No dossier update receipt yet.';
      document.getElementById('news-impact-brief').innerHTML = markdownBrief(analysis.newsImpactBrief);
      document.getElementById('market-gap-table').innerHTML = table(filteredMarketGaps(), marketGapColumns);
      document.getElementById('edge-we-value-more').innerHTML = counterpartyCards(filteredCounterpartyEdges('we_may_value_more').slice(0, 5));
      document.getElementById('edge-owner-overvalues').innerHTML = counterpartyCards(filteredCounterpartyEdges('owner_may_overvalue').slice(0, 5));
      document.getElementById('edge-do-not-chase').innerHTML = counterpartyCards(filteredCounterpartyEdges('do_not_chase').slice(0, 5));
      document.getElementById('edge-mutual-fit').innerHTML = counterpartyCards(filteredCounterpartyEdges('mutual_fit').slice(0, 5));
      const counterpartyInterest = filteredCounterpartyInterest();
      document.getElementById('counterparty-asset-interest').innerHTML = counterpartyInterestCards(counterpartyInterest.slice(0, 8));
      document.getElementById('counterparty-asset-interest-table').innerHTML = table(counterpartyInterest, counterpartyInterestColumns);
      document.getElementById('counterparty-edge-table').innerHTML = table(filteredCounterpartyEdges(), counterpartyColumns);
      const scenarioRows = scenarioRankings();
      document.getElementById('market-lens-status').innerHTML = scenarioStatus(scenarioRows);
      document.getElementById('scenario-targets').innerHTML = scenarioCards(scenarioRows.filter(row => row.scenario_label === 'scenario_target').slice(0, 6));
      document.getElementById('scenario-sells').innerHTML = scenarioCards(scenarioRows.filter(row => row.scenario_label === 'scenario_sell').slice(0, 6));
      document.getElementById('scenario-movers').innerHTML = scenarioCards(scenarioMovers(scenarioRows).slice(0, 6));
      document.getElementById('scenario-table').innerHTML = table(scenarioRows.slice(0, 80), scenarioColumns);
      document.getElementById('asset-ledger-table').innerHTML = table(
        sortRows(applySearch(tables.team_asset_inventory.filter(row => Number(row.roster_id) === state.teamId)), ['asset_type', 'market_value']).reverse(),
        assetLedgerColumns
      );
      document.getElementById('opportunity-table').innerHTML = table(applySearch(tables.opportunity_board), opportunityColumns);
      document.getElementById('news-impact-table').innerHTML = table(filteredNewsImpact(), newsImpactColumns);
      document.getElementById('news-match-table').innerHTML = table(filteredNewsMatches(), newsMatchColumns);
      document.getElementById('manager-grid').innerHTML = managerGridCards();
      document.getElementById('player-browser').innerHTML = playerBrowserCards();
      document.getElementById('active-manager-dossier').innerHTML = activeManagerDossier();
      document.getElementById('manager-tag-cards').innerHTML = profileTagCards(filteredManagerTags().slice(0, 16), false);
      document.getElementById('manager-trade-profiles').innerHTML = managerTradeProfileCards();
      document.getElementById('manager-cycle-table').innerHTML = table(filteredManagerCycles(), managerCycleColumns);
      document.getElementById('manager-profile-tag-table').innerHTML = table(filteredManagerTags(), profileTagColumns);
      document.getElementById('player-dossier-cards').innerHTML = playerDossierCards(filteredPlayerDossiers().slice(0, 12));
      document.getElementById('player-tag-cards').innerHTML = profileTagCards(filteredPlayerTags().slice(0, 18), true);
      document.getElementById('player-dossier-table').innerHTML = table(filteredPlayerDossiers(), playerDossierColumns);
      document.getElementById('player-transaction-history-table').innerHTML = table(filteredPlayerHistory(), playerHistoryColumns);
      document.getElementById('manager-valuation-table').innerHTML = table(applySearch(tables.manager_valuation_profiles), managerValuationColumns);
      document.getElementById('manager-transaction-preferences-table').innerHTML = table(applySearch(tables.manager_transaction_preferences), managerTransactionPreferenceColumns);
      document.getElementById('manager-signal-table').innerHTML = table(applySearch(tables.manager_behavior_signals), managerSignalColumns);
      document.getElementById('manager-event-table').innerHTML = table(
        sortRows(applySearch(scopedCurrentRows(tables.manager_event_log || []).filter(row => Number(row.roster_id) === state.teamId)), ['week']).reverse(),
        managerEventColumns
      );
      document.getElementById('manager-table').innerHTML = table(applySearch(tables.manager_profiles), managerColumns);
      document.getElementById('pick-table').innerHTML = table(filteredPicks(), pickColumns);
      document.getElementById('trade-table').innerHTML = table(filteredTrades(), tradeColumns);
      document.getElementById('waiver-table').innerHTML = table(filteredWaivers(), waiverColumns);
      document.getElementById('operator-status-panel').innerHTML = operatorPanel();
      document.getElementById('operator-generation-plan-panel').innerHTML = writerPlanPanel();
      renderDataRoomQuestions();
      renderDataQualityReceipt();
      document.getElementById('diagnostics-panel').innerHTML = diagnostics();
      document.getElementById('draft-table').innerHTML = table(applySearch(tables.draft_picks), draftColumns);
      renderDraftRoom();
    }}

    function filteredMarketGaps() {{
      let rows = tables.asset_market_gaps.slice();
      if (state.gapScope === 'targets') rows = rows.filter(row => Number(row.target_roster_id) !== state.teamId);
      if (state.gapScope === 'team') rows = rows.filter(row => Number(row.target_roster_id) === state.teamId);
      return sortRows(applySearch(rows), ['market_gap_score']).reverse().slice(0, 80);
    }}

    function filteredCounterpartyEdges(edgeType = null) {{
      let rows = tables.counterparty_trade_edges.filter(row => Number(row.target_roster_id) !== state.teamId);
      if (edgeType) rows = rows.filter(row => row.edge_type === edgeType);
      return sortRows(applySearch(rows), ['trade_edge_score']).reverse().slice(0, 80);
    }}

    function filteredCounterpartyInterest() {{
      const rows = (tables.counterparty_asset_interest || [])
        .filter(row => Number(row.active_roster_id) === state.teamId);
      return sortRows(applySearch(rows), ['conversation_fit_score', 'market_value']).reverse().slice(0, 100);
    }}

    function scenarioRankings() {{
      const totalWeight = lensWeightTotal();
      const validWeights = totalWeight > 0;
      const signalByPlayer = rowMap(tables.player_signal_scores, 'player_id');
      const consensusByPlayer = rowMap(tables.market_consensus_values, 'player_id');
      const newsByPlayer = newsHeatByPlayer();
      const managerPrefs = managerPreferenceMap();
      const rows = [];

      for (const edge of tables.counterparty_trade_edges) {{
        if (Number(edge.target_roster_id) === state.teamId) continue;
        const playerId = String(edge.player_id || '');
        const signal = signalByPlayer.get(playerId) || {{}};
        const consensus = consensusByPlayer.get(playerId) || {{}};
        const positionGroup = scenarioPositionGroup(edge.position || signal.position);
        const manager = managerPrefs.get(`${{edge.target_roster_id}}|${{positionGroup}}`) || managerPrefs.get(`${{edge.target_roster_id}}|DEPTH`) || {{}};
        const marketComponent = capScore(edge.market_consensus_value || consensus.consensus_value || signal.market_value);
        const projectionComponent = capScore(signal.projection_edge_score || edge.our_value_score);
        const managerPreference = capScore(manager.preference_score);
        const managerComponent = capScore(100 - managerPreference);
        const timelineComponent = capScore(signal.timeline_fit_score);
        const newsComponent = newsByPlayer.get(playerId) || 0;
        const scenarioScore = validWeights ? weightedScenarioScore({{ marketComponent, projectionComponent, managerComponent, timelineComponent, newsComponent }}) : 0;
        const warning = scenarioWarning(consensus, signal, manager, edge, totalWeight);
        rows.push({{
          scenario_label: scenarioLabel(edge, scenarioScore, 'target'),
          target_team: edge.target_team,
          player_id: playerId,
          player_name: edge.player_name,
          position: edge.position,
          scenario_score: scenarioScore,
          canonical_model: edge.edge_type,
          market_component: marketComponent,
          projection_component: projectionComponent,
          manager_component: managerComponent,
          timeline_component: timelineComponent,
          news_component: newsComponent,
          scenario_warning: warning,
          confidence: scenarioConfidence(edge.confidence, signal.confidence, manager.confidence, warning),
          evidence: `market=${{marketComponent}}; projection=${{projectionComponent}}; manager=${{managerComponent}}; timeline=${{timelineComponent}}; news=${{newsComponent}}; canonical=${{edge.edge_type}}`
        }});
      }}

      for (const action of tables.action_recommendations.filter(row => Number(row.roster_id) === state.teamId && row.action_label === 'sell_window')) {{
        const playerId = String(action.player_id || '');
        const signal = signalByPlayer.get(playerId) || {{}};
        const consensus = consensusByPlayer.get(playerId) || {{}};
        const marketComponent = capScore(action.market_value || consensus.consensus_value || signal.market_value);
        const projectionComponent = capScore(signal.projection_edge_score || action.projected_ppg * 4);
        const managerComponent = 50;
        const timelineComponent = capScore(100 - (signal.timeline_fit_score || 50));
        const newsComponent = newsByPlayer.get(playerId) || 0;
        const scenarioScore = validWeights ? weightedScenarioScore({{ marketComponent, projectionComponent, managerComponent, timelineComponent, newsComponent }}) : 0;
        const warning = scenarioWarning(consensus, signal, {{}}, action, totalWeight);
        rows.push({{
          scenario_label: 'scenario_sell',
          target_team: action.team_name,
          player_id: playerId,
          player_name: action.player_name,
          position: action.position,
          scenario_score: scenarioScore,
          canonical_model: action.consumer_label || action.action_label,
          market_component: marketComponent,
          projection_component: projectionComponent,
          manager_component: managerComponent,
          timeline_component: timelineComponent,
          news_component: newsComponent,
          scenario_warning: warning,
          confidence: scenarioConfidence(action.confidence, signal.confidence, '', warning),
          evidence: `market=${{marketComponent}}; projection=${{projectionComponent}}; timeline_sell_pressure=${{timelineComponent}}; news=${{newsComponent}}; canonical=${{action.action_label}}`
        }});
      }}

      return sortRows(applySearch(rows), ['scenario_score']).reverse();
    }}

    function scenarioLabel(row, score, fallback) {{
      if (row.edge_type === 'do_not_chase' || score < 28) return 'do_not_chase';
      if (row.edge_type === 'owner_may_overvalue') return 'owner_may_overvalue';
      if (score >= 62) return 'scenario_target';
      if (row.edge_type === 'mutual_fit') return 'mutual_fit';
      return fallback === 'target' ? 'scenario_watch' : 'scenario_sell';
    }}

    function scenarioMovers(rows) {{
      return rows
        .map(row => ({{ ...row, mover_delta: Math.abs(num(row.scenario_score) - canonicalScore(row.canonical_model)) }}))
        .sort((a, b) => b.mover_delta - a.mover_delta);
    }}

    function scenarioCards(rows) {{
      if (!rows.length) return '<p class="note">No scenario rows found for this lens.</p>';
      return `<div class="brief-list">${{rows.map((row, index) => briefCard({{
        title: `${{row.player_name || 'Unknown asset'}} - ${{row.target_team || 'Unknown team'}}`,
        category: categoryFor('scenario_label', row.scenario_label),
        rank: index + 1,
        playerId: row.player_id,
        chips: [
          row.scenario_label,
          row.position,
          row.scenario_score ? `scenario ${{row.scenario_score}}` : '',
          row.canonical_model ? `canonical ${{row.canonical_model}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: `${{row.evidence || ''}} Warning: ${{row.scenario_warning || 'none'}}`
      }})).join('')}}</div>`;
    }}

    function scenarioStatus(rows) {{
      const total = lensWeightTotal();
      const degraded = rows.filter(row => String(row.scenario_warning || '').includes('degraded')).length;
      const summary = `Preset: ${{state.lensPreset}}. Weight total: ${{total}}. Scenario rows: ${{rows.length}}. Degraded rows: ${{degraded}}.`;
      const warning = total === 100 ? 'Weights are valid.' : 'Weights should sum to 100 before treating rankings as comparable.';
      return `${{escapeHtml(summary)}}<br>${{escapeHtml(warning)}}<br><span class="joke">This is the argument simulator. It changes rankings, not reality.</span>`;
    }}

    function writerPlanPanel() {{
      const plan = state.writerPlan;
      if (!plan) return '<p class="note">No writer plan loaded. Preview it before starting a cost-incurring run.</p>';
      const counts = plan.counts || {{}};
      const articleEntries = plan.articles && typeof plan.articles === 'object'
        ? Object.entries(plan.articles)
        : [];
      const rows = articleEntries.map(([key, item]) => ({{
        article: item?.title || key,
        reporter: item?.reporter?.name || item?.reporter?.persona_id || '',
        state: item?.state || 'unknown',
        decision: item?.decision || '',
        evidence: item?.evidence_count ?? 0,
        sources: item?.source_count ?? 0,
        reason: item?.reason || ''
      }}));
      const summary = `${{counts.generate || 0}} generation call(s) · ${{counts.reuse || 0}} reuse(s) · ${{counts.skipped || 0}} evidence-limited · ${{counts.blocked || 0}} blocked`;
      return `<div class="panel article-panel" data-testid="writer-generation-plan"><h3>Writer plan <span class="tag">no provider call</span></h3><p class="note">${{escapeHtml(plan.message || summary)}}</p><p class="note">No provider request was made for this preview. Each desk is checked against its scoped evidence fingerprint, publication receipt, reporter, content hash, and configured model. “Generate” means a new article is eligible; it does not claim that a call has happened.</p>${{rows.length ? table(rows, ['article', 'reporter', 'state', 'decision', 'evidence', 'sources', 'reason']) : '<p class="note">No article plan rows are available.</p>'}}</div>`;
    }}

    function operatorPanel() {{
      const status = state.operatorStatus || {{ state: 'unknown', message: 'Operator status has not loaded yet.' }};
      const articleEntries = status.articles && typeof status.articles === 'object'
        ? Object.entries(status.articles)
        : [];
      const legacySuccessMessage = !articleEntries.length
        && status.state === 'failed'
        && /writers run/i.test(status.message || '');
      const displayedMessage = legacySuccessMessage
        ? 'Legacy operator record; per-article writer receipts were not retained.'
        : (status.message || '');
      const rows = [
        {{ item: 'State', value: status.state || 'unknown' }},
        {{ item: 'Job', value: status.job || 'none' }},
        {{ item: 'Stage', value: status.stage || 'unknown' }},
        {{ item: 'Message', value: displayedMessage }},
        {{ item: 'Updated at', value: status.updated_at || status.generated_at || '' }},
        {{ item: 'Operator enabled', value: status.operator_enabled ? 'yes' : 'no token configured' }},
        {{ item: 'League', value: status.league_name || manifest.leagueId || 'Current league' }},
        {{ item: 'Evidence count', value: status.evidence_count || '' }},
        {{ item: 'Writer API', value: status.writer_api_configured ? `configured (${{status.writer_api_key_env || 'secret'}})` : `missing ${{status.writer_api_key_env || 'writer key'}}` }},
        {{ item: 'Writer provider', value: status.writer_provider || status.provider || '' }},
        {{ item: 'Writer model', value: status.writer_model || status.model || '' }},
        {{ item: 'Reasoning effort', value: status.writer_reasoning_effort || status.reasoning_effort || '' }},
        {{ item: 'Writer timeout', value: status.writer_timeout_seconds || status.timeout_seconds ? `${{status.writer_timeout_seconds || status.timeout_seconds}}s per request` : '' }},
        {{ item: 'Publication', value: (status.content_status || {{}}).label || 'No publication receipt' }},
        {{ item: 'Bundle revision', value: (status.reader_bundle || {{}}).served_revision || (status.publication_receipt || {{}}).bundle_revision || manifest.bundleRevision || 'unbound' }},
        {{ item: 'Reader contract', value: (() => {{
          const reader = status.reader_bundle || {{}};
          const root = reader.selected_root || 'unselected';
          const reasons = Array.isArray(reader.reasons) && reader.reasons.length ? ` · ${{reader.reasons.join(', ')}}` : '';
          return `${{reader.state || 'unknown'}} · ${{root}}${{reasons}}`;
        }})() }}
      ];
      const validation = status.validation || {{}};
      const errors = validation.errors || status.errors || [];
      const articleRows = articleEntries.map(([key, result]) => ({{
        article: key,
        state: result?.state || 'unknown',
        reporter: result?.reporter?.name || result?.reporter?.persona_id || '',
        detail: result?.errors?.join('; ') || result?.message || ''
      }}));
      const receiptDetail = articleRows.length
        ? `<h4>Writer receipt detail</h4>${{table(articleRows, ['article', 'state', 'reporter', 'detail'])}}<p class="note">Only articles marked complete or unchanged have current LLM receipts. Failed or skipped sections remain deterministic fallback content.</p>`
        : '<p class="note">No per-article writer receipts were returned by the last run. Treat this as an incomplete or older operator record until a new run reports its sections.</p>';
      return table(rows, ['item', 'value']) + receiptDetail + (errors.length
        ? `<details class="evidence-drawer" open><summary>Validation Errors</summary><div class="brief-card-evidence">${{escapeHtml(errors.join('; '))}}</div></details>`
        : '<p class="note">No operator validation errors reported.</p>');
    }}

    function filteredNewsImpact() {{
      let rows = scopedCurrentLeagueNews();
      if (state.newsScope === 'league-impact') rows = rows.filter(row => Number(row.roster_id));
      if (state.newsScope === 'watchlist') rows = rows.filter(row => !Number(row.roster_id));
      if (state.newsScope === 'unmatched') rows = [];
      return sortRows(applySearch(rows), ['published_at']).reverse().slice(0, 80);
    }}

    function filteredNewsMatches() {{
      let rows = tables.player_news_matches.slice();
      if (state.newsScope !== 'unmatched') rows = rows.filter(row => String(row.match_method) !== 'no_match' && !truthy(row.is_ambiguous));
      if (state.newsScope === 'unmatched') rows = rows.filter(row => String(row.match_method) === 'no_match' || truthy(row.is_ambiguous));
      return applySearch(rows).slice(0, 80);
    }}

    function filteredManagerCycles() {{
      return sortRows(applySearch(tables.manager_cycle_profiles.slice()), ['team_name']).slice(0, 80);
    }}

    function filteredManagerTags() {{
      return sortRows(applySearch(tables.manager_profile_tags.slice()), ['score']).reverse().slice(0, 120);
    }}

    function filteredPlayerDossiers() {{
      let rows = tables.player_dossiers.filter(row => Number(row.roster_id) === state.teamId);
      return sortRows(applySearch(rows), ['market_value', 'projected_ppg']).reverse().slice(0, 120);
    }}

    function filteredPlayerTags() {{
      const teamPlayerIds = new Set(filteredPlayerDossiers().map(row => String(row.player_id)));
      let rows = tables.player_profile_tags.filter(row => teamPlayerIds.has(String(row.entity_id)));
      return sortRows(applySearch(rows), ['score']).reverse().slice(0, 120);
    }}

    function filteredPlayerHistory() {{
      const teamPlayerIds = new Set(filteredPlayerDossiers().map(row => String(row.player_id)));
      const teamPlayerNames = new Set(filteredPlayerDossiers().map(row => String(row.player_name)));
      let rows = tables.player_transaction_history.filter(row => {{
        const playerId = String(row.player_id || '');
        return playerId ? teamPlayerIds.has(playerId) : teamPlayerNames.has(String(row.player_name));
      }});
      return sortRows(applySearch(rows), ['season', 'created_datetime']).reverse().slice(0, 120);
    }}

    function filteredProjections() {{
      let rows = tables.player_projection_season.slice();
      if (state.projectionScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.projectionConfidence !== 'ALL') rows = rows.filter(row => row.projection_confidence === state.projectionConfidence);
      return sortRows(applySearch(rows), ['projected_fantasy_points']).reverse().slice(0, 120);
    }}

    function signalBreakoutRows() {{
      let rows = tables.breakout_candidates.slice();
      if (state.signalScope === 'team') rows = rows.filter(row => currentRosterPlayerNames().has(String(row.player_name)));
      if (state.signalConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.signalConfidence);
      return sortRows(applySearch(rows), ['breakout_score']).reverse();
    }}

    function signalSellRows() {{
      let rows = tables.sell_candidates.slice();
      if (state.signalScope === 'team') rows = rows.filter(row => String(row.current_team_name) === activeTeamName());
      if (state.signalConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.signalConfidence);
      return sortRows(applySearch(rows), ['sell_score']).reverse();
    }}

    function filteredSignalGaps() {{
      const names = currentRosterPlayerNames();
      let rows = tables.projection_market_gaps.slice();
      if (state.signalScope === 'team') rows = rows.filter(row => names.has(String(row.player_name)));
      if (state.signalConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.signalConfidence);
      return sortRows(applySearch(rows), ['gap_score']).reverse().slice(0, 80);
    }}

    function filteredNewsMarketEdges() {{
      let rows = (tables.news_market_edges || []).slice();
      if (state.signalScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.signalConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.signalConfidence);
      return sortRows(applySearch(rows), ['news_market_edge_score']).reverse().slice(0, 80);
    }}

    function filteredHorizonRows() {{
      let rows = scopedCurrentRows(tables.player_horizon_market_scores || []);
      if (state.horizonScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.horizonLane !== 'ALL') rows = rows.filter(row => row.value_lane === state.horizonLane);
      const sortKey = state.horizonSort || 'team_fit';
      rows = applySearch(rows);
      // Every horizon score is position-relative. Keep the board grouped and
      // sorted inside position so a QB percentile can never masquerade as a
      // universal price or league-wide player ranking.
      const grouped = new Map();
      rows.forEach(row => {{
        const position = String(row.position || 'OTHER');
        if (!grouped.has(position)) grouped.set(position, []);
        grouped.get(position).push(row);
      }});
      const selected = [];
      [...grouped.keys()].sort().forEach(position => {{
        let positionRows = grouped.get(position) || [];
        if (sortKey === 'team_fit') {{
          positionRows = positionRows.slice().sort((left, right) => {{
            const fitDelta = horizonTeamFit(right) - horizonTeamFit(left);
            return fitDelta || String(left.player_name || '').localeCompare(String(right.player_name || ''));
          }});
        }} else if (['market_disagreement', 'market_lead', 'market_lag'].includes(sortKey)) {{
          const metric = sortKey === 'market_disagreement' ? horizonMarketDisagreement : sortKey === 'market_lead' ? horizonMarketLead : horizonMarketLag;
          positionRows = positionRows.slice().sort((left, right) => {{
            const leftValue = metric(left);
            const rightValue = metric(right);
            if (leftValue === null && rightValue === null) return String(left.player_name || '').localeCompare(String(right.player_name || ''));
            if (leftValue === null) return 1;
            if (rightValue === null) return -1;
            return (rightValue - leftValue) || String(left.player_name || '').localeCompare(String(right.player_name || ''));
          }});
        }} else {{
          positionRows = sortRows(positionRows, [sortKey, 'player_name']).reverse();
        }}
        selected.push(...positionRows.slice(0, 8));
      }});
      return selected;
    }}

    function horizonTeamLens() {{
      const profile = app.strategyProfile || {{}};
      const direction = `${{profile.team_direction || ''}} ${{profile.contention_window || ''}}`.toLowerCase();
      if (/contender|win.?now|compete/.test(direction)) return 'contender';
      if (/rebuild|asset.?bank|patient|future/.test(direction)) return 'rebuilder';
      return 'balanced';
    }}

    function horizonTeamFit(row) {{
      const lens = horizonTeamLens();
      const contender = row.contender_fit_score === undefined || row.contender_fit_score === null || row.contender_fit_score === '' ? null : Number(row.contender_fit_score);
      const rebuilder = row.rebuilder_fit_score === undefined || row.rebuilder_fit_score === null || row.rebuilder_fit_score === '' ? null : Number(row.rebuilder_fit_score);
      if (lens === 'contender') return Number.isFinite(contender) ? contender : null;
      if (lens === 'rebuilder') return Number.isFinite(rebuilder) ? rebuilder : null;
      if (Number.isFinite(contender) && Number.isFinite(rebuilder)) return (contender + rebuilder) / 2;
      return Number.isFinite(contender) ? contender : Number.isFinite(rebuilder) ? rebuilder : null;
    }}

    const horizonMarketDeltaFields = [
      'next_game_minus_market_delta',
      'rest_of_season_minus_market_delta',
      'dynasty_minus_market_delta',
      'career_minus_market_delta'
    ];

    function horizonMarketDeltas(row) {{
      return horizonMarketDeltaFields
        .map(field => Number(row[field]))
        .filter(value => Number.isFinite(value));
    }}

    function horizonMarketDisagreement(row) {{
      const deltas = horizonMarketDeltas(row);
      return deltas.length ? Math.max(...deltas.map(value => Math.abs(value))) : null;
    }}

    function horizonMarketLead(row) {{
      const deltas = horizonMarketDeltas(row);
      return deltas.length ? Math.max(...deltas) : null;
    }}

    function horizonMarketLag(row) {{
      const deltas = horizonMarketDeltas(row);
      return deltas.length ? Math.min(...deltas) : null;
    }}

    function horizonScoreValue(value) {{
      return value === undefined || value === null || value === '' ? 'n/a' : String(value);
    }}

    function horizonScoreWidth(value) {{
      const numeric = Number(value);
      return Number.isFinite(numeric) ? Math.min(100, Math.max(0, numeric)) : 0;
    }}

    function horizonScoreMeter(value, labelText) {{
      const display = horizonScoreValue(value);
      const available = display !== 'n/a';
      const width = horizonScoreWidth(value);
      const meter = available
        ? `<div class="horizon-market-meter" role="progressbar" aria-label="${{escapeHtml(labelText)}} position-relative percentile" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${{escapeHtml(String(width))}}"><span class="horizon-market-meter-fill" style="width:${{width}}%"></span></div>`
        : '<div class="horizon-market-meter horizon-market-meter-na" aria-label="Score unavailable"></div>';
      return `<div class="horizon-market-score" data-testid="horizon-score-meter">
        <div class="horizon-market-score-top"><span>${{escapeHtml(labelText)}}</span><strong>${{escapeHtml(display)}}</strong></div>
        ${{meter}}
        <span class="horizon-market-scale">position-relative percentile / 100</span>
      </div>`;
    }}

    function horizonCardMeter(value, labelText) {{
      const display = horizonScoreValue(value);
      if (display === 'n/a') return '<div class="horizon-card-meter horizon-card-meter-na" aria-label="Score unavailable"></div>';
      const width = horizonScoreWidth(value);
      return `<div class="horizon-card-meter" role="progressbar" aria-label="${{escapeHtml(labelText)}} position-relative percentile" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${{escapeHtml(String(width))}}"><span class="horizon-card-meter-fill" style="width:${{width}}%"></span></div>`;
    }}

    function horizonRestSeasonCountLabel(row) {{
      if (row.rest_of_season_games !== undefined && row.rest_of_season_games !== null && row.rest_of_season_games !== '') {{
        return `${{horizonScoreValue(row.rest_of_season_games)}} scheduled games`;
      }}
      const status = String(row.rest_of_season_status || '');
      const limitation = status === 'unavailable_missing_projection'
        ? 'season projection unavailable'
        : status === 'season_projection_baseline'
          ? 'season projection baseline'
          : String(row.schedule_status || 'schedule unavailable');
      return `scheduled game count unavailable (${{horizonScoreValue(limitation)}})`;
    }}

    function horizonRestSeasonPpgLabel(row) {{
      const ppg = horizonScoreValue(row.rest_of_season_ppg);
      if (String(row.current_availability_status || '').toLowerCase() === 'no_current_nfl_team'
        || String(row.availability_note || '').toLowerCase().includes('no current nfl team')) {{
        return `conditional baseline PPG if signed ${{ppg}}`;
      }}
      return horizonHasCurrentAvailabilityFlag(row)
        ? `conditional baseline PPG if active ${{ppg}}`
        : `season baseline PPG ${{ppg}}`;
    }}

    function projectionPpgText(row, value) {{
      const status = String(row?.current_availability_status || '').toLowerCase();
      const note = String(row?.availability_note || row?.projection_note || '').toLowerCase();
      const shown = value === undefined || value === null || value === '' ? 'n/a' : value;
      if (status === 'no_current_nfl_team' || note.includes('no current nfl team') || note.includes('sleeper currently lists no nfl team')) {{
        return `conditional baseline PPG if signed ${{shown}}`;
      }}
      return horizonHasCurrentAvailabilityFlag(row)
        ? `conditional baseline PPG if active ${{shown}}`
        : `season baseline PPG ${{shown}}`;
    }}

    function projectionPointsText(row, value) {{
      const status = String(row?.current_availability_status || '').toLowerCase();
      const note = String(row?.availability_note || row?.projection_note || '').toLowerCase();
      const shown = value === undefined || value === null || value === '' ? 'n/a' : value;
      if (status === 'no_current_nfl_team' || note.includes('no current nfl team') || note.includes('sleeper currently lists no nfl team')) {{
        return `conditional production baseline if signed ${{shown}}`;
      }}
      if (horizonHasCurrentAvailabilityFlag(row)) return `conditional production baseline if active ${{shown}}`;
      return `projected fantasy points ${{shown}}`;
    }}

    function horizonHasCurrentAvailabilityFlag(row) {{
      if (String(row.current_availability_status || '').toLowerCase() === 'no_current_nfl_team'
        || String(row.availability_note || '').toLowerCase().includes('no current nfl team')) return true;
      const status = String(row.injury_status || '').trim().toLowerCase();
      if (status) return !['none', 'healthy', 'active', 'available', 'no current injury', 'no current sleeper injury flag'].includes(status);
      const note = String(row.availability_note || '').trim().toLowerCase();
      if (!note || note.startsWith('no current')) return false;
      return ['questionable', 'doubtful', 'out', 'injured', 'injury', 'ir', 'pup', 'suspended', 'limited'].some(marker => note === marker || note.startsWith(marker + ' ') || note.includes(' ' + marker + ' ') || note.endsWith(' ' + marker));
    }}

    function horizonViewDefinition() {{
      const definitions = {{
        all: {{
          label: 'All clocks',
          note: 'Use the full card to inspect every decision window. Scores remain position-relative percentiles; market value is the cross-position price anchor.'
        }},
        this_week: {{
          label: 'This week',
          note: 'Who helps this lineup now? This view emphasizes the next-game score, availability, opponent context, and the same-position clock-versus-market lead.'
        }},
        rest_of_season: {{
          label: 'Rest of season',
          note: 'Who compounds through this season? The baseline PPG and scheduled-game count remain visible, but the production baseline is not recovery-adjusted.'
        }},
        dynasty: {{
          label: 'Dynasty / career',
          note: 'Who belongs in the long window? Dynasty is a market/timeline lens; career is a bounded five-year scenario, not a lifetime forecast.'
        }},
        fit: {{
          label: 'Contender vs rebuilder',
          note: 'Where does roster posture change the read? Fit scores are weighted combinations of the clocks, not trade prices or evidence of manager intent.'
        }},
        repricing: {{
          label: 'Repricing leads',
          note: 'Where does a decision clock differ from the same-position market percentile? Positive and negative deltas are research leads, not proven mispricing.'
        }}
      }};
      return definitions[state.horizonView] || definitions.all;
    }}

    function horizonMarketViewMarkup(row) {{
      const view = state.horizonView || 'all';
      const marketAnchor = `market value ${{horizonScoreValue(row.market_value)}} · market percentile ${{horizonScoreValue(row.market_percentile)}}`;
      const opponent = row.next_game_opponent ? `vs ${{row.next_game_opponent}} (${{row.next_game_home_away || 'game'}})` : 'opponent unavailable';
      if (view === 'this_week') {{
        return `<div class="horizon-market-primary"><div><strong>This week's utility</strong><p>${{escapeHtml(opponent)}} · expected ${{escapeHtml(horizonScoreValue(row.next_game_expected_points))}} points vs baseline ${{escapeHtml(horizonScoreValue(row.next_game_baseline_points))}} · ${{escapeHtml(row.next_game_status || 'availability unavailable')}}</p></div><div class="horizon-market-primary-score">${{escapeHtml(horizonScoreValue(row.next_game_market_score))}}<small>position percentile</small></div></div><p class="brief-card-evidence"><strong>Clock vs market:</strong> ${{escapeHtml(horizonScoreValue(row.next_game_minus_market_delta))}} points of percentile difference · ${{escapeHtml(marketAnchor)}}. Matchup factor ${{escapeHtml(horizonScoreValue(row.next_game_matchup_factor))}} (${{escapeHtml(row.next_game_matchup_adjustment_status || 'unavailable')}}).</p>`;
      }}
      if (view === 'rest_of_season') {{
        return `<div class="horizon-market-primary"><div><strong>Season utility</strong><p>${{escapeHtml(horizonRestSeasonCountLabel(row))}} · ${{escapeHtml(horizonRestSeasonPpgLabel(row))}} · production baseline is not recovery-adjusted</p></div><div class="horizon-market-primary-score">${{escapeHtml(horizonScoreValue(row.rest_of_season_market_score))}}<small>position percentile</small></div></div><p class="brief-card-evidence"><strong>Clock vs market:</strong> ${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_market_delta))}} points of percentile difference · ${{escapeHtml(marketAnchor)}}. Transition from this week: ${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_next_game_delta))}}.</p>`;
      }}
      if (view === 'dynasty') {{
        return `<div class="horizon-market-primary"><div><strong>Long-window value</strong><p>Dynasty market ${{escapeHtml(horizonScoreValue(row.dynasty_market_score))}} · career window ${{escapeHtml(horizonScoreValue(row.career_projection_score))}} · age ${{escapeHtml(horizonScoreValue(row.age))}} · career is a bounded five-year scenario</p></div><div class="horizon-market-primary-score">${{escapeHtml(horizonScoreValue(row.dynasty_market_score))}}<small>dynasty percentile</small></div></div><p class="brief-card-evidence"><strong>Clock vs market:</strong> dynasty ${{escapeHtml(horizonScoreValue(row.dynasty_minus_market_delta))}} · career ${{escapeHtml(horizonScoreValue(row.career_minus_market_delta))}} points of percentile difference · ${{escapeHtml(marketAnchor)}}. Dynasty-to-career transition: ${{escapeHtml(horizonScoreValue(row.career_minus_dynasty_delta))}}.</p>`;
      }}
      if (view === 'fit') {{
        return `<div class="horizon-market-primary"><div><strong>${{escapeHtml(label(horizonTeamLens()))}} roster fit</strong><p>Contender ${{escapeHtml(horizonScoreValue(row.contender_fit_score))}} · rebuilder ${{escapeHtml(horizonScoreValue(row.rebuilder_fit_score))}} · spread ${{escapeHtml(horizonScoreValue(row.rebuilder_contender_spread))}} · fit coverage ${{escapeHtml(horizonScoreValue(row.fit_coverage))}}</p></div><div class="horizon-market-primary-score">${{escapeHtml(horizonScoreValue(horizonTeamFit(row)))}}<small>active lens percentile</small></div></div><p class="brief-card-evidence"><strong>Why it changes:</strong> the active roster lens is a weighted combination of the four clocks. Value lane ${{escapeHtml(label(row.value_lane || 'balanced_window'))}}; this is fit context, not a universal value or a claim about the current owner's intent.</p>`;
      }}
      if (view === 'repricing') {{
        return `<p class="brief-card-evidence"><strong>Same-position repricing leads:</strong> ${{escapeHtml(marketAnchor)}}. A positive delta means the clock is above the market percentile; a negative delta means it is below. These differences are research leads, not dollar gaps or proof of mispricing.</p><div class="horizon-market-score-grid horizon-market-reprice-grid" aria-label="Clock versus position market deltas"><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.next_game_minus_market_delta))}}</strong><span>Next week vs market</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_market_delta))}}</strong><span>Season vs market</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.dynasty_minus_market_delta))}}</strong><span>Dynasty vs market</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.career_minus_market_delta))}}</strong><span>Career vs market</span></div></div>`;
      }}
      return `<div class="horizon-market-score-grid horizon-market-clock-grid" aria-label="Decision horizon market scores">${{horizonScoreMeter(row.next_game_market_score, 'This week')}}${{horizonScoreMeter(row.rest_of_season_market_score, 'Rest of season')}}${{horizonScoreMeter(row.dynasty_market_score, 'Dynasty')}}${{horizonScoreMeter(row.career_projection_score, 'Career window')}}</div><div class="horizon-market-score-grid horizon-market-fit-grid" aria-label="Strategy fit scores"><div class="horizon-market-score"><strong>${{escapeHtml(horizonScoreValue(row.contender_fit_score))}}</strong><span>Contender fit percentile</span></div><div class="horizon-market-score"><strong>${{escapeHtml(horizonScoreValue(row.rebuilder_fit_score))}}</strong><span>Rebuilder fit percentile</span></div><div class="horizon-market-score"><strong>${{escapeHtml(horizonScoreValue(horizonTeamFit(row)))}}</strong><span>Active ${{escapeHtml(label(horizonTeamLens()))}} fit percentile</span></div></div><div class="horizon-market-score-grid horizon-market-reprice-grid" aria-label="Clock versus position market deltas"><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.next_game_minus_market_delta))}}</strong><span>Next vs market</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_market_delta))}}</strong><span>ROS vs market</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.dynasty_minus_market_delta))}}</strong><span>Dynasty vs market</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.career_minus_market_delta))}}</strong><span>Career vs market</span></div></div><div class="horizon-market-score-grid horizon-market-delta-grid" aria-label="Clock transition deltas"><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_next_game_delta))}}</strong><span>ROS minus next</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.dynasty_minus_rest_of_season_delta))}}</strong><span>Dynasty minus ROS</span></div><div class="horizon-market-score horizon-market-delta"><strong>${{escapeHtml(horizonScoreValue(row.career_minus_dynasty_delta))}}</strong><span>Career minus dynasty</span></div></div>`;
    }}

    function horizonMarketCard(row, index) {{
      const playerId = String(row.player_id || '');
      const title = playerId
        ? `<a class="entity-link" href="#player-${{escapeHtml(playerId)}}">${{escapeHtml(row.player_name || 'Unknown player')}}</a>`
        : escapeHtml(row.player_name || 'Unknown player');
      const lane = label(row.value_lane || 'balanced_window');
      const opponent = row.next_game_opponent ? `vs ${{row.next_game_opponent}} (${{row.next_game_home_away || 'game'}})` : 'opponent unavailable';
      const evidence = row.evidence || 'Horizon evidence is not recorded.';
      const risk = row.risk || 'Inspect availability and source freshness before acting.';
      const trace = row.source_trace || 'player_horizon_market_scores';
      const rosGamesLabel = horizonRestSeasonCountLabel(row);
      const marketValueLabel = row.market_value !== undefined && row.market_value !== null && row.market_value !== ''
        ? `market value ${{horizonScoreValue(row.market_value)}}`
        : 'market value unavailable';
      const marketReceiptLabel = `${{horizonScoreValue(row.market_source_count)}} source(s) · ${{horizonScoreValue(row.market_disagreement_score)}} disagreement · ${{row.market_source_confidence || 'confidence unavailable'}}`;
      const marketRead = state.horizonView === 'all'
        ? `<p class="brief-card-evidence"><strong>Market read:</strong> ${{escapeHtml(opponent)}} · matchup factor ${{escapeHtml(horizonScoreValue(row.next_game_matchup_factor))}} (${{escapeHtml(row.next_game_matchup_adjustment_status || 'unavailable')}}) · ${{escapeHtml(marketValueLabel)}} is the cross-position price anchor · position-relative percentiles are not dollar values · market evidence ${{escapeHtml(marketReceiptLabel)}} · clock minus position-market deltas: next ${{escapeHtml(horizonScoreValue(row.next_game_minus_market_delta))}}, ROS ${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_market_delta))}}, dynasty ${{escapeHtml(horizonScoreValue(row.dynasty_minus_market_delta))}}, career ${{escapeHtml(horizonScoreValue(row.career_minus_market_delta))}} · rest of season ${{escapeHtml(rosGamesLabel)}}, production baseline not recovery-adjusted · clock shifts: ROS minus next ${{escapeHtml(horizonScoreValue(row.rest_of_season_minus_next_game_delta))}}, dynasty minus ROS ${{escapeHtml(horizonScoreValue(row.dynasty_minus_rest_of_season_delta))}}, career minus dynasty ${{escapeHtml(horizonScoreValue(row.career_minus_dynasty_delta))}} · ${{escapeHtml(label(horizonTeamLens()))}} lens ${{escapeHtml(horizonScoreValue(horizonTeamFit(row)))}} · spread ${{escapeHtml(horizonScoreValue(row.rebuilder_contender_spread))}}.</p>`
        : `<p class="brief-card-evidence"><strong>Evidence receipt:</strong> ${{escapeHtml(marketValueLabel)}} · market evidence ${{escapeHtml(marketReceiptLabel)}} · source trace remains in the drawer below.</p>`;
      const focusedClass = state.horizonView && state.horizonView !== 'all' ? ' is-focused' : '';
      return `<article class="horizon-market-card${{focusedClass}}" data-testid="horizon-market-row">
        <div class="brief-card-top"><strong>${{index + 1}}. ${{title}}</strong><span class="tag">${{escapeHtml(lane)}}</span></div>
         <div class="brief-card-meta"><span class="brief-chip">${{escapeHtml(row.position || 'position unavailable')}}</span><span class="brief-chip">${{escapeHtml(row.confidence || 'confidence unavailable')}}</span><span class="brief-chip">${{escapeHtml(row.current_availability_status || 'availability status unavailable')}}</span><span class="brief-chip">${{escapeHtml(row.next_game_status || 'next game status unavailable')}}</span><span class="brief-chip">${{escapeHtml(row.horizon_model_version || 'model version unavailable')}}</span><span class="brief-chip">fit coverage ${{escapeHtml(row.fit_coverage || 'n/a')}}</span><span class="brief-chip">${{escapeHtml(marketValueLabel)}}</span><span class="brief-chip">${{escapeHtml(marketReceiptLabel)}}</span></div>
        ${{horizonMarketViewMarkup(row)}}
         ${{marketRead}}
        <details class="evidence-drawer"><summary>Horizon evidence receipt</summary><p class="brief-card-evidence">${{escapeHtml(evidence)}}</p><p class="note"><strong>Risk:</strong> ${{escapeHtml(risk)}} · source trace: ${{escapeHtml(trace)}}</p></details>
      </article>`;
    }}

    function renderHorizonMarketBoard() {{
      const rows = filteredHorizonRows();
      const view = horizonViewDefinition();
      setText('horizon-view-note', `${{view.label}}: ${{view.note}}`);
      const rebuilder = rows.filter(row => String(row.value_lane || '') === 'rebuilder_edge').length;
      const contender = rows.filter(row => String(row.value_lane || '') === 'contender_edge').length;
      const limited = rows.filter(row => String(row.confidence || '').toLowerCase() !== 'high').length;
      document.getElementById('horizon-market-summary').innerHTML = [
        entityTile('Rows shown', rows.length),
        entityTile('View', view.label),
        entityTile('Team lens', label(horizonTeamLens())),
        entityTile('Rebuilder edges', rebuilder),
        entityTile('Contender edges', contender),
        entityTile('Needs review', limited)
      ].join('');
      const grouped = new Map();
      rows.forEach(row => {{
        const position = String(row.position || 'OTHER');
        if (!grouped.has(position)) grouped.set(position, []);
        grouped.get(position).push(row);
      }});
      const sections = [...grouped.entries()].sort((left, right) => left[0].localeCompare(right[0])).map(([position, positionRows]) =>
        `<section class="horizon-position-section"><h4>${{escapeHtml(position)}} <span class="note">· comparisons within position</span></h4><div class="horizon-market-list">${{positionRows.map((row, index) => horizonMarketCard(row, index)).join('')}}</div></section>`
      ).join('');
      document.getElementById('horizon-market-board').innerHTML = rows.length
        ? sections
        : '<p class="note">No horizon rows match this scope and lane. Check the refresh receipt before treating the market as empty.</p>';
    }}

    function filteredTeamFits() {{
      let rows = tables.team_fit_scores.slice();
      if (state.signalScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.signalConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.signalConfidence);
      return sortRows(applySearch(rows), ['timeline_fit_score', 'need_fit_score']).reverse().slice(0, 80);
    }}

    function filteredTargetTheses() {{
      let rows = (analysis.targetTheses || []).slice();
      if (state.analysisScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.analysisConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.analysisConfidence);
      return applySearch(rows).slice(0, 12);
    }}

    function filteredSellTheses() {{
      let rows = (analysis.sellTheses || []).slice();
      if (state.analysisScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.analysisConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.analysisConfidence);
      return applySearch(rows).slice(0, 12);
    }}

    function filteredTradeTheses() {{
      let rows = (analysis.tradeTheses || []).slice();
      if (state.analysisScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.analysisConfidence !== 'ALL') rows = rows.filter(row => row.confidence === state.analysisConfidence);
      return applySearch(rows).slice(0, 12);
    }}

    function currentRosterPlayerNames() {{
      return new Set(currentSeasonRoster().filter(row => Number(row.roster_id) === state.teamId).map(row => String(row.player_name)));
    }}

    function activeTeamName() {{
      const team = currentSeasonTeams().find(row => Number(row.roster_id) === state.teamId) || tables.teams.find(row => Number(row.roster_id) === state.teamId) || {{}};
      return String(team.team_name || team.display_name || '');
    }}

    function currentSeasonTeams() {{
      const current = scopedCurrentRows(tables.teams || []);
      return current.length ? current : latestRowsByRoster(tables.teams);
    }}

    function currentSeasonRoster() {{
      const current = scopedCurrentRows(tables.roster_players || []);
      return current.length ? current : tables.roster_players;
    }}

    function sameIdentifier(left, right) {{
      const leftText = String(left ?? '').trim();
      const rightText = String(right ?? '').trim();
      if (!leftText || !rightText) return false;
      if (leftText === rightText) return true;
      const leftNumber = Number(leftText);
      const rightNumber = Number(rightText);
      return Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber === rightNumber;
    }}

    function scopedCurrentRows(rows) {{
      let scopedRows = (rows || []).slice();
      const leagueId = String(manifest.leagueId || '').trim();
      if (leagueId) {{
        const identified = scopedRows.filter(row => String(row.league_id ?? '').trim());
        const scoped = identified.filter(row => sameIdentifier(row.league_id, leagueId));
        // Legacy/global rows have no league identity and are safe to retain when
        // the current bundle has not produced a league-specific impact row.
        scopedRows = scoped.length ? scoped : scopedRows.filter(row => !String(row.league_id ?? '').trim());
      }}
      const season = String(app.currentSeason || '').trim();
      if (season) {{
        const currentSeason = scopedRows.filter(row => sameIdentifier(row.season, season));
        scopedRows = currentSeason.length ? currentSeason : scopedRows;
      }}
      return scopedRows;
    }}

    function scopedCurrentLeagueNews() {{
      return scopedCurrentRows(tables.league_news_impact || []);
    }}

    function latestRowsByRoster(rows) {{
      const latest = new Map();
      rows.forEach(row => {{
        const key = String(row.roster_id || '');
        const existing = latest.get(key);
        if (!existing || String(row.season || '') > String(existing.season || '')) latest.set(key, row);
      }});
      return [...latest.values()];
    }}

    function legacyManagerRenderPlaceholder() {{
      return table(
        tables.manager_profiles.filter(row => Number(row.roster_id) === state.teamId),
        managerColumns
      );
    }}

    function filteredPicks() {{
      let rows = tables.pick_ownership.slice();
      if (state.pickFilter === 'my-original-away') rows = rows.filter(row => truthy(row.is_my_original_pick) && !truthy(row.i_currently_own_it));
      if (state.pickFilter === 'currently-owned') rows = rows.filter(row => Number(row.current_owner_roster_id) === state.teamId);
      if (state.pickFilter === 'active-original') rows = rows.filter(row => Number(row.original_roster_id) === state.teamId);
      return sortRows(applySearch(rows), ['pick_season', 'round', 'original_roster_id']);
    }}

    function filteredTrades() {{
      let rows = tables.trades.slice();
      if (state.tradeScope === 'team') {{
        rows = rows.filter(row => Number(row.team_a_roster_id) === state.teamId || Number(row.team_b_roster_id) === state.teamId);
      }}
      return sortRows(applySearch(rows), ['created_datetime']).reverse();
    }}

    function filteredWaivers() {{
      let rows = tables.waivers.slice();
      if (state.waiverScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.waiverStatus !== 'ALL') rows = rows.filter(row => row.status === state.waiverStatus);
      return sortRows(applySearch(rows), ['week', 'transaction_id']).reverse();
    }}

    function teamOverview(team, roster, trades) {{
      const picksOwned = tables.pick_ownership.filter(row => Number(row.current_owner_roster_id) === state.teamId).length;
      const originalPicksAway = tables.pick_ownership.filter(row => Number(row.original_roster_id) === state.teamId && Number(row.current_owner_roster_id) !== state.teamId).length;
      return table([{{
        team_name: team.team_name || team.display_name || '',
        manager: team.display_name || '',
        roster_id: state.teamId,
        rostered_players: roster.length,
        picks_owned: picksOwned,
        original_picks_elsewhere: originalPicksAway,
        mapped_trades: trades.length
      }}], ['team_name', 'manager', 'roster_id', 'rostered_players', 'picks_owned', 'original_picks_elsewhere', 'mapped_trades']);
    }}

    function strategyRosterRows(rows) {{
      const playerIds = new Set((rows || []).map(row => String(row.player_id || '')));
      const fitRows = (tables.team_fit_scores || []).filter(row => Number(row.roster_id) === state.teamId && playerIds.has(String(row.player_id || '')));
      const actionRows = (tables.action_recommendations || []).filter(row => Number(row.roster_id) === state.teamId && playerIds.has(String(row.player_id || '')));
      const fitByPlayer = new Map(fitRows.map(row => [String(row.player_id || ''), row]));
      const actionByPlayer = new Map(actionRows.map(row => [String(row.player_id || ''), row]));
      return (rows || []).map(player => {{
        const fit = fitByPlayer.get(String(player.player_id || '')) || {{}};
        const action = actionByPlayer.get(String(player.player_id || '')) || {{}};
        return {{
          ...player,
          strategy_fit: fit.fit_label || 'not_scored',
          strategy_action: action.consumer_label || 'Monitor',
          timeline_fit_score: fit.timeline_fit_score ?? '',
          liquidity_fit_score: fit.liquidity_fit_score ?? ''
        }};
      }});
    }}

    function strategyOverlay(activeTeam, allTeamRoster) {{
      const profile = app.strategyProfile || {{}};
      const tracked = app.trackedPicks || [];
      const rosterIds = new Set((allTeamRoster || []).map(row => String(row.player_id || '')));
      const horizonRows = scopedCurrentRows(tables.player_horizon_market_scores || []).filter(row => Number(row.roster_id) === state.teamId && (!rosterIds.size || rosterIds.has(String(row.player_id || ''))));
      const fits = (tables.team_fit_scores || []).filter(row => Number(row.roster_id) === state.teamId && rosterIds.has(String(row.player_id || '')));
      const actions = (tables.action_recommendations || []).filter(row => Number(row.roster_id) === state.teamId && rosterIds.has(String(row.player_id || '')));
      const needs = findRow(tables.team_needs_matrix, 'roster_id', state.teamId);
      const fitCounts = fits.reduce((counts, row) => {{
        const key = row.fit_label || 'not_scored';
        counts[key] = (counts[key] || 0) + 1;
        return counts;
      }}, {{}});
      const actionCounts = actions.reduce((counts, row) => {{
        const key = row.consumer_label || 'Monitor';
        counts[key] = (counts[key] || 0) + 1;
        return counts;
      }}, {{}});
      const fitSummary = Object.entries(fitCounts)
        .sort((left, right) => right[1] - left[1])
        .map(([key, count]) => `${{label(key)}}: ${{count}}`)
        .join(' · ') || 'No roster fit rows available';
      const actionSummary = Object.entries(actionCounts)
        .sort((left, right) => right[1] - left[1])
        .slice(0, 4)
        .map(([key, count]) => `${{key}}: ${{count}}`)
        .join(' · ') || 'No roster action rows available';
      const needSummary = [
        `QB ${{needs.need_qb || 'unknown'}}`,
        `RB ${{needs.need_rb || 'unknown'}}`,
        `pass catchers ${{needs.need_pass_catcher || 'unknown'}}`,
        `picks ${{needs.need_picks || 'unknown'}}`
      ].join(' · ');
      const topFits = fits.slice().sort((left, right) => (
        (Number(right.timeline_fit_score) + Number(right.need_fit_score) + Number(right.liquidity_fit_score)) -
        (Number(left.timeline_fit_score) + Number(left.need_fit_score) + Number(left.liquidity_fit_score))
      )).slice(0, 3);
      const topFitText = topFits.map(row => `${{row.player_name || 'unnamed player'}} · ${{label(row.fit_label || 'not scored')}} (timeline ${{row.timeline_fit_score ?? 'n/a'}}, need ${{row.need_fit_score ?? 'n/a'}}, liquidity ${{row.liquidity_fit_score ?? 'n/a'}})`).join('; ');
      const profileName = profile.name || 'Generic Sleeper team analysis';
      const direction = profile.team_direction || 'not configured';
      const window = profile.contention_window || 'not configured';
      const horizonLens = horizonTeamLens();
      const horizonProfile = horizonRows.map(row => String(row.fit_basis || '').match(/fit weight profile=([^;]+)/)?.[1]).find(Boolean) || 'not recorded';
      const horizonBasis = horizonRows.map(row => String(row.fit_basis || '')).find(Boolean) || 'No four-window fit receipt is available for this roster.';
      return `<div class="strategy-overlay">
        <h4>Strategy alignment</h4>
        <div class="tile-row">${{entityTile('Profile', profileName)}}${{entityTile('Team shape', needs.team_shape || 'unknown')}}${{entityTile('Fit rows', fits.length)}}${{entityTile('Horizon lens', horizonLens)}}${{entityTile('Tracked picks', tracked.length)}}</div>
        <p class="brief-card-evidence"><strong>Decision lens:</strong> ${{escapeHtml(label(direction))}} · <strong>Window:</strong> ${{escapeHtml(label(window))}}.</p>
        <p class="brief-card-evidence"><strong>Four-window fit:</strong> ${{escapeHtml(label(horizonLens))}} · ${{escapeHtml(horizonRows.length)}} roster horizon rows · weighting receipt ${{escapeHtml(horizonProfile)}}.</p>
        <p class="brief-card-evidence"><strong>Roster needs:</strong> ${{escapeHtml(needSummary)}}.</p>
        <p class="brief-card-evidence"><strong>Strategy fit:</strong> ${{escapeHtml(fitSummary)}}.</p>
        <p class="brief-card-evidence"><strong>Current action mix:</strong> ${{escapeHtml(actionSummary)}}.</p>
        ${{topFitText ? `<details class="evidence-drawer"><summary>Top aligned roster evidence</summary><p class="note">${{escapeHtml(topFitText)}}</p></details>` : '<p class="note">No exact roster fit rows are available for this strategy view.</p>'}}
        <details class="evidence-drawer"><summary>Four-window weighting receipt</summary><p class="note">${{escapeHtml(horizonBasis)}}</p></details>
        <p class="note">These are deterministic fit and action labels for the selected roster. They are decision support, not a prediction of a trade or outcome.</p>
      </div>`;
    }}

    function renderDataRoomQuestions() {{
      const answerNode = document.getElementById('data-room-answer');
      const visualsNode = document.getElementById('data-room-visuals');
      if (!answerNode || !visualsNode) return;
      const result = dataRoomQuestionResult(state.dataQuestion || 'changed');
      answerNode.innerHTML = `<strong>${{escapeHtml(result.title)}}</strong><br>${{escapeHtml(result.answer)}}`;
      visualsNode.innerHTML = (result.visuals || []).join('');
    }}

    function renderDataQualityReceipt() {{
      const node = document.getElementById('data-quality-receipt-body');
      if (!node) return;
      const receipt = (app.dataQuality || {{}}).player_history_identity || {{}};
      const status = String(receipt.status || 'missing');
      const statusLabel = {{
        verified: 'Verified',
        partial: 'Partial coverage',
        contract_error: 'Contract issue',
        empty: 'No rows',
        missing: 'Not recorded'
      }}[status] || label(status);
      const rows = Number(receipt.row_count || 0);
      const resolved = Number(receipt.resolved_rows || 0);
      const unresolved = Number(receipt.unresolved_rows || 0);
      const directions = receipt.trade_direction_counts || {{}};
      const methods = Object.entries(receipt.identity_method_counts || {{}})
        .map(([method, count]) => `${{label(method)}}: ${{count}}`)
        .join(' · ') || 'No identity methods recorded';
      const errors = (receipt.errors || []).slice(0, 4);
      const directionStatus = receipt.trade_direction_status === 'not_applicable'
        ? 'No trade rows'
        : `${{label(receipt.trade_direction_status || 'unknown')}} (${{directions.acquired || 0}} acquired · ${{directions.sold || 0}} sold)`;
      const limitation = status === 'verified'
        ? 'Every historical row has a supported identity path; source IDs are preferred when available.'
        : status === 'partial'
          ? 'Some rows still rely on ambiguous or unmatched names. Treat historical joins as limited until those rows are resolved.'
          : status === 'contract_error'
            ? 'The bundle contains rows that violate the history contract. Do not treat this ledger as trustworthy until the source or normalization step is repaired.'
            : 'No historical transaction evidence is available in this bundle.';
      node.innerHTML = `<div class="tile-row">${{entityTile('History rows', rows)}}${{entityTile('Resolved joins', resolved)}}${{entityTile('Unresolved rows', unresolved)}}${{entityTile('Resolved rate', `${{Math.round(Number(receipt.resolved_rate || 0) * 100)}}%`)}}</div><p class="brief-card-evidence"><strong>Status:</strong> ${{escapeHtml(statusLabel)}} · <strong>Trade direction:</strong> ${{escapeHtml(directionStatus)}}.</p><p class="brief-card-evidence"><strong>Identity methods:</strong> ${{escapeHtml(methods)}}</p><p class="note">${{escapeHtml(limitation)}}</p>${{errors.length ? `<details class="evidence-drawer"><summary>Contract warnings</summary><ul class="article-list">${{errors.map(error => `<li>${{escapeHtml(error)}}</li>`).join('')}}</ul></details>` : ''}}`;
    }}

    function renderLearningLedger(summary) {{
      const node = document.getElementById('learning-ledger-body');
      if (!node) return;
      const feedback = summary.feedback_counts || {{}};
      const outcomes = summary.outcome_counts || {{}};
      const recommendationOutcomes = summary.recommendation_outcome_counts || {{}};
      const cards = [
        entityTile('Useful', feedback.useful || 0),
        entityTile('Needs work', feedback.not_useful || 0),
        entityTile('Evidence reviewed', feedback.evidence_opened || 0),
        entityTile('Saved / pursued', (feedback.saved || 0) + (feedback.pursued || 0)),
        entityTile('Open calls', outcomes.open || 0),
        entityTile('Resolved calls', summary.resolved_outcomes || 0),
        entityTile('Recommendation calls', summary.recommendation_count || 0),
        entityTile('Resolved recommendations', summary.recommendation_resolved_outcomes || 0)
      ].join('');
      const rate = summary.confirmed_rate === null || summary.confirmed_rate === undefined
        ? 'Not enough resolved calls for a rate.'
        : `${{Math.round(Number(summary.confirmed_rate) * 100)}}% of resolved calls confirmed useful`;
      const recommendationRate = summary.recommendation_confirmed_rate === null || summary.recommendation_confirmed_rate === undefined
        ? 'Recommendation rate is not established yet.'
        : `${{Math.round(Number(summary.recommendation_confirmed_rate) * 100)}}% of resolved recommendation calls confirmed useful`;
      const recommendationState = `${{recommendationOutcomes.open || 0}} open · ${{recommendationOutcomes.confirmed || 0}} confirmed · ${{recommendationOutcomes.missed || 0}} missed · ${{recommendationOutcomes.unclear || 0}} unclear`;
      const latest = summary.latest_recorded_at ? `Last recorded ${{summary.latest_recorded_at}}.` : 'No explicit signals recorded yet.';
      const reporterNames = new Map((manifest.reporterLineup || []).map(row => [String(row.persona_id || ''), String(row.name || '')]));
      const reporterRowsById = new Map();
      Object.entries(manifest.articleReceipts || {{}}).forEach(([articleKey, receipt]) => {{
        const reporterId = String(receipt?.reporter_id || receipt?.reporter_persona || 'unassigned');
        const current = reporterRowsById.get(reporterId) || {{
          reporter_id: reporterId,
          reporter_name: String(receipt?.reporter_name || ''),
          writer_mode: String(receipt?.mode || receipt?.model_mode || receipt?.writer_mode || ''),
          article_keys: [],
          artifact_count: 0,
          interaction_count: 0,
          useful: 0,
          not_useful: 0,
          evidence_opened: 0,
          resolved_outcomes: 0,
          confirmed_rate: null
        }};
        current.artifact_count = Math.max(Number(current.artifact_count || 0), 0) + 1;
        if (!current.article_keys.includes(articleKey)) current.article_keys.push(articleKey);
        reporterRowsById.set(reporterId, current);
      }});
      (Array.isArray(summary.reporter_breakdown) ? summary.reporter_breakdown : []).forEach(row => {{
        const reporterId = String(row.reporter_id || 'unassigned');
        const current = reporterRowsById.get(reporterId) || {{ reporter_id: reporterId, article_keys: [], artifact_count: 0 }};
        reporterRowsById.set(reporterId, {{
          ...current,
          ...row,
          artifact_count: Math.max(Number(current.artifact_count || 0), Number(row.artifact_count || 0)),
          article_keys: [...new Set([...(current.article_keys || []), ...(row.article_keys || [])])]
        }});
      }});
      const reporterRows = [...reporterRowsById.values()].sort((left, right) => String(left.reporter_id).localeCompare(String(right.reporter_id)));
      const breakdown = reporterRows.length
        ? `<div class="learning-breakdown"><h4>Which desks are earning trust?</h4><div class="brief-list">${{reporterRows.map(row => {{
            const reporterId = String(row.reporter_id || 'unassigned');
            const reporterName = row.reporter_name || reporterNames.get(reporterId) || label(reporterId);
            const resolvedCount = Number(row.resolved_outcomes || 0);
            const outcomeLabel = resolvedCount ? `${{Math.round(Number(row.confirmed_rate || 0) * 100)}}% confirmed across ${{resolvedCount}} resolved call${{resolvedCount === 1 ? '' : 's'}}` : 'No resolved calls yet';
            const signalLabel = `${{Number(row.interaction_count || 0)}} deliberate signal${{Number(row.interaction_count || 0) === 1 ? '' : 's'}} · ${{Number(row.artifact_count || 0)}} article receipt${{Number(row.artifact_count || 0) === 1 ? '' : 's'}}`;
            const usefulness = `${{Number(row.useful || 0)}} useful · ${{Number(row.not_useful || 0)}} needs work · ${{Number(row.evidence_opened || 0)}} evidence opened`;
            return `<article class="brief-card"><div class="brief-card-body"><div class="brief-card-title">${{escapeHtml(reporterName)}} <span class="tag">${{escapeHtml(row.writer_mode ? label(row.writer_mode) : 'Receipt state unavailable')}}</span></div><div class="brief-card-meta"><span class="brief-chip">${{escapeHtml(signalLabel)}}</span><span class="brief-chip">${{escapeHtml(outcomeLabel)}}</span></div><div class="brief-card-evidence">${{escapeHtml(usefulness)}}${{row.article_keys?.length ? ` · keys: ${{row.article_keys.join(', ')}}` : ''}}</div></div></article>`;
          }}).join('')}}</div></div>`
        : '';
      node.innerHTML = `<div class="tile-row">${{cards}}</div><p class="note">Article learning: ${{escapeHtml(rate)}} · ${{escapeHtml(latest)}} ${{escapeHtml(String(summary.artifact_count || 0))}} artifacts in scope.</p><p class="note"><strong>Recommendation learning:</strong> ${{escapeHtml(recommendationRate)}} · ${{escapeHtml(recommendationState)}}.</p>${{breakdown}}`;
    }}

    async function hydrateLearningLedger() {{
      const node = document.getElementById('learning-ledger-body');
      if (!node || !manifest.leagueId) return;
      try {{
        const response = await fetch(`/api/leagues/${{encodeURIComponent(manifest.leagueId)}}/learning-summary`);
        if (!response.ok) return;
        renderLearningLedger(await response.json());
      }} catch (error) {{
        console.warn('Could not load the decision ledger', error);
      }}
    }}

    function renderEditionChanges(payload) {{
      const node = document.getElementById('edition-changes-body');
      if (!node) return;
      const changes = Array.isArray(payload.changes) ? payload.changes : [];
      if (!changes.length) {{
        node.innerHTML = '<p class="note">No article receipts are indexed for this league yet.</p>';
        return;
      }}
      const label = {{ new: 'New', updated: 'Changed', failed: 'Generation failed', unchanged: 'No content change', untracked: 'Not tracked' }};
      node.innerHTML = `<div class="edition-change-list">${{changes.map(row => {{
        const state = String(row.change_type || 'untracked');
        const model = row.model ? ` · ${{escapeHtml(row.model)}}` : '';
        const usage = row.usage && (row.usage.total_tokens || row.usage.input_tokens || row.usage.output_tokens)
          ? ` · ${{escapeHtml(String(row.usage.total_tokens || ((Number(row.usage.input_tokens) || 0) + (Number(row.usage.output_tokens) || 0))))}} tokens${{row.cost_known ? ' · cost receipt available' : ' · price not estimated'}}`
          : '';
        const detail = state === 'updated' && row.prior_evidence_fingerprint
          ? 'Evidence fingerprint changed since the prior receipt.'
          : state === 'new' ? 'First receipt for this article in the current durable workspace.'
          : state === 'failed' ? escapeHtml(row.fallback_reason || 'The deterministic fallback remains the published state.')
          : state === 'unchanged' ? 'The current evidence and article hash match the prior receipt.'
          : 'No prior receipt is available for comparison.';
        return `<article class="edition-change"><div><span class="tag">${{escapeHtml(label[state] || state)}}</span><strong>${{escapeHtml(row.artifact_key || 'Article')}}</strong></div><p class="note">${{detail}}${{model}}${{usage}}</p></article>`;
      }}).join('')}}</div>`;
    }}

    async function hydrateEditionChanges() {{
      const node = document.getElementById('edition-changes-body');
      if (!node || !manifest.leagueId) return;
      try {{
        const response = await fetch(`/api/leagues/${{encodeURIComponent(manifest.leagueId)}}/edition-changes`);
        if (!response.ok) return;
        renderEditionChanges(await response.json());
      }} catch (error) {{
        console.warn('Could not load edition changes', error);
      }}
    }}

    function dataRoomQuestionResult(question) {{
      const roster = currentSeasonRoster().filter(row => Number(row.roster_id) === state.teamId);
      const team = currentSeasonTeams().find(row => Number(row.roster_id) === state.teamId) || {{}};
      const currentNews = scopedCurrentLeagueNews();
      const latestNews = sortRows(currentNews, ['published_at']).reverse()[0] || {{}};
      const latestTrade = sortRows((tables.trades || []).slice(), ['created_datetime']).reverse()[0] || {{}};
      const latestWaiver = sortRows((tables.waivers || []).slice(), ['created_datetime', 'week']).reverse()[0] || {{}};
      const recentEvents = [
        ...sortRows(currentNews, ['published_at']).reverse().slice(0, 5).map(row => ({{
          sortKey: row.published_at || '',
          text: `News · ${{row.player_name || 'Unknown player'}}: ${{row.evidence || row.impact_type || 'signal recorded'}} · ${{row.published_at || 'time not recorded'}}`
        }})),
        ...sortRows((tables.trades || []).slice(), ['created_datetime']).reverse().slice(0, 5).map(row => ({{
          sortKey: row.created_datetime || '',
          text: `Trade · ${{row.team_a_name || 'Roster A'}} ↔ ${{row.team_b_name || 'Roster B'}}: ${{row.team_a_players_received || row.team_a_picks_received || row.team_b_players_received || row.team_b_picks_received || 'assets recorded'}} · ${{row.created_datetime || 'time not recorded'}}`
        }})),
        ...sortRows((tables.waivers || []).slice(), ['created_datetime', 'week']).reverse().slice(0, 5).map(row => ({{
          sortKey: row.created_datetime || String(row.week || ''),
          text: `Waiver · ${{row.team_name || `Roster ${{row.roster_id || 'unknown'}}`}} added ${{row.player_added || 'an unknown player'}}${{row.player_dropped ? ` and dropped ${{row.player_dropped}}` : ''}} · ${{row.created_datetime || `week ${{row.week || 'unknown'}}`}}`
        }}))
      ].sort((left, right) => String(right.sortKey || '').localeCompare(String(left.sortKey || ''))).slice(0, 8).map(row => row.text);
      const horizonMovements = (tables.horizon_market_movements || [])
        .filter(row => !row.league_id || sameIdentifier(row.league_id, manifest.leagueId))
        .filter(row => String(row.movement_status || '') === 'changed')
        .sort((left, right) => (Number(right.largest_clock_movement_magnitude) || 0) - (Number(left.largest_clock_movement_magnitude) || 0))
        .slice(0, 8);
     const horizonMovementVisual = decisionListVisual('Market clock changes', horizonMovements.length
        ? horizonMovements.map(row => `${{row.player_name || 'Unknown player'}}: ${{row.largest_clock_movement_window || 'clock'}} ${{row.largest_clock_movement_delta || 'n/a'}} since week ${{row.prior_as_of_week || 'unknown'}} · market value delta ${{row.market_value_delta || 'n/a'}} · lane ${{label(row.value_lane || 'unavailable')}}`)
       : ['No changed horizon rows have an earlier exact-scope snapshot yet. The first run establishes the baseline.']);
      const delta = app.dataRoomDelta || {{}};
      const deltaEvents = Array.isArray(delta.added_events) ? delta.added_events : [];
      const deltaVisual = delta.status === 'verified'
        ? decisionListVisual('Since the prior reader bundle', deltaEvents.length
          ? deltaEvents.map(row => `${{row.headline || row.category || 'Event'}}: ${{row.detail || 'event recorded'}} · ${{row.recorded_at || 'time unavailable'}}`)
          : ['No new news, trade, or waiver rows were added since the prior reader bundle.'])
        : decisionListVisual('Change receipt', [delta.reason || 'No prior reader bundle is available for a historical comparison.']);
      if (question === 'matters') {{
        const composition = {{}};
        roster.forEach(row => {{ composition[row.position || 'Unknown'] = (composition[row.position || 'Unknown'] || 0) + 1; }});
        const rows = Object.entries(composition).map(([labelText, value]) => ({{ label: labelText, value, display: `${{value}} players` }}));
        return {{
          title: 'Why it matters to my team',
          answer: `${{team.team_name || app.myTeamName || 'Your team'}} has ${{roster.length}} rostered players in the confirmed current-season scope. Composition is a starting point for fit; it is not a lineup recommendation by itself.`,
          visuals: [decisionVisual('Roster composition', rows, 'Counted from the exact Sleeper roster scope.'), decisionListVisual('Open next', ['Open My Team for player-level projections and role signals.', 'Open Trade Desk for two-sided counterparty fit.', 'Check the strategy profile before treating a gap as actionable.'])]
        }};
      }}
      if (question === 'mispriced') {{
        const newsRows = filteredNewsMarketEdges().slice(0, 6).map(row => ({{
          label: row.player_name || 'Unknown player',
          value: Number(row.news_market_edge_score) || 0,
          display: `${{row.edge_type || 'news-market review'}} · ${{row.news_market_edge_score || 0}}`,
          playerId: row.player_id
        }}));
        const signalRows = filteredSignalGaps().slice(0, 6).map(row => ({{
          label: row.player_name || 'Unknown player',
          value: Math.abs(Number(row.gap_score) || 0),
          display: `${{row.gap_score || 0}} gap`,
          playerId: row.player_id
        }}));
        const horizonRows = scopedCurrentRows(tables.player_horizon_market_scores || [])
          .filter(row => Number(row.roster_id) === state.teamId)
          .slice()
          .sort((left, right) => (horizonMarketDisagreement(right) || 0) - (horizonMarketDisagreement(left) || 0))
          .slice(0, 6)
          .map(row => ({{
            label: row.player_name || 'Unknown player',
            value: horizonMarketDisagreement(row) || 0,
            display: `${{row.value_lane || 'clock / market review'}} · ${{horizonMarketDisagreement(row) || 0}}`,
            playerId: row.player_id
          }}));
        const rows = (newsRows.length ? newsRows : signalRows.length ? signalRows : horizonRows);
        return {{
          title: 'Which players deserve a price check?',
          answer: rows.length ? (newsRows.length ? 'These are current scoped news-market dislocations: a catalyst is present while the deterministic price or sell-pressure lane remains meaningful. They are research leads, not proof that the market is wrong.' : signalRows.length ? 'These are the largest current model gaps in the selected scope. A gap is a prompt for price discovery, not proof that the market is wrong.' : 'These horizon rows have the largest same-position clock-versus-market disagreement in the selected roster. The movement is a research lead, not proof that the market is wrong.') : 'No scored market gaps are available in the current evidence bundle.',
          visuals: [decisionVisual(newsRows.length ? 'News-market dislocations' : signalRows.length ? 'Largest modeled gaps' : 'Horizon clock / market leads', rows, 'Inspect the source receipt, projection confidence, role, and live market before acting.')]
        }};
      }}
      if (question === 'traders') {{
        const rows = (tables.manager_behavior_signals || []).filter(row => Number(row.roster_id) !== state.teamId).sort((a, b) => Number(b.trade_activity_score || 0) - Number(a.trade_activity_score || 0)).slice(0, 6).map(row => ({{
          label: row.team_name || `Roster ${{row.roster_id}}`,
          value: Number(row.trade_activity_score) || 0,
          display: `${{row.trade_activity_score || 0}} activity`,
          entityHash: `team-${{row.roster_id}}`
        }}));
        return {{
          title: 'Who is most likely to trade?',
          answer: rows.length ? 'This ranking describes observed transaction activity, not willingness or intent. Use the manager dossier to see sample size and historical posture.' : 'No manager activity rows are available yet.',
          visuals: [decisionVisual('Observed activity', rows, 'Deterministic activity score; not a prediction of a completed trade.'), decisionListVisual('Guardrail', ['Manager tendencies are estimates from recorded behavior.', 'Private editor notes are hypotheses, not source evidence.', 'No offer is sent or implied by this surface.'])]
        }};
      }}
      if (question === 'disagree') {{
        const rows = (tables.player_opportunity_scores || []).slice().sort((a, b) => Number(b.xfp_regression_score || 0) - Number(a.xfp_regression_score || 0)).slice(0, 6).map(row => ({{
          label: row.player_name || 'Unknown player',
          value: Number(row.xfp_regression_score) || 0,
          display: `${{row.xfp_regression_score || 0}} usage/output`,
          playerId: row.player_id
        }}));
        return {{
          title: 'Which signals disagree?',
          answer: rows.length ? 'Usage-versus-output disagreement is the clearest current contradiction surfaced by the model. It can reveal a buy-low or risk flag, but it still needs role, news, and projection context.' : 'No usage-versus-output comparison is available in the current bundle.',
          visuals: [decisionVisual('Opportunity versus production', rows, 'Higher bars mean more modeled opportunity outrunning box-score production.')]
        }};
      }}
      if (question === 'weak') {{
        const sourceRows = [...(tables.source_freshness || []), ...(tables.news_source_freshness || []), ...(tables.projection_source_freshness || [])].map(row => ({{
          label: row.source || row.dataset || 'Source',
          value: ['cached', 'refreshed', 'complete', 'available'].includes(String(row.status || '').toLowerCase()) ? 100 : 35,
          display: row.status || 'unknown'
        }}));
        return {{
          title: 'What evidence is weak or stale?',
          answer: sourceRows.some(row => row.value < 100) ? 'At least one source is limited, stale, disabled, or unavailable. The edition remains readable, but confidence should fall with the source receipt.' : 'The recorded source receipts are current in this bundle; still inspect timestamps before relying on a high-stakes edge.',
          visuals: [decisionVisual('Source receipt', sourceRows, '100 means the source is marked current; limited rows remain visible rather than hidden.'), decisionListVisual('Data-room rule', ['A single source is labeled as single-source evidence.', 'A missing optional provider does not become invented consensus.', 'Open Diagnostics for the raw freshness tables and checked-at timestamps.'])]
        }};
      }}
      if (question === 'next') {{
        const dossier = (analysis.managerDossierItems || []).find(row => Number(row.roster_id) !== state.teamId) || {{}};
        const questions = dossier.questions_to_ask || [];
        const theses = (analysis.tradeTheses || []).filter(row => Number(row.target_manager_roster_id) !== state.teamId).slice(0, 4);
        return {{
          title: 'What should I investigate next?',
          answer: questions.length ? 'The next investigation is a manager-specific question grounded in the dossier, not a generic content prompt.' : theses.length ? 'Start with the highest-confidence Trade Desk packet, then open the underlying manager history before deciding whether the fit is real.' : 'No next investigation is supported by the current evidence bundle.',
          visuals: [decisionListVisual('Questions to carry into the room', questions.length ? questions : ['Which evidence row would change this recommendation?', 'What would make the estimated fit invalid?', 'Which source needs a refresh before I act?']), decisionVisual('Trade packets available', theses.map(row => ({{ label: row.target_manager_name || 'Manager', value: row.confidence === 'high' ? 100 : row.confidence === 'medium' ? 65 : 35, display: row.confidence || 'low' }})), 'Confidence is evidence quality, not certainty of a deal.')]
        }};
      }}
      return {{
        title: 'What changed?',
        answer: delta.status === 'verified'
          ? `${{deltaEvents.length}} news, trade, or waiver rows were added since the prior reader bundle, with ${{horizonMovements.length}} changed market-clock rows. The current pulse below is the latest recorded event view; it is separate from the historical delta.`
          : `${{currentNews.length}} league news signals, ${{tables.trades?.length || 0}} trades, and ${{tables.waivers?.length || 0}} waiver rows are in this snapshot. ${{horizonMovements.length}} changed market-clock rows have an earlier exact-scope comparison; the pulse below is not a historical delta unless a prior receipt says so.`,
        visuals: [deltaVisual, horizonMovementVisual, decisionVisual('Current event volume', [
          {{ label: 'News signals', value: currentNews.length, display: String(currentNews.length) }},
          {{ label: 'Trades', value: (tables.trades || []).length, display: String((tables.trades || []).length) }},
          {{ label: 'Waivers', value: (tables.waivers || []).length, display: String((tables.waivers || []).length) }}
        ], 'Counts are the current evidence snapshot, not a claim that every row is newly created.'), decisionListVisual('Latest recorded league events', recentEvents.length ? recentEvents : ['No event rows are available in the current evidence bundle.']), decisionListVisual('Latest receipts', [
          `News: ${{latestNews.published_at || 'not recorded'}}`,
          `Trade: ${{latestTrade.created_datetime || 'not recorded'}}`,
          `Waiver: ${{latestWaiver.week || 'not recorded'}}`
        ])]
      }};
    }}

    function decisionVisual(title, rows, note) {{
      if (!rows || !rows.length) return `<div class="decision-visual"><h3>${{escapeHtml(title)}}</h3><p class="note">No rows available.</p></div>`;
      const max = Math.max(...rows.map(row => Math.abs(Number(row.value) || 0)), 1);
      return `<div class="decision-visual"><h3>${{escapeHtml(title)}}</h3>${{rows.map(row => `<div class="decision-bar-row"><span>${{escapeHtml(row.label || 'Unknown')}}</span><span class="decision-bar-track"><span class="decision-bar-fill" style="width:${{Math.max(5, Math.min(100, (Math.abs(Number(row.value) || 0) / max) * 100))}}%"></span></span><span class="decision-bar-value">${{escapeHtml(String(row.display ?? row.value ?? ''))}}</span></div>`).join('')}}${{note ? `<p class="note">${{escapeHtml(note)}}</p>` : ''}}</div>`;
    }}

    function decisionListVisual(title, rows) {{
      return `<div class="decision-visual"><h3>${{escapeHtml(title)}}</h3><ul class="decision-list">${{(rows || []).map(row => `<li>${{escapeHtml(String(row))}}</li>`).join('')}}</ul></div>`;
    }}

    function diagnostics() {{
      const metadata = (tables.refresh_metadata || [])[0] || {{}};
      const leagueIds = metadata.configured_league_ids || Object.values(app.configuredLeagues || {{}}).filter(Boolean).join(';');
      const counts = app.tableCounts || manifest.tableCounts || {{}};
      const historyQuality = (app.dataQuality || {{}}).player_history_identity || {{}};
      return table([
        {{ item: 'Generated at', value: metadata.generated_at || 'unknown' }},
        {{ item: 'Current season', value: metadata.current_season || app.currentSeason || '' }},
        {{ item: 'Configured leagues', value: leagueIds }},
        {{ item: 'Configured seasons', value: metadata.configured_seasons || '' }},
        {{ item: 'Ingested seasons', value: metadata.ingested_seasons || '' }},
        {{ item: 'Transaction weeks', value: `${{metadata.transaction_week_start || ''}}-${{metadata.transaction_week_end || ''}}` }},
        {{ item: 'Source scope', value: metadata.source_scope || 'Sleeper public API only' }},
        {{ item: 'Players cached', value: counts.players || tables.players.length }},
        {{ item: 'Raw cache root', value: metadata.raw_cache_root || 'data/raw' }},
        {{ item: 'Raw external cache root', value: metadata.raw_external_cache_root || 'data/raw_external' }},
        {{ item: 'Market source rows', value: metadata.market_source_rows || tables.market_value_sources.length }},
        {{ item: 'Market consensus rows', value: metadata.market_consensus_rows || tables.market_consensus_values.length }},
        {{ item: 'Player market rows', value: tables.player_market_values.length }},
        {{ item: 'Pick market rows', value: tables.pick_market_values.length }},
        {{ item: 'Usage rows', value: counts.player_usage_weekly || tables.player_usage_weekly.length }},
        {{ item: 'Economic asset rows', value: tables.team_asset_inventory.length }},
        {{ item: 'News event rows', value: tables.news_events.length }},
        {{ item: 'News impact rows', value: tables.league_news_impact.length }},
        {{ item: 'Projection season rows', value: tables.player_projection_season.length }},
        {{ item: 'Projection weekly rows', value: counts.player_projection_weekly || tables.player_projection_weekly.length }},
        {{ item: 'Available market horizon rows', value: metadata.available_player_horizon_rows || tables.available_player_horizon_scores.length }},
       {{ item: 'Horizon outcome observations', value: metadata.horizon_accuracy_rows || tables.horizon_score_accuracy.length }},
        {{ item: 'Horizon movement rows', value: metadata.horizon_movement_rows || tables.horizon_market_movements.length }},
        {{ item: 'Signal score rows', value: tables.player_signal_scores.length }},
        {{ item: 'News-market edge rows', value: tables.news_market_edges.length }},
        {{ item: 'Action recommendation rows', value: tables.action_recommendations.length }},
        {{ item: 'Manager valuation profile rows', value: metadata.manager_valuation_profile_rows || tables.manager_valuation_profiles.length }},
        {{ item: 'Observed transaction lane rows', value: metadata.manager_transaction_preference_rows || tables.manager_transaction_preferences.length }},
        {{ item: 'Counterparty edge rows', value: metadata.counterparty_edge_rows || tables.counterparty_trade_edges.length }},
        {{ item: 'Manager profile tag rows', value: metadata.manager_profile_tag_rows || tables.manager_profile_tags.length }},
        {{ item: 'Manager cycle rows', value: tables.manager_cycle_profiles.length }},
        {{ item: 'Player dossier rows', value: metadata.player_dossier_rows || tables.player_dossiers.length }},
        {{ item: 'Player history identity', value: `${{historyQuality.status || 'not recorded'}} · ${{historyQuality.resolved_rows || 0}}/${{historyQuality.row_count || 0}} resolved` }},
        {{ item: 'Player profile tag rows', value: metadata.player_profile_tag_rows || tables.player_profile_tags.length }},
        {{ item: 'Breakout candidate rows', value: tables.breakout_candidates.length }},
        {{ item: 'Sell candidate rows', value: tables.sell_candidates.length }},
        {{ item: 'Analysis artifacts', value: metadata.analysis_artifacts_status || analysis.status || 'missing' }},
        {{ item: 'Analysis generated at', value: metadata.analysis_generated_at || 'unknown' }},
        {{ item: 'Analysis context packets', value: metadata.analysis_context_packet_count || (analysis.contextPackets || []).length }},
        {{ item: 'Target thesis rows', value: metadata.target_thesis_count || (analysis.targetTheses || []).length }},
        {{ item: 'Sell thesis rows', value: metadata.sell_thesis_count || (analysis.sellTheses || []).length }},
        {{ item: 'Trade thesis rows', value: metadata.trade_thesis_count || (analysis.tradeTheses || []).length }},
        {{ item: 'Counterparty audience rows', value: metadata.counterparty_asset_interest_rows || tables.counterparty_asset_interest.length }},
        {{ item: 'Recommendation packets', value: metadata.recommendation_packets_status || 'planned_contract_only' }}
      ], ['item', 'value']) + '<h3>Market Consensus</h3>' + table(tables.market_consensus_values.slice(0, 40), marketConsensusColumns) + '<h3>Source Freshness</h3>' + table(tables.source_freshness, sourceColumns) + '<h3>News Source Freshness</h3>' + table(tables.news_source_freshness, sourceColumns) + '<h3>Projection Source Freshness</h3>' + table(tables.projection_source_freshness, sourceColumns);
    }}

    function priorityCards(rows) {{
      if (!rows.length) return '<p class="note">No high-priority items right now.</p>';
      return `<div class="brief-list">${{rows.map((row, index) => briefCard({{
        title: `${{row.item_type_label || 'Item'}} - ${{row.entity_name || 'Unknown'}}`,
        category: categoryFor('item_type', row.item_type),
        rank: index + 1,
        playerId: row.entity_type === 'player' ? row.entity_id : null,
        entityHash: row.entity_type === 'player' ? `player-${{row.entity_id}}` : (row.entity_type === 'manager' ? `team-${{num(row.entity_id)}}` : ''),
        chips: [
          row.team_name,
          row.priority_score !== undefined && row.priority_score !== null && row.priority_score !== '' ? `priority ${{row.priority_score}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : '',
          row.risk ? `risk ${{row.risk}}` : ''
        ],
        evidence: `${{row.why || ''}} Evidence: ${{row.evidence || ''}}`
      }})).join('')}}</div>`;
    }}

    function counterpartyCards(rows) {{
      if (!rows.length) return '<p class="note">No counterparty edge rows found.</p>';
      return `<div class="brief-list">${{rows.map((row, index) => briefCard({{
        title: `${{row.player_name || 'Unknown player'}} - ${{row.target_team || 'Unknown manager'}}`,
        category: categoryFor('edge_type', row.edge_type),
        rank: index + 1,
        playerId: row.player_id,
        chips: [
          row.edge_type,
          row.position,
          row.trade_edge_score ? `edge ${{row.trade_edge_score}}` : '',
          row.target_team_lens ? `${{row.target_team_lens}} timeline` : '',
          row.horizon_fit_edge ? `timeline edge ${{row.horizon_fit_edge}}` : '',
          row.horizon_fit_read ? label(row.horizon_fit_read) : '',
          row.horizon_market_disagreement_window ? `${{label(row.horizon_market_disagreement_window)}} clock` : '',
          row.horizon_market_disagreement_delta ? `clock-market ${{row.horizon_market_disagreement_delta}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: `${{row.evidence || 'No evidence provided.'}} Timeline: ${{row.horizon_fit_basis || 'timeline fit unavailable'}} Repricing: ${{row.horizon_market_disagreement_read ? `${{label(row.horizon_market_disagreement_read)}} in ${{label(row.horizon_market_disagreement_window)}} (${{row.horizon_market_disagreement_delta}})` : 'horizon-to-market comparison unavailable'}} Risk: ${{row.risk || ''}}`
      }})).join('')}}</div>`;
    }}

    function signalCards(rows, mode) {{
      if (!rows.length) return '<p class="note">No signal rows found.</p>';
      const bucket = categoryFor('mode', mode);
      return `<div class="brief-list">${{rows.slice(0, 8).map((row, index) => briefCard({{
        title: `${{row.player_name || 'Unknown player'}}${{row.current_team_name ? ` - ${{row.current_team_name}}` : ''}}`,
        category: bucket,
        rank: index + 1,
        playerId: row.player_id,
        entityHash: row.player_id ? `player-${{row.player_id}}` : '',
        chips: [
          mode,
          row.position,
          row.breakout_score ? `breakout ${{row.breakout_score}}` : '',
          row.sell_score ? `sell ${{row.sell_score}}` : '',
          row.market_value ? `market ${{row.market_value}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: row.evidence || row.source_trace || 'No evidence provided.'
      }})).join('')}}</div>`;
    }}

    function counterpartyInterestCards(rows) {{
      if (!rows.length) return '<p class="note">No active-roster asset has a supported observed audience lane.</p>';
      return `<div class="brief-list">${{rows.map((row, index) => briefCard({{
        title: `${{row.asset_name || 'Unknown asset'}} - ${{row.target_team || 'Unknown manager'}}`,
        category: categoryFor('conversation_fit_label', row.conversation_fit_label),
        rank: index + 1,
        playerId: row.asset_id,
        entityHash: row.asset_id ? `player-${{row.asset_id}}` : '',
        chips: [
          row.position,
          row.transaction_lane_read,
          row.conversation_fit_score ? `conversation fit ${{row.conversation_fit_score}}` : '',
          row.target_team_lens ? `${{row.target_team_lens}} timeline` : '',
          row.target_need ? `need ${{row.target_need}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: `${{row.evidence || 'No evidence provided.'}} Risk: ${{row.risk || ''}}`
      }})).join('')}}</div>`;
    }}

    function renderDraftRoom() {{
      const room = draftRoom || {{}};
      const summary = room.summary || {{}};
      const team = room.team || {{}};
      setText('draft-room-available', summary.available_player_count || 0);
      setText('draft-room-targets', summary.trade_target_count || 0);
      setText('draft-room-fades', summary.fade_count || 0);
      setText('draft-room-picks', summary.future_pick_count || 0);
      document.getElementById('draft-room-status').innerHTML = draftRoomStatus(room);
      document.getElementById('draft-room-board').innerHTML = draftRoomCards(room.draft_board || [], 'board');
      document.getElementById('draft-room-target-list').innerHTML = draftRoomCards(room.trade_targets || [], 'target');
      document.getElementById('draft-room-fade-list').innerHTML = draftRoomCards(room.fades || [], 'fade');
      document.getElementById('draft-room-pick-list').innerHTML = draftRoomPickCards(room.pick_leverage || []);
      document.getElementById('draft-room-data-quality').innerHTML = draftRoomQuality(room);
    }}

    function draftRoomStatus(room) {{
      const team = room.team || {{}};
      const summary = room.summary || {{}};
      const draft = room.draft_context || {{}};
      const needs = Object.entries(team.needs || {{}})
        .filter(([, value]) => value && value !== 'unknown')
        .map(([position, value]) => `${{position}}: ${{value}}`)
        .join(' · ');
      const posture = team.team_direction || team.team_shape || 'team posture unavailable';
      const unconfirmed = Number(summary.unconfirmed_player_count || 0);
      const draftType = draft.draft_type && draft.draft_type !== 'unknown' ? ` · ${{draft.draft_type}}` : '';
      const draftTimer = draft.pick_timer_seconds ? ` · ${{Math.round(Number(draft.pick_timer_seconds) / 60)}} min pick timer` : '';
      const draftFormat = draft.rounds && draft.teams ? `${{draft.rounds}} rounds · ${{draft.teams}} teams${{draftType}}${{draftTimer}}` : 'format not recorded';
      const draftNote = `Draft feed: ${{draft.label || 'Status unavailable'}} · ${{draftFormat}}. ${{draft.message || 'Draft event status is not available from the confirmed feed.'}}`;
      const identityNote = unconfirmed
        ? `${{unconfirmed}} market name${{unconfirmed === 1 ? '' : 's'}} still need Sleeper confirmation before draft use. ${{draftNote}}`
        : `Market-board identities are linked or uniquely matched to Sleeper. ${{draftNote}}`;
      return `<div class="data-room-intro"><div><strong>${{escapeHtml(team.team_name || 'Unknown team')}}</strong> · ${{escapeHtml(String(room.season || 'current season'))}}<p class="note">${{escapeHtml(team.strategy_name || posture)}}${{team.contention_window ? ` · window ${{escapeHtml(team.contention_window)}}` : ''}}</p><p class="note">Needs: ${{escapeHtml(needs || 'not configured')}}. The board contains ${{escapeHtml(String(summary.available_player_count || 0))}} market-ranked names not matched to the current league roster; ${{escapeHtml(String(summary.available_horizon_count || 0))}} have at least one comparable clock score from the same model used by rostered players. ${{escapeHtml(identityNote)}}</p></div><a class="button-link" href="#view-data-room">Open source health</a></div>`;
    }}

    function draftRoomCards(rows, mode) {{
      if (!rows.length) return `<p class="note">No ${{mode === 'fade' ? 'fade' : mode === 'target' ? 'trade target' : 'available market'}} rows found in the current evidence bundle.</p>`;
      const bucket = mode === 'fade' ? 'sell' : 'buy';
      return `<div class="brief-list">${{rows.slice(0, 12).map((row, index) => briefCard({{
        title: row.player_name || 'Unknown player',
        category: bucket,
        rank: index + 1,
        playerId: row.player_id,
        entityHash: row.player_id ? `player-${{row.player_id}}` : '',
        chips: [
          row.position,
          row.fit,
          row.need && row.need !== 'unknown' ? `need ${{row.need}}` : '',
          row.market_value ? `market ${{row.market_value}}` : '',
          row.action_label || row.consumer_label || '',
          row.horizon_status !== 'unavailable' ? `windows ${{row.horizon_fit_coverage || 'n/a'}} · next ${{row.next_game_market_score || 'n/a'}} · ROS ${{row.rest_of_season_market_score || 'n/a'}} · dynasty ${{row.dynasty_market_score || 'n/a'}}` : 'four-window unavailable',
          row.value_lane ? label(row.value_lane) : '',
          row.identity_status ? `identity ${{row.identity_status.replaceAll('_', ' ')}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        summary: row.why || '',
        watchouts: row.risk || '',
        evidence: `${{row.evidence || 'No evidence provided.'}} Source: ${{row.source_trace || 'not recorded'}}`
      }})).join('')}}</div>`;
    }}

    function draftRoomPickCards(rows) {{
      if (!rows.length) return '<p class="note">No current or future pick rows found.</p>';
      return `<div class="brief-list">${{rows.slice(0, 24).map((row, index) => briefCard({{
        title: `${{row.pick_season}} Round ${{row.round}}`,
        category: row.ownership_status === 'your_original_pick_away' ? 'alert' : row.ownership_status === 'owned_by_you' ? 'hold' : 'info',
        rank: index + 1,
        chips: [row.ownership_status, row.priority, row.market_value ? `curve ${{row.market_value}}` : '', row.value_source],
        summary: row.why || '',
        watchouts: row.risk || '',
        evidence: `${{row.evidence || ''}} Owner: ${{row.current_owner || 'unknown'}}. Original: ${{row.original_team || 'unknown'}}.`
      }})).join('')}}</div>`;
    }}

    function draftRoomQuality(room) {{
      const quality = room.data_quality || {{}};
      const health = (quality.source_health || []).map(row => `${{row.source}}/${{row.dataset}}: ${{row.status}}`).join(' · ');
      const identity = quality.market_player_identity || {{}};
      return `<p><strong>Market board:</strong> ${{escapeHtml(quality.market_player_source || 'unavailable')}} (${{escapeHtml(String(quality.market_player_rows || 0))}} rows).</p><p><strong>Identity:</strong> ${{escapeHtml(String(identity.sleeper_id || 0))}} Sleeper IDs · ${{escapeHtml(String(identity.sleeper_unique_name_match || 0))}} unique matches · ${{escapeHtml(String(identity.unconfirmed_name_match || 0))}} unconfirmed.</p><p><strong>Clock coverage:</strong> ${{escapeHtml(String((draftRoom.summary || {{}}).available_horizon_count || 0))}} available-market names have at least one comparable horizon score. These are research rows, not waiver-eligibility receipts.</p><p><strong>Pick valuation:</strong> ${{escapeHtml(quality.pick_value_source || 'unavailable')}} (${{escapeHtml(String(quality.pick_value_rows || 0))}} external value rows).</p><p><strong>Freshness:</strong> ${{escapeHtml(health || 'source freshness not recorded')}}</p>`;
    }}

    function thesisCards(rows, mode) {{
      if (!rows.length) return `<p class="note">No ${{mode}} theses found for this scope.</p>`;
      const bucket = categoryFor('mode', mode);
      return `<div class="brief-list">${{rows.map(row => {{
        const packet = mode === 'trade' ? tradePacketMarkup(row, 'Trade decision packet') : '';
        return briefCard({{
        title: row.player_name || row.target_manager_name || row.thesis_id || 'Analysis thesis',
        category: categoryFor('signal_label', row.signal_label) !== 'info' ? categoryFor('signal_label', row.signal_label) : bucket,
        playerId: row.player_id,
        decisionKey: row.thesis_id || `${{mode}}:${{row.player_id || row.target_manager_roster_id || row.target_manager_name || 'unknown'}}`,
        decisionType: mode,
        decisionSubjectId: row.player_id || row.target_manager_roster_id || '',
        decisionSubjectName: row.player_name || row.target_manager_name || '',
        decisionConfidence: row.confidence || '',
        decisionRisk: row.risk || '',
        decisionEvidence: `${{row.evidence || row.analysis_text || ''}} Source: ${{row.source_trace || ''}}`,
        chips: [
          mode,
          row.target_manager_name,
          row.position,
          row.signal_label || row.approach_type,
          row.confidence ? `confidence ${{row.confidence}}` : '',
          row.risk ? `risk ${{row.risk}}` : ''
        ],
        evidence: `${{row.analysis_text || ''}} Evidence: ${{row.evidence || ''}} Source: ${{row.source_trace || ''}}`,
        detailsHtml: packet
      }});
      }}).join('')}}</div>`;
    }}

    function markdownBrief(text) {{
      if (!text) return '<p class="note">Analysis artifact is missing. Refresh can regenerate this without blocking the fact tables.</p>';
      const withoutFrontMatter = String(text).replace(/^---[\\s\\S]*?---\\n/, '');
      const lines = withoutFrontMatter.split('\\n').filter(line => line.trim()).slice(0, 18);
      return `<div class="brief-list">${{lines.map(line => `<div class="brief-card-evidence">${{escapeHtml(line.replace(/^#+\\s*/, '').replace(/^-\\s*/, ''))}}</div>`).join('')}}</div>`;
    }}

    function articleBody(text) {{
      if (!text) return '<p class="note">No written analysis yet. Use Update &amp; Write Analysis in Operator Mode to generate it.</p>';
      const body = String(text).replace(/^---[\\s\\S]*?---\\n/, '');
      const parts = [];
      let para = [];
      let list = [];
      const flushPara = () => {{ if (para.length) {{ parts.push(`<p class="article-p">${{articleInline(para.join(' '))}}</p>`); para = []; }} }};
      const flushList = () => {{ if (list.length) {{ parts.push(`<ul class="article-list">${{list.map(item => `<li>${{articleInline(item)}}</li>`).join('')}}</ul>`); list = []; }} }};
      for (const raw of body.split('\\n')) {{
        const line = raw.trim();
        if (!line) {{ flushPara(); flushList(); continue; }}
        if (line.startsWith('# ') && !line.startsWith('## ')) {{ continue; }}
        if (line.startsWith('## ')) {{ flushPara(); flushList(); parts.push(`<h4 class="article-h">${{articleInline(line.replace(/^##\\s*/, ''))}}</h4>`); continue; }}
        if (line.startsWith('- ')) {{ flushPara(); list.push(line.replace(/^-\\s*/, '')); continue; }}
        flushList(); para.push(line);
      }}
      flushPara(); flushList();
      return `<div class="article-body">${{parts.join('')}}</div>`;
    }}

    function articleInline(value) {{
      // Escape evidence first, then permit only the small Markdown subset used
      // by deterministic fallbacks and the structured writer contract.
      return escapeHtml(value)
        .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
    }}

    function articleModeLabel(mode) {{
      return mode === 'automatic_llm' ? 'LLM-written' : 'Deterministic';
    }}

    function insightFor(entityType, entityId) {{
      const id = String(entityId || '');
      return (analysis.insightCards || []).find(row => String(row.entity_type || '') === entityType && String(row.entity_id || '') === id) || {{}};
    }}

    function topTags(entityType, entityId, limit) {{
      const id = String(entityId || '');
      const table = entityType === 'manager' ? tables.manager_profile_tags : tables.player_profile_tags;
      return table
        .filter(row => String(row.entity_id || '') === id)
        .sort((a, b) => num(b.score) - num(a.score))
        .slice(0, limit);
    }}

    function managerTrajectoryMarkup(trajectory, marker) {{
      if (!trajectory || !trajectory.status) return '';
      const recent = trajectory.recent || {{}};
      const prior = trajectory.prior || {{}};
      const seasons = windowData => (windowData.seasons || []).join(', ') || 'not recorded';
      const record = windowData => windowData.record || 'not recorded';
      const winRate = windowData => windowData.win_rate === null || windowData.win_rate === undefined || windowData.win_rate === ''
        ? 'n/a win rate'
        : `${{Math.round(num(windowData.win_rate) * 100)}}% win rate`;
      const activity = windowData => `${{windowData.trades ?? 0}} trades · ${{windowData.waiver_claims ?? 0}} waivers · ${{windowData.faab_spent ?? 0}} FAAB`;
      const outcomeCoverage = windowData => `recorded outcomes: ${{(windowData.outcome_seasons || []).join(', ') || 'none'}}${{(windowData.partial_seasons || []).length ? ` · partial: ${{windowData.partial_seasons.join(', ')}}` : ''}}`;
      return `<section class="manager-trajectory" data-testid="${{escapeHtml(marker)}}"><div class="manager-trajectory-heading"><strong>Manager trajectory</strong><span>${{escapeHtml(trajectory.status === 'comparison' ? 'observed windows' : label(trajectory.status))}}</span></div><div class="manager-trajectory-grid"><div class="manager-trajectory-window"><strong>Recent · ${{escapeHtml(seasons(recent))}}</strong><span>${{escapeHtml(activity(recent))}}<br>${{escapeHtml(record(recent))}} · ${{escapeHtml(winRate(recent))}}<br>${{escapeHtml(outcomeCoverage(recent))}}</span></div><div class="manager-trajectory-window"><strong>Prior · ${{escapeHtml(seasons(prior))}}</strong><span>${{escapeHtml(activity(prior))}}<br>${{escapeHtml(record(prior))}} · ${{escapeHtml(winRate(prior))}}<br>${{escapeHtml(outcomeCoverage(prior))}}</span></div></div><p class="manager-trajectory-read">${{escapeHtml(trajectory.activity_read || 'not comparable')}} activity · ${{escapeHtml(trajectory.outcome_read || 'not comparable')}} · ${{escapeHtml(trajectory.outcome_status || 'outcome coverage unknown')}} · descriptive only</p><details class="evidence-drawer"><summary>Trajectory evidence</summary><p class="brief-card-evidence">${{escapeHtml(trajectory.evidence || '')}} ${{escapeHtml(trajectory.risk || '')}}</p></details></section>`;
    }}

    function activeManagerDossier() {{
      const cycle = tables.manager_cycle_profiles.find(row => Number(row.roster_id) === state.teamId) || {{}};
      const tags = topTags('manager', state.teamId, 5);
      const insight = insightFor('manager', state.teamId);
      const dossier = (analysis.managerDossierItems || []).find(row => Number(row.roster_id) === state.teamId) || {{}};
      const sample = dossier.sample_size || {{}};
      const outcome = dossier.outcome_summary || {{}};
      const fit = dossier.trade_fit_evaluation || {{}};
      const history = Array.isArray(dossier.season_history) ? dossier.season_history : [];
      const repeated = dossier.repeated_behavior || {{}};
      const trajectory = dossier.trajectory || {{}};
      const transactionProfile = dossier.transaction_profile || {{}};
      if (!cycle.team_name && !tags.length && !dossier.dossier_id) return '<p class="note">No manager profile found.</p>';
      const chips = [
        cycle.dynasty_cycle,
        cycle.trade_temperature,
        cycle.pick_posture,
        cycle.waiver_posture,
        ...tags.map(row => row.tag),
        cycle.confidence ? `confidence ${{cycle.confidence}}` : ''
      ].filter(Boolean);
      const historyMarkup = history.length
        ? `<details class="evidence-drawer"><summary>Season ledger (${{history.length}} seasons)</summary><div class="brief-list">${{history.slice().reverse().map(row => `<p class="brief-card-evidence"><strong>${{escapeHtml(String(row.season || 'season'))}}</strong> · ${{escapeHtml(row.team_name || 'historical name unavailable')}} · ${{escapeHtml(String(row.trades || 0))}} trades · ${{escapeHtml(String(row.waiver_claims || 0))}} waivers${{row.outcome_status === 'recorded' ? ` · record ${{escapeHtml(`${{row.wins || 0}}-${{row.losses || 0}}-${{row.ties || 0}}`)}}` : ' · outcomes not recorded'}}${{row.peak_transaction_week ? ` · peak activity week ${{escapeHtml(String(row.peak_transaction_week))}}` : ''}}</p>`).join('')}}</div></details>`
        : '';
      const repeatedMarkup = repeated.players_acquired?.length || repeated.players_sold?.length || repeated.trade_partners?.length
        ? `<details class="evidence-drawer"><summary>Repeated behavior</summary>${{repeated.players_acquired?.length ? `<p class="brief-card-evidence"><strong>Acquired:</strong> ${{escapeHtml(repeated.players_acquired.slice(0, 8).join('; '))}}</p>` : ''}}${{repeated.players_sold?.length ? `<p class="brief-card-evidence"><strong>Sold:</strong> ${{escapeHtml(repeated.players_sold.slice(0, 8).join('; '))}}</p>` : ''}}${{repeated.trade_partners?.length ? `<p class="brief-card-evidence"><strong>Partners:</strong> ${{escapeHtml(repeated.trade_partners.slice(0, 5).map(row => typeof row === 'string' ? row : `${{row.name}} (${{row.count || 0}})`).join('; '))}}</p>` : ''}}</details>`
        : '';
      const trajectoryMarkup = managerTrajectoryMarkup(trajectory, 'manager-trajectory-snapshot');
      const transactionProfileMarkup = managerTransactionProfileMarkup(transactionProfile);
      return `<article class="brief-card manager-dossier-snapshot"><div class="brief-card-top"><strong>${{escapeHtml(insight.headline || dossier.team_name || cycle.team_name || activeTeamName())}}</strong><span class="tag">${{escapeHtml(dossier.dossier_id ? 'Evidence dossier' : 'Deterministic profile')}}</span></div>${{chips.length ? `<div class="brief-card-meta">${{chips.map(value => `<span class="brief-chip">${{escapeHtml(value)}}</span>`).join('')}}</div>` : ''}}<p class="article-p">${{escapeHtml(dossier.analysis_text || insight.one_line_read || `Likely needs: ${{cycle.likely_needs || 'unclear'}}. Likely sells: ${{cycle.likely_sells || 'unclear'}}.`)}}</p><div class="tile-row">${{entityTile('Seasons', sample.seasons ?? '')}}${{entityTile('Trades', sample.trades ?? '')}}${{entityTile('Waivers', sample.waiver_claims ?? '')}}${{entityTile('Observed events', sample.observed_events ?? '')}}${{entityTile('Outcome record', outcome.record || 'not recorded')}}${{entityTile('Aligned fits', fit.aligned_fit_count ?? 0)}}</div><p class="note"><strong>Read carefully:</strong> ${{escapeHtml(insight.watchouts || dossier.risk || 'Observed behavior is not manager intent.')}}</p>${{trajectoryMarkup}}${{transactionProfileMarkup}}${{historyMarkup}}${{repeatedMarkup}}<a class="button-link" href="#team-${{Number(state.teamId)}}">Open full manager dossier →</a></article>`;
    }}

    function profileTagCards(rows, isPlayer) {{
      if (!rows.length) return '<p class="note">No profile tags found.</p>';
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: row.entity_name || 'Unknown',
        category: categoryFor('tag', row.tag),
        playerId: isPlayer ? row.entity_id : null,
        chips: [
          row.tag,
          row.score ? `score ${{row.score}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        summary: row.risk || 'Evidence-backed tag.',
        evidence: row.evidence || 'No evidence provided.'
      }})).join('')}}</div>`;
    }}

    function playerDossierCards(rows) {{
      if (!rows.length) return '<p class="note">No player dossiers found for this team.</p>';
      const tagsByPlayer = new Map();
      tables.player_profile_tags.forEach(row => {{
        const key = String(row.entity_id || '');
        const list = tagsByPlayer.get(key) || [];
        list.push(row.tag);
        tagsByPlayer.set(key, list);
      }});
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: (insightFor('player', row.player_id).headline || row.player_name || 'Unknown player'),
        category: categoryFor('signal_label', row.signal_label),
        playerId: row.player_id,
        entityHash: row.player_id ? `player-${{row.player_id}}` : '',
        chips: [
          row.position,
          row.market_value ? `market ${{row.market_value}}` : '',
          row.projected_ppg !== undefined && row.projected_ppg !== '' ? projectionPpgText(row, row.projected_ppg) : '',
          row.availability_note ? row.availability_note : '',
          row.availability_scope === 'current_season_snapshot' ? 'current Sleeper snapshot' : row.availability_scope === 'historical_unavailable' ? 'historical availability unavailable' : '',
          row.projection_confidence ? `projection ${{row.projection_confidence}}` : '',
          ...(topTags('player', row.player_id, 4).map(tag => tag.tag))
        ],
        summary: insightFor('player', row.player_id).one_line_read || `Signal: ${{row.signal_label || 'none'}}. News: ${{row.news_impact || 'none'}}.`,
        watchouts: insightFor('player', row.player_id).watchouts || 'Player tags are prompts for review, not outcome guarantees.',
        evidence: `Market: ${{row.market_value || 'unknown'}}. ${{projectionPpgText(row, row.projected_ppg)}}. Availability: ${{row.availability_note || 'not recorded'}}. League transactions: ${{row.transaction_count || 0}}. Last transaction: ${{row.last_transaction || 'none'}}.`
      }})).join('')}}</div>`;
    }}

    function weightedScenarioScore(components) {{
      const weights = state.lensWeights;
      const total = lensWeightTotal();
      if (total <= 0) return 0;
      const score = (
        components.marketComponent * weights.market +
        components.projectionComponent * weights.projection +
        components.managerComponent * weights.manager +
        components.timelineComponent * weights.timeline +
        components.newsComponent * weights.news
      ) / total;
      return Math.round(score * 100) / 100;
    }}

    function lensWeightTotal() {{
      return Object.values(state.lensWeights).reduce((sum, value) => sum + Number(value || 0), 0);
    }}

    function capScore(value) {{
      const score = num(value);
      if (!Number.isFinite(score)) return 0;
      return Math.round(Math.max(0, Math.min(100, score)) * 100) / 100;
    }}

    function canonicalScore(label) {{
      const text = String(label || '');
      if (text.includes('we_may_value_more') || text.includes('True Buy Low')) return 75;
      if (text.includes('mutual_fit') || text.includes('Price Check')) return 58;
      if (text.includes('owner_may_overvalue') || text.includes('Core Hold')) return 42;
      if (text.includes('do_not_chase') || text.includes('Avoid')) return 12;
      return 35;
    }}

    function rowMap(rows, key) {{
      const map = new Map();
      rows.forEach(row => {{
        const value = String(row[key] || '');
        if (value && !map.has(value)) map.set(value, row);
      }});
      return map;
    }}

    function newsHeatByPlayer() {{
      const map = new Map();
      scopedCurrentLeagueNews().forEach(row => {{
        const playerId = String(row.player_id || '');
        if (!playerId) return;
        const current = map.get(playerId) || 0;
        const impact = String(row.impact_type || '');
        const score = impact.includes('market_heat') ? 80 : impact.includes('injury') ? 70 : 45;
        map.set(playerId, Math.max(current, score));
      }});
      return map;
    }}

    function managerPreferenceMap() {{
      const map = new Map();
      tables.manager_valuation_profiles.forEach(row => {{
        const key = `${{row.roster_id}}|${{row.position_group}}`;
        const existing = map.get(key) || {{}};
        if (num(row.preference_score) >= num(existing.preference_score)) map.set(key, row);
      }});
      return map;
    }}

    function scenarioPositionGroup(position) {{
      if (position === 'WR' || position === 'TE') return 'PASS_CATCHER';
      if (position === 'RB') return 'RB';
      if (position === 'QB') return 'QB';
      return 'DEPTH';
    }}

    function scenarioWarning(consensus, signal, manager, row, totalWeight) {{
      const warnings = [];
      if (totalWeight !== 100) warnings.push('degraded: weights do not sum to 100');
      if (!consensus || !consensus.consensus_value) warnings.push('degraded: market consensus missing');
      if (num(consensus.disagreement_score) >= 25) warnings.push('degraded: market sources disagree');
      if (String(signal.projection_confidence || signal.confidence || '').toLowerCase() === 'low') warnings.push('degraded: projection confidence low');
      if (manager && String(manager.confidence || '').toLowerCase() === 'low') warnings.push('degraded: manager preference sparse');
      if (String(row.risk || '').toLowerCase().includes('sparse')) warnings.push('degraded: sparse evidence');
      return warnings.length ? warnings.join('; ') : 'none';
    }}

    function scenarioConfidence(edgeConfidence, signalConfidence, managerConfidence, warning) {{
      if (String(warning || '').includes('degraded')) return 'low';
      if (edgeConfidence === 'high' && signalConfidence === 'high' && managerConfidence === 'high') return 'high';
      if (edgeConfidence === 'low' || signalConfidence === 'low' || managerConfidence === 'low') return 'low';
      return 'medium';
    }}

    function decisionOutcomeControl(card) {{
      if (!card.decisionKey) return '';
      const subjectName = card.decisionSubjectName || card.title || '';
      return `<div class="decision-outcome" data-decision-key="${{escapeHtml(String(card.decisionKey))}}" data-decision-type="${{escapeHtml(String(card.decisionType || ''))}}" data-decision-subject-id="${{escapeHtml(String(card.decisionSubjectId || ''))}}" data-decision-subject-name="${{escapeHtml(String(subjectName))}}" data-decision-confidence="${{escapeHtml(String(card.decisionConfidence || ''))}}" data-decision-risk="${{escapeHtml(String(card.decisionRisk || ''))}}" data-decision-evidence="${{escapeHtml(String(card.decisionEvidence || ''))}}">
        <label>${{card.decisionType === 'manager_fit' ? 'Manager-fit outcome' : 'Recommendation outcome'}}<select data-decision-outcome-select="${{escapeHtml(String(card.decisionKey))}}">
          <option value="open">Track this call</option>
          <option value="confirmed">Confirmed useful</option>
          <option value="missed">Missed or wrong</option>
          <option value="unclear">Unclear / needs more evidence</option>
        </select></label>
        <button type="button" data-content-interaction="decision_outcome" data-artifact-key="${{escapeHtml(String(card.decisionKey))}}">Save outcome</button>
      </div>`;
    }}

    function briefCard(card) {{
      const bucket = card.category || 'info';
      const rankNum = Number(card.rank);
      const rank = card.rank && Number.isFinite(rankNum) ? rankNum : null;
      const playerId = card.playerId || null;

      const chips = (card.chips || []).filter(value => value !== undefined && value !== null && String(value) !== '' && String(value) !== '0');
      const summary = card.summary || card.oneLine || '';
      const watchouts = card.watchouts ? `<div class="brief-card-evidence"><strong>Watch:</strong> ${{escapeHtml(card.watchouts)}}</div>` : '';
      const details = card.details || card.evidence || '';
      const detailsHtml = card.detailsHtml || '';
      const decisionOutcome = decisionOutcomeControl(card);

      const rankBlock = rank
        ? `<div class="brief-card-rank ${{rank <= 3 ? 'brief-card-rank-top' : ''}}">${{rank}}</div>`
        : '';
      const headshotBlock = playerId
        ? `<div class="brief-card-headshot">${{headshotImg(playerId, card.title || '')}}</div>`
        : '';
      const mediaBlock = `<div class="brief-card-media">${{rankBlock}}${{headshotBlock}}</div>`;

      const titleText = escapeHtml(card.title || 'Untitled');
      const titleHtml = card.entityHash ? `<a class="entity-link" href="#${{escapeHtml(String(card.entityHash))}}">${{titleText}}</a>` : titleText;
      return `<article class="brief-card cat-${{bucket}}">
        ${{mediaBlock}}
        <div class="brief-card-body">
          <div class="brief-card-title">${{titleHtml}}</div>
          <div class="brief-card-meta">${{chips.map(chip => `<span class="brief-chip">${{escapeHtml(chip)}}</span>`).join('')}}</div>
          ${{summary ? `<div class="brief-card-summary">${{escapeHtml(summary)}}</div>` : ''}}
          ${{watchouts}}
          ${{details ? `<details class="evidence-drawer"><summary>Evidence</summary><div class="brief-card-evidence">${{escapeHtml(details)}}</div></details>` : ''}}
          ${{detailsHtml ? `<details class="evidence-drawer trade-packet-drawer"><summary>Open the two-sided decision packet</summary>${{detailsHtml}}</details>` : ''}}
          ${{decisionOutcome}}
        </div>
      </article>`;
    }}

    function table(rows, columns) {{
      if (!rows.length) return '<p class="note">No rows found.</p>';
      const head = columns.map(column => `<th>${{escapeHtml(columnLabel(column))}}</th>`).join('');
      const body = rows.map(row => `<tr>${{columns.map(column => `<td>${{renderCell(row, column)}}</td>`).join('')}}</tr>`).join('');
      return `<div class="table-wrap"><table><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table></div>`;
    }}

    function list(items) {{
      if (!items.length) return '<p class="note">None found.</p>';
      return `<ul class="list">${{items.map(item => `<li>${{escapeHtml(item)}}</li>`).join('')}}</ul>`;
    }}

    function applySearch(rows) {{
      if (!state.query) return rows;
      return rows.filter(row => Object.values(row).some(value => String(value).toLowerCase().includes(state.query)));
    }}

    function sortRows(rows, columns) {{
      return rows.slice().sort((a, b) => {{
        for (const column of columns) {{
          const left = a[column];
          const right = b[column];
          const leftNum = Number(left);
          const rightNum = Number(right);
          const cmp = Number.isFinite(leftNum) && Number.isFinite(rightNum)
            ? leftNum - rightNum
            : String(left ?? '').localeCompare(String(right ?? ''));
          if (cmp !== 0) return cmp;
        }}
        return 0;
      }});
    }}

    function setActive(selector, activeButton) {{
      document.querySelectorAll(selector).forEach(button => button.classList.toggle('active', button === activeButton));
    }}

    const VIEW_IDS = [
      'view-today', 'view-draft-room', 'view-my-team', 'view-players', 'view-league',
      'view-trade-desk', 'view-news', 'view-data-room'
    ];

    function findRow(rows, key, value) {{
      const target = String(value ?? '');
      return (rows || []).find(row => String(row[key] ?? '') === target) || {{}};
    }}

    function findRows(rows, key, value) {{
      const target = String(value ?? '');
      return (rows || []).filter(row => String(row[key] ?? '') === target);
    }}

    function entityTile(label, value, kind) {{
      const num = Number(value);
      const shown = value === undefined || value === null || value === '' ? '--' : value;
      let band = '';
      if (kind === 'score' && Number.isFinite(num)) {{
        band = num >= 70 ? 'score-high' : num >= 40 ? 'score-mid' : 'score-low';
      }}
      return `<div class="entity-tile"><div class="entity-tile-value ${{band}}">${{escapeHtml(String(shown))}}</div><div class="entity-tile-label">${{escapeHtml(label)}}</div></div>`;
    }}

    function tradePacketMarkup(thesis, heading) {{
      if (!thesis || !thesis.thesis_id) return '';
      const pursue = (thesis.assets_to_pursue || []).slice(0, 5)
        .map(asset => `${{asset.player_name || 'unnamed target'}} (${{asset.position || 'asset'}}; ${{asset.confidence || 'confidence unknown'}})`)
        .join(', ') || thesis.assets_to_discuss || 'No named target';
      const offers = (thesis.offer_candidates || []).slice(0, 5)
        .map(asset => `${{asset.asset_name || 'unnamed asset'}} (${{asset.position_group || asset.position || 'asset'}}; lane ${{asset.manager_preference_label || 'low-signal manager lane'}}; evidence ${{String(asset.manager_preference_evidence_count ?? 0)}})`)
        .join(', ') || (thesis.assets_we_can_offer || []).join(', ') || 'Not established';
      const audience = (thesis.assets_target_may_value || []).slice(0, 5)
        .map(asset => `${{asset.asset_name || 'unnamed asset'}} (${{asset.position || 'asset'}}; fit ${{asset.conversation_fit_score ?? 'n/a'}}; ${{asset.transaction_lane_read || 'observed lane'}})`)
        .join(', ') || 'No active-roster audience lane is supported';
      const alternatives = (thesis.alternative_counterparties || []).filter(Boolean).join(', ');
      const conditions = thesis.do_not_chase_conditions || [];
      const evidence = [thesis.evidence, thesis.source_trace].filter(Boolean).join(' Source: ');
      const horizonRead = thesis.horizon_fit_read
        ? `${{label(thesis.horizon_fit_read)}}: target ${{thesis.target_horizon_fit_score ?? 'n/a'}} vs our ${{thesis.active_horizon_fit_score ?? 'n/a'}} (edge ${{thesis.horizon_fit_edge ?? 'n/a'}}).`
        : 'No target-versus-active timeline fit was joined to this thesis; inspect the refresh receipt before treating that as balance.';
      const repricingRead = thesis.horizon_market_disagreement_window
        ? `${{label(thesis.horizon_market_disagreement_read || 'clock-market read')}} in ${{label(thesis.horizon_market_disagreement_window)}} (${{thesis.horizon_market_disagreement_delta ?? 'n/a'}}); research lead only, not a dollar gap.`
        : 'No horizon-to-market repricing comparison was joined to this thesis.';
      return `<div class="trade-packet" data-trade-packet="${{escapeHtml(String(thesis.thesis_id))}}">
        <h3>${{escapeHtml(heading || 'Trade decision packet')}}</h3>
        <p class="article-p"><strong>Pursue:</strong> ${{escapeHtml(pursue)}}</p>
        <p class="article-p"><strong>Potential assets from our roster to discuss (not a generated offer):</strong> ${{escapeHtml(offers)}}</p>
        <p class="article-p"><strong>Possible audience for our assets:</strong> ${{escapeHtml(audience)}}</p>
        <p class="article-p"><strong>Alternative counterparties:</strong> ${{escapeHtml(alternatives || 'No alternate counterparty is supported for this target by the current evidence.')}}</p>
        <p class="article-p"><strong>Why this manager might care:</strong> ${{escapeHtml(thesis.why_manager_might_care || 'Not established')}}</p>
        <p class="article-p"><strong>Timeline fit:</strong> ${{escapeHtml(horizonRead)}} This is separate from market price and position-relative horizon percentiles.</p>
        <p class="article-p"><strong>Market vs clock:</strong> ${{escapeHtml(repricingRead)}} The canonical market value remains the cross-position price anchor.</p>
        <p class="article-p"><strong>Price guardrails:</strong> offer band ${{escapeHtml(String(thesis.plausible_offer_range?.low ?? 'n/a'))}}–${{escapeHtml(String(thesis.plausible_offer_range?.high ?? 'n/a'))}} estimated market value; minimum return ${{escapeHtml(String(thesis.minimum_acceptable_return?.value ?? 'n/a'))}}.</p>
        <p class="article-p"><strong>Risk of waiting:</strong> ${{escapeHtml(thesis.risk_of_waiting || 'not established')}} <strong>Risk of acting:</strong> ${{escapeHtml(thesis.risk_of_acting || thesis.risk || 'review evidence')}}.</p>
        ${{conditions.length ? `<details class="evidence-drawer"><summary>Do-not-chase conditions</summary><ul class="article-list">${{conditions.map(row => `<li>${{escapeHtml(row)}}</li>`).join('')}}</ul></details>` : ''}}
        ${{evidence ? `<details class="evidence-drawer"><summary>Evidence and source trace</summary><p class="brief-card-evidence">${{escapeHtml(evidence)}}</p></details>` : ''}}
        <p class="note"><strong>Read-only guardrail:</strong> This is a conversation shortlist grounded in observed history, not a generated offer or predicted response. The human manager decides whether to investigate or act.</p>
      </div>`;
    }}

    function managerTradeFitMarkup(dossier) {{
      const tradeFits = dossier?.trade_fits || [];
      const status = String(dossier?.trade_fit_status || (tradeFits.length ? 'supported' : 'none_supported'));
      const summary = dossier?.trade_fit_summary || (tradeFits.length
        ? `${{tradeFits.length}} evidence-backed trade fit${{tradeFits.length === 1 ? '' : 's'}} are supported by the current edge rows.`
        : 'No supported trade fit is present in the current counterparty edge rows; do not manufacture a target from manager labels alone.');
      const evaluation = dossier?.trade_fit_evaluation || {{}};
      const lanes = evaluation.historical_lanes || [];
      const alignmentByPlayer = new Map((evaluation.fit_alignment || []).map(row => [String(row.player_id || ''), row]));
      const fitCards = tradeFits.length
        ? `<div class="brief-list">${{tradeFits.map((row, index) => {{
            const alignment = alignmentByPlayer.get(String(row.player_id || '')) || {{}};
            const laneText = alignment.status === 'aligned'
              ? `Historical lane: ${{alignment.lane_label || alignment.position_group || 'observed group'}}`
              : 'No direct historical lane in the observed profile';
            const laneEvidence = alignment.evidence ? `Historical lane evidence: ${{alignment.evidence}}` : alignment.reason || '';
            return briefCard({{ title: row.player_name || 'Unknown player', category: categoryFor('edge_type', row.edge_type), rank: index + 1, chips: [row.position, row.edge_type, row.trade_edge_score ? `edge ${{row.trade_edge_score}}` : '', row.target_team_lens ? `${{row.target_team_lens}} timeline` : '', row.horizon_fit_edge ? `timeline edge ${{row.horizon_fit_edge}}` : '', row.confidence ? `confidence ${{row.confidence}}` : ''], summary: [row.risk || 'Conversation hypothesis; verify the price.', row.horizon_fit_read ? `${{label(row.horizon_fit_read)}}: target ${{row.target_horizon_fit_score ?? 'n/a'}} vs active ${{row.active_horizon_fit_score ?? 'n/a'}}` : 'Timeline fit unavailable', laneText].filter(Boolean).join(' · '), evidence: [row.evidence || 'No evidence supplied.', row.horizon_fit_basis || '', laneEvidence].filter(Boolean).join(' · '), decisionKey: `manager-fit:${{String(dossier.roster_id || 'unknown')}}:${{String(row.player_id || index)}}`, decisionType: 'manager_fit', decisionSubjectId: row.player_id || '', decisionSubjectName: row.player_name || 'manager fit', decisionConfidence: row.confidence || '', decisionRisk: row.risk || '', decisionEvidence: [row.evidence || '', row.horizon_fit_basis || '', laneEvidence].filter(Boolean).join(' · ') }});
          }}).join('')}}</div>`
        : '<p class="note">No fit card is shown because the current evidence does not support one.</p>';
      const laneMarkup = lanes.length
        ? `<details class="evidence-drawer"><summary>Cross-season valuation lanes (${{lanes.length}})</summary><p class="brief-card-evidence">These lanes summarize observed activity across ${{escapeHtml(String(evaluation.historical_seasons ?? 0))}} season${{Number(evaluation.historical_seasons || 0) === 1 ? '' : 's'}}. They help prioritize a conversation; they do not establish intent. ${{escapeHtml(String(evaluation.aligned_fit_count ?? 0))}} current fit${{Number(evaluation.aligned_fit_count || 0) === 1 ? '' : 's'}} align directly; ${{escapeHtml(String(evaluation.no_direct_lane_fit_count ?? 0))}} have no direct lane.</p><div class="brief-list">${{lanes.map(row => `<p class="brief-card-evidence"><strong>${{escapeHtml(row.label || row.position_group || 'Observed lane')}}</strong> · ${{escapeHtml(row.position_group || 'group unavailable')}} · score ${{escapeHtml(String(row.recency_weighted_score ?? row.preference_score ?? 'n/a'))}} · evidence ${{escapeHtml(String(row.evidence_count ?? 0))}} · confidence ${{escapeHtml(row.confidence || 'unknown')}}</p>`).join('')}}</div></details>`
        : '<p class="note">No historical valuation lane is available for this manager.</p>';
      return `<details class="evidence-drawer manager-trade-fit"><summary>Trade-fit status · ${{escapeHtml(status === 'supported' ? 'supported' : 'none supported')}}</summary><p class="brief-card-evidence">${{escapeHtml(summary)}}</p>${{fitCards}}${{laneMarkup}}</details>`;
    }}

    function managerTransactionProfileMarkup(profile) {{
      const lanes = Array.isArray(profile?.lanes) ? profile.lanes : [];
      if (!lanes.length) return '<p class="note">No identity-resolved player transaction lanes are available for this manager.</p>';
      const shown = value => value === undefined || value === null || value === '' ? 'n/a' : value;
      const pair = (labelText, acquired, sold, delta) => `${{labelText}}: acquired ${{shown(acquired)}} · sold ${{shown(sold)}}${{delta !== undefined && delta !== null && delta !== '' ? ` · delta ${{delta}}` : ''}}`;
      const cards = lanes.slice(0, 6).map(row => `<article class="manager-lane-card">
        <div class="brief-card-top"><strong>${{escapeHtml(row.position_group || 'Unknown position')}}</strong><span class="tag">${{escapeHtml(row.transaction_read || 'observed lane')}}</span></div>
        <p class="brief-card-evidence"><strong>Observed movement:</strong> acquired ${{escapeHtml(String(shown(row.acquired_count)))}} · sold ${{escapeHtml(String(shown(row.sold_count)))}} · net ${{escapeHtml(String(shown(row.net_acquired_count)))}} · current roster overlap acquired/sold ${{escapeHtml(String(shown(row.current_roster_acquired_count)))}}/${{escapeHtml(String(shown(row.current_roster_sold_count)))}}</p>
        <p class="brief-card-evidence"><strong>Current horizon context:</strong> ${{escapeHtml(pair('Next game', row.acquired_next_game_market_score, row.sold_next_game_market_score, row.acquired_minus_sold_next_game_delta))}} · ${{escapeHtml(pair('Rest of season', row.acquired_rest_of_season_market_score, row.sold_rest_of_season_market_score, row.acquired_minus_sold_rest_of_season_delta))}} · ${{escapeHtml(pair('Dynasty', row.acquired_dynasty_market_score, row.sold_dynasty_market_score, row.acquired_minus_sold_dynasty_delta))}} · ${{escapeHtml(pair('Career window', row.acquired_career_projection_score, row.sold_career_projection_score, row.acquired_minus_sold_career_delta))}}</p>
        <p class="brief-card-evidence"><strong>Strategy context:</strong> contender acquired/sold ${{escapeHtml(String(shown(row.acquired_contender_fit_score)))}}/${{escapeHtml(String(shown(row.sold_contender_fit_score)))}} · rebuilder acquired/sold ${{escapeHtml(String(shown(row.acquired_rebuilder_fit_score)))}}/${{escapeHtml(String(shown(row.sold_rebuilder_fit_score)))}}</p>
        <p class="note">${{escapeHtml(String(row.horizon_coverage_detail || row.horizon_coverage || 'Horizon coverage unavailable'))}} · ${{escapeHtml(String(row.history_status || 'history status unavailable'))}} · confidence ${{escapeHtml(String(row.confidence || 'unknown'))}}</p>
        <details class="evidence-drawer"><summary>Names and receipt</summary><p class="brief-card-evidence"><strong>Acquired:</strong> ${{escapeHtml(String(row.unique_acquired_players || 'none recorded'))}}</p><p class="brief-card-evidence"><strong>Sold:</strong> ${{escapeHtml(String(row.unique_sold_players || 'none recorded'))}}</p><p class="brief-card-evidence">${{escapeHtml(String(row.evidence || 'manager_transaction_preferences'))}} · source trace: ${{escapeHtml(String(row.source_trace || 'manager_transaction_preferences'))}}</p></details>
      </article>`).join('');
      return `<details class="evidence-drawer manager-transaction-profile" data-testid="manager-transaction-profile"><summary>Observed player transaction lanes (${{lanes.length}})</summary><p class="brief-card-evidence">${{escapeHtml(String(profile.summary || 'Observed transaction lanes are descriptive only.'))}}</p><div class="brief-list">${{cards}}</div></details>`;
    }}

    function managerCounterpartyInterestMarkup(profile) {{
      const rows = Array.isArray(profile?.rows) ? profile.rows : [];
      if (!rows.length) return '';
      const cards = rows.slice(0, 8).map((row, index) => briefCard({{
        title: `${{row.asset_name || 'Unknown asset'}} · audience question`,
        category: categoryFor('conversation_fit_label', row.conversation_fit_label),
        rank: index + 1,
        playerId: row.asset_id,
        entityHash: row.asset_id ? `player-${{row.asset_id}}` : '',
        chips: [
          row.position,
          row.transaction_lane_read,
          row.conversation_fit_score ? `fit ${{row.conversation_fit_score}}` : '',
          row.target_need ? `need ${{row.target_need}}` : '',
          row.target_team_lens ? `${{row.target_team_lens}} timeline` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        summary: `${{row.horizon_fit_read || 'Timeline fit unavailable'}} · observed lane is not proof of intent or acceptance`,
        evidence: [row.evidence || '', row.risk || '', row.source_trace || ''].filter(Boolean).join(' · ')
      }})).join('');
      return `<div class="panel article-panel" data-testid="manager-counterparty-interest"><h3>Possible audiences for our assets</h3><p class="note">${{escapeHtml(String(profile.summary || 'These are conversation priorities grounded in observed history.'))}} They are questions to investigate, not predicted responses.</p><div class="brief-list">${{cards}}</div></div>`;
    }}

    function managerTransactionTimelineMarkup(events) {{
      const rows = (events || []).slice(0, 24);
      if (!rows.length) return '<p class="note">No event-level transaction history is available for this manager.</p>';
      const clean = value => String(value ?? '').trim();
      const movement = row => [
        clean(row.players_in) ? `In: ${{escapeHtml(clean(row.players_in))}}` : '',
        clean(row.players_out) ? `Out: ${{escapeHtml(clean(row.players_out))}}` : '',
        clean(row.picks_in) ? `Picks in: ${{escapeHtml(clean(row.picks_in))}}` : '',
        clean(row.picks_out) ? `Picks out: ${{escapeHtml(clean(row.picks_out))}}` : '',
        clean(row.faab_in) ? `FAAB in: ${{escapeHtml(clean(row.faab_in))}}` : '',
        clean(row.faab_out) ? `FAAB out: ${{escapeHtml(clean(row.faab_out))}}` : ''
      ].filter(Boolean).join(' · ') || 'No asset detail recorded';
      return `<details class="evidence-drawer manager-transaction-timeline"><summary>Observed transaction timeline (${{rows.length}} latest events)</summary><p class="brief-card-evidence">Event-level evidence is scoped to this roster and ordered newest first. It records what Sleeper logged; it does not establish why the manager acted or what they will do next.</p><div class="manager-event-list">${{rows.map(row => `<article class="manager-event-row">
        <div class="brief-card-top"><strong>${{escapeHtml(label(row.event_type || 'event'))}} · ${{escapeHtml(String(row.season || 'season unknown'))}} · week ${{escapeHtml(String(row.week || 'n/a'))}}</strong><span class="tag">${{escapeHtml(clean(row.created_datetime) || 'time unavailable')}}</span></div>
        <p class="brief-card-evidence"><strong>Counterparty:</strong> ${{escapeHtml(clean(row.counterparty) || 'none recorded')}}</p>
        <p class="brief-card-evidence"><strong>Movement:</strong> ${{movement(row)}}</p>
        <p class="note"><strong>Event-level evidence:</strong> ${{escapeHtml(clean(row.evidence) || 'manager_event_log')}} · source trace: manager_event_log</p>
      </article>`).join('')}}</div></details>`;
    }}

    function backLink() {{
      return '<a class="back-link" href="javascript:history.back()">&larr; back</a>';
    }}

    function playerHorizonMarkup(horizon) {{
      if (!horizon || !horizon.player_id) return '';
      const shown = value => value === undefined || value === null || value === '' ? 'n/a' : value;
      const availabilitySource = horizon.current_availability_status === 'no_current_nfl_team'
        ? 'No current NFL team in Sleeper; current role unavailable'
        : horizon.availability_scope === 'current_season_snapshot'
        ? 'Current Sleeper player snapshot'
        : horizon.availability_scope === 'historical_unavailable'
          ? 'Historical availability unavailable by contract'
          : 'Availability scope not recorded';
      const scoreCard = (title, score, detail, status, basis) => `<article class="horizon-card"><div class="brief-card-top"><strong>${{escapeHtml(title)}}</strong><span class="tag">percentile ${{escapeHtml(String(shown(score)))}}</span></div>${{horizonCardMeter(score, title)}}<p class="brief-card-evidence">${{escapeHtml(detail)}}</p><p class="note">${{escapeHtml(String(status || 'status unavailable'))}}</p>${{basis ? `<details class="horizon-basis"><summary>How this is calculated</summary><p class="note">${{escapeHtml(String(basis))}}</p></details>` : ''}}</article>`;
      const opponentDetail = horizon.next_game_opponent ? `vs ${{horizon.next_game_opponent}} (${{horizon.next_game_home_away || 'game'}})` : 'opponent unavailable';
      const validationDetail = horizon.next_game_matchup_validation_status && horizon.next_game_matchup_validation_status !== 'unavailable'
        ? ` · holdout ${{horizon.next_game_matchup_validation_status}} (${{shown(horizon.next_game_matchup_validation_games)}} games; MAE delta ${{shown(horizon.next_game_matchup_validation_mae_delta)}})`
        : '';
      const adjustmentDetail = horizon.next_game_matchup_adjustment_status === 'applied' ? 'factor applied' : horizon.next_game_matchup_factor ? 'factor descriptive only' : 'no factor applied';
      const nextDetail = `week ${{shown(horizon.next_game_week)}} · ${{opponentDetail}} · expected ${{shown(horizon.next_game_expected_points)}} points / baseline ${{shown(horizon.next_game_baseline_points)}} · factor ${{shown(horizon.next_game_matchup_factor)}} (${{adjustmentDetail}})${{validationDetail}}`;
      const hasRosGames = horizon.rest_of_season_games !== undefined && horizon.rest_of_season_games !== null && horizon.rest_of_season_games !== '';
      const rosSchedule = hasRosGames
        ? `${{shown(horizon.rest_of_season_games)}} scheduled games / ${{shown(horizon.rest_of_season_bye_weeks)}} bye weeks`
        : horizonRestSeasonCountLabel(horizon);
      const rosDetail = `${{rosSchedule}} · ${{shown(horizon.rest_of_season_baseline_points)}} baseline points · ${{horizonRestSeasonPpgLabel(horizon)}} · rest-of-season baseline is not recovery-adjusted`;
      const dynastyDetail = `${{shown(horizon.dynasty_status)}} · five-year career-window score ${{shown(horizon.career_projection_score)}} · cross-position price anchor market value ${{shown(horizon.market_value)}} · value lane: ${{shown(horizon.value_lane)}}`;
      const clockShiftDetail = `ROS minus next ${{shown(horizon.rest_of_season_minus_next_game_delta)}} · dynasty minus ROS ${{shown(horizon.dynasty_minus_rest_of_season_delta)}} · career minus dynasty ${{shown(horizon.career_minus_dynasty_delta)}}`;
      const dynastyBasis = [horizon.dynasty_basis, horizon.career_projection_basis ? `Career window: ${{horizon.career_projection_basis}}` : ''].filter(Boolean).join(' ');
      const careerHistoryDetail = horizon.career_history_status === 'matched'
        ? `history anchor ${{shown(horizon.career_history_ppg)}} PPG across ${{shown(horizon.career_history_games)}} games / ${{shown(horizon.career_history_seasons)}} seasons (source player id ${{shown(horizon.career_history_source_player_id)}})`
        : horizon.career_history_status === 'ambiguous'
          ? 'historical anchor withheld because the source-player join is ambiguous'
          : 'historical production anchor unavailable';
      const careerDetail = `${{shown(horizon.career_projection_points)}} projected points across ${{shown(horizon.career_projection_years)}} years · ${{shown(horizon.career_projection_ppg)}} blended PPG · ${{careerHistoryDetail}} · internal age-curve scenario${{horizon.career_history_status === 'matched' ? ' (history-anchored)' : ''}}, not a lifetime forecast`;
      const fitDetail = `contender ${{shown(horizon.contender_fit_score)}} · rebuilder ${{shown(horizon.rebuilder_fit_score)}} · spread ${{shown(horizon.rebuilder_contender_spread)}} · fit coverage ${{shown(horizon.fit_coverage)}}`;
      const marketDeltaDetail = `next game ${{shown(horizon.next_game_minus_market_delta)}} · rest of season ${{shown(horizon.rest_of_season_minus_market_delta)}} · dynasty ${{shown(horizon.dynasty_minus_market_delta)}} · career window ${{shown(horizon.career_minus_market_delta)}}`;
      const marketReceiptDetail = `${{shown(horizon.market_source_count)}} source(s) · disagreement ${{shown(horizon.market_disagreement_score)}} · confidence ${{shown(horizon.market_source_confidence)}}`;
      const calibrationRows = (tables.horizon_score_accuracy || []).filter(row => String(row.position || '') === String(horizon.position || ''));
      const calibrationDetail = calibrationRows.length
        ? calibrationRows.map(row => `${{label(row.horizon || 'horizon')}}: ${{row.evaluation_status || 'status unavailable'}} · n=${{shown(row.n_player_snapshots || row.n_snapshots)}} · rank correlation ${{shown(row.spearman_rank_correlation)}}`).join(' · ')
        : 'No dated realized outcomes have been graded for this position yet. The scores remain structural comparisons, not outcome-calibrated forecasts.';
      return `<section class="panel article-panel player-horizon-panel" data-testid="player-horizons"><div class="brief-card-top"><h3>Market clocks &amp; career window</h3><span class="tag">as of week ${{escapeHtml(String(shown(horizon.as_of_week)))}}</span></div><p class="note">The same player can grade differently by decision horizon. These are position-relative percentile scores, not dollar market values or cross-position price rankings, and are not yet outcome-calibrated forecasts. Model ${{escapeHtml(String(horizon.horizon_model_version || 'unversioned'))}}. Next game is opponent-neutral until a schedule/bye source is available when schedule evidence is missing; a known opponent may add historical defensive context. Dynasty is a market/timeline lens. The career window is shown separately as an internal five-year scenario, not a career-points forecast.</p><p class="brief-card-evidence"><strong>Availability receipt:</strong> ${{escapeHtml(availabilitySource)}} · injury fields are current-only and do not become historical observations.</p><div class="horizon-grid">${{scoreCard('Next game', horizon.next_game_market_score, nextDetail, horizon.next_game_status, horizon.next_game_basis)}}${{scoreCard('Rest of season', horizon.rest_of_season_market_score, rosDetail, horizon.rest_of_season_status, horizon.rest_of_season_basis)}}${{scoreCard('Dynasty market', horizon.dynasty_market_score, dynastyDetail, horizon.dynasty_status, dynastyBasis)}}${{scoreCard('Career window', horizon.career_projection_score, careerDetail, horizon.career_projection_status, horizon.career_projection_basis)}}</div><p class="brief-card-evidence"><strong>Clock shifts:</strong> ${{escapeHtml(clockShiftDetail)}}. Each is later-clock minus earlier-clock; unavailable means one of the two component scores is unavailable.</p><p class="brief-card-evidence"><strong>Clock vs position-market percentile:</strong> ${{escapeHtml(marketDeltaDetail)}}. These are repricing leads, not dollar gaps or proof of mispricing; market value ${{escapeHtml(shown(horizon.market_value))}} remains the cross-position price anchor. <strong>Market evidence:</strong> ${{escapeHtml(marketReceiptDetail)}}.</p><p class="brief-card-evidence"><strong>Contender vs rebuilder:</strong> ${{escapeHtml(fitDetail)}}</p><details class="evidence-drawer"><summary>Outcome evaluation receipt</summary><p class="brief-card-evidence">${{escapeHtml(calibrationDetail)}}</p><p class="note">Outcome evaluation is descriptive rank evidence, not a calibrated probability. Dynasty and career windows require longer longitudinal labels.</p></details><details class="evidence-drawer"><summary>Horizon evidence receipt</summary><p class="brief-card-evidence">${{escapeHtml(String(horizon.evidence || 'player_horizon_market_scores'))}}</p><p class="note"><strong>Score basis:</strong> ${{escapeHtml(String(horizon.horizon_score_basis || 'position-relative percentiles, not dollar market values'))}}</p><p class="note"><strong>Fit basis:</strong> ${{escapeHtml(String(horizon.fit_basis || 'not recorded'))}}</p><p class="note"><strong>Risk:</strong> ${{escapeHtml(String(horizon.risk || 'Inspect the source trace and availability before acting.'))}} · source trace: ${{escapeHtml(String(horizon.source_trace || 'player_horizon_market_scores'))}}</p></details></section>`;
    }}

    function renderPlayerPage(playerId) {{
      const id = String(playerId ?? '');
      const dossierRow = findRow(tables.player_dossiers, 'player_id', id);
      const signal = findRow(tables.player_signal_scores, 'player_id', id);
      const opp = findRow(tables.player_opportunity_scores, 'player_id', id);
      const horizonRows = scopedCurrentRows(tables.player_horizon_market_scores || []).filter(row => String(row.player_id || '') === id);
      const availableHorizon = scopedCurrentRows(tables.available_player_horizon_scores || [])
        .find(row => String(row.player_id || '') === id && ['sleeper_id', 'sleeper_unique_name_match'].includes(String(row.identity_status || '')))
        || {{}};
      const rosterRow = findRow(currentSeasonRoster(), 'player_id', id) || {{}};
      const action = findRow(tables.action_recommendations, 'player_id', id);
      const isAvailableMarket = Boolean(availableHorizon.player_id) && !rosterRow.player_id && !dossierRow.player_id;
      const dossier = dossierRow.player_id
        ? dossierRow
        : isAvailableMarket
          ? {{
              player_id: availableHorizon.player_id,
              player_name: availableHorizon.player_name,
              position: availableHorizon.position,
              age: availableHorizon.age,
              market_value: availableHorizon.market_value,
              projected_ppg: availableHorizon.rest_of_season_ppg || '',
              projection_confidence: availableHorizon.confidence || '',
              injury_status: availableHorizon.injury_status || '',
              availability_scope: 'current_season_snapshot',
              availability_note: availableHorizon.availability_note || '',
              roster_status: 'available_market_research',
              source_trace: availableHorizon.source_trace || 'available_player_horizon_scores'
            }}
          : dossierRow;
      const playerMeta = findRow(tables.players, 'player_id', id);
      const horizon = isAvailableMarket
        ? availableHorizon
        : horizonRows.find(row => !num(dossier.roster_id || signal.roster_id || rosterRow.roster_id) || Number(row.roster_id) === num(dossier.roster_id || signal.roster_id || rosterRow.roster_id)) || horizonRows[0] || {{}};
      const name = dossier.player_name || signal.player_name || rosterRow.player_name || playerMeta.full_name || 'Unknown player';
      const position = dossier.position || signal.position || rosterRow.position || playerMeta.position || '';
      const ownerName = isAvailableMarket ? '' : dossier.team_name || signal.team_name || rosterRow.team_name || '';
      const ownerId = isAvailableMarket ? 0 : num(dossier.roster_id || signal.roster_id || rosterRow.roster_id);
      const inventoryAsset = (tables.team_asset_inventory || []).find(row => Number(row.roster_id) === ownerId && String(row.asset_type || '').toLowerCase() === 'player' && String(row.asset_id || '') === id) || {{}};
      const inventoryMarketAvailable = inventoryAsset.market_value !== undefined && inventoryAsset.market_value !== '';
      const tags = topTags('player', id, 6);
      const newsRows = scopedCurrentLeagueNews().filter(row => String(row.player_id ?? '') === id).slice(0, 6);
      const insight = insightFor('player', id);
      const profileMarketValue = dossier.market_value ?? signal.market_value ?? '';
      const marketValue = inventoryMarketAvailable ? inventoryAsset.market_value : (ownerId ? '' : profileMarketValue);
      const marketTrace = inventoryMarketAvailable ? (inventoryAsset.source_trace || 'team_asset_inventory') : (ownerId ? 'team_asset_inventory' : (dossier.source_trace || signal.source_trace));
      const marketDescriptor = inventoryMarketAvailable
        ? (String(inventoryAsset.source_trace || '') === 'internal_proxy_player_value' ? 'internal proxy value' : 'asset ledger value')
        : isAvailableMarket
          ? 'available-market cross-position anchor'
        : (ownerId ? 'asset ledger value unavailable' : 'profile market value');
      const historyName = dossier.player_name || signal.player_name || rosterRow.player_name || '';
      const normalizedHistoryName = value => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
      const history = (tables.player_transaction_history || []).filter(row => String(row.player_id || '') === id || (!String(row.player_id || '') && normalizedHistoryName(row.player_name) === normalizedHistoryName(historyName))).slice(0, 20);
      const compactTrace = value => String(value || '').split(/[;|]/).map(item => item.trim()).filter(Boolean).map(item => item.replace(/^https?:\\/\\//, '').split('/').slice(0, 2).join('/')).filter(Boolean).slice(0, 3).join(' · ');
      const fullTraces = [...new Set([marketTrace, dossier.source_trace, signal.source_trace, opp.source_trace, ...newsRows.map(row => row.source_trace)].flatMap(value => String(value || '').split(/[;|]/).map(item => item.trim()).filter(Boolean)))];
      const ownerScope = ownerId && Number(app.myRosterId) === ownerId ? 'Your roster' : ownerId ? 'Opponent roster' : 'Unrostered';
      const availabilityScope = String(rosterRow.availability_scope || dossier.availability_scope || '');
      const availabilitySource = availabilityScope === 'current_season_snapshot'
        ? 'Current Sleeper player snapshot'
        : availabilityScope === 'historical_unavailable'
          ? 'Historical availability unavailable by contract'
          : isAvailableMarket
            ? 'Current Sleeper player snapshot'
            : 'Availability scope not recorded';
      const projectionValue = dossier.projected_ppg ?? signal.projected_ppg;
      const projectionRow = Object.assign({{}}, rosterRow || {{}}, signal || {{}}, dossier || {{}});
      const projectionDisplay = projectionValue !== undefined && projectionValue !== ''
        ? projectionPpgText(projectionRow, projectionValue)
        : '';
      const playerEvidence = [
        {{ label: 'Roster context', value: `${{isAvailableMarket ? 'Available-market research' : ownerScope}}${{ownerName ? ` · ${{ownerName}}` : ''}}`, trace: isAvailableMarket ? 'available_player_horizon_scores' : 'verified_roster_scope' }},
        {{ label: 'Availability source', value: availabilitySource, trace: 'roster_players.availability_scope' }},
        {{ label: 'Market', value: marketValue !== '' ? `value ${{marketValue}} (${{marketDescriptor}})` : '', trace: compactTrace(marketTrace) }},
        {{ label: 'Market source', value: inventoryMarketAvailable ? marketDescriptor : 'profile market value unavailable', trace: compactTrace(marketTrace) }},
        {{ label: 'Projection', value: projectionDisplay ? `${{projectionDisplay}} (${{dossier.projection_confidence || signal.projection_confidence || 'confidence unknown'}}); rest-of-season baseline is not recovery-adjusted; ${{dossier.availability_note || 'availability not recorded'}}` : '', trace: compactTrace(dossier.source_trace || signal.source_trace) }},
        {{ label: 'Decision horizons', value: horizon.player_id ? `next ${{horizon.next_game_market_score || 'n/a'}} · rest of season ${{horizon.rest_of_season_market_score || 'n/a'}} · dynasty ${{horizon.dynasty_market_score || 'n/a'}} · career window ${{horizon.career_projection_score || 'n/a'}} · contender fit ${{horizon.contender_fit_score || 'n/a'}} · rebuilder fit ${{horizon.rebuilder_fit_score || 'n/a'}} · market evidence ${{horizon.market_source_count || 'n/a'}} source(s) / ${{horizon.market_source_confidence || 'n/a'}} confidence` : '', trace: compactTrace(horizon.source_trace) }},
        {{ label: 'Opportunity', value: opp.opportunity_score !== undefined && opp.opportunity_score !== '' ? `score ${{opp.opportunity_score}} vs production ${{opp.production_score ?? 'n/a'}}` : '', trace: compactTrace(opp.source_trace) }},
        {{ label: 'Role trend', value: opp.role_trend_score !== undefined && opp.role_trend_score !== '' ? `score ${{opp.role_trend_score}}; fragility ${{opp.fragility_score ?? 'n/a'}}` : '', trace: compactTrace(opp.source_trace) }},
        {{ label: 'League history', value: history.length ? `${{history.length}} recorded transaction${{history.length === 1 ? '' : 's'}} in this bundle` : '', trace: 'player_transaction_history' }},
        {{ label: 'News', value: newsRows.length ? `${{newsRows.length}} mapped news signal${{newsRows.length === 1 ? '' : 's'}}` : '', trace: compactTrace(newsRows[0]?.source_trace) }}
      ].filter(row => row.value);
      if (isAvailableMarket) {{
        playerEvidence.push(
          {{ label: 'Availability boundary', value: 'Current roster absence is inferred from this league snapshot; waiver or free-agent eligibility is not verified here.', trace: compactTrace(availableHorizon.source_trace || 'available_player_horizon_scores') }},
          {{ label: 'Clock coverage', value: `next ${{availableHorizon.next_game_market_score || 'n/a'}} · rest of season ${{availableHorizon.rest_of_season_market_score || 'n/a'}} · dynasty ${{availableHorizon.dynasty_market_score || 'n/a'}} · career window ${{availableHorizon.career_projection_score || 'n/a'}} (${{availableHorizon.fit_coverage || 'n/a'}} available)`, trace: 'available_player_horizon_scores' }}
        );
      }}
      const actionText = action.why || action.action_label || action.consumer_label || '';
      const traceDetails = fullTraces.length ? `<details class="evidence-drawer"><summary>Show full source traces</summary><ul class="article-list">${{fullTraces.map(row => `<li>${{escapeHtml(row)}}</li>`).join('')}}</ul></details>` : '';
      const playerPacket = `<div class="panel article-panel player-decision-packet"><h3>Player dossier</h3><p class="article-p"><strong>Current read:</strong> ${{escapeHtml(insight.headline || insight.one_line_read || `${{name}} is in the evidence room, not a verdict.`)}}</p>${{insight.why_it_matters ? `<p class="article-p"><strong>Why it matters:</strong> ${{escapeHtml(insight.why_it_matters)}}</p>` : ''}}${{insight.what_changed ? `<p class="article-p"><strong>What changed:</strong> ${{escapeHtml(insight.what_changed)}}</p>` : ''}}${{actionText ? `<p class="article-p"><strong>Decision lens:</strong> ${{escapeHtml(actionText)}}</p>` : ''}}${{action.risk || insight.watchouts ? `<p class="note"><strong>Watch:</strong> ${{escapeHtml(action.risk || insight.watchouts)}}</p>` : ''}}${{playerEvidence.length ? `<details class="evidence-drawer" open><summary>Evidence chain</summary><ul class="article-list">${{playerEvidence.map(row => `<li><strong>${{escapeHtml(row.label)}}:</strong> ${{escapeHtml(String(row.value))}}${{row.trace ? ` <span class="note">(${{escapeHtml(row.trace)}})</span>` : ''}}</li>`).join('')}}</ul></details>` : ''}}${{traceDetails}}<p class="note"><strong>Guardrail:</strong> This is a deterministic evidence synthesis with an analyst lens. Confidence ${{escapeHtml(String(action.confidence || insight.confidence || signal.confidence || 'unknown'))}}; inspect the source trace and freshness before acting. It does not imply a trade, waiver claim, or future outcome.</p></div>`;
      if (!name || name === 'Unknown player') {{
        document.getElementById('player-page-body').innerHTML = `${{backLink()}}<p class="note">No data found for this player id. They may be outside the current rostered pool.</p>`;
        return;
      }}
      document.getElementById('player-page-body').innerHTML = `
        ${{backLink()}}
        <div class="entity-header">
          <div class="entity-headshot">${{headshotImg(id, name)}}</div>
          <div>
            <h2>${{escapeHtml(name)}}</h2>
            <div class="brief-card-meta">
              ${{position ? `<span class="brief-chip">${{escapeHtml(position)}}</span>` : ''}}
              ${{dossier.age ? `<span class="brief-chip">age ${{escapeHtml(String(dossier.age))}}</span>` : ''}}
              ${{ownerName ? `<a class="brief-chip entity-link" href="#team-${{ownerId}}">${{escapeHtml(ownerName)}}</a>` : `<span class="brief-chip">${{isAvailableMarket ? 'available-market research' : 'unrostered'}}</span>`}}
              ${{signal.signal_label ? `<span class="brief-chip">${{escapeHtml(label(signal.signal_label))}}</span>` : ''}}
            </div>
            ${{insight.one_line_read ? `<p class="article-p">${{escapeHtml(insight.one_line_read)}}</p>` : ''}}
          </div>
        </div>
        <div class="tile-row">
          ${{entityTile('Market Value', marketValue)}}
          ${{entityTile('Production baseline', projectionDisplay)}}
          ${{entityTile('Availability', dossier.injury_status || (isAvailableMarket ? 'snapshot-unrostered' : 'not flagged'))}}
          ${{entityTile('Opportunity', opp.opportunity_score ?? signal.opportunity_score ?? '', 'score')}}
          ${{entityTile('Production', opp.production_score ?? '', 'score')}}
          ${{entityTile('Usage vs Output', opp.xfp_regression_score ?? signal.xfp_regression_score ?? '', 'score')}}
          ${{entityTile('Role Trend', opp.role_trend_score ?? signal.role_trend_score ?? '', 'score')}}
          ${{entityTile('Fragility', opp.fragility_score ?? signal.fragility_score ?? '', 'score')}}
          ${{entityTile('Breakout', signal.breakout_score ?? '', 'score')}}
          ${{entityTile('Sell', signal.sell_score ?? '', 'score')}}
        </div>
        ${{playerPacket}}
        ${{playerHorizonMarkup(horizon)}}
        ${{isAvailableMarket ? '<p class="note" data-testid="available-player-boundary"><strong>Available-market boundary:</strong> This player is identity-resolved and absent from the selected league roster snapshot. Confirm current waiver/free-agent eligibility and news before acting; this page is research, not a claim receipt.</p>' : ''}}
        ${{tags.length ? `<div class="brief-card-meta">${{tags.map(row => `<span class="brief-chip cat-chip-${{categoryFor('tag', row.tag)}}">${{escapeHtml(row.tag)}}</span>`).join('')}}</div>` : ''}}
        ${{opp.opportunity_evidence ? `<p class="note">Usage: ${{escapeHtml(opp.opportunity_evidence)}} (${{escapeHtml(String(opp.games_sample || 0))}} games sampled)</p>` : ''}}
        ${{newsRows.length ? `<h3>News</h3><div class="brief-list">${{newsRows.map(row => briefCard({{
          title: `${{row.impact_type ? label(row.impact_type) : 'News'}}`,
          category: 'info',
          chips: [row.source, row.published_at],
          evidence: row.evidence || ''
        }})).join('')}}</div>` : ''}}
        ${{history.length ? `<details class="data-drawer"><summary>Transaction history (${{history.length}})</summary>${{table(history, playerHistoryColumns)}}</details>` : ''}}
      `;
    }}

    function renderTeamPage(rosterId) {{
      const rid = Number(rosterId);
      const team = currentSeasonTeams().find(row => Number(row.roster_id) === rid) || findRow(tables.teams, 'roster_id', rid);
      const cycle = (tables.manager_cycle_profiles || []).find(row => Number(row.roster_id) === rid) || {{}};
      const behavior = (tables.manager_behavior_signals || []).find(row => Number(row.roster_id) === rid) || {{}};
      const teamName = team.team_name || team.display_name || cycle.team_name || `Roster ${{rid}}`;
      const tags = topTags('manager', rid, 6);
      const roster = currentSeasonRoster().filter(row => Number(row.roster_id) === rid);
      const dossierByPlayer = rowMap(tables.player_dossiers, 'player_id');
      const rosterCards = roster
        .map(row => ({{ row, market: num((dossierByPlayer.get(String(row.player_id)) || {{}}).market_value) }}))
        .sort((a, b) => b.market - a.market)
        .slice(0, 30);
      const picks = (tables.pick_ownership || []).filter(row => Number(row.current_owner_roster_id) === rid && String(row.round) === '1');
      const inventoryRows = (tables.team_asset_inventory || []).filter(row => Number(row.roster_id) === rid && String(row.asset_type || '').toLowerCase() === 'player');
      const inventoryByPlayer = rowMap(inventoryRows, 'asset_id');
      const needs = (tables.team_needs_matrix || []).find(row => Number(row.roster_id) === rid) || {{}};
      const positionCounts = {{}};
      roster.forEach(row => {{
        const position = String(row.position || 'Unknown');
        positionCounts[position] = (positionCounts[position] || 0) + 1;
      }});
      const constructionDossiers = roster
        .map(row => dossierByPlayer.get(String(row.player_id)) || {{}})
        .filter(row => Object.keys(row).length);
      const marketRows = roster
        .map(row => inventoryByPlayer.get(String(row.player_id)) || {{}})
        .filter(row => Object.keys(row).length && row.market_value !== undefined && row.market_value !== '');
      const marketProxyRows = marketRows.filter(row => String(row.source_trace || '') === 'internal_proxy_player_value');
      const projectionDossiers = constructionDossiers.filter(row => row.projected_ppg !== undefined && row.projected_ppg !== '');
      const marketTotal = marketRows.reduce((total, row) => total + num(row.market_value), 0);
      const projectedPpgTotal = projectionDossiers.reduce((total, row) => total + num(row.projected_ppg), 0);
      const actionRows = (tables.action_recommendations || []).filter(row => Number(row.roster_id) === rid);
      const actionMix = {{}};
      actionRows.forEach(row => {{
        const action = String(row.action_label || row.consumer_label || 'unlabeled');
        actionMix[action] = (actionMix[action] || 0) + 1;
      }});
      const needLanes = [
        ['QB', 'need_qb'],
        ['RB', 'need_rb'],
        ['pass catcher', 'need_pass_catcher'],
        ['picks', 'need_picks']
      ].filter(([, key]) => truthy(needs[key]) || num(needs[key]) > 0).map(([labelText]) => labelText);
      const positionMix = Object.entries(positionCounts).sort(([left], [right]) => left.localeCompare(right)).map(([position, count]) => `${{position}} ${{count}}`).join(' · ') || 'No roster rows';
      const actionMixText = Object.entries(actionMix).sort(([left], [right]) => left.localeCompare(right)).map(([action, count]) => `${{action}} ${{count}}`).join(' · ') || 'No roster-scoped action rows';
      const constructionEvidence = `roster_id=${{rid}}; season=${{app.currentSeason || 'unknown'}}; players=${{roster.length}}; positions=${{positionMix}}; market_rows=${{marketRows.length}}; market_proxy_rows=${{marketProxyRows.length}}; projection_rows=${{projectionDossiers.length}}; action_rows=${{actionRows.length}}; source_tables=roster_players;team_asset_inventory;player_dossiers;team_needs_matrix;action_recommendations`;
      const thesis = (analysis.tradeTheses || []).find(row => Number(row.target_manager_roster_id) === rid) || {{}};
      const edges = (tables.counterparty_trade_edges || []).filter(row => Number(row.target_roster_id) === rid).slice(0, 5);
      const dossier = (analysis.managerDossierItems || []).find(row => Number(row.roster_id) === rid) || {{}};
      const dossierHistory = dossier.season_history || [];
      const trajectory = dossier.trajectory || {{}};
      const trajectoryMarkup = managerTrajectoryMarkup(trajectory, 'manager-trajectory-dossier');
      const transactionTimeline = managerTransactionTimelineMarkup(dossier.transaction_timeline || []);
      const dossierQuestions = dossier.questions_to_ask || [];
      const repeated = dossier.repeated_behavior || {{}};
      const tradePacket = tradePacketMarkup(thesis, 'Trade decision packet');
      const counterpartyInterest = managerCounterpartyInterestMarkup(dossier.counterparty_interest || {{}});
      document.getElementById('team-page-body').innerHTML = `
        ${{backLink()}}
        <div class="entity-header">
          <div>
            <h2>${{escapeHtml(teamName)}}</h2>
            <div class="brief-card-meta">
              ${{cycle.dynasty_cycle ? `<span class="brief-chip cat-chip-${{categoryFor('dynasty_cycle', cycle.dynasty_cycle)}}">${{escapeHtml(label(cycle.dynasty_cycle))}}</span>` : ''}}
              ${{cycle.trade_temperature ? `<span class="brief-chip">${{escapeHtml(cycle.trade_temperature)}}</span>` : ''}}
              ${{cycle.pick_posture ? `<span class="brief-chip">${{escapeHtml(cycle.pick_posture)}}</span>` : ''}}
              ${{tags.map(row => `<span class="brief-chip">${{escapeHtml(row.tag)}}</span>`).join('')}}
            </div>
            ${{cycle.likely_needs ? `<p class="article-p">Likely needs: ${{escapeHtml(cycle.likely_needs)}}</p>` : ''}}
            ${{cycle.likely_sells ? `<p class="article-p">Likely sells: ${{escapeHtml(cycle.likely_sells)}}</p>` : ''}}
          </div>
        </div>
        <div class="panel article-panel team-construction">
          <h3>Team construction</h3>
          <p class="note">Current-season roster snapshot for exact roster ID ${{escapeHtml(String(rid))}}. These are deterministic joins, not a lineup recommendation.</p>
          <div class="tile-row">
            ${{entityTile('Roster Players', roster.length)}}
            ${{entityTile('Market Value', marketRows.length ? Math.round(marketTotal * 100) / 100 : 'n/a')}}
            ${{entityTile('Projected PPG', projectionDossiers.length ? Math.round(projectedPpgTotal * 100) / 100 : 'n/a')}}
            ${{entityTile('Future 1sts', picks.length)}}
          </div>
          <p class="article-p"><strong>Position mix:</strong> ${{escapeHtml(positionMix)}}</p>
          <p class="article-p"><strong>Market coverage:</strong> ${{escapeHtml(`${{marketRows.length}}/${{roster.length}} rows` + (marketProxyRows.length ? ` · ${{marketProxyRows.length}} internal proxy values` : ''))}}</p>
          <p class="article-p"><strong>Need lanes:</strong> ${{escapeHtml(needLanes.join(' · ') || 'No current need lane is marked')}}</p>
          <p class="article-p"><strong>Recommendation mix:</strong> ${{escapeHtml(actionMixText)}}</p>
          <details class="evidence-drawer"><summary>Construction evidence</summary><p class="brief-card-evidence">${{escapeHtml(constructionEvidence)}}</p></details>
        </div>
        <div class="tile-row">
          ${{entityTile('Trade Activity', behavior.trade_activity_score ?? '', 'score')}}
          ${{entityTile('Pick Buyer', behavior.pick_buyer_score ?? '', 'score')}}
          ${{entityTile('Pick Seller', behavior.pick_seller_score ?? '', 'score')}}
          ${{entityTile('FAAB Aggression', behavior.faab_aggression_score ?? '', 'score')}}
          ${{entityTile('Future 1sts Owned', picks.length)}}
        </div>
          ${{dossier.dossier_id ? `<div class="panel article-panel"><h3>Manager dossier</h3><p class="article-p">${{escapeHtml(dossier.analysis_text || '')}}</p><div class="tile-row">${{entityTile('Seasons', dossier.sample_size?.seasons ?? '')}}${{entityTile('Observed Trades', dossier.sample_size?.trades ?? '')}}${{entityTile('Waiver Claims', dossier.sample_size?.waiver_claims ?? '')}}${{entityTile('Observed Events', dossier.sample_size?.observed_events ?? '')}}${{entityTile('Active Seasons', dossier.sample_size?.seasons_with_activity ?? '')}}${{entityTile('Scored Matchups', dossier.outcome_summary?.status === 'not_recorded' ? 'n/a' : (dossier.outcome_summary?.scored_matchups ?? dossier.outcome_summary?.played ?? 0))}}${{entityTile('Outcome record', dossier.outcome_summary?.record || 'not recorded')}}${{entityTile('Roster Assets', dossier.roster_construction?.asset_count ?? '')}}${{entityTile('Market Value', dossier.roster_construction?.market_value_total ?? '')}}</div><p class="note"><strong>Observed behavior:</strong> ${{escapeHtml((dossier.behavior_observations || []).map(row => `${{row.label}}: ${{row.value}}`).join(' · '))}}</p>${{dossier.outcome_summary ? `<p class="note" data-testid="manager-outcome-receipt"><strong>Season outcomes:</strong> ${{escapeHtml(dossier.outcome_summary.narrative || 'Not recorded')}} · ${{escapeHtml(dossier.outcome_summary.evidence || 'outcome evidence not recorded')}}</p>` : ''}}${{trajectoryMarkup}}${{repeated.players_acquired?.length || repeated.players_sold?.length || repeated.trade_partners?.length ? `<details class="evidence-drawer"><summary>Repeated behavior</summary>${{repeated.players_acquired?.length ? `<p class="brief-card-evidence"><strong>Acquired repeatedly:</strong> ${{escapeHtml(repeated.players_acquired.join('; '))}}</p>` : ''}}${{repeated.players_sold?.length ? `<p class="brief-card-evidence"><strong>Sold repeatedly:</strong> ${{escapeHtml(repeated.players_sold.join('; '))}}</p>` : ''}}${{repeated.trade_partners?.length ? `<p class="brief-card-evidence"><strong>Frequent partners:</strong> ${{escapeHtml(repeated.trade_partners.map(row => typeof row === 'string' ? row : `${{row.name}} (${{row.count || 0}})`).join('; '))}}</p>` : ''}}</details>` : ''}}${{dossierHistory.length ? `<details class="evidence-drawer"><summary>Season-by-season history</summary><div class="brief-list">${{dossierHistory.map(row => `<p class="brief-card-evidence"><strong>${{escapeHtml(String(row.season))}}</strong> · ${{escapeHtml(row.team_name || 'historical team name unavailable')}} · ${{escapeHtml(String(row.trades || 0))}} trades · ${{escapeHtml(String(row.waiver_claims || 0))}} waivers${{row.roster_player_count ? ` · ${{escapeHtml(String(row.roster_player_count))}} roster players` : ''}}${{row.active_weeks ? ` · active weeks: ${{escapeHtml(String(row.active_weeks))}}` : ''}}${{row.peak_transaction_week ? ` · peak week: ${{escapeHtml(String(row.peak_transaction_week))}}` : ''}}${{row.trade_partners ? ` · partners: ${{escapeHtml(String(row.trade_partners))}}` : ''}}${{row.outcome_status === 'recorded' ? ` · record ${{escapeHtml(`${{row.wins || 0}}-${{row.losses || 0}}-${{row.ties || 0}}`)}} · ${{escapeHtml(String(row.points_for || 0))}} for / ${{escapeHtml(String(row.points_against || 0))}} against` : row.outcome_status === 'partial' ? ' · matchup outcome partial' : ''}}</p>`).join('')}}</div></details>` : ''}}${{transactionTimeline}}${{managerTradeFitMarkup(dossier)}}${{dossierQuestions.length ? `<details class="evidence-drawer"><summary>Questions worth asking</summary><ul class="article-list">${{dossierQuestions.map(row => `<li>${{escapeHtml(row)}}</li>`).join('')}}</ul></details>` : ''}}<p class="note">${{escapeHtml((dossier.unknowns || []).join(' '))}}</p></div>` : ''}}
        ${{thesis.analysis_text ? `<div class="panel article-panel"><h3>Trade Angle</h3><p class="article-p">${{escapeHtml(thesis.analysis_text)}}</p></div>` : ''}}
        ${{counterpartyInterest}}
        ${{tradePacket}}
        ${{edges.length ? `<h3>Where Values Disagree</h3><div class="brief-list">${{edges.map((row, index) => briefCard({{
          title: `${{row.player_name || 'Unknown'}}`,
          category: categoryFor('edge_type', row.edge_type),
          rank: index + 1,
          playerId: row.player_id,
          entityHash: `player-${{row.player_id}}`,
          chips: [row.edge_type, row.position, row.trade_edge_score ? `edge ${{row.trade_edge_score}}` : '', row.target_team_lens ? `${{row.target_team_lens}} timeline` : '', row.horizon_fit_edge ? `timeline edge ${{row.horizon_fit_edge}}` : '', row.horizon_fit_read ? label(row.horizon_fit_read) : ''],
          evidence: [row.evidence || '', row.horizon_fit_basis || 'timeline fit unavailable'].filter(Boolean).join(' · ')
        }})).join('')}}</div>` : ''}}
        <h3>Roster (by market value)</h3>
        <div class="brief-list">${{rosterCards.map(({{ row, market }}) => briefCard({{
          title: `${{row.player_name}}`,
          category: 'info',
          playerId: row.player_id,
          entityHash: `player-${{row.player_id}}`,
          chips: [row.position, market ? `market ${{market}}` : '', row.roster_status]
        }})).join('')}}</div>
      `;
    }}

    function showSection(sectionId) {{
      let targetId = sectionId;
      // Entity routes: #player-{{sleeperId}} and #team-{{rosterId}} open detail pages rendered
      // on demand from the bundle. Everything else resolves to one of the seven task views.
      const playerMatch = /^player-(.+)$/.exec(String(sectionId || ''));
      const teamMatch = /^team-(\\d+)$/.exec(String(sectionId || ''));
      if (playerMatch) {{
        renderPlayerPage(playerMatch[1]);
        targetId = 'player-page';
      }} else if (teamMatch) {{
        renderTeamPage(Number(teamMatch[1]));
        targetId = 'team-page';
      }} else if (!VIEW_IDS.includes(sectionId)) {{
        targetId = 'view-today';
      }}
      document.querySelectorAll('main > section').forEach(section => {{
        section.hidden = section.id !== targetId;
      }});
      document.querySelectorAll('.side-rail nav a').forEach(link => {{
        link.classList.toggle('active', link.getAttribute('href') === `#${{targetId}}`);
      }});
      state.activeSection = targetId;
      const hashTarget = playerMatch || teamMatch ? sectionId : targetId;
      if (location.hash !== `#${{hashTarget}}`) {{
        history.pushState(null, '', `#${{hashTarget}}`);
      }}
      document.querySelector('main').scrollTop = 0;
      window.scrollTo(0, 0);
    }}

    function setText(id, value) {{
      document.getElementById(id).textContent = String(value);
    }}

    function truthy(value) {{
      return value === true || String(value).toLowerCase() === 'true';
    }}

    function num(value) {{
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    }}

    function unique(values) {{
      return [...new Set(values.filter(value => value !== undefined && value !== null && value !== ''))];
    }}

    function label(value) {{
      if (value === 'ALL') return 'All';
      return String(value).replaceAll('_', ' ').replace(/\\b\\w/g, letter => letter.toUpperCase());
    }}

    const CATEGORY_BUCKETS = {{
      true_buy_low: 'buy', breakout_target: 'buy', we_may_value_more: 'buy', buy_or_watch: 'buy',
      breakout: 'buy', target: 'buy', contender: 'buy', 'pick spender': 'buy', 'veteran buyer': 'buy',
      'breakout candidate': 'buy', 'post-hype sleeper': 'buy', 'emerging role': 'buy', 'injury discount': 'buy',
      scenario_target: 'buy',

      sell_window: 'sell', sell_candidate: 'sell', owner_may_overvalue: 'sell', do_not_chase: 'sell',
      sell: 'sell', rebuild: 'sell', rebuilder: 'sell', 'declining asset': 'sell', 'roster clogger': 'sell',
      'market overheat': 'sell', scenario_sell: 'sell',

      core_hold: 'hold', mutual_fit: 'hold', productive_hold: 'hold', trade: 'hold', transition: 'hold',
      'pick accumulator': 'hold', 'liquidity chip': 'hold', 'franchise cornerstone': 'hold',

      price_check: 'watch', deep_watch: 'watch', monitor: 'watch', missing_projection_watch: 'watch',
      insufficient_signal: 'watch', 'waiver aggressor': 'watch', 'trade grinder': 'watch',
      'depth churner': 'watch', 'hype train': 'watch', scenario_watch: 'watch',

      news: 'info', avoid_noise: 'info', fair_or_unclear: 'info', market_rich: 'info',
      balanced_or_unclear: 'info', 'pass-catcher collector': 'info', 'low-signal manager': 'info',

      pick_alert: 'alert', manager_angle: 'alert', projection_value_gap: 'alert'
    }};

    function categoryFor(sourceHint, rawValue) {{
      const value = String(rawValue || '').toLowerCase();
      return CATEGORY_BUCKETS[value] || 'info';
    }}

    function categoryLabel(bucket) {{
      return {{ buy: 'Buy', sell: 'Sell', hold: 'Hold', watch: 'Watch', info: 'Info', alert: 'Alert' }}[bucket] || 'Info';
    }}

    function playerHeadshotUrl(playerId) {{
      const id = String(playerId || '').trim();
      if (!id) return '';
      return `https://sleepercdn.com/content/nfl/players/thumb/${{encodeURIComponent(id)}}.jpg`;
    }}

    function playerInitials(name) {{
      const parts = String(name || '').trim().split(/\\s+/).filter(Boolean);
      if (!parts.length) return '?';
      return (parts[0][0] + (parts[parts.length - 1][0] || '')).toUpperCase();
    }}

    function headshotImg(playerId, displayName) {{
      const url = playerHeadshotUrl(playerId);
      const initials = escapeHtml(playerInitials(displayName));
      if (!url) return `<div class="headshot-fallback">${{initials}}</div>`;
      return `<img class="headshot-img" src="${{escapeHtml(url)}}" alt="" loading="lazy" onerror="this.outerHTML='<div class=&quot;headshot-fallback&quot;>${{initials}}</div>'">`;
    }}

    function columnField(column) {{
      return typeof column === 'string' ? column : column.field;
    }}

    function columnKind(column) {{
      return typeof column === 'string' ? 'text' : (column.kind || 'text');
    }}

    function columnLabel(column) {{
      return typeof column === 'string' ? label(column) : (column.label || label(column.field));
    }}

    function renderCell(row, column) {{
      const kind = columnKind(column);
      const field = columnField(column);
      const value = row[field];
      if (kind === 'delta') return deltaCell(value);
      if (field === 'projected_fantasy_points') {{
        const display = projectionPointsText(row, value);
        if (kind === 'score') return scoreCell(value, display);
        return formatCell(display);
      }}
      if (field === 'projected_ppg') {{
        const display = projectionPpgText(row, value);
        if (kind === 'score') return scoreCell(value, display);
        return formatCell(display);
      }}
      if (kind === 'score') return scoreCell(value);
      return formatCell(value);
    }}

    function deltaCell(value) {{
      const parsed = Number(value);
      if (!Number.isFinite(parsed) || parsed === 0) return `<span class="delta-cell delta-flat">${{escapeHtml(formatCell(value))}}</span>`;
      const arrow = parsed > 0 ? '\\u25B2' : '\\u25BC';
      const cls = parsed > 0 ? 'delta-up' : 'delta-down';
      return `<span class="delta-cell ${{cls}}">${{arrow}} ${{escapeHtml(String(Math.abs(parsed)))}}</span>`;
    }}

    function scoreCell(value, displayValue) {{
      const parsed = Number(value);
      const score = Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : 0;
      const band = score >= 70 ? 'score-high' : score >= 40 ? 'score-mid' : 'score-low';
      return `<span class="score-tile ${{band}}">${{escapeHtml(formatCell(displayValue === undefined ? value : displayValue))}}</span>`;
    }}

    function formatCell(value) {{
      const text = value === undefined || value === null ? '' : String(value);
      if (text.toLowerCase() === 'true') return '<span class="tag">yes</span>';
      if (text.toLowerCase() === 'false') return '<span class="tag warn">no</span>';
      return escapeHtml(text);
    }}

    function escapeHtml(value) {{
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }}

    init();
  </script>
</body>
</html>
"""
