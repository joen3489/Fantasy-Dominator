"""Deterministic quality checks for the private newsroom.

The evaluation layer deliberately measures the seams the product promises:
evidence, source receipts, horizon ownership, information differentiation,
unsupported certainty, and execution telemetry.  It does not pretend that a
reader click proves a recommendation was good.  Outcome usefulness remains
``not_scored`` until an observed result is recorded.

Design source: ``docs/durable_newsroom_epic.md`` Slice 0 and the evidence and
editorial boundaries in ``AGENTS.md``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .articles import ARTICLES
from .operator import validate_article_output
from .personas import DEFAULT_ARTICLE_REPORTERS, REPORTER_PERSONAS


EVALUATION_SCHEMA_VERSION = "newsroom_evaluation_v1"
ARTICLE_BY_KEY = {article.key: article for article in ARTICLES}
DEFAULT_EXPECTED_ARTICLES = tuple(article.key for article in ARTICLES)


def _metric(status: str, score: float | None = None, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if score is not None:
        result["score"] = round(max(0.0, min(1.0, float(score))), 3)
    if details:
        result["details"] = details
    return result


def _string_set(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    return {str(item).strip() for item in values if str(item).strip()}


def _source_ids(packets: Sequence[Mapping[str, Any]]) -> set[str]:
    output: set[str] = set()
    for packet in packets:
        output.update(_string_set(packet.get("source_ids") or packet.get("source_trace")))
    return output


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Read the JSON-bearing front matter used by article receipts."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return {}, text
    front: dict[str, Any] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if key.endswith("_json"):
            try:
                front[key] = json.loads(raw)
                continue
            except json.JSONDecodeError:
                pass
        front[key] = raw
    body = "\n".join(lines[end + 1:]).strip()
    return front, body


def load_artifact_run(analysis_dir: Path) -> dict[str, Any]:
    """Load the current published article artifacts as an evaluation run.

    Current article files carry a bounded evidence manifest.  Older files may
    still lack it; in that case evidence-boundary coverage remains
    ``not_scored`` instead of treating self-reported citation IDs as proof.
    """

    articles: list[dict[str, Any]] = []
    reality_check_packet: dict[str, Any] = {}
    reality_check_path = analysis_dir / "reality_check.json"
    if reality_check_path.is_file():
        try:
            raw_reality_check = json.loads(reality_check_path.read_text(encoding="utf-8"))
            if isinstance(raw_reality_check, Mapping):
                reality_check_packet = dict(raw_reality_check)
        except (OSError, UnicodeError, json.JSONDecodeError):
            reality_check_packet = {}
    generated_at = ""
    for definition in ARTICLES:
        path = analysis_dir / definition.output_filename
        if not path.exists():
            continue
        try:
            front, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        payload = front.get("article_payload_json")
        payload = payload if isinstance(payload, Mapping) else {}
        source_receipt = front.get("source_receipt_json")
        source_receipt = source_receipt if isinstance(source_receipt, Mapping) else {}
        evidence_manifest = front.get("evidence_manifest_json")
        evidence_manifest = evidence_manifest if isinstance(evidence_manifest, list) else []
        generated_at = generated_at or str(front.get("generated_at") or "")
        byline_reporter_id = str(front.get("reporter_persona") or "")
        assigned_reporter_id = str(front.get("assigned_reporter_persona") or byline_reporter_id)
        # Deterministic fallback copy is intentionally bylined as Front Office,
        # while its receipt still carries the specialist desk that owns the
        # question. Evaluate the information contract against that assignment
        # without making fallback prose look LLM-authored.
        reporter_id = assigned_reporter_id if byline_reporter_id == "front_office" else byline_reporter_id
        persona = REPORTER_PERSONAS.get(reporter_id)
        articles.append(
            {
                "article_key": definition.key,
                "narrative_markdown": body,
                "cited_evidence_ids": list(payload.get("evidence_ids") or []),
                "claim_positions": list(payload.get("claim_positions") or []) if isinstance(payload.get("claim_positions"), list) else [],
                "reporter_id": reporter_id,
                "byline_reporter_id": byline_reporter_id,
                "assigned_reporter_id": assigned_reporter_id,
                "reporter_name": str(front.get("reporter_name") or ""),
                "assigned_reporter_name": str(front.get("assigned_reporter_name") or (persona.name if persona else "")),
                "decision_lens": persona.decision_lens if persona else "",
                "information_scope": persona.evidence_scope if persona else "",
                "primary_question": persona.question if persona else "",
                "evidence_count": payload.get("evidence_count"),
                "source_ids": list(source_receipt.get("source_ids") or payload.get("source_ids") or []),
                "source_count": source_receipt.get("source_count") or payload.get("source_count"),
                "evidence_packets": evidence_manifest,
                "model": str(front.get("model") or ""),
                "model_mode": str(front.get("model_mode") or ""),
                "evidence_fingerprint": str(front.get("evidence_fingerprint") or ""),
            }
        )
    edition_packet_path = analysis_dir / "edition_packet.json"
    packet = {}
    if edition_packet_path.exists():
        try:
            packet = json.loads(edition_packet_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            packet = {}
    return {
        "run_id": str(packet.get("run_id") or generated_at or "artifact-snapshot"),
        "generated_at": generated_at,
        "expected_article_keys": list(DEFAULT_EXPECTED_ARTICLES),
        "articles": articles,
        "execution_receipts": _load_execution_receipts(analysis_dir, packet),
        "reality_check_packet": reality_check_packet,
        "outcome_observations": [],
        "source": "published_analysis_artifacts",
    }


def _load_execution_receipts(analysis_dir: Path, packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Load the safe run/job telemetry without requiring provider access."""

    path = analysis_dir / "edition_receipt.json"
    if not path.is_file():
        run_id = str(packet.get("run_id") or "").strip()
        if run_id:
            safe_id = "".join(char for char in run_id if char.isalnum() or char in "_-")
            path = analysis_dir / "edition_runs" / f"{safe_id}.receipt.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = payload.get("jobs") if isinstance(payload, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _article_packets(article: Mapping[str, Any], global_evidence: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    packets = article.get("evidence_packets")
    if isinstance(packets, list):
        return [dict(packet) for packet in packets if isinstance(packet, Mapping)]
    references = _string_set(
        list(article.get("cited_evidence_ids") or [])
        + list(article.get("required_evidence_ids") or [])
        + list(article.get("valid_evidence_ids") or [])
    )
    return [dict(global_evidence[evidence_id]) for evidence_id in references if evidence_id in global_evidence]


