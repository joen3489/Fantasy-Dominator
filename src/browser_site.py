from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import PROCESSED_DIR, load_config


def build_browser_site(output_dir: Path, processed_dir: Path = PROCESSED_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
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
        "player_market_values": _records(processed_dir / "player_market_values.csv"),
        "pick_market_values": _records(processed_dir / "pick_market_values.csv"),
        "team_asset_inventory": _records(processed_dir / "team_asset_inventory.csv"),
        "manager_event_log": _records(processed_dir / "manager_event_log.csv"),
        "team_needs_matrix": _records(processed_dir / "team_needs_matrix.csv"),
        "manager_behavior_signals": _records(processed_dir / "manager_behavior_signals.csv"),
        "liquidity_scores": _records(processed_dir / "liquidity_scores.csv"),
        "asset_market_gaps": _records(processed_dir / "asset_market_gaps.csv"),
        "opportunity_board": _records(processed_dir / "opportunity_board.csv"),
        "source_freshness": _records(processed_dir / "source_freshness.csv"),
        "news_events": _records(processed_dir / "news_events.csv"),
        "player_news_matches": _records(processed_dir / "player_news_matches.csv"),
        "league_news_impact": _records(processed_dir / "league_news_impact.csv"),
        "news_source_freshness": _records(processed_dir / "news_source_freshness.csv"),
        "player_projection_season": _records(processed_dir / "player_projection_season.csv"),
        "player_projection_weekly": _records(processed_dir / "player_projection_weekly.csv"),
        "projection_source_freshness": _records(processed_dir / "projection_source_freshness.csv"),
    }
    my_roster = [row for row in tables["roster_players"] if _is_true(row.get("is_my_team"))]
    my_roster_id = int(my_roster[0]["roster_id"]) if my_roster else None
    my_team_name = _my_team_name(tables["teams"], my_roster_id)
    config = load_config()
    target = output_dir / "index.html"
    target.write_text(_page(tables, my_roster_id, my_team_name, config), encoding="utf-8")
    return target


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_csv(path).fillna("")
    return frame.to_dict(orient="records")


