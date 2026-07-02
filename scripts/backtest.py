from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import run_score_backtest


DEFAULT_INPUT = Path("data/raw_external/nflverse/2026/player_stats.csv")
DEFAULT_OUTPUT = Path("data/processed/score_backtest_summary.csv")
DEFAULT_SEASONS = list(range(2015, 2025))
DEFAULT_SNAPSHOT_WEEKS = [6, 9, 12]


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    weekly_stats = pd.read_csv(args.input)
    summary = run_score_backtest(
        weekly_stats,
        seasons=_parse_int_list(args.seasons),
        snapshot_weeks=_parse_int_list(args.weeks),
    )

    if summary.empty:
        print("No computable backtest results.")
    else:
        print(summary.to_string(index=False))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest opportunity scores against rest-of-season PPR output.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seasons", default=",".join(str(season) for season in DEFAULT_SEASONS))
    parser.add_argument("--weeks", default=",".join(str(week) for week in DEFAULT_SNAPSHOT_WEEKS))
    return parser.parse_args(argv)


def _parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


if __name__ == "__main__":
    main()
