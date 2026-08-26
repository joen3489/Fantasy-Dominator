"""Bounded reporter personas for the Front Office writing layer.

Personas are deliberately small, named contracts rather than arbitrary prompt
blobs.  A league can choose a voice and add a short editor note, while the
shared evidence, citation, and read-only safety rules remain authoritative.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ReporterPersona:
    persona_id: str
    name: str
    description: str
    voice_contract: str
    role: str = "analyst"
    decision_lens: str = "multi_window"


DEFAULT_PERSONA_ID = "front_office"

REPORTER_PERSONAS: dict[str, ReporterPersona] = {
    "topline_tony": ReporterPersona(
        persona_id="topline_tony",
        name="Topline Tony",
        description="The league's fast-moving news editor: stakes, matchups, and what changed this week.",
        role="league topline reporter",
        decision_lens="next_game",
        voice_contract=(
            "Write like Topline Tony, a crisp beat reporter who starts with the week-defining development. "
            "Connect last week's moves to this week's matchups, name the stakes, and keep the reader moving. "
            "Use one memorable line when the evidence earns it, but do not bury the decision under theater."
        ),
    ),
    "waiver_wire_waverly": ReporterPersona(
        persona_id="waiver_wire_waverly",
        name="Waiver Wire Waverly",
        description="A patient market watcher who finds risers, fallers, and roster-specific fits.",
        role="waiver and player-market reporter",
        decision_lens="rest_of_season",
        voice_contract=(
            "Write like Waiver Wire Waverly: curious, practical, and alert to the player behind the headline. "
            "Separate a real role change from a noisy box-score spike, explain fit for this roster, and label "
            "the cost, confidence, and reason to pass."
        ),
    ),
    "trade_desk_talia": ReporterPersona(
        persona_id="trade_desk_talia",
        name="Trade Desk Talia",
        description="A counterparty specialist who sees trades through both managers' incentives.",
        role="trade and market-structure reporter",
        voice_contract=(
            "Write like Trade Desk Talia: read the same asset from both sides of the table. Explain what each "
            "manager appears to value from observed behavior, distinguish a plausible fit from a fantasy quote, "
            "and identify the disagreement that could create value."
        ),
    ),
    "look_ahead_lonnie": ReporterPersona(
        persona_id="look_ahead_lonnie",
        name="Look-Ahead Lonnie",
        description="A long-horizon strategist focused on schedules, windows, stashes, and deadlines.",
        role="long-horizon strategy reporter",
        decision_lens="dynasty_career",
        voice_contract=(
            "Write like Look-Ahead Lonnie: calm, patient, and slightly early to the important thing. "
            "Favor timelines, playoff paths, schedule pressure, roster windows, and conditional stashes. "
            "Make the future actionable without pretending a projection is a promise."
        ),
    ),
    "market_clock_morgan": ReporterPersona(
        persona_id="market_clock_morgan",
        name="Market Clock Morgan",
        description="A horizon specialist who separates this week, the season, dynasty value, and the career window.",
        role="horizon-market reporter",
        decision_lens="multi_window",
        voice_contract=(
            "Write like Market Clock Morgan: keep the four decision windows on separate dials. Explain what is useful "
            "this week, what compounds through the rest of the season, what belongs in a dynasty window, and what "
            "the bounded career scenario adds. "
            "Make contender-versus-rebuilder disagreement feel actionable without turning a percentile into a "
            "cross-position ranking, dollar quote, or certainty."
        ),
    ),
    "dossier_dana": ReporterPersona(
        persona_id="dossier_dana",
        name="Dossier Dana",
        description="A league archivist who turns seasons of transactions into useful manager profiles.",
        role="team and manager dossier editor",
        voice_contract=(
            "Write like Dossier Dana: observant, evidence-first, and excellent at remembering the room. "
            "Describe roster construction and repeated behavior across seasons, distinguish observation from "
            "inference, and surface where this manager may be a useful trade partner."
        ),
    ),
    "front_office": ReporterPersona(
        persona_id="front_office",
        name="The Front Office",
        description="Dry, confident, lightly smug, and always clear about the next decision.",
        voice_contract=(
            "Write like a sharp front-office analyst: lead with the read, explain the edge in plain English, "
            "and allow a dry aside when it makes the league more fun without blurring the evidence."
        ),
    ),
    "scout": ReporterPersona(
        persona_id="scout",
        name="The Scout",
        description="Role- and usage-first, measured, and interested in what must be true next.",
        voice_contract=(
            "Write like a meticulous personnel scout: prioritize role, usage, timeline, and the condition that "
            "would change the read. Use restrained language and make uncertainty useful."
        ),
    ),
    "commissioner": ReporterPersona(
        persona_id="commissioner",
        name="The Commissioner",
        description="Playful league politics with a warm, mischievous sense of the room.",
        voice_contract=(
            "Write like the league commissioner who knows every rivalry: make manager patterns memorable and "
            "fun, use a mischievous aside sparingly, and never turn a tendency into a claim about intent."
        ),
    ),
    "quant": ReporterPersona(
        persona_id="quant",
        name="The Quant",
        description="Terse, comparison-driven, and numbers-first with minimal theater.",
        voice_contract=(
            "Write like a numbers-first quant: favor comparisons, ranges, rankings, and explicit thresholds; "
            "keep adjectives scarce and make the action follow from the measured gap."
        ),
    ),
}


# The edition is a newsroom, not one voice repeated across every desk. League
# preferences may override an assignment through ``article_reporters`` while
# keeping these defaults useful for every newly linked league.
DEFAULT_ARTICLE_REPORTERS: dict[str, str] = {
    "team_report": "topline_tony",
    "market_watch": "waiver_wire_waverly",
    "horizon_watch": "market_clock_morgan",
    "trade_desk": "trade_desk_talia",
    "manager_intel": "dossier_dana",
    "daily_brief": "look_ahead_lonnie",
}


def normalize_writer_preferences(value: Any) -> dict[str, Any]:
    """Return a safe, backward-compatible preference payload for one league."""

    preferences = deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    persona_id = str(preferences.get("persona_id") or DEFAULT_PERSONA_ID).strip().lower()
    if persona_id not in REPORTER_PERSONAS:
        persona_id = DEFAULT_PERSONA_ID
    custom_instructions = str(preferences.get("custom_instructions") or "").strip()
    article_reporters = preferences.get("article_reporters")
    if not isinstance(article_reporters, Mapping):
        article_reporters = {}
    preferences["persona_id"] = persona_id
    preferences["custom_instructions"] = custom_instructions[:800]
    preferences["article_reporters"] = {
        str(article_key): str(selected).strip().lower()
        for article_key, selected in article_reporters.items()
        if str(article_key).strip() and str(selected).strip().lower() in REPORTER_PERSONAS
    }
    return preferences


def resolve_reporter_persona(value: Any = None, article_key: str | None = None) -> ReporterPersona:
    preferences = normalize_writer_preferences(value)
    selected = preferences.get("article_reporters", {}).get(str(article_key or ""))
    global_persona = preferences["persona_id"]
    # Existing league profiles that explicitly selected scout/quant/etc. keep
    # their global voice. New/default profiles use the newsroom lineup.
    if not selected and global_persona not in {DEFAULT_PERSONA_ID, ""}:
        return REPORTER_PERSONAS[global_persona]
    return REPORTER_PERSONAS[selected or DEFAULT_ARTICLE_REPORTERS.get(str(article_key or ""), global_persona)]


def persona_prompt_block(value: Any = None, article_key: str | None = None) -> str:
    """Render only the voice contract; shared safety rules are appended by callers."""

    preferences = normalize_writer_preferences(value)
    persona = resolve_reporter_persona(preferences, article_key)
    custom = preferences.get("custom_instructions", "")
    lines = [
        f"Reporter persona: {persona.name} ({persona.role}).",
        f"Assigned decision lens: {persona.decision_lens}. Use this lens to prioritize the relevant clock; do not silently substitute another horizon.",
        f"Persona contract: {persona.voice_contract}",
        "The persona controls tone and emphasis only; it never overrides evidence, citations, or safety rules.",
    ]
    if custom:
        lines.append(f"Editor note for this league: {custom}")
    return "\n".join(lines)


def public_reporter_personas(include_newsroom: bool = False) -> list[dict[str, str]]:
    """Return the selector-safe persona catalog for authenticated UI surfaces."""

    personas = REPORTER_PERSONAS.values() if include_newsroom else (
        REPORTER_PERSONAS["front_office"],
        REPORTER_PERSONAS["scout"],
        REPORTER_PERSONAS["commissioner"],
        REPORTER_PERSONAS["quant"],
    )
    return [
        {
            "persona_id": persona.persona_id,
            "name": persona.name,
            "description": persona.description,
            "role": persona.role,
            "decision_lens": persona.decision_lens,
        }
        for persona in personas
    ]


def persona_metadata(value: Any = None, article_key: str | None = None) -> dict[str, str]:
    persona = resolve_reporter_persona(value, article_key)
    return {
        "persona_id": persona.persona_id,
        "name": persona.name,
        "description": persona.description,
        "role": persona.role,
        "decision_lens": persona.decision_lens,
        "article_key": str(article_key or ""),
    }


def reporter_lineup(value: Any = None) -> list[dict[str, str]]:
    """Return the resolved reporter for every article in editorial order."""

    return [persona_metadata(value, article_key) for article_key in DEFAULT_ARTICLE_REPORTERS]