def evaluate_article(
    article: Mapping[str, Any],
    *,
    global_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    reality_check_packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    key = str(article.get("article_key") or article.get("key") or "").strip()
    definition = ARTICLE_BY_KEY.get(key)
    cited = _string_set(article.get("cited_evidence_ids") or article.get("evidence_ids"))
    packets = _article_packets(article, global_evidence or {})
    packet_ids = {str(packet.get("evidence_id")) for packet in packets if str(packet.get("evidence_id") or "").strip()}
    explicit_valid_ids = _string_set(article.get("valid_evidence_ids")) if "valid_evidence_ids" in article else set()
    verified_ids = explicit_valid_ids or packet_ids
    evidence_boundary_available = bool(explicit_valid_ids or packets)
    validation_ids = verified_ids if evidence_boundary_available else cited
    output = dict(article.get("output") or {}) if isinstance(article.get("output"), Mapping) else {}
    output.setdefault("narrative_markdown", str(article.get("narrative_markdown") or ""))
    output.setdefault("cited_evidence_ids", list(cited))
    if isinstance(article.get("claim_positions"), list):
        output["claim_positions"] = list(article.get("claim_positions") or [])
    headers = tuple(definition.headers) if definition else tuple()
    validation = validate_article_output(
        output,
        validation_ids,
        headers,
        packets if evidence_boundary_available else None,
        article_key=key,
        reality_check_packet=reality_check_packet,
    )

    errors: list[str] = []
    if not definition:
        errors.append(f"Unknown article key: {key or '<empty>'}")
    if evidence_boundary_available:
        unknown = sorted(cited - verified_ids)
        if unknown:
            errors.append(f"{key} cites evidence IDs not present in its frozen packet: {','.join(unknown)}")

    required_evidence = _string_set(article.get("required_evidence_ids"))
    if required_evidence:
        missing = sorted(required_evidence - cited)
        evidence_metric = _metric(
            "scored",
            len(required_evidence & cited) / len(required_evidence),
            required_count=len(required_evidence),
            cited_required_count=len(required_evidence & cited),
            missing_required_ids=missing,
        )
        if missing:
            errors.append(f"{key} did not cite required fixture evidence: {','.join(missing)}")
    else:
        if evidence_boundary_available:
            missing = sorted(cited - verified_ids)
            evidence_metric = _metric(
                "scored",
                len(cited - set(missing)) / len(cited) if cited else 0.0,
                packet_count=len(packet_ids),
                cited_count=len(cited),
                verified_citation_count=len(cited - set(missing)),
                missing_citation_ids=missing,
            )
        else:
            evidence_metric = _metric(
                "not_scored",
                reason="complete writer packet was not persisted in this artifact",
                cited_count=len(cited),
                evidence_count=article.get("evidence_count"),
            )

    source_ids = _string_set(article.get("source_ids")) or _source_ids(packets)
    required_sources = _string_set(article.get("required_source_ids"))
    if required_sources:
        missing_sources = sorted(required_sources - source_ids)
        source_metric = _metric(
            "scored",
            len(required_sources & source_ids) / len(required_sources),
            required_count=len(required_sources),
            present_count=len(required_sources & source_ids),
            missing_required_ids=missing_sources,
        )
        if missing_sources:
            errors.append(f"{key} is missing required source receipts: {','.join(missing_sources)}")
    else:
        source_metric = _metric("scored" if source_ids else "not_scored", 1.0 if source_ids else None, source_count=len(source_ids))

    expected_reporter = str(article.get("expected_reporter_id") or DEFAULT_ARTICLE_REPORTERS.get(key) or "")
    actual_reporter = str(article.get("reporter_id") or "")
    persona = REPORTER_PERSONAS.get(actual_reporter)
    expected_persona = REPORTER_PERSONAS.get(expected_reporter)
    supplied_lens = str(article.get("decision_lens") or "")
    horizon_ok = bool(actual_reporter and expected_reporter and actual_reporter == expected_reporter)
    if supplied_lens and persona:
        horizon_ok = horizon_ok and supplied_lens == persona.decision_lens
    horizon_metric = _metric(
        "scored" if expected_reporter else "not_scored",
        1.0 if horizon_ok else 0.0 if expected_reporter else None,
        expected_reporter=expected_reporter,
        actual_reporter=actual_reporter,
        expected_lens=expected_persona.decision_lens if expected_persona else "",
        actual_lens=supplied_lens or (persona.decision_lens if persona else ""),
    )
    if expected_reporter and not horizon_ok:
        errors.append(
            f"{key} does not satisfy its desk contract: reporter {actual_reporter or '<unknown>'}, "
            f"expected {expected_reporter} and lens {expected_persona.decision_lens if expected_persona else '<unknown>'}"
        )

    boundary_errors = list((validation.get("boundary_checks") or {}).get("errors") or [])
    reality_errors = list((validation.get("reality_check") or {}).get("errors") or [])
    forbidden_errors = [error for error in validation.get("errors", []) if "forbidden language" in str(error).lower()]
    certainty_errors = boundary_errors + reality_errors + forbidden_errors
    certainty_metric = _metric(
        "scored",
        0.0 if certainty_errors else 1.0,
        errors=certainty_errors,
        warnings=(validation.get("boundary_checks") or {}).get("warnings", [])
        + list((validation.get("reality_check") or {}).get("warnings") or []),
    )

    claim_positions = article.get("claim_positions")
    claim_checks = validation.get("claim_position_checks") if isinstance(validation.get("claim_position_checks"), Mapping) else {}
    if isinstance(claim_positions, list) and claim_positions:
        supplied_count = len(claim_positions)
        valid_count = int(claim_checks.get("count") or 0)
        claim_metric = _metric(
            "scored",
            valid_count / supplied_count if supplied_count else 0.0,
            supplied_count=supplied_count,
            valid_count=valid_count,
            errors=list(claim_checks.get("errors") or []),
        )
    else:
        claim_metric = _metric(
            "not_scored",
            reason="article did not persist a structured claim register",
        )

    validation_errors = [str(error) for error in validation.get("errors") or []]
    errors.extend(validation_errors)
    return {
        "article_key": key,
        "status": "fail" if errors else "pass",
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(validation.get("warnings") or [])),
        "metrics": {
            "evidence_coverage": evidence_metric,
            "source_trace_coverage": source_metric,
            "horizon_alignment": horizon_metric,
            "unsupported_certainty": certainty_metric,
            "claim_register": claim_metric,
        },
        "receipt": {
            "reporter_id": actual_reporter,
            "reporter_name": str(article.get("reporter_name") or (persona.name if persona else "")),
            "decision_lens": supplied_lens or (persona.decision_lens if persona else ""),
            "information_scope": str(article.get("information_scope") or (persona.evidence_scope if persona else "")),
            "primary_question": str(article.get("primary_question") or (persona.question if persona else "")),
            "source_count": len(source_ids),
            "cited_evidence_count": len(cited),
            "evidence_boundary_available": evidence_boundary_available,
            "evidence_fingerprint": str(article.get("evidence_fingerprint") or ""),
            "model": str(article.get("model") or ""),
            "model_mode": str(article.get("model_mode") or ""),
        },
        "validation": validation,
    }


