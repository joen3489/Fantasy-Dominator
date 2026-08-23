"""Small provider boundary for structured Front Office writer calls.

The writing layer should know about a tool contract and evidence packet, not
about one vendor's request and response shape. Keeping this adapter tiny keeps
the compatibility path available while making OpenAI Luna the default writer.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

import requests


OPENAI_API_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    reasoning_effort: str
    api_key_env: str


def configured_llm(model: str | None = None) -> LLMConfig:
    """Resolve the provider without making a network call.

    Production defaults to OpenAI Luna. Anthropic remains available when the
    provider or a legacy Claude model is explicitly configured. A model slug
    beginning with ``gpt-`` also selects OpenAI, which makes direct callers
    unambiguous during migration.
    """

    requested_provider = os.environ.get("FRONT_OFFICE_LLM_PROVIDER", "").strip().lower()
    explicit_model = str(model or "").strip()
    legacy_model = os.environ.get("FRONT_OFFICE_INSIGHT_MODEL", "").strip()
    requested_model = explicit_model or legacy_model
    if not requested_provider:
        if requested_model and not requested_model.startswith("gpt-"):
            requested_provider = "anthropic"
        else:
            requested_provider = "openai"
    if requested_provider not in {"anthropic", "openai"}:
        raise ValueError(f"Unsupported FRONT_OFFICE_LLM_PROVIDER: {requested_provider}")

    if requested_provider == "openai":
        configured_model = os.environ.get("FRONT_OFFICE_LLM_MODEL", "").strip()
        resolved_model = configured_model or (requested_model if requested_model.startswith("gpt-") else DEFAULT_OPENAI_MODEL)
        effort = os.environ.get("FRONT_OFFICE_LLM_REASONING_EFFORT", "medium").strip().lower() or "medium"
        return LLMConfig("openai", resolved_model, effort, "OPENAI_API_KEY")

    resolved_model = requested_model or DEFAULT_ANTHROPIC_MODEL
    return LLMConfig("anthropic", resolved_model, "", "ANTHROPIC_API_KEY")


def writer_api_configuration() -> dict[str, Any]:
    """Return safe configuration status for health and authenticated UI views."""

    config = configured_llm()
    return {
        "provider": config.provider,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "api_key_env": config.api_key_env,
        "configured": bool(os.environ.get(config.api_key_env, "").strip()),
    }


def call_structured_tool(
    *,
    system_prompt: str,
    evidence: list[dict[str, Any]],
    api_key: str,
    model: str,
    tool: dict[str, Any],
    timeout: int = 60,
    request_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Call one provider and return the forced structured tool payload."""

    post = request_post or requests.post
    config = configured_llm(model)
    if config.provider == "openai":
        return _call_openai(post, config, system_prompt, evidence, api_key, tool, timeout)
    return _call_anthropic(post, config, system_prompt, evidence, api_key, tool, timeout)


def _call_anthropic(
    post: Callable[..., Any],
    config: LLMConfig,
    system_prompt: str,
    evidence: list[dict[str, Any]],
    api_key: str,
    tool: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    response = post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": config.model,
            "max_tokens": 8192,
            "system": system_prompt,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
            "messages": [{"role": "user", "content": json.dumps({"evidence": evidence})}],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("stop_reason") == "max_tokens":
        raise ValueError("Anthropic response was truncated at the token limit before finishing the structured output.")
    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == tool["name"]:
            payload = block.get("input", {})
            return payload if isinstance(payload, dict) else {}
    raise ValueError(f"Anthropic response did not include a {tool['name']} tool call.")


def _call_openai(
    post: Callable[..., Any],
    config: LLMConfig,
    system_prompt: str,
    evidence: list[dict[str, Any]],
    api_key: str,
    tool: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    function_tool = {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", "Return the requested structured output."),
        "parameters": _strict_schema(tool.get("input_schema", {"type": "object", "properties": {}})),
        "strict": True,
    }
    response = post(
        OPENAI_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        json={
            "model": config.model,
            "reasoning": {"effort": config.reasoning_effort},
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"evidence": evidence})},
            ],
            "tools": [function_tool],
            "tool_choice": {"type": "function", "name": tool["name"]},
            "parallel_tool_calls": False,
            "store": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    for item in body.get("output", []):
        if item.get("type") == "function_call" and item.get("name") == tool["name"]:
            try:
                payload = json.loads(item.get("arguments") or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("OpenAI function-call arguments were not valid JSON.") from exc
            return payload if isinstance(payload, dict) else {}
    raise ValueError(f"OpenAI response did not include a {tool['name']} function call.")


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make the existing tool schemas valid for strict Responses calls."""

    result = deepcopy(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}}
    _tighten_object_schema(result)
    return result


def _tighten_object_schema(node: Any) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
            for child in properties.values():
                _tighten_object_schema(child)
    elif node.get("type") == "array":
        _tighten_object_schema(node.get("items"))
