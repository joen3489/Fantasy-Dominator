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


DEFAULT_PERSONA_ID = "front_office"

REPORTER_PERSONAS: dict[str, ReporterPersona] = {
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


def normalize_writer_preferences(value: Any) -> dict[str, Any]:
    """Return a safe, backward-compatible preference payload for one league."""

    preferences = deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    persona_id = str(preferences.get("persona_id") or DEFAULT_PERSONA_ID).strip().lower()
    if persona_id not in REPORTER_PERSONAS:
        persona_id = DEFAULT_PERSONA_ID
    custom_instructions = str(preferences.get("custom_instructions") or "").strip()
    preferences["persona_id"] = persona_id
    preferences["custom_instructions"] = custom_instructions[:800]
    return preferences


def resolve_reporter_persona(value: Any = None) -> ReporterPersona:
    preferences = normalize_writer_preferences(value)
    return REPORTER_PERSONAS[preferences["persona_id"]]


def persona_prompt_block(value: Any = None) -> str:
    """Render only the voice contract; shared safety rules are appended by callers."""

    preferences = normalize_writer_preferences(value)
    persona = REPORTER_PERSONAS[preferences["persona_id"]]
    custom = preferences.get("custom_instructions", "")
    lines = [
        f"Reporter persona: {persona.name}.",
        f"Persona contract: {persona.voice_contract}",
        "The persona controls tone and emphasis only; it never overrides evidence, citations, or safety rules.",
    ]
    if custom:
        lines.append(f"Editor note for this league: {custom}")
    return "\n".join(lines)


def public_reporter_personas() -> list[dict[str, str]]:
    """Return the selector-safe persona catalog for authenticated UI surfaces."""

    return [
        {
            "persona_id": persona.persona_id,
            "name": persona.name,
            "description": persona.description,
        }
        for persona in REPORTER_PERSONAS.values()
    ]


def persona_metadata(value: Any = None) -> dict[str, str]:
    persona = resolve_reporter_persona(value)
    return {
        "persona_id": persona.persona_id,
        "name": persona.name,
        "description": persona.description,
    }
