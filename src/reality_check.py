from __future__ import annotations

"""Deterministic verification packet for the private newsroom.

Reality Check is deliberately a packet, not another ranking model.  It records
the conditions that should limit an editorial claim: current availability,
identity joins, source limitations, and uncalibrated market/projection inputs.
The packet is persisted with the analysis artifacts so the reader can tell
whether a warning belongs to the current edition or to an older page shell.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .availability import current_availability_status


REALITY_CHECK_SCHEMA_VERSION = "reality_check_v1"


def build_reality_check_packet(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    league_id: str = "",
    season: str = "",
    roster_id: int | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a roster ledger plus a league-actionability limitation ledger.

    Private team checks remain scoped to the selected roster.  Actionable
    market and trade evidence is broader than that roster, though: a writer
    may discuss a waiver target, a counterparty asset, or a market lead that
    is not currently on the manager's team.  Those rows must inherit the same
    current-availability and projection guardrails before they reach prose.
    """

    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    league_id = _clean(league_id)
    season = _clean(season)
    roster_text = _clean(roster_id)
    roster = [
        dict(row)
        for row in _scoped_rows(tables.get("roster_players") or [], league_id, season)
        if _same_id(row.get("roster_id"), roster_id)
    ]
    dossiers = [
        dict(row)
        for row in _scoped_rows(tables.get("player_dossiers") or [], league_id, season)
        if not roster_id or _same_id(row.get("roster_id"), roster_id)
    ]
    dossier_ids = {_clean(row.get("player_id")) for row in dossiers if _clean(row.get("player_id"))}
    signals = {
        _clean(row.get("player_id")): dict(row)
        for row in _scoped_rows(tables.get("player_signal_scores") or [], league_id, season)
        if _clean(row.get("player_id"))
        and (not roster_id or _same_id(row.get("roster_id"), roster_id))
    }

    checks: list[dict[str, Any]] = []
    for row in roster:
        player_id = _clean(row.get("player_id"))
        player_name = _clean(row.get("player_name")) or player_id or "Roster player"
        status = current_availability_status(row)
        if status == "no_current_nfl_team":
            checks.append(
                _check(
                    "availability.no_current_nfl_team",
                    "high",
                    player_id,
                    player_name,
                    "No current NFL team",
                    "Historical production is conditional context; current-role and next-game claims are unavailable until a team and role are confirmed.",
                    "roster_players",
                    row,
                    league_id,
                    season,
                    roster_text,
                )
            )
        elif status.startswith("injury_"):
            checks.append(
                _check(
                    "availability.injury_flag",
                    "high" if status in {"injury_out", "injury_doubtful"} else "medium",
                    player_id,
                    player_name,
                    f"Current availability is {status.removeprefix('injury_')}",
                    "Any production baseline remains conditional on availability; recovery timing is not modeled by this packet.",
                    "roster_players",
                    row,
                    league_id,
                    season,
                    roster_text,
                )
            )

        if player_id and player_id not in dossier_ids:
            checks.append(
                _check(
                    "identity.missing_player_dossier",
                    "medium",
                    player_id,
                    player_name,
                    "Player dossier join is missing",
                    "The roster row is present, but no dossier is joined to this exact Sleeper player ID. Missing is not zero value.",
                    "roster_players;player_dossiers",
                    row,
                    league_id,
                    season,
                    roster_text,
                )
            )

        signal = signals.get(player_id, {})
        market_status = _clean(signal.get("market_gap_status")).lower()
        if market_status == "proxy_market_not_calibrated":
            checks.append(
                _check(
                    "market.proxy_not_calibrated",
                    "medium",
                    player_id,
                    player_name,
                    "Market value is an internal proxy",
                    "The market row can support a research comparison, but it is not calibrated external market evidence and should not drive a strong mispricing claim.",
                    "player_signal_scores;player_dossiers",
                    signal or row,
                    league_id,
                    season,
                    roster_text,
                )
            )
        elif market_status == "availability_conditioned_unavailable":
            checks.append(
                _check(
                    "market.availability_conditioned",
                    "high",
                    player_id,
                    player_name,
                    "Market comparison is availability-conditioned",
                    "The row is retained for context but is not an actionable current-role ranking.",
                    "player_signal_scores",
                    signal or row,
                    league_id,
                    season,
                    roster_text,
                )
            )
        if signal and _clean(signal.get("signal_label")) == "missing_projection_watch":
            checks.append(
                _check(
                    "projection.missing_input",
                    "medium",
                    player_id,
                    player_name,
                    "Projection input is missing or thin",
                    "Do not turn a placeholder or zero projection into a confident current-season claim; inspect the projection receipt first.",
                    "player_signal_scores;player_projection_season",
                    signal,
                    league_id,
                    season,
                    roster_text,
                )
            )

    # The exact roster ledger above is intentionally private.  This second
    # ledger covers the current-season player universe used by market, waiver,
    # horizon, and trade scopes.  It is assembled from deterministic tables
    # rather than names in generated prose, so a non-rostered player cannot
    # bypass a no-team or injury limitation simply by entering through a
    # different article scope.
    market_rows_by_player = _actionable_player_rows(tables, league_id, season)
    market_quality = {
        "priced_rows": 0,
        "multi_source_rows": 0,
        "single_source_rows": 0,
        "unavailable_source_rows": 0,
        "outlier_checks": 0,
    }
    for player_id, candidate in market_rows_by_player.items():
        player_name = _clean(candidate.get("player_name")) or player_id or "Actionable player"
        status = current_availability_status(candidate)
        if status == "no_current_nfl_team":
            checks.append(
                _check(
                    "availability.no_current_nfl_team",
                    "high",
                    player_id,
                    player_name,
                    "No current NFL team",
                    "Historical production is conditional context; current-role and next-game claims are unavailable until a team and role are confirmed.",
                    "actionable_player_inputs",
                    candidate,
                    league_id,
                    season,
                    roster_text,
                    scope="league_actionable_player_universe",
                )
            )
        elif status.startswith("injury_"):
            checks.append(
                _check(
                    "availability.injury_flag",
                    "high" if status in {"injury_out", "injury_doubtful"} else "medium",
                    player_id,
                    player_name,
                    f"Current availability is {status.removeprefix('injury_')}",
                    "Any production baseline remains conditional on availability; recovery timing is not modeled by this packet.",
                    "actionable_player_inputs",
                    candidate,
                    league_id,
                    season,
                    roster_text,
                    scope="league_actionable_player_universe",
                )
            )

        market_source_count = _number_or_none(candidate.get("market_source_count"))
        market_percentile = _number_or_none(candidate.get("market_percentile"))
        clock_deltas = {
            "next_game": _number_or_none(candidate.get("next_game_minus_market_delta")),
            "rest_of_season": _number_or_none(candidate.get("rest_of_season_minus_market_delta")),
            "dynasty": _number_or_none(candidate.get("dynasty_minus_market_delta")),
            "career_window": _number_or_none(candidate.get("career_minus_market_delta")),
        }
        available_deltas = [(window, delta) for window, delta in clock_deltas.items() if delta is not None]
        confidence = _clean(candidate.get("market_source_confidence")).lower()
        largest_delta = max((abs(delta) for _, delta in available_deltas), default=0.0)
        if market_percentile is not None:
            market_quality["priced_rows"] += 1
            if market_source_count is None:
                market_quality["unavailable_source_rows"] += 1
            elif market_source_count <= 1:
                market_quality["single_source_rows"] += 1
            else:
                market_quality["multi_source_rows"] += 1
        if market_percentile is not None and available_deltas and market_source_count is not None and market_source_count <= 1 and largest_delta >= 25:
            window, delta = max(available_deltas, key=lambda item: abs(item[1]))
            market_quality["outlier_checks"] += 1
            checks.append(
                _check(
                    "market.single_source_not_calibrated",
                    "medium",
                    player_id,
                    player_name,
                    "Clock/market comparison is single-source",
                    "The same-position clock delta is a research lead, but a one-source price anchor is not strong enough for a confident mispricing claim.",
                    "player_horizon_market_scores;market_consensus_values",
                    candidate,
                    league_id,
                    season,
                    roster_text,
                    scope="league_actionable_player_universe",
                    observed={
                        "position": _clean(candidate.get("position")) or "unknown",
                        "market_percentile": market_percentile,
                        "market_source_count": market_source_count,
                        "market_source_confidence": confidence or "unknown",
                        "clock_window": window,
                        "clock_market_delta": delta,
                        "comparison_basis": "position_relative_clock_vs_market_percentile",
                    },
                )
            )
        if market_percentile is not None and available_deltas and market_source_count is not None and market_source_count >= 2:
            window, delta = max(available_deltas, key=lambda item: abs(item[1]))
            if abs(delta) >= 35:
                market_quality["outlier_checks"] += 1
                quality = f"{market_source_count:g}-source market" + (f" with {confidence} confidence" if confidence else "")
                checks.append(
                    _check(
                        "market.large_clock_disagreement",
                        "medium" if abs(delta) >= 50 else "low",
                        player_id,
                        player_name,
                        f"Large {window.replace('_', ' ')} clock/market disagreement",
                        f"The {window.replace('_', ' ')} score is {delta:+.1f} percentile points versus the same-position market anchor ({quality}). This is a discovery queue item, not proof of mispricing or a cross-position ranking.",
                        "player_horizon_market_scores;market_consensus_values",
                        candidate,
                        league_id,
                        season,
                        roster_text,
                        scope="league_actionable_player_universe",
                        observed={
                            "position": _clean(candidate.get("position")) or "unknown",
                            "market_percentile": market_percentile,
                            "market_source_count": market_source_count,
                            "market_source_confidence": confidence or "unknown",
                            "clock_window": window,
                            "clock_market_delta": delta,
                            "comparison_basis": "position_relative_clock_vs_market_percentile",
                        },
                    )
                )
        if _clean(candidate.get("market_gap_status")).lower() == "availability_conditioned_unavailable":
            checks.append(
                _check(
                    "market.availability_conditioned",
                    "high",
                    player_id,
                    player_name,
                    "Market comparison is availability-conditioned",
                    "The row is retained for context but is not an actionable current-role ranking.",
                    "actionable_player_inputs",
                    candidate,
                    league_id,
                    season,
                    roster_text,
                    scope="league_actionable_player_universe",
                )
            )

    for row in _rows(tables.get("source_freshness") or []):
        source = _clean(row.get("source")) or "source"
        dataset = _clean(row.get("dataset")) or "dataset"
        status = _clean(row.get("status")) or "unknown"
        if status.lower() not in {"cached", "fresh", "current", "ok", "available"}:
            checks.append(
                _check(
                    "source.limited_receipt",
                    "medium",
                    "",
                    f"{source} · {dataset}",
                    f"Source receipt is {status}",
                    "Affected reads remain available only as limited context until the source is configured or refreshed.",
                    "source_freshness",
                    row,
                    league_id,
                    season,
                    roster_text,
                )
            )

    checks = _deduplicate_checks(checks)
    severity_counts = {severity: sum(1 for check in checks if check["severity"] == severity) for severity in ("high", "medium", "low")}
    source_tables = sorted(
        {
            table
            for check in checks
            for table in str(check.get("source_table") or "").split(";")
            if table
        }
    )
    status = "flagged" if checks else "clear"
    market_quality_status = (
        "multi_source_available"
        if market_quality["multi_source_rows"]
        else "single_source_limited"
        if market_quality["single_source_rows"]
        else "market_receipt_unavailable"
    )
    market_quality_summary = {
        **market_quality,
        "status": market_quality_status,
        "basis": (
            "Clock scores and market percentiles are position-relative; market value remains the cross-position price anchor. "
            "Outlier checks require a usable market percentile and retain source-count and clock-window receipts."
        ),
    }
    return {
        "artifact_type": "reality_check",
        "schema_version": REALITY_CHECK_SCHEMA_VERSION,
        "generation_mode": "deterministic_template",
        "generated_at": generated_at,
        "league_id": league_id,
        "season": season,
        "roster_id": int(roster_id) if _clean(roster_id).isdigit() else roster_id,
        "status": status,
        "summary": (
            f"{len(checks)} deterministic limitation{'s' if len(checks) != 1 else ''} flagged across the selected roster and actionable league player universe."
            if checks
            else "No deterministic limitation was flagged for the selected roster or actionable league player universe in this snapshot."
        ),
        "checks": checks,
        "items": checks,
        "severity_counts": severity_counts,
        "market_quality": market_quality_summary,
        "roster_rows_checked": len(roster),
        "dossier_rows_checked": len(dossiers),
        "source_tables": source_tables,
        "source_receipt": {
            "scope": "selected_league_roster_and_actionable_player_universe",
            "source_tables": source_tables,
            "freshness_table": "source_freshness",
            "status": status,
        },
        "fingerprint": _fingerprint(checks, league_id, season, roster_text, market_quality_summary),
        "actionable_player_rows_checked": len(market_rows_by_player),
    }


