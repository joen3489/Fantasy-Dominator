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
    "news_events": ("source", "event_id", "published_at", "source_trace"),
    "news_source_freshness": ("source", "dataset", "status", "checked_at"),
    "source_freshness": ("source", "dataset", "status", "checked_at"),
    "projection_source_freshness": ("source", "dataset", "status", "checked_at"),
    "today_priority_board": ("source_trace",),
    "player_dossiers": ("source_trace",),
    "league_news_impact": ("source_trace",),
    "player_signal_scores": ("source_trace",),
}

REQUIRED_ANALYSIS = "analysis_validation.json"
CURRENT_STATUSES = {"refreshed", "cached"}
PLAYER_HISTORY_IDENTITY_METHODS = {"source_id", "normalized_name", "ambiguous_name", "unmatched_name"}


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

    player_history_identity = _audit_player_history(processed_dir / "player_transaction_history.csv", errors, warnings)
    if player_history_identity is not None:
        table_counts["player_transaction_history"] = player_history_identity["row_count"]

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

    for table in ("today_priority_board", "player_dossiers", "league_news_impact", "player_signal_scores"):
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
        "news_event_count": len(news_rows),
        "source_summary": source_summary,
        "analysis": analysis,
        "errors": errors,
        "warnings": warnings,
    }


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.is_file():
        return [], f"missing {path.name}"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle)), None
    except (OSError, csv.Error) as exc:
        return [], f"could not read {path.name}: {exc}"


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