def _average_metric(results: Sequence[Mapping[str, Any]], name: str) -> dict[str, Any]:
    metrics = [result.get("metrics", {}).get(name, {}) for result in results]
    scored = [float(metric["score"]) for metric in metrics if metric.get("status") == "scored" and "score" in metric]
    if not scored:
        return _metric("not_scored", reason=f"no article supplied a scored {name} fixture")
    return _metric("scored", sum(scored) / len(scored), article_count=len(scored))


def _voice_distinctness(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    receipts = [result.get("receipt", {}) for result in results if result.get("receipt", {}).get("reporter_id")]
    if not receipts:
        return _metric("not_scored", reason="no reporter receipts")
    dimensions = {
        "reporter_ids": [str(receipt.get("reporter_id") or "") for receipt in receipts],
        "decision_lenses": [str(receipt.get("decision_lens") or "") for receipt in receipts],
        "information_scopes": [str(receipt.get("information_scope") or "") for receipt in receipts],
        "primary_questions": [str(receipt.get("primary_question") or "") for receipt in receipts],
    }
    ratios = {
        name: len(set(values)) / len(values) if values else 0.0
        for name, values in dimensions.items()
    }
    duplicates = {name: sorted({value for value in values if values.count(value) > 1}) for name, values in dimensions.items()}
    # A shared clock is legitimate: Topline Tony and the market desk may both
    # discuss the current week while answering different questions.  The
    # information contract, question, and reporter identity therefore carry
    # the score; the lens ratio remains a diagnostic detail.
    weighted_score = (
        ratios["reporter_ids"] * 0.4
        + ratios["information_scopes"] * 0.3
        + ratios["primary_questions"] * 0.3
    )
    return _metric("scored", weighted_score, distinctness_ratios=ratios, duplicates=duplicates)


def _usefulness(run: Mapping[str, Any]) -> dict[str, Any]:
    observations = [row for row in (run.get("outcome_observations") or []) if isinstance(row, Mapping)]
    resolved = [row for row in observations if str(row.get("result") or "").lower() in {"correct", "incorrect", "mixed"}]
    if not resolved:
        return _metric("not_scored", reason="no observed recommendation outcomes are recorded")
    points = sum(1.0 if str(row.get("result")).lower() == "correct" else 0.5 if str(row.get("result")).lower() == "mixed" else 0.0 for row in resolved)
    return _metric("scored", points / len(resolved), resolved_count=len(resolved), unresolved_count=len(observations) - len(resolved))


def _execution_receipts(run: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    receipts = [row for row in (run.get("execution_receipts") or []) if isinstance(row, Mapping)]
    if not receipts:
        return _metric("not_scored", reason="no per-job timing or usage receipts supplied")
    durations = [float(row["duration_ms"]) for row in receipts if row.get("duration_ms") not in (None, "")]
    if not durations:
        return _metric("not_scored", reason="execution receipts have no duration_ms")
    return _metric("scored", 1.0, receipt_count=len(receipts), duration_ms_total=round(sum(durations), 2), duration_ms_max=round(max(durations), 2))


def evaluate_run(
    run: Mapping[str, Any],
    *,
    expected_article_keys: Sequence[str] = DEFAULT_EXPECTED_ARTICLES,
    global_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    article_reports = [
        evaluate_article(
            article,
            global_evidence=global_evidence,
            reality_check_packet=run.get("reality_check_packet") if isinstance(run.get("reality_check_packet"), Mapping) else None,
        )
        for article in (run.get("articles") or [])
        if isinstance(article, Mapping)
    ]
    by_key = {report["article_key"]: report for report in article_reports}
    missing = sorted(set(expected_article_keys) - set(by_key))
    errors = [f"Missing expected article: {key}" for key in missing]
    errors.extend(error for report in article_reports for error in report.get("errors", []))
    voice = _voice_distinctness(article_reports)
    metrics = {
        "evidence_coverage": _average_metric(article_reports, "evidence_coverage"),
        "source_trace_coverage": _average_metric(article_reports, "source_trace_coverage"),
        "horizon_alignment": _average_metric(article_reports, "horizon_alignment"),
        "unsupported_certainty": _average_metric(article_reports, "unsupported_certainty"),
        "claim_register": _average_metric(article_reports, "claim_register"),
        "voice_distinctness": voice,
        "usefulness": _usefulness(run),
        "execution_receipts": _execution_receipts(run, article_reports),
    }
    quality_not_scored = [
        name
        for name in (
            "evidence_coverage",
            "horizon_alignment",
            "unsupported_certainty",
            "claim_register",
            "voice_distinctness",
            "usefulness",
            "execution_receipts",
        )
        if metrics[name].get("status") == "not_scored"
    ]
    status = "fail" if errors else "partial" if quality_not_scored else "pass"
    return {
        "run_id": str(run.get("run_id") or "unnamed-run"),
        "label": str(run.get("label") or run.get("run_id") or "Unnamed run"),
        "model": str(run.get("model") or ""),
        "reasoning_effort": str(run.get("reasoning_effort") or ""),
        "status": status,
        "errors": list(dict.fromkeys(errors)),
        "missing_articles": missing,
        "article_count": len(article_reports),
        "metrics": metrics,
        "articles": article_reports,
    }


def evaluate_newsroom_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one or more runs against the same frozen evidence fixture."""

    global_evidence = {
        str(row.get("evidence_id")): dict(row)
        for row in (fixture.get("evidence") or [])
        if isinstance(row, Mapping) and str(row.get("evidence_id") or "").strip()
    }
    expected = tuple(str(key) for key in (fixture.get("expected_article_keys") or DEFAULT_EXPECTED_ARTICLES))
    runs = fixture.get("runs") or [fixture]
    reports = [evaluate_run(run, expected_article_keys=expected, global_evidence=global_evidence) for run in runs if isinstance(run, Mapping)]
    comparison: list[dict[str, Any]] = []
    if reports:
        baseline = reports[0]
        for report in reports[1:]:
            deltas: dict[str, float] = {}
            for metric_name, baseline_metric in baseline.get("metrics", {}).items():
                candidate_metric = report.get("metrics", {}).get(metric_name, {})
                if baseline_metric.get("score") is not None and candidate_metric.get("score") is not None:
                    deltas[metric_name] = round(float(candidate_metric["score"]) - float(baseline_metric["score"]), 3)
            comparison.append({"baseline_run_id": baseline["run_id"], "candidate_run_id": report["run_id"], "metric_deltas": deltas})
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "fixture_id": str(fixture.get("fixture_id") or "unnamed-fixture"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": reports,
        "comparison": comparison,
    }
