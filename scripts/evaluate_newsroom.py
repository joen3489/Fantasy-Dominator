from __future__ import annotations

"""Run the newsroom quality scorecard without making provider calls."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.newsroom_evaluation import evaluate_newsroom_fixture, load_artifact_run


DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "newsroom_eval" / "reference.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="Frozen evidence fixture to evaluate")
    parser.add_argument("--analysis-dir", type=Path, help="Evaluate published article artifacts instead of a fixture")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return nonzero unless every evaluated run is fully scored and passes")
    args = parser.parse_args()

    if args.analysis_dir:
        report = evaluate_newsroom_fixture(load_artifact_run(args.analysis_dir))
    else:
        try:
            fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"Unable to read newsroom fixture: {exc}", file=sys.stderr)
            return 2
        report = evaluate_newsroom_fixture(fixture)

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    statuses = [str(run.get("status")) for run in report.get("runs", [])]
    if args.strict and (not statuses or any(status != "pass" for status in statuses)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