def _check(
    check_id: str,
    severity: str,
    entity_id: str,
    entity_name: str,
    title: str,
    detail: str,
    source_table: str,
    row: Mapping[str, Any],
    league_id: str,
    season: str,
    roster_id: str,
    scope: str = "selected_roster",
    observed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_id = _evidence_id(source_table, row, league_id, season, roster_id, entity_id)
    source_trace = _clean(row.get("source_trace")) or source_table
    result = {
        "check_id": check_id,
        "severity": severity,
        "entity_type": "player" if entity_id else "source",
        "entity_id": entity_id,
        "entity_name": entity_name,
        "title": title,
        "detail": detail,
        "evidence_ids": [evidence_id],
        "source_table": source_table,
        "source_trace": source_trace,
        "scope": scope,
    }
    if isinstance(observed, Mapping):
        result["observed"] = {
            str(key): value
            for key, value in observed.items()
            if value not in (None, "")
        }
    return result


def _evidence_id(
    source_table: str,
    row: Mapping[str, Any],
    league_id: str,
    season: str,
    roster_id: str,
    entity_id: str,
) -> str:
    explicit = _clean(row.get("evidence_id"))
    if explicit:
        return explicit
    source_key = next(
        (
            _clean(row.get(key))
            for key in ("event_id", "transaction_id", "matchup_id", "player_id", "source")
            if _clean(row.get(key))
        ),
        entity_id or "receipt",
    )
    return f"reality:{source_table.split(';')[0]}:{league_id or 'league'}:{season or 'season'}:{roster_id or 'all'}:{source_key}"


def _scoped_rows(rows: Sequence[Mapping[str, Any]], league_id: str, season: str) -> list[Mapping[str, Any]]:
    materialized = [row for row in rows if isinstance(row, Mapping)]
    if league_id and any(_clean(row.get("league_id")) for row in materialized):
        materialized = [row for row in materialized if not _clean(row.get("league_id")) or _same_id(row.get("league_id"), league_id)]
    if season and any(_clean(row.get("season")) for row in materialized):
        materialized = [row for row in materialized if not _clean(row.get("season")) or _same_id(row.get("season"), season)]
    return materialized


def _rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if isinstance(row, Mapping)]


