from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import ANALYSIS_DIR, PROCESSED_DIR, load_config


def build_browser_site(output_dir: Path, processed_dir: Path = PROCESSED_DIR, analysis_dir: Path = ANALYSIS_DIR, league_type: str = "dynasty") -> Path:
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
        "draft_picks": _records(processed_dir / "draft_picks.csv"),
        "refresh_metadata": _records(processed_dir / "refresh_metadata.csv"),
        "player_usage_weekly": _records(processed_dir / "player_usage_weekly.csv"),
        "market_value_sources": _records(processed_dir / "market_value_sources.csv"),
        "market_consensus_values": _records(processed_dir / "market_consensus_values.csv"),
        "player_market_values": _records(processed_dir / "player_market_values.csv"),
        "pick_market_values": _records(processed_dir / "pick_market_values.csv"),
        "team_asset_inventory": _records(processed_dir / "team_asset_inventory.csv"),
        "manager_event_log": _records(processed_dir / "manager_event_log.csv"),
        "team_needs_matrix": _records(processed_dir / "team_needs_matrix.csv"),
        "manager_behavior_signals": _records(processed_dir / "manager_behavior_signals.csv"),
        "manager_valuation_profiles": _records(processed_dir / "manager_valuation_profiles.csv"),
        "liquidity_scores": _records(processed_dir / "liquidity_scores.csv"),
        "asset_market_gaps": _records(processed_dir / "asset_market_gaps.csv"),
        "opportunity_board": _records(processed_dir / "opportunity_board.csv"),
        "counterparty_trade_edges": _records(processed_dir / "counterparty_trade_edges.csv"),
        "source_freshness": _records(processed_dir / "source_freshness.csv"),
        "news_events": _records(processed_dir / "news_events.csv"),
        "player_news_matches": _records(processed_dir / "player_news_matches.csv"),
        "league_news_impact": _records(processed_dir / "league_news_impact.csv"),
        "news_source_freshness": _records(processed_dir / "news_source_freshness.csv"),
        "player_projection_season": _records(processed_dir / "player_projection_season.csv"),
        "player_projection_weekly": _records(processed_dir / "player_projection_weekly.csv"),
        "projection_source_freshness": _records(processed_dir / "projection_source_freshness.csv"),
        "player_signal_scores": _records(processed_dir / "player_signal_scores.csv"),
        "breakout_candidates": _records(processed_dir / "breakout_candidates.csv"),
        "sell_candidates": _records(processed_dir / "sell_candidates.csv"),
        "projection_market_gaps": _records(processed_dir / "projection_market_gaps.csv"),
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
    my_roster = [row for row in tables["roster_players"] if _is_true(row.get("is_my_team"))]
    my_roster_id = int(my_roster[0]["roster_id"]) if my_roster else None
    my_team_name = _my_team_name(tables["teams"], my_roster_id)
    config = load_config()
    analysis = _analysis_artifacts(analysis_dir)
    manifest = _write_data_chunks(data_dir, tables, my_roster_id, my_team_name, config, analysis)
    target = output_dir / "index.html"
    target.write_text(_page(my_team_name, manifest, league_type), encoding="utf-8")
    return target


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_csv(path).fillna("")
    return frame.to_dict(orient="records")


def _analysis_artifacts(analysis_dir: Path) -> dict[str, Any]:
    return {
        "status": "available" if analysis_dir.exists() else "missing",
        "targetTheses": _json_items(analysis_dir / "target_theses.json"),
        "sellTheses": _json_items(analysis_dir / "sell_theses.json"),
        "tradeTheses": _json_items(analysis_dir / "trade_theses.json"),
        "managerDossierItems": _json_items(analysis_dir / "manager_dossiers.json"),
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
        "tradeDeskRead": _text_or_empty(analysis_dir / "trade_desk.md"),
        "tradeDeskReadMode": _front_matter_field(analysis_dir / "trade_desk.md", "model_mode"),
        "managerIntel": _text_or_empty(analysis_dir / "manager_intel.md"),
        "managerIntelMode": _front_matter_field(analysis_dir / "manager_intel.md", "model_mode"),
        "insightCards": _json_items(analysis_dir / "validated_insight_cards.json"),
        "insightValidation": _json_items(analysis_dir / "insight_card_validation.json"),
    }


def _front_matter_field(path: Path, key: str) -> str:
    text = _text_or_empty(path)
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
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


