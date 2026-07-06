from __future__ import annotations

"""Path helpers for isolating league state without breaking legacy imports."""

from dataclasses import dataclass
from pathlib import Path

from .utils import (
    ANALYSIS_DIR,
    CACHE_DIR,
    DATA_DIR,
    OPERATOR_INBOX_DIR,
    OPERATOR_OUTBOX_DIR,
    OPERATOR_STATUS_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    RAW_EXTERNAL_DIR,
    REPORTS_DIR,
    SITE_DIR,
)


# Anchored to the project root like every other data path (utils.DATA_DIR) -- a CWD-relative
# path here would silently write league state to the wrong place when the server process is
# started from a different working directory.
LEAGUES_ROOT = DATA_DIR / "leagues"


@dataclass(frozen=True)
class LeaguePaths:
    """Concrete directory layout for either one Sleeper league or the legacy app."""

    league_id: str
    root: Path
    raw_dir: Path
    raw_external_dir: Path
    processed_dir: Path
    cache_dir: Path
    reports_dir: Path
    site_dir: Path
    analysis_dir: Path
    operator_inbox_dir: Path
    operator_outbox_dir: Path
    operator_status_dir: Path

    @classmethod
    def for_league(cls, league_id: str) -> LeaguePaths:
        root = LEAGUES_ROOT / str(league_id)
        operator_dir = root / "operator"
        return cls(
            league_id=str(league_id),
            root=root,
            raw_dir=root / "raw",
            raw_external_dir=RAW_EXTERNAL_DIR,
            processed_dir=root / "processed",
            cache_dir=root / "cache",
            reports_dir=root / "reports",
            site_dir=root / "site",
            analysis_dir=root / "analysis",
            operator_inbox_dir=operator_dir / "inbox",
            operator_outbox_dir=operator_dir / "outbox",
            operator_status_dir=operator_dir / "status",
        )

    @classmethod
    def default(cls) -> LeaguePaths:
        return cls(
            league_id="default",
            root=DATA_DIR,
            raw_dir=RAW_DIR,
            raw_external_dir=RAW_EXTERNAL_DIR,
            processed_dir=PROCESSED_DIR,
            cache_dir=CACHE_DIR,
            reports_dir=REPORTS_DIR,
            site_dir=SITE_DIR,
            analysis_dir=ANALYSIS_DIR,
            operator_inbox_dir=OPERATOR_INBOX_DIR,
            operator_outbox_dir=OPERATOR_OUTBOX_DIR,
            operator_status_dir=OPERATOR_STATUS_DIR,
        )

    def ensure(self) -> None:
        for path in (
            self.raw_dir,
            self.raw_external_dir,
            self.processed_dir,
            self.cache_dir,
            self.reports_dir,
            self.site_dir,
            self.analysis_dir,
            self.operator_inbox_dir,
            self.operator_outbox_dir,
            self.operator_status_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