def _deduplicate_checks(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for check in checks:
        key = (
            _clean(check.get("check_id")),
            _clean(check.get("entity_id")),
        )
        existing = seen.get(key)
        if existing is not None:
            existing_evidence = list(existing.get("evidence_ids") or [])
            for evidence_id in check.get("evidence_ids") or []:
                if evidence_id not in existing_evidence:
                    existing_evidence.append(evidence_id)
            existing["evidence_ids"] = existing_evidence
            source_tables = [
                value for value in str(existing.get("source_table") or "").split(";") if value
            ]
            for source_table in str(check.get("source_table") or "").split(";"):
                if source_table and source_table not in source_tables:
                    source_tables.append(source_table)
            existing["source_table"] = ";".join(source_tables)
            traces = [value for value in str(existing.get("source_trace") or "").split("; ") if value]
            for trace in str(check.get("source_trace") or "").split("; "):
                if trace and trace not in traces:
                    traces.append(trace)
            existing["source_trace"] = "; ".join(traces)
            if existing.get("scope") == "selected_roster" and check.get("scope") != "selected_roster":
                existing["scope"] = check.get("scope")
            continue
        item = dict(check)
        seen[key] = item
        output.append(item)
    return output


def _actionable_player_rows(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    league_id: str,
    season: str,
) -> dict[str, dict[str, Any]]:
    """Merge current player inputs without allowing a weak row to erase a strong one."""

    # Horizon rows carry the league boundary and the complete decision-layer
    # status.  The other tables fill gaps for legacy/global artifacts and
    # market signals.  Blank values never overwrite a previously observed
    # value, and roster_id is deliberately not used as a filter here.
    sources = (
        "player_horizon_market_scores",
        "available_player_horizon_scores",
        "player_signal_scores",
        "player_dossiers",
    )
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for row in _scoped_rows(tables.get(source) or [], league_id, season):
            player_id = _clean(row.get("player_id"))
            if not player_id:
                continue
            target = merged.setdefault(player_id, {"player_id": player_id, "_source_tables": []})
            if source not in target["_source_tables"]:
                target["_source_tables"].append(source)
            for key, value in dict(row).items():
                if key.startswith("_"):
                    continue
                if _clean(target.get(key)) or not _clean(value):
                    continue
                target[key] = value
    return merged


def _fingerprint(
    checks: Sequence[Mapping[str, Any]],
    league_id: str,
    season: str,
    roster_id: str,
    market_quality: Mapping[str, Any] | None = None,
) -> str:
    raw = "|".join(
        [league_id, season, roster_id]
        + [str(sorted((market_quality or {}).items()))]
        + [
            ":".join(
                _clean(check.get(field))
                for field in ("check_id", "severity", "entity_id", "title", "source_trace")
            )
            for check in checks
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _same_id(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    left_text = _clean(left)
    right_text = _clean(right)
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except (TypeError, ValueError):
        return False


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "<na>"} else text


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None