def _is_true(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _my_team_name(teams: list[dict[str, Any]], my_roster_id: int | None) -> str:
    for team in teams:
        if my_roster_id is not None and int(team.get("roster_id", -1)) == my_roster_id:
            return str(team.get("team_name", "Unknown team"))
    return "Unknown team"


def _page(
    tables: dict[str, list[dict[str, Any]]],
    my_roster_id: int | None,
    my_team_name: str,
    config: dict[str, Any],
) -> str:
    data_json = json.dumps(
        {
            "tables": tables,
            "myRosterId": my_roster_id,
            "myTeamName": my_team_name,
            "strategyProfile": config.get("strategy_profile") or {},
            "trackedPicks": config.get("tracked_picks") or [],
            "currentSeason": config.get("current_season", ""),
            "configuredLeagues": config.get("leagues") or {},
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sleeper Dynasty Data</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f3;
      --panel: #ffffff;
      --ink: #15171a;
      --muted: #626a73;
      --line: #d8ddd2;
      --accent: #116149;
      --accent-2: #9b3d2e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }}
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
    nav {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 12px 28px;
      border-bottom: 1px solid var(--line);
      background: #eef1e9;
      position: sticky;
      top: 72px;
      z-index: 2;
    }}
    nav a, button, select, input {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      font: inherit;
      font-size: 14px;
    }}
    nav a {{
      color: var(--ink);
      text-decoration: none;
      padding: 8px 10px;
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
    .brief-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcf8;
      padding: 11px 12px;
      display: grid;
      gap: 7px;
    }}
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
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: #34403b; background: #f1f3ed; font-weight: 700; position: sticky; top: 0; }}
    .table-wrap {{ overflow: auto; max-height: 520px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); }}
    .tag {{ display: inline-block; color: #fff; background: var(--accent); border-radius: 4px; padding: 2px 6px; font-size: 12px; }}
    .warn {{ background: var(--accent-2); }}
    .note {{ color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .list {{ margin: 0; padding-left: 20px; font-size: 13px; }}
    @media (max-width: 720px) {{
      header, nav, main {{ padding-left: 14px; padding-right: 14px; }}
      nav {{ position: static; }}
      .grid {{ grid-template-columns: 1fr; }}
      th {{ position: static; }}
      select, input {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Sleeper Dynasty Data</h1>
    <p><span id="active-team-label">{escape(my_team_name)}</span> weekly command surface. Data refresh is read-only.</p>
  </header>
  <nav>
    <a href="#todays-board">Today's Board</a>
    <a href="#decision-board">Decision Board</a>
    <a href="#team-overview">Team Overview</a>
    <a href="#roster-value">Roster Value</a>
    <a href="#projection-board">Projection Board</a>
    <a href="#market-gaps">Market Gaps</a>
    <a href="#asset-ledger">Asset Ledger</a>
    <a href="#opportunity-board">Opportunity Board</a>
    <a href="#news-desk">News Desk</a>
    <a href="#manager-map">Manager Map</a>
    <a href="#manager-behavior">Manager Behavior</a>
    <a href="#pick-ledger">Pick Ledger</a>
    <a href="#trade-market">Trade Market</a>
    <a href="#waiver-market">Waiver Market</a>
    <a href="#diagnostics">Diagnostics</a>
    <a href="#draft">Draft</a>
  </nav>
  <main>
    <section id="todays-board">
      <h2>Today's Board</h2>
      <div class="grid">
        <div class="panel"><h3>Buy-Low Targets</h3><div id="today-buy-low"></div></div>
        <div class="panel"><h3>Sell Windows</h3><div id="today-sell-window"></div></div>
        <div class="panel"><h3>My Roster News</h3><div id="today-my-news"></div></div>
        <div class="panel"><h3>Trade Target News</h3><div id="today-target-news"></div></div>
        <div class="panel"><h3>Pick Alerts</h3><div id="today-pick-alerts"></div></div>
        <div class="panel"><h3>Manager Angles</h3><div id="today-manager-angles"></div></div>
      </div>
    </section>

    <section id="decision-board">
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
    </section>

    <section id="team-overview">
      <h2>Team Overview</h2>
      <div class="grid">
        <div class="panel"><h3>Active Team Profile</h3><div id="team-overview-panel"></div></div>
        <div class="panel"><h3>Strategy Overlay</h3><div id="strategy-panel"></div></div>
      </div>
    </section>

    <section id="roster-value">
      <h2>Roster Value Board</h2>
      <div class="controls">
        <label>Position<select id="position-filter"></select></label>
        <label>Status<select id="status-filter"></select></label>
      </div>
      <p class="note">Value tags are planned as a strategy overlay. For now this board uses Sleeper roster/player data only.</p>
      <div id="roster-table"></div>
    </section>

    <section id="projection-board">
      <h2>Projection Board</h2>
      <div class="controls">
        <button class="projection-scope active" data-projection-scope="team" type="button">Active Team</button>
        <button class="projection-scope" data-projection-scope="league" type="button">League</button>
        <label>Confidence<select id="projection-confidence-filter"></select></label>
      </div>
      <div id="projection-table"></div>
    </section>

    <section id="market-gaps">
      <h2>Market Gaps</h2>
      <div class="controls">
        <button class="gap-scope active" data-gap-scope="targets" type="button">Targets</button>
        <button class="gap-scope" data-gap-scope="team" type="button">My Assets</button>
        <button class="gap-scope" data-gap-scope="league" type="button">League</button>
      </div>
      <div id="market-gap-table"></div>
    </section>

    <section id="asset-ledger">
      <h2>Asset Ledger</h2>
      <div id="asset-ledger-table"></div>
    </section>

    <section id="opportunity-board">
      <h2>Opportunity Board</h2>
      <div id="opportunity-table"></div>
    </section>

    <section id="news-desk">
      <h2>News Desk</h2>
      <div class="controls">
        <button class="news-scope active" data-news-scope="league-impact" type="button">League Impact</button>
        <button class="news-scope" data-news-scope="watchlist" type="button">Watchlist / Waiver</button>
        <button class="news-scope" data-news-scope="unmatched" type="button">Unmatched Feed Items</button>
      </div>
      <div id="news-impact-table"></div>
      <h3>Player News Matches</h3>
      <div id="news-match-table"></div>
    </section>

    <section id="manager-map">
      <h2>Manager Map</h2>
      <div class="grid">
        <div class="panel"><h3>Behavior Signals</h3><div id="manager-signal-table"></div></div>
        <div class="panel"><h3>Manager Event Log</h3><div id="manager-event-table"></div></div>
      </div>
    </section>

    <section id="manager-behavior">
      <h2>Manager Behavior</h2>
      <div id="active-manager-profile"></div>
      <h3>League Manager Profiles</h3>
      <div id="manager-table"></div>
    </section>

    <section id="pick-ledger">
      <h2>Pick Ledger</h2>
      <div class="controls">
        <button class="pick-filter active" data-pick-filter="all" type="button">All Picks</button>
        <button class="pick-filter" data-pick-filter="my-original-away" type="button">My Original Elsewhere</button>
        <button class="pick-filter" data-pick-filter="currently-owned" type="button">Currently Owned</button>
        <button class="pick-filter" data-pick-filter="active-original" type="button">Active Team Original</button>
      </div>
      <div id="pick-table"></div>
    </section>

    <section id="trade-market">
      <h2>Trade Market</h2>
      <div class="controls">
        <button class="scope-filter active" data-scope="team" type="button">Active Team</button>
        <button class="scope-filter" data-scope="league" type="button">League</button>
      </div>
      <div id="trade-table"></div>
    </section>

    <section id="waiver-market">
      <h2>Waiver Market</h2>
      <div class="controls">
        <button class="waiver-scope active" data-waiver-scope="team" type="button">Active Team</button>
        <button class="waiver-scope" data-waiver-scope="league" type="button">League</button>
        <label>Status<select id="waiver-status-filter"></select></label>
      </div>
      <div id="waiver-table"></div>
    </section>

    <section id="diagnostics">
      <h2>Data Diagnostics</h2>
      <div id="diagnostics-panel"></div>
    </section>

    <section id="draft"><h2>Draft Results</h2><div id="draft-table"></div></section>
  </main>
  <script id="app-data" type="application/json">{data_json}</script>
  <script>
    const app = JSON.parse(document.getElementById('app-data').textContent);
    const tables = app.tables;
    const state = {{
      teamId: Number(app.myRosterId),
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
      projectionConfidence: 'ALL'
    }};

    const rosterColumns = ['player_name', 'position', 'nfl_team', 'roster_status', 'age', 'years_exp'];
    const managerColumns = ['team_name', 'total_trades', 'future_1sts_acquired', 'future_1sts_sold', 'faab_spent_on_waivers', 'number_of_waiver_claims', 'contender_rebuilder_indicator'];
    const pickColumns = ['pick_season', 'round', 'original_team', 'current_owner', 'previous_owner', 'is_my_original_pick', 'i_currently_own_it'];
    const tradeColumns = ['week', 'created_datetime', 'team_a_name', 'team_a_players_received', 'team_a_picks_received', 'team_a_faab_received', 'team_b_name', 'team_b_players_received', 'team_b_picks_received', 'team_b_faab_received'];
    const waiverColumns = ['week', 'team_name', 'player_added', 'player_dropped', 'waiver_bid', 'status', 'failure_reason'];
    const draftColumns = ['pick_no', 'round', 'roster_id', 'player_name', 'position', 'nfl_team'];
    const marketGapColumns = ['opportunity_type', 'target_team', 'asset_type', 'asset_name', 'position', 'market_value', 'market_gap_score', 'timeline_fit', 'evidence', 'risk', 'confidence'];
    const assetLedgerColumns = ['asset_type', 'asset_name', 'position', 'market_value', 'liquidity_tier', 'timeline_fit', 'source_trace'];
    const opportunityColumns = ['action_type', 'target_team', 'asset_in', 'asset_out', 'manager_signal', 'evidence', 'risk', 'confidence', 'source_trace'];
    const managerSignalColumns = ['team_name', 'trade_activity_score', 'pick_buyer_score', 'pick_seller_score', 'faab_aggression_score', 'waiver_activity_score', 'plain_language_label', 'evidence'];
    const managerEventColumns = ['event_type', 'week', 'team_name', 'counterparty', 'players_in', 'picks_in', 'faab_in', 'players_out', 'picks_out', 'faab_out', 'evidence'];
    const sourceColumns = ['source', 'dataset', 'status', 'row_count', 'checked_at', 'source_url', 'cache_path'];
    const newsImpactColumns = ['published_at', 'source', 'player_name', 'team_name', 'impact_type', 'evidence', 'risk', 'confidence', 'source_trace'];
    const newsMatchColumns = ['source', 'input_player_name', 'matched_player_name', 'match_method', 'match_confidence', 'is_ambiguous', 'source_trace'];
    const todayOpportunityColumns = ['opportunity_type', 'target_team', 'asset_name', 'position', 'market_gap_score', 'evidence', 'risk', 'confidence'];
    const todayNewsColumns = ['published_at', 'source', 'player_name', 'team_name', 'impact_type', 'evidence', 'risk', 'confidence'];
    const todayManagerColumns = ['team_name', 'plain_language_label', 'trade_activity_score', 'pick_seller_score', 'faab_aggression_score', 'evidence'];
    const projectionColumns = ['player_name', 'position', 'team', 'team_name', 'projected_fantasy_points', 'projected_ppg', 'projected_games', 'projection_confidence', 'projection_method', 'projection_note'];

    function init() {{
      populateTeamFilter();
      populateSelect('position-filter', ['ALL', ...unique(tables.roster_players.map(row => row.position)).sort()]);
      populateSelect('status-filter', ['ALL', ...unique(tables.roster_players.map(row => row.roster_status)).sort()]);
      populateSelect('waiver-status-filter', ['ALL', ...unique(tables.waivers.map(row => row.status)).sort()]);
      populateSelect('projection-confidence-filter', ['ALL', ...unique(tables.player_projection_season.map(row => row.projection_confidence)).sort()]);
      bindControls();
      render();
    }}

    function populateTeamFilter() {{
      const select = document.getElementById('team-filter');
      select.innerHTML = tables.teams
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
    }}

    function syncControls() {{
      document.getElementById('team-filter').value = String(state.teamId);
      document.getElementById('global-search').value = state.query;
      document.getElementById('position-filter').value = state.position;
      document.getElementById('status-filter').value = state.status;
      document.getElementById('waiver-status-filter').value = state.waiverStatus;
      document.getElementById('projection-confidence-filter').value = state.projectionConfidence;
      document.querySelectorAll('.pick-filter').forEach(button => button.classList.toggle('active', button.dataset.pickFilter === state.pickFilter));
      document.querySelectorAll('.scope-filter').forEach(button => button.classList.toggle('active', button.dataset.scope === state.tradeScope));
      document.querySelectorAll('.waiver-scope').forEach(button => button.classList.toggle('active', button.dataset.waiverScope === state.waiverScope));
      document.querySelectorAll('.gap-scope').forEach(button => button.classList.toggle('active', button.dataset.gapScope === state.gapScope));
      document.querySelectorAll('.news-scope').forEach(button => button.classList.toggle('active', button.dataset.newsScope === state.newsScope));
      document.querySelectorAll('.projection-scope').forEach(button => button.classList.toggle('active', button.dataset.projectionScope === state.projectionScope));
    }}

    function render() {{
      const activeTeam = tables.teams.find(team => Number(team.roster_id) === state.teamId) || {{}};
      const teamName = activeTeam.team_name || activeTeam.display_name || 'Unknown team';
      document.getElementById('active-team-label').textContent = teamName;

      let roster = tables.roster_players.filter(row => Number(row.roster_id) === state.teamId);
      if (state.position !== 'ALL') roster = roster.filter(row => row.position === state.position);
      if (state.status !== 'ALL') roster = roster.filter(row => row.roster_status === state.status);
      roster = applySearch(roster);

      const allTeamRoster = tables.roster_players.filter(row => Number(row.roster_id) === state.teamId);
      const qbCount = allTeamRoster.filter(row => row.position === 'QB').length;
      const rbCount = allTeamRoster.filter(row => row.position === 'RB').length;
      const passCount = allTeamRoster.filter(row => row.position === 'WR' || row.position === 'TE').length;
      const teamTrades = tables.trades.filter(row => Number(row.team_a_roster_id) === state.teamId || Number(row.team_b_roster_id) === state.teamId);
      const myPicksAway = tables.pick_ownership.filter(row => truthy(row.is_my_original_pick) && !truthy(row.i_currently_own_it));
      const rankedGaps = sortRows(applySearch(tables.asset_market_gaps), ['market_gap_score']).reverse();
      const buyLowTargets = rankedGaps.filter(row => Number(row.target_roster_id) !== state.teamId && String(row.opportunity_type).includes('buy')).slice(0, 5);
      const sellWindows = rankedGaps.filter(row => Number(row.target_roster_id) === state.teamId || String(row.opportunity_type).includes('sell')).slice(0, 5);
      const myNews = sortRows(tables.league_news_impact.filter(row => Number(row.roster_id) === state.teamId), ['published_at']).reverse().slice(0, 5);
      const targetNews = sortRows(tables.league_news_impact.filter(row => Number(row.roster_id) && Number(row.roster_id) !== state.teamId), ['published_at']).reverse().slice(0, 5);
      const managerAngles = sortRows(tables.manager_behavior_signals.filter(row => Number(row.roster_id) !== state.teamId), ['trade_activity_score', 'pick_seller_score']).reverse().slice(0, 5);

      setText('metric-roster', allTeamRoster.length);
      setText('metric-qb', qbCount);
      setText('metric-rb', rbCount);
      setText('metric-pass', passCount);
      setText('metric-my-picks-away', myPicksAway.length);
      setText('metric-team-trades', teamTrades.length);

      document.getElementById('my-pick-alerts').innerHTML = list(myPicksAway.map(row => `${{row.pick_season}} round ${{row.round}}: ${{row.current_owner}}`));
      document.getElementById('today-buy-low').innerHTML = opportunityCards(buyLowTargets, 'buy');
      document.getElementById('today-sell-window').innerHTML = opportunityCards(sellWindows, 'sell');
      document.getElementById('today-my-news').innerHTML = newsCards(myNews);
      document.getElementById('today-target-news').innerHTML = newsCards(targetNews);
      document.getElementById('today-pick-alerts').innerHTML = pickAlertCards(myPicksAway.slice(0, 5));
      document.getElementById('today-manager-angles').innerHTML = managerCards(managerAngles);
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
      document.getElementById('market-gap-table').innerHTML = table(filteredMarketGaps(), marketGapColumns);
      document.getElementById('asset-ledger-table').innerHTML = table(
        sortRows(applySearch(tables.team_asset_inventory.filter(row => Number(row.roster_id) === state.teamId)), ['asset_type', 'market_value']).reverse(),
        assetLedgerColumns
      );
      document.getElementById('opportunity-table').innerHTML = table(applySearch(tables.opportunity_board), opportunityColumns);
      document.getElementById('news-impact-table').innerHTML = table(filteredNewsImpact(), newsImpactColumns);
      document.getElementById('news-match-table').innerHTML = table(filteredNewsMatches(), newsMatchColumns);
      document.getElementById('manager-signal-table').innerHTML = table(applySearch(tables.manager_behavior_signals), managerSignalColumns);
      document.getElementById('manager-event-table').innerHTML = table(
        sortRows(applySearch(tables.manager_event_log.filter(row => Number(row.roster_id) === state.teamId)), ['week']).reverse(),
        managerEventColumns
      );
      document.getElementById('manager-table').innerHTML = table(applySearch(tables.manager_profiles), managerColumns);
      document.getElementById('pick-table').innerHTML = table(filteredPicks(), pickColumns);
      document.getElementById('trade-table').innerHTML = table(filteredTrades(), tradeColumns);
      document.getElementById('waiver-table').innerHTML = table(filteredWaivers(), waiverColumns);
      document.getElementById('diagnostics-panel').innerHTML = diagnostics();
      document.getElementById('draft-table').innerHTML = table(applySearch(tables.draft_picks), draftColumns);
    }}

    function filteredMarketGaps() {{
      let rows = tables.asset_market_gaps.slice();
      if (state.gapScope === 'targets') rows = rows.filter(row => Number(row.target_roster_id) !== state.teamId);
      if (state.gapScope === 'team') rows = rows.filter(row => Number(row.target_roster_id) === state.teamId);
      return sortRows(applySearch(rows), ['market_gap_score']).reverse().slice(0, 80);
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

    function filteredProjections() {{
      let rows = tables.player_projection_season.slice();
      if (state.projectionScope === 'team') rows = rows.filter(row => Number(row.roster_id) === state.teamId);
      if (state.projectionConfidence !== 'ALL') rows = rows.filter(row => row.projection_confidence === state.projectionConfidence);
      return sortRows(applySearch(rows), ['projected_fantasy_points']).reverse().slice(0, 120);
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
      return table([
        {{ item: 'Generated at', value: metadata.generated_at || 'unknown' }},
        {{ item: 'Current season', value: metadata.current_season || app.currentSeason || '' }},
        {{ item: 'Configured leagues', value: leagueIds }},
        {{ item: 'Transaction weeks', value: `${{metadata.transaction_week_start || ''}}-${{metadata.transaction_week_end || ''}}` }},
        {{ item: 'Source scope', value: metadata.source_scope || 'Sleeper public API only' }},
        {{ item: 'Players cached', value: tables.players.length }},
        {{ item: 'Raw cache root', value: metadata.raw_cache_root || 'data/raw' }},
        {{ item: 'Raw external cache root', value: metadata.raw_external_cache_root || 'data/raw_external' }},
        {{ item: 'Player market rows', value: tables.player_market_values.length }},
        {{ item: 'Pick market rows', value: tables.pick_market_values.length }},
        {{ item: 'Usage rows', value: tables.player_usage_weekly.length }},
        {{ item: 'Economic asset rows', value: tables.team_asset_inventory.length }},
        {{ item: 'News event rows', value: tables.news_events.length }},
        {{ item: 'News impact rows', value: tables.league_news_impact.length }},
        {{ item: 'Projection season rows', value: tables.player_projection_season.length }},
        {{ item: 'Projection weekly rows', value: tables.player_projection_weekly.length }},
        {{ item: 'Recommendation packets', value: metadata.recommendation_packets_status || 'planned_contract_only' }}
      ], ['item', 'value']) + '<h3>Source Freshness</h3>' + table(tables.source_freshness, sourceColumns) + '<h3>News Source Freshness</h3>' + table(tables.news_source_freshness, sourceColumns) + '<h3>Projection Source Freshness</h3>' + table(tables.projection_source_freshness, sourceColumns);
    }}

    function opportunityCards(rows, mode) {{
      if (!rows.length) return '<p class="note">No high-signal items found.</p>';
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: `${{row.asset_name || 'Unknown asset'}}${{row.target_team ? ` - ${{row.target_team}}` : ''}}`,
        chips: [
          row.opportunity_type || mode,
          row.position,
          row.market_gap_score ? `score ${{row.market_gap_score}}` : '',
          row.risk ? `risk ${{row.risk}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: row.evidence || row.timeline_fit || row.source_trace || 'No evidence provided.'
      }})).join('')}}</div>`;
    }}

    function newsCards(rows) {{
      if (!rows.length) return '<p class="note">No high-signal news found.</p>';
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: `${{row.player_name || 'Unknown player'}}${{row.team_name ? ` - ${{row.team_name}}` : ''}}`,
        chips: [
          row.impact_type,
          row.source,
          row.risk ? `risk ${{row.risk}}` : '',
          row.confidence ? `confidence ${{row.confidence}}` : ''
        ],
        evidence: row.evidence || row.source_trace || 'No evidence provided.'
      }})).join('')}}</div>`;
    }}

    function pickAlertCards(rows) {{
      if (!rows.length) return '<p class="note">No pick alerts found.</p>';
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: `${{row.pick_season}} R${{row.round}} - ${{row.original_team || 'Original team unknown'}}`,
        chips: [
          row.current_owner ? `held by ${{row.current_owner}}` : '',
          row.previous_owner ? `from ${{row.previous_owner}}` : '',
          truthy(row.is_my_original_pick) ? 'my original pick' : ''
        ],
        evidence: `Current owner: ${{row.current_owner || 'unknown'}}. Previous owner: ${{row.previous_owner || 'unknown'}}.`
      }})).join('')}}</div>`;
    }}

    function managerCards(rows) {{
      if (!rows.length) return '<p class="note">No manager angles found.</p>';
      return `<div class="brief-list">${{rows.map(row => briefCard({{
        title: row.team_name || 'Unknown manager',
        chips: [
          row.plain_language_label,
          row.trade_activity_score ? `trade ${{row.trade_activity_score}}` : '',
          row.pick_seller_score ? `pick sell ${{row.pick_seller_score}}` : '',
          row.faab_aggression_score ? `faab ${{row.faab_aggression_score}}` : ''
        ],
        evidence: row.evidence || 'No evidence provided.'
      }})).join('')}}</div>`;
    }}

    function briefCard(card) {{
      const chips = (card.chips || []).filter(value => value !== undefined && value !== null && String(value) !== '' && String(value) !== '0');
      return `<article class="brief-card">
        <div class="brief-card-title">${{escapeHtml(card.title || 'Untitled')}}</div>
        <div class="brief-card-meta">${{chips.map(chip => `<span class="brief-chip">${{escapeHtml(chip)}}</span>`).join('')}}</div>
        <div class="brief-card-evidence">${{escapeHtml(card.evidence || '')}}</div>
      </article>`;
    }}

    function table(rows, columns) {{
      if (!rows.length) return '<p class="note">No rows found.</p>';
      const head = columns.map(column => `<th>${{escapeHtml(label(column))}}</th>`).join('');
      const body = rows.map(row => `<tr>${{columns.map(column => `<td>${{formatCell(row[column])}}</td>`).join('')}}</tr>`).join('');
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

    function setText(id, value) {{
      document.getElementById(id).textContent = String(value);
    }}

    function truthy(value) {{
      return value === true || String(value).toLowerCase() === 'true';
    }}

    function unique(values) {{
      return [...new Set(values.filter(value => value !== undefined && value !== null && value !== ''))];
    }}

    function label(value) {{
      if (value === 'ALL') return 'All';
      return String(value).replaceAll('_', ' ').replace(/\\b\\w/g, letter => letter.toUpperCase());
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