def _write_data_chunks(
    data_dir: Path,
    tables: dict[str, list[dict[str, Any]]],
    my_roster_id: int | None,
    my_team_name: str,
    config: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    audit_only_tables = {
        "players",
        "player_usage_weekly",
        "player_projection_weekly",
    }
    table_counts = {name: len(rows) for name, rows in tables.items()}
    app_tables = {name: rows for name, rows in tables.items() if name not in audit_only_tables}
    app_payload = {
        "tables": app_tables,
        "myRosterId": my_roster_id,
        "myTeamName": my_team_name,
        "strategyProfile": config.get("strategy_profile") or {},
        "trackedPicks": config.get("tracked_picks") or [],
        "currentSeason": config.get("current_season", ""),
        "configuredLeagues": config.get("leagues") or {},
        "analysis": analysis,
        "tableCounts": table_counts,
    }
    (data_dir / "app_bundle.json").write_text(
        json.dumps(app_payload, ensure_ascii=False).replace("</", "<\\/"),
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
        "auditTables": {name: f"data/audit/{name}.json" for name in sorted(audit_only_tables)},
        "tableCounts": table_counts,
        "initialTables": sorted(app_tables),
        "payloadPolicy": "initial_shell_plus_fact_bundle; audit_only_tables_lazy_loaded",
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
      .side-rail {{ position: static; height: auto; }}
      header, main {{ padding-left: 14px; padding-right: 14px; }}
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
        <nav>
          <a href="#view-today">Today</a>
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
        <nav>
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
      <p class="note">Value tags are planned as a strategy overlay. For now this board uses Sleeper roster/player data only.</p>
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
      <h3>Manager Room</h3>
      <p class="note">Manager tags are deterministic reads from observed trades, waivers, FAAB, picks, roster shape, and recency. They estimate tendencies; they do not read minds, sadly. Click a manager card to open their page.</p>
      <div id="manager-grid"></div>
      <div class="grid">
        <div class="panel"><h3>Active Manager Dossier</h3><div id="active-manager-dossier"></div></div>
        <div class="panel"><h3>League Manager Tags</h3><div id="manager-tag-cards"></div></div>
      </div>
      <h3>Manager Cycle Profiles</h3>
      <div id="manager-cycle-table"></div>
      <h3>Manager Tag Evidence</h3>
      <div id="manager-profile-tag-table"></div>
      <div class="panel"><h3>Manager Dossiers</h3><div id="manager-dossiers"></div></div>
    </div>

    <div id="manager-map" class="view-block">
      <h2>Manager Map</h2>
      <div class="grid">
        <div class="panel"><h3>Manager Valuation Profiles</h3><div id="manager-valuation-table"></div></div>
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
          <button id="operator-import" type="button">Import Insight JSON</button>
          <button id="operator-validate" type="button">Validate Insights</button>
          <button id="operator-rebuild" type="button">Rebuild Browser</button>
          <button id="operator-reload" type="button">Reload Latest</button>
          <button id="operator-copy-chat-context" type="button">Copy Chat Context</button>
        </div>
        <p class="note">Update &amp; Write Analysis refreshes the data, then has Claude write one focused article per section (Team Report, Market Watch, Trade Desk Read, Manager Intel) plus the Daily GM Brief, and rebuilds the site (requires ANTHROPIC_API_KEY on the server). Each article falls back to its deterministic version if its own call fails. Copy Chat Context copies clean markdown, ready to paste into any chat, instead of raw JSON.</p>
        <textarea id="operator-insight-json" rows="8" placeholder="Paste Codex/ChatGPT insight JSON here when you want the app to validate and import it."></textarea>
        <div id="operator-status-panel"></div>
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
      analysisScope: 'team',
      analysisConfidence: 'ALL',
      lensPreset: 'Balanced Market',
      lensWeights: {{ market: 25, projection: 25, manager: 20, timeline: 20, news: 10 }},
      operatorToken: '',
      operatorStatus: null
    }};

    const marketLensPresets = {{
      'Balanced Market': {{ market: 25, projection: 25, manager: 20, timeline: 20, news: 10 }},
      'Projection Contrarian': {{ market: 10, projection: 45, manager: 15, timeline: 20, news: 10 }},
      'Counterparty Exploit': {{ market: 15, projection: 20, manager: 40, timeline: 15, news: 10 }},
      'Contender Trade Market': {{ market: 30, projection: 25, manager: 20, timeline: 15, news: 10 }},
      'Rebuild Asset Bank': {{ market: 20, projection: 20, manager: 15, timeline: 35, news: 10 }},
      'News Heat Check': {{ market: 20, projection: 15, manager: 15, timeline: 10, news: 40 }}
    }};

    const rosterColumns = ['player_name', 'position', 'nfl_team', 'roster_status', 'age', 'years_exp'];
    const managerColumns = ['team_name', 'owner_id', 'seasons_covered', 'roster_ids_by_season', 'total_trades', 'future_1sts_acquired', 'future_1sts_sold', 'faab_spent_on_waivers', 'number_of_waiver_claims', 'contender_rebuilder_indicator'];
    const pickColumns = ['pick_season', 'round', 'original_team', 'current_owner', 'previous_owner', 'is_my_original_pick', 'i_currently_own_it'];
    const tradeColumns = ['week', 'created_datetime', 'team_a_name', 'team_a_players_received', 'team_a_picks_received', 'team_a_faab_received', 'team_b_name', 'team_b_players_received', 'team_b_picks_received', 'team_b_faab_received'];
    const waiverColumns = ['week', 'team_name', 'player_added', 'player_dropped', 'waiver_bid', 'status', 'failure_reason'];
    const draftColumns = ['pick_no', 'round', 'roster_id', 'player_name', 'position', 'nfl_team'];
    const marketGapColumns = ['opportunity_type', 'target_team', 'asset_type', 'asset_name', 'position', 'market_value', {{ field: 'market_gap_score', kind: 'delta' }}, 'timeline_fit', 'evidence', 'risk', 'confidence'];
    const counterpartyColumns = ['edge_type', 'target_team', 'player_name', 'position', {{ field: 'our_value_score', kind: 'score' }}, {{ field: 'market_consensus_value', kind: 'score' }}, {{ field: 'estimated_owner_value_score', kind: 'score' }}, {{ field: 'trade_edge_score', kind: 'delta' }}, 'evidence', 'risk', 'confidence'];
    const scenarioColumns = ['scenario_label', 'target_team', 'player_name', 'position', {{ field: 'scenario_score', kind: 'score' }}, 'canonical_model', {{ field: 'market_component', kind: 'score' }}, {{ field: 'projection_component', kind: 'score' }}, {{ field: 'manager_component', kind: 'score' }}, {{ field: 'timeline_component', kind: 'score' }}, {{ field: 'news_component', kind: 'score' }}, 'scenario_warning', 'confidence'];
    const assetLedgerColumns = ['asset_type', 'asset_name', 'position', 'market_value', 'liquidity_tier', 'timeline_fit', 'source_trace'];
    const opportunityColumns = ['action_type', 'target_team', 'asset_in', 'asset_out', 'manager_signal', 'evidence', 'risk', 'confidence', 'source_trace'];
    const marketConsensusColumns = ['player_name', 'position', 'consensus_value', 'source_count', 'disagreement_score', 'best_source', 'confidence', 'source_trace'];
    const managerSignalColumns = ['team_name', {{ field: 'trade_activity_score', kind: 'score' }}, {{ field: 'pick_buyer_score', kind: 'score' }}, {{ field: 'pick_seller_score', kind: 'score' }}, {{ field: 'faab_aggression_score', kind: 'score' }}, {{ field: 'waiver_activity_score', kind: 'score' }}, 'plain_language_label', 'evidence'];
    const managerValuationColumns = ['team_name', 'asset_type', 'position_group', 'preference_score', 'evidence_count', 'confidence', 'label', 'evidence'];
    const managerEventColumns = ['event_type', 'week', 'team_name', 'counterparty', 'players_in', 'picks_in', 'faab_in', 'players_out', 'picks_out', 'faab_out', 'evidence'];
    const sourceColumns = ['source', 'dataset', 'status', 'row_count', 'checked_at', 'source_url', 'cache_path'];
    const newsImpactColumns = ['published_at', 'source', 'player_name', 'team_name', 'impact_type', 'evidence', 'risk', 'confidence', 'source_trace'];
    const newsMatchColumns = ['source', 'input_player_name', 'matched_player_name', 'match_method', 'match_confidence', 'is_ambiguous', 'source_trace'];
    const todayOpportunityColumns = ['opportunity_type', 'target_team', 'asset_name', 'position', 'market_gap_score', 'evidence', 'risk', 'confidence'];
    const todayNewsColumns = ['published_at', 'source', 'player_name', 'team_name', 'impact_type', 'evidence', 'risk', 'confidence'];
    const todayManagerColumns = ['team_name', 'plain_language_label', 'trade_activity_score', 'pick_seller_score', 'faab_aggression_score', 'evidence'];
    const projectionColumns = ['player_name', 'position', 'team', 'team_name', {{ field: 'projected_fantasy_points', kind: 'score' }}, {{ field: 'projected_ppg', kind: 'score' }}, 'projected_games', 'projection_confidence', 'projection_method', 'projection_note'];
    const signalGapColumns = ['player_name', 'position', 'projected_fantasy_points', 'projected_ppg', 'market_value', {{ field: 'gap_score', kind: 'delta' }}, 'gap_label', 'risk', 'confidence', 'evidence'];
    const teamFitColumns = ['team_name', 'player_name', 'position', 'fit_label', {{ field: 'timeline_fit_score', kind: 'score' }}, {{ field: 'need_fit_score', kind: 'score' }}, {{ field: 'liquidity_fit_score', kind: 'score' }}, 'risk', 'confidence', 'evidence'];
    const actionColumns = ['consumer_label', 'player_name', 'position', 'team_name', 'action_score', 'projected_ppg', 'market_value', 'why', 'risk', 'confidence'];
    const managerCycleColumns = ['team_name', 'dynasty_cycle', 'trade_temperature', 'pick_posture', 'waiver_posture', 'likely_needs', 'likely_sells', 'confidence', 'evidence'];
    const profileTagColumns = ['entity_name', 'tag', 'score', 'confidence', 'evidence', 'risk'];
    const playerDossierColumns = ['player_name', 'position', 'team_name', 'roster_status', 'market_value', 'projected_ppg', 'projection_confidence', 'signal_label', 'breakout_score', 'sell_score', 'news_impact', 'transaction_count', 'last_transaction'];
    const playerHistoryColumns = ['player_name', 'event_type', 'season', 'week', 'team_name', 'counterparty', 'direction', 'evidence'];
    async function init() {{
      try {{
        app = await fetchJson(manifest.bundlePath);
      }} catch (error) {{
        document.getElementById('loading-state').textContent = `The Front Office could not load its data bundle: ${{error.message}}`;
        return;
      }}
      tables = app.tables || {{}};
      analysis = app.analysis || {{}};
      state.teamId = Number(app.myRosterId);
      ensureTables();
      populateTeamFilter();
      populateSelect('position-filter', ['ALL', ...unique(tables.roster_players.map(row => row.position)).sort()]);
      populateSelect('status-filter', ['ALL', ...unique(tables.roster_players.map(row => row.roster_status)).sort()]);
      populateSelect('waiver-status-filter', ['ALL', ...unique(tables.waivers.map(row => row.status)).sort()]);
      populateSelect('projection-confidence-filter', ['ALL', ...unique(tables.player_projection_season.map(row => row.projection_confidence)).sort()]);
      populateSelect('signal-label-filter', ['ALL', ...unique(tables.player_signal_scores.map(row => row.signal_label)).sort()]);
      populateSelect('signal-confidence-filter', ['ALL', ...unique(tables.player_signal_scores.map(row => row.confidence)).sort()]);
      populateSelect('analysis-confidence-filter', ['ALL', ...unique([...(analysis.targetTheses || []), ...(analysis.sellTheses || []), ...(analysis.tradeTheses || [])].map(row => row.confidence)).sort()]);
      renderMarketLensPresetButtons();
      bindControls();
      await refreshOperatorStatus();
      document.getElementById('loading-state').hidden = true;
      document.querySelector('main').hidden = false;
      render();
      showSection(location.hash.replace('#', ''));
    }}

    async function fetchJson(path) {{
      const response = await fetch(path, {{ cache: 'no-store' }});
      if (!response.ok) throw new Error(`${{response.status}} ${{response.statusText}}`);
      return response.json();
    }}

    async function refreshOperatorStatus() {{
      try {{
        state.operatorStatus = await fetchJson('/api/operator/status');
      }} catch (error) {{
        state.operatorStatus = {{ state: 'unavailable', message: `Operator API unavailable: ${{error.message}}`, operator_enabled: false }};
      }}
    }}

    async function runOperatorAction(path) {{
      if (!state.operatorToken) {{
        state.operatorStatus = {{ state: 'blocked', message: 'Enter the operator token before running write actions.' }};
        render();
        return;
      }}
      try {{
        const response = await fetch(path, {{
          method: 'POST',
          cache: 'no-store',
          headers: {{ 'X-Front-Office-Token': state.operatorToken }}
        }});
        state.operatorStatus = await response.json();
      }} catch (error) {{
        state.operatorStatus = {{ state: 'failed', message: `Operator action failed: ${{error.message}}` }};
      }}
      render();
      pollOperatorStatus();
    }}

    async function copyChatContext() {{
      const statusEl = document.getElementById('operator-chat-context-status');
      if (!state.operatorToken) {{
        statusEl.textContent = 'Enter the operator token before copying chat context.';
        return;
      }}
      statusEl.textContent = 'Building chat context...';
      try {{
        const response = await fetch('/api/operator/chat-context', {{
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
        state.operatorStatus = {{ state: 'blocked', message: 'Enter the operator token before importing insights.' }};
        render();
        return;
      }}
      let payload = {{}};
      try {{
        payload = JSON.parse(document.getElementById('operator-insight-json').value || '{{}}');
      }} catch (error) {{
        state.operatorStatus = {{ state: 'failed', message: `Insight JSON is invalid: ${{error.message}}` }};
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
          body: JSON.stringify(payload)
        }});
        state.operatorStatus = await response.json();
      }} catch (error) {{
        state.operatorStatus = {{ state: 'failed', message: `Insight import failed: ${{error.message}}` }};
      }}
      render();
      pollOperatorStatus();
    }}

    async function pollOperatorStatus() {{
      for (let index = 0; index < 30; index += 1) {{
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
        'teams', 'players', 'roster_players', 'manager_profiles', 'pick_ownership', 'trades', 'waivers',
        'draft_picks', 'refresh_metadata', 'player_usage_weekly', 'market_value_sources', 'market_consensus_values',
        'player_market_values', 'pick_market_values', 'team_asset_inventory', 'manager_event_log', 'team_needs_matrix', 'manager_behavior_signals',
        'manager_valuation_profiles', 'liquidity_scores', 'asset_market_gaps', 'opportunity_board', 'counterparty_trade_edges', 'source_freshness', 'news_events',
        'player_news_matches', 'league_news_impact', 'news_source_freshness', 'player_projection_season',
        'player_projection_weekly', 'projection_source_freshness', 'player_signal_scores', 'breakout_candidates',
        'sell_candidates', 'projection_market_gaps', 'team_fit_scores', 'action_recommendations',
        'manager_profile_tags', 'manager_cycle_profiles', 'player_dossiers', 'player_transaction_history', 'player_profile_tags'
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
      document.querySelectorAll('.analysis-scope').forEach(button => {{
        button.addEventListener('click', () => {{
          state.analysisScope = button.dataset.analysisScope;
          setActive('.analysis-scope', button);
          render();
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
      document.getElementById('operator-refresh').addEventListener('click', () => runOperatorAction('/api/operator/refresh'));
      document.getElementById('operator-build-packet').addEventListener('click', () => runOperatorAction('/api/operator/build-packet'));
      document.getElementById('operator-generate-insights').addEventListener('click', () => runOperatorAction('/api/operator/generate-insights'));
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

    function playerBrowserCards() {{
      const rows = sortRows(applySearch(tables.player_dossiers), ['market_value']).reverse().slice(0, 24);
      if (!rows.length) return '<p class="note">No player dossiers yet.</p>';
      return `<h3>Top of the Player Pool</h3><div class="brief-list">${{rows.map((row, index) => briefCard({{
        title: row.player_name || 'Unknown',
        category: categoryFor('signal_label', row.signal_label),
        rank: index + 1,
        playerId: row.player_id,
        entityHash: `player-${{row.player_id}}`,
        chips: [row.position, row.team_name, row.market_value ? `market ${{row.market_value}}` : '', row.projected_ppg ? `ppg ${{row.projected_ppg}}` : '']
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
      document.getElementById('analysis-confidence-filter').value = state.analysisConfidence;
      document.querySelectorAll('.pick-filter').forEach(button => button.classList.toggle('active', button.dataset.pickFilter === state.pickFilter));
      document.querySelectorAll('.scope-filter').forEach(button => button.classList.toggle('active', button.dataset.scope === state.tradeScope));
      document.querySelectorAll('.waiver-scope').forEach(button => button.classList.toggle('active', button.dataset.waiverScope === state.waiverScope));
      document.querySelectorAll('.gap-scope').forEach(button => button.classList.toggle('active', button.dataset.gapScope === state.gapScope));
      document.querySelectorAll('.news-scope').forEach(button => button.classList.toggle('active', button.dataset.newsScope === state.newsScope));
      document.querySelectorAll('.projection-scope').forEach(button => button.classList.toggle('active', button.dataset.projectionScope === state.projectionScope));
      document.querySelectorAll('.signal-scope').forEach(button => button.classList.toggle('active', button.dataset.signalScope === state.signalScope));
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
      document.getElementById('strategy-panel').innerHTML = strategyOverlay();
      document.getElementById('likely-traders').innerHTML = table(
        applySearch(tables.manager_profiles.slice().sort((a, b) => Number(b.total_trades) - Number(a.total_trades)).slice(0, 8)),
        managerColumns
      );
      document.getElementById('roster-table').innerHTML = table(sortRows(roster, ['position', 'player_name']), rosterColumns);
      document.getElementById('active-manager-profile').innerHTML = table(
        tables.manager_behavior_signals.filter(row => Number(row.roster_id) === state.teamId),
        managerSignalColumns
      );
      document.getElementById('projection-table').innerHTML = table(filteredProjections(), projectionColumns);
      document.getElementById('signal-breakouts').innerHTML = signalCards(signalBreakoutRows(), 'breakout');
      document.getElementById('signal-sells').innerHTML = signalCards(signalSellRows(), 'sell');
      document.getElementById('signal-gap-table').innerHTML = table(filteredSignalGaps(), signalGapColumns);
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
      document.getElementById('target-theses').innerHTML = thesisCards(filteredTargetTheses(), 'target');
      document.getElementById('sell-theses').innerHTML = thesisCards(filteredSellTheses(), 'sell');
      document.getElementById('trade-theses').innerHTML = thesisCards(filteredTradeTheses(), 'trade');
      document.getElementById('manager-dossiers').innerHTML = markdownBrief(analysis.managerDossiers);
      document.getElementById('news-impact-brief').innerHTML = markdownBrief(analysis.newsImpactBrief);
      document.getElementById('market-gap-table').innerHTML = table(filteredMarketGaps(), marketGapColumns);
      document.getElementById('edge-we-value-more').innerHTML = counterpartyCards(filteredCounterpartyEdges('we_may_value_more').slice(0, 5));
      document.getElementById('edge-owner-overvalues').innerHTML = counterpartyCards(filteredCounterpartyEdges('owner_may_overvalue').slice(0, 5));
      document.getElementById('edge-do-not-chase').innerHTML = counterpartyCards(filteredCounterpartyEdges('do_not_chase').slice(0, 5));
      document.getElementById('edge-mutual-fit').innerHTML = counterpartyCards(filteredCounterpartyEdges('mutual_fit').slice(0, 5));
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
      document.getElementById('manager-cycle-table').innerHTML = table(filteredManagerCycles(), managerCycleColumns);
      document.getElementById('manager-profile-tag-table').innerHTML = table(filteredManagerTags(), profileTagColumns);
      document.getElementById('player-dossier-cards').innerHTML = playerDossierCards(filteredPlayerDossiers().slice(0, 12));
      document.getElementById('player-tag-cards').innerHTML = profileTagCards(filteredPlayerTags().slice(0, 18), true);
      document.getElementById('player-dossier-table').innerHTML = table(filteredPlayerDossiers(), playerDossierColumns);
      document.getElementById('player-transaction-history-table').innerHTML = table(filteredPlayerHistory(), playerHistoryColumns);
      document.getElementById('manager-valuation-table').innerHTML = table(applySearch(tables.manager_valuation_profiles), managerValuationColumns);
      document.getElementById('manager-signal-table').innerHTML = table(applySearch(tables.manager_behavior_signals), managerSignalColumns);
      document.getElementById('manager-event-table').innerHTML = table(
        sortRows(applySearch(tables.manager_event_log.filter(row => Number(row.roster_id) === state.teamId)), ['week']).reverse(),
        managerEventColumns
      );
      document.getElementById('manager-table').innerHTML = table(applySearch(tables.manager_profiles), managerColumns);
      document.getElementById('pick-table').innerHTML = table(filteredPicks(), pickColumns);
      document.getElementById('trade-table').innerHTML = table(filteredTrades(), tradeColumns);
      document.getElementById('waiver-table').innerHTML = table(filteredWaivers(), waiverColumns);
      document.getElementById('operator-status-panel').innerHTML = operatorPanel();
      document.getElementById('diagnostics-panel').innerHTML = diagnostics();
      document.getElementById('draft-table').innerHTML = table(applySearch(tables.draft_picks), draftColumns);
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

    function operatorPanel() {{
      const status = state.operatorStatus || {{ state: 'unknown', message: 'Operator status has not loaded yet.' }};
      const rows = [
        {{ item: 'State', value: status.state || 'unknown' }},
        {{ item: 'Job', value: status.job || 'none' }},
        {{ item: 'Message', value: status.message || '' }},
        {{ item: 'Updated at', value: status.updated_at || status.generated_at || '' }},
        {{ item: 'Operator enabled', value: status.operator_enabled ? 'yes' : 'no token configured' }},
        {{ item: 'Packet path', value: status.packet_path || '' }},
        {{ item: 'Output path', value: status.output_path || '' }},
        {{ item: 'Validated path', value: status.validated_path || '' }},
        {{ item: 'Evidence count', value: status.evidence_count || '' }}
      ];
      const validation = status.validation || {{}};
      const errors = validation.errors || status.errors || [];
      return table(rows, ['item', 'value']) + (errors.length
        ? `<details class="evidence-drawer" open><summary>Validation Errors</summary><div class="brief-card-evidence">${{escapeHtml(errors.join('; '))}}</div></details>`
        : '<p class="note">No operator validation errors reported.</p>');
    }}

    function filteredNewsImpact() {{
      let rows = tables.league_news_impact.slice();
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
      const teamPlayerNames = new Set(filteredPlayerDossiers().map(row => String(row.player_name)));
      let rows = tables.player_transaction_history.filter(row => teamPlayerNames.has(String(row.player_name)));
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
      const currentSeason = String(app.currentSeason || '');
      const current = tables.teams.filter(row => String(row.season || '') === currentSeason);
      return current.length ? current : latestRowsByRoster(tables.teams);
    }}

    function currentSeasonRoster() {{
      const currentSeason = String(app.currentSeason || '');
      const current = tables.roster_players.filter(row => String(row.season || '') === currentSeason);
      return current.length ? current : tables.roster_players;
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

    function strategyOverlay() {{
      const profile = app.strategyProfile || {{}};
      const tracked = app.trackedPicks || [];
      return list([
        `Profile: ${{profile.name || 'Generic Sleeper team analysis'}}`,
        `Direction: ${{profile.team_direction || 'not configured'}}`,
        `Window: ${{profile.contention_window || 'not configured'}}`,
        `Tracked picks: ${{tracked.length}}`
      ]);
    }}

    function diagnostics() {{
      const metadata = (tables.refresh_metadata || [])[0] || {{}};
      const leagueIds = metadata.configured_league_ids || Object.values(app.configuredLeagues || {{}}).filter(Boolean).join(';');
      const counts = app.tableCounts || manifest.tableCounts || {{}};
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
        {{ item: 'Signal score rows', value: tables.player_signal_scores.length }},
        {{ item: 'Action recommendation rows', value: tables.action_recommendations.length }},
        {{ item: 'Manager valuation profile rows', value: metadata.manager_valuation_profile_rows || tables.manager_valuation_profiles.length }},
        {{ item: 'Counterparty edge rows', value: metadata.counterparty_edge_rows || tables.counterparty_trade_edges.length }},
        {{ item: 'Manager profile tag rows', value: metadata.manager_profile_tag_rows || tables.manager_profile_tags.length }},
        {{ item: 'Manager cycle rows', value: tables.manager_cycle_profiles.length }},
        {{ item: 'Player dossier rows', value: metadata.player_dossier_rows || tables.player_dossiers.length }},
        {{ item: 'Player profile tag rows', value: metadata.player_profile_tag_rows || tables.player_profile_tags.length }},
        {{ item: 'Breakout candidate rows', value: tables.breakout_candidates.length }},
        {{ item: 'Sell candidate rows', value: tables.sell_candidates.length }},
        {{ item: 'Analysis artifacts', value: metadata.analysis_artifacts_status || analysis.status || 'missing' }},
        {{ item: 'Analysis generated at', value: metadata.analysis_generated_at || 'unknown' }},
        {{ item: 'Analysis context packets', value: metadata.analysis_context_packet_count || (analysis.contextPackets || []).length }},
        {{ item: 'Target thesis rows', value: metadata.target_thesis_count || (analysis.targetTheses || []).length }},
        {{ item: 'Sell thesis rows', value: metadata.sell_thesis_count || (analysis.sellTheses || []).length }},
        {{ item: 'Trade thesis rows', value: metadata.trade_thesis_count || (analysis.tradeTheses || []).length }},
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
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: `${{row.evidence || 'No evidence provided.'}} Risk: ${{row.risk || ''}}`
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

    function thesisCards(rows, mode) {{
      if (!rows.length) return `<p class="note">No ${{mode}} theses found for this scope.</p>`;
      const bucket = categoryFor('mode', mode);
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: row.player_name || row.target_manager_name || row.thesis_id || 'Analysis thesis',
        category: categoryFor('signal_label', row.signal_label) !== 'info' ? categoryFor('signal_label', row.signal_label) : bucket,
        playerId: row.player_id,
        chips: [
          mode,
          row.position,
          row.signal_label || row.approach_type,
          row.confidence ? `confidence ${{row.confidence}}` : '',
          row.risk ? `risk ${{row.risk}}` : ''
        ],
        evidence: `${{row.analysis_text || ''}} Evidence: ${{row.evidence || ''}} Source: ${{row.source_trace || ''}}`
      }})).join('')}}</div>`;
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
      const flushPara = () => {{ if (para.length) {{ parts.push(`<p class="article-p">${{escapeHtml(para.join(' '))}}</p>`); para = []; }} }};
      const flushList = () => {{ if (list.length) {{ parts.push(`<ul class="article-list">${{list.map(item => `<li>${{escapeHtml(item)}}</li>`).join('')}}</ul>`); list = []; }} }};
      for (const raw of body.split('\\n')) {{
        const line = raw.trim();
        if (!line) {{ flushPara(); flushList(); continue; }}
        if (line.startsWith('# ') && !line.startsWith('## ')) {{ continue; }}
        if (line.startsWith('## ')) {{ flushPara(); flushList(); parts.push(`<h4 class="article-h">${{escapeHtml(line.replace(/^##\\s*/, ''))}}</h4>`); continue; }}
        if (line.startsWith('- ')) {{ flushPara(); list.push(line.replace(/^-\\s*/, '')); continue; }}
        flushList(); para.push(line);
      }}
      flushPara(); flushList();
      return `<div class="article-body">${{parts.join('')}}</div>`;
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

    function activeManagerDossier() {{
      const cycle = tables.manager_cycle_profiles.find(row => Number(row.roster_id) === state.teamId) || {{}};
      const tags = topTags('manager', state.teamId, 5);
      const insight = insightFor('manager', state.teamId);
      if (!cycle.team_name && !tags.length) return '<p class="note">No manager profile found.</p>';
      return briefCard({{
        title: insight.headline || cycle.team_name || activeTeamName(),
        category: categoryFor('dynasty_cycle', cycle.dynasty_cycle),
        chips: [
          cycle.dynasty_cycle,
          cycle.trade_temperature,
          cycle.pick_posture,
          cycle.waiver_posture,
          ...tags.map(row => row.tag),
          cycle.confidence ? `confidence ${{cycle.confidence}}` : ''
        ],
        summary: insight.one_line_read || `Likely needs: ${{cycle.likely_needs || 'unclear'}}. Likely sells: ${{cycle.likely_sells || 'unclear'}}.`,
        watchouts: insight.watchouts || 'Treat this as a tendency estimate, not manager intent.',
        evidence: `${{cycle.evidence || ''}} Tags: ${{tags.map(row => `${{row.tag}} (${{row.score}})`).join(', ') || 'none'}}. Likely needs: ${{cycle.likely_needs || 'unclear'}}. Likely sells: ${{cycle.likely_sells || 'unclear'}}.`
      }});
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
          row.projected_ppg ? `ppg ${{row.projected_ppg}}` : '',
          row.projection_confidence ? `projection ${{row.projection_confidence}}` : '',
          ...(topTags('player', row.player_id, 4).map(tag => tag.tag))
        ],
        summary: insightFor('player', row.player_id).one_line_read || `Signal: ${{row.signal_label || 'none'}}. News: ${{row.news_impact || 'none'}}.`,
        watchouts: insightFor('player', row.player_id).watchouts || 'Player tags are prompts for review, not outcome guarantees.',
        evidence: `Market: ${{row.market_value || 'unknown'}}. PPG: ${{row.projected_ppg || 'unknown'}}. League transactions: ${{row.transaction_count || 0}}. Last transaction: ${{row.last_transaction || 'none'}}.`
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
      tables.league_news_impact.forEach(row => {{
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

    function briefCard(card) {{
      const bucket = card.category || 'info';
      const rankNum = Number(card.rank);
      const rank = card.rank && Number.isFinite(rankNum) ? rankNum : null;
      const playerId = card.playerId || null;

      const chips = (card.chips || []).filter(value => value !== undefined && value !== null && String(value) !== '' && String(value) !== '0');
      const summary = card.summary || card.oneLine || '';
      const watchouts = card.watchouts ? `<div class="brief-card-evidence"><strong>Watch:</strong> ${{escapeHtml(card.watchouts)}}</div>` : '';
      const details = card.details || card.evidence || '';

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
      'view-today', 'view-my-team', 'view-players', 'view-league',
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

    function backLink() {{
      return '<a class="back-link" href="javascript:history.back()">&larr; back</a>';
    }}

    function renderPlayerPage(playerId) {{
      const id = String(playerId ?? '');
      const dossier = findRow(tables.player_dossiers, 'player_id', id);
      const signal = findRow(tables.player_signal_scores, 'player_id', id);
      const opp = findRow(tables.player_opportunity_scores, 'player_id', id);
      const rosterRow = findRow(currentSeasonRoster(), 'player_id', id) || {{}};
      const action = findRow(tables.action_recommendations, 'player_id', id);
      const name = dossier.player_name || signal.player_name || rosterRow.player_name || 'Unknown player';
      const position = dossier.position || signal.position || rosterRow.position || '';
      const ownerName = dossier.team_name || signal.team_name || rosterRow.team_name || '';
      const ownerId = num(dossier.roster_id || signal.roster_id || rosterRow.roster_id);
      const tags = topTags('player', id, 6);
      const newsRows = (tables.league_news_impact || []).filter(row => String(row.player_id ?? '') === id).slice(0, 6);
      const history = findRows(tables.player_transaction_history, 'player_id', id).slice(0, 20);
      const insight = insightFor('player', id);
      const marketValue = dossier.market_value ?? signal.market_value ?? '';
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
              ${{ownerName ? `<a class="brief-chip entity-link" href="#team-${{ownerId}}">${{escapeHtml(ownerName)}}</a>` : '<span class="brief-chip">unrostered</span>'}}
              ${{signal.signal_label ? `<span class="brief-chip">${{escapeHtml(label(signal.signal_label))}}</span>` : ''}}
            </div>
            ${{insight.one_line_read ? `<p class="article-p">${{escapeHtml(insight.one_line_read)}}</p>` : ''}}
          </div>
        </div>
        <div class="tile-row">
          ${{entityTile('Market Value', marketValue)}}
          ${{entityTile('Projected PPG', dossier.projected_ppg ?? signal.projected_ppg ?? '')}}
          ${{entityTile('Opportunity', opp.opportunity_score ?? signal.opportunity_score ?? '', 'score')}}
          ${{entityTile('Production', opp.production_score ?? '', 'score')}}
          ${{entityTile('Usage vs Output', opp.xfp_regression_score ?? signal.xfp_regression_score ?? '', 'score')}}
          ${{entityTile('Role Trend', opp.role_trend_score ?? signal.role_trend_score ?? '', 'score')}}
          ${{entityTile('Fragility', opp.fragility_score ?? signal.fragility_score ?? '', 'score')}}
          ${{entityTile('Breakout', signal.breakout_score ?? '', 'score')}}
          ${{entityTile('Sell', signal.sell_score ?? '', 'score')}}
        </div>
        ${{tags.length ? `<div class="brief-card-meta">${{tags.map(row => `<span class="brief-chip cat-chip-${{categoryFor('tag', row.tag)}}">${{escapeHtml(row.tag)}}</span>`).join('')}}</div>` : ''}}
        ${{action.why ? `<div class="panel article-panel"><h3>${{escapeHtml(action.consumer_label || 'Read')}}</h3><p class="article-p">${{escapeHtml(action.why)}}</p><p class="note">${{escapeHtml(action.risk || '')}}</p></div>` : ''}}
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
      const thesis = (analysis.tradeTheses || []).find(row => Number(row.target_manager_roster_id) === rid) || {{}};
      const edges = (tables.counterparty_trade_edges || []).filter(row => Number(row.target_roster_id) === rid).slice(0, 5);
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
        <div class="tile-row">
          ${{entityTile('Trade Activity', behavior.trade_activity_score ?? '', 'score')}}
          ${{entityTile('Pick Buyer', behavior.pick_buyer_score ?? '', 'score')}}
          ${{entityTile('Pick Seller', behavior.pick_seller_score ?? '', 'score')}}
          ${{entityTile('FAAB Aggression', behavior.faab_aggression_score ?? '', 'score')}}
          ${{entityTile('Future 1sts Owned', picks.length)}}
        </div>
        ${{thesis.analysis_text ? `<div class="panel article-panel"><h3>Trade Angle</h3><p class="article-p">${{escapeHtml(thesis.analysis_text)}}</p></div>` : ''}}
        ${{edges.length ? `<h3>Where Values Disagree</h3><div class="brief-list">${{edges.map((row, index) => briefCard({{
          title: `${{row.player_name || 'Unknown'}}`,
          category: categoryFor('edge_type', row.edge_type),
          rank: index + 1,
          playerId: row.player_id,
          entityHash: `player-${{row.player_id}}`,
          chips: [row.edge_type, row.position, row.trade_edge_score ? `edge ${{row.trade_edge_score}}` : ''],
          evidence: row.evidence || ''
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
      const value = row[columnField(column)];
      if (kind === 'delta') return deltaCell(value);
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

    function scoreCell(value) {{
      const parsed = Number(value);
      const score = Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : 0;
      const band = score >= 70 ? 'score-high' : score >= 40 ? 'score-mid' : 'score-low';
      return `<span class="score-tile ${{band}}">${{escapeHtml(formatCell(value))}}</span>`;
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
