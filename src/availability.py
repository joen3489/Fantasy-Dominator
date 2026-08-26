"""Shared semantics for current-player availability and projection language.

Projection rows are season baselines. A current Sleeper injury/status field or
an absent current NFL team may qualify that baseline for immediate use, but
neutral values such as Active, Healthy, or None must not turn ordinary
projections into conditional claims. Keeping this seam shared prevents the
writers, ratings, and front page from drifting apart.
"""

import re
from typing import Any, Mapping


_NEUTRAL_STATUSES = {
    "",
    "active",
    "healthy",
    "available",
    "none",
    "no current injury",
    "no current sleeper injury flag",
}
_LIMITING_NOTE_MARKERS = (
    "questionable",
    "doubtful",
    "out",
    "injured",
    "injury",
    "ir",
    "pup",
    "suspended",
    "limited",
)
_NO_TEAM_NOTE_MARKER = "no current nfl team"


def _clean_text(value: Any) -> str:
    """Normalize scalar values read from CSV/DataFrame rows.

    Pandas represents blank CSV cells as ``NaN``. Treating that sentinel as
    text would turn a missing NFL team into the literal team ``NAN`` and a
    missing injury field into an invented injury flag.
    """

    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "<na>"} else text


def _has_current_team_field(row: Mapping[str, Any]) -> bool:
    """Return whether the row carries a current NFL-team field.

    ``team`` is the NFL team in projection/player records; ``team_name`` is
    the fantasy roster label and must never be used for this decision.
    """

    return "nfl_team" in row or "team" in row


def current_nfl_team(row: Mapping[str, Any]) -> str:
    """Read the canonical current NFL team without falling back to a fantasy name."""

    value = row.get("nfl_team") if "nfl_team" in row else row.get("team", "")
    return _clean_text(value).upper()


def current_availability_status(row: Mapping[str, Any]) -> str:
    """Classify the current Sleeper snapshot for decision-layer consumers.

    A blank NFL team is meaningful current-state evidence for a rostered free
    agent. It is not the same thing as a missing injury flag, and it must not
    receive an ordinary next-game projection.
    """

    scope = _clean_text(row.get("availability_scope")).lower()
    note = _clean_text(row.get("availability_note")).lower()
    if scope and scope != "current_season_snapshot":
        return "historical_unavailable"
    if _NO_TEAM_NOTE_MARKER in note or (
        scope == "current_season_snapshot"
        and _has_current_team_field(row)
        and not current_nfl_team(row)
    ):
        return "no_current_nfl_team"
    injury_status = _clean_text(row.get("injury_status")).lower()
    if not injury_status or injury_status in _NEUTRAL_STATUSES:
        return "available" if _has_current_team_field(row) else "unknown"
    if injury_status in {"out", "ir", "injured reserve", "pup", "suspended"} or any(
        marker in injury_status for marker in ("out", "injured reserve", "pup", "suspended")
    ):
        return "injury_out"
    if "doubtful" in injury_status:
        return "injury_doubtful"
    if "questionable" in injury_status or "probable" in injury_status:
        return "injury_questionable"
    return "injury_flagged"


def availability_factor(row: Mapping[str, Any]) -> tuple[float, str]:
    """Return immediate-use multiplier and a stable reader-facing label."""

    status = current_availability_status(row)
    if status == "no_current_nfl_team":
        return 0.0, status
    if status == "injury_out":
        return 0.0, "out"
    if status == "injury_doubtful":
        return 0.35, "doubtful"
    if status == "injury_questionable":
        return 0.65, "questionable"
    if status == "injury_flagged":
        return 0.80, "flagged"
    return 1.0, "available"


def availability_note(row: Mapping[str, Any]) -> str:
    """Describe current availability without rewriting the production baseline."""

    status = current_availability_status(row)
    if status == "no_current_nfl_team":
        return "No current NFL team in Sleeper; historical baseline is conditional on signing"
    injury_status = _clean_text(row.get("injury_status"))
    body = _clean_text(row.get("injury_body_part"))
    if injury_status:
        return f"{injury_status}{f' ({body})' if body else ''}; baseline projection does not adjust for availability"
    if status == "historical_unavailable":
        return "Historical availability unavailable by contract"
    return "No current Sleeper injury flag; baseline projection"


def has_current_availability_flag(row: Mapping[str, Any]) -> bool:
    """Return whether a current row contains a status that limits availability."""

    if current_availability_status(row) in {
        "no_current_nfl_team",
        "injury_out",
        "injury_doubtful",
        "injury_questionable",
        "injury_flagged",
    }:
        return True
    status = str(row.get("injury_status") or "").strip().lower()
    if status:
        return status not in _NEUTRAL_STATUSES
    note = str(row.get("availability_note") or "").strip().lower()
    if not note or note in _NEUTRAL_STATUSES or note.startswith("no current"):
        return False
    return _NO_TEAM_NOTE_MARKER in note or any(
        re.search(rf"\b{re.escape(marker)}\b", note) for marker in _LIMITING_NOTE_MARKERS
    )


def baseline_ppg_label(row: Mapping[str, Any]) -> str:
    """Return the reader-facing label for a deterministic PPG baseline."""

    if current_availability_status(row) == "no_current_nfl_team" or _NO_TEAM_NOTE_MARKER in str(
        row.get("availability_note") or ""
    ).lower():
        return "conditional baseline PPG if signed"
    if has_current_availability_flag(row):
        return "conditional baseline PPG if active"
    return "season baseline PPG"


def baseline_ppg_text(row: Mapping[str, Any], value: Any) -> str:
    """Format a baseline value without hiding its availability condition."""

    if baseline_ppg_label(row) == "conditional baseline PPG if signed":
        return f"conditional baseline PPG if signed {value}"
    if has_current_availability_flag(row):
        return f"conditional baseline PPG if active {value}"
    return f"season baseline {value} PPG"
