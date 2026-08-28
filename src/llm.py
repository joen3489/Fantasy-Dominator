"""Small provider boundary for structured Front Office writer calls.

The writing layer should know about a tool contract and evidence packet, not
about one vendor's request and response shape. Keeping this adapter tiny keeps
the compatibility path available while making OpenAI Luna the default writer.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

import requests


OPENAI_API_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_LLM_TIMEOUT_SECONDS = 120
_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


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
        effort = os.environ.get("FRONT_OFFICE_LLM_REASONING_EFFORT", "max").strip().lower() or "max"
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
        "timeout_seconds": llm_timeout_seconds(),
        "api_key_env": config.api_key_env,
        "configured": bool(os.environ.get(config.api_key_env, "").strip()),
    }


def llm_timeout_seconds() -> int:
    """Return the bounded per-request timeout for a structured writer call.

    Luna with maximum reasoning can legitimately take longer than the old
    one-minute default. Keep the setting visible and bounded so a deployment
    cannot accidentally turn a single desk into an unbounded background job.
    """

    raw = os.environ.get("FRONT_OFFICE_LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        return min(300, max(30, int(raw)))
    except ValueError:
        return DEFAULT_LLM_TIMEOUT_SECONDS


def call_structured_tool(
    *,
    system_prompt: str,
    evidence: list[dict[str, Any]],
    api_key: str,
    model: str,
    tool: dict[str, Any],
    editorial_context: list[dict[str, Any]] | None = None,
    reasoning_effort: str | None = None,
    prompt_cache_key: str | None = None,
    safety_identifier: str | None = None,
    timeout: int | None = None,
    request_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Call one provider and return the forced structured tool payload."""

    post = request_post or requests.post
    config = configured_llm(model)
    request_timeout = llm_timeout_seconds() if timeout is None else timeout
    context = editorial_context or []
    if config.provider == "openai":
        return _call_openai(
            post,
            config,
            system_prompt,
            evidence,
            context,
            api_key,
            tool,
            request_timeout,
            reasoning_effort=reasoning_effort,
            prompt_cache_key=prompt_cache_key,
            safety_identifier=safety_identifier,
        )
    return _call_anthropic(post, config, system_prompt, evidence, context, api_key, tool, request_timeout)


def _call_anthropic(
    post: Callable[..., Any],
    config: LLMConfig,
    system_prompt: str,
    evidence: list[dict[str, Any]],
    editorial_context: list[dict[str, Any]],
    api_key: str,
    tool: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    response = _post_with_retry(
        post,
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
            "messages": [{"role": "user", "content": json.dumps({"evidence": evidence, "editorial_context": editorial_context})}],
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
            if not isinstance(payload, dict):
                return {}
            return payload | {
                "_provider_receipt": {
                    "provider": config.provider,
                    "model": config.model,
                    "usage": body.get("usage") if isinstance(body.get("usage"), dict) else {},
                    **_response_telemetry(response),
                }
            }
    raise ValueError(f"Anthropic response did not include a {tool['name']} tool call.")


def _call_openai(
    post: Callable[..., Any],
    config: LLMConfig,
    system_prompt: str,
    evidence: list[dict[str, Any]],
    editorial_context: list[dict[str, Any]],
    api_key: str,
    tool: dict[str, Any],
    timeout: int,
    *,
    reasoning_effort: str | None = None,
    prompt_cache_key: str | None = None,
    safety_identifier: str | None = None,
) -> dict[str, Any]:
    function_tool = {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", "Return the requested structured output."),
        "parameters": _strict_schema(tool.get("input_schema", {"type": "object", "properties": {}})),
        "strict": True,
    }
    effective_effort = str(reasoning_effort or config.reasoning_effort or "").strip().lower()
    cache_key = str(prompt_cache_key or "").strip()[:64]
    safe_identifier = str(safety_identifier or "").strip()[:64]
    request_json: dict[str, Any] = {
        "model": config.model,
        "reasoning": {"effort": effective_effort},
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"evidence": evidence, "editorial_context": editorial_context})},
        ],
        "tools": [function_tool],
        "tool_choice": {"type": "function", "name": tool["name"]},
        "parallel_tool_calls": False,
        "store": False,
    }
    if cache_key:
        # The stable key keeps cache bucketing private to the selected app
        # scope. The static system prompt is intentionally before dynamic
        # evidence so repeated editions can reuse its prefix.
        request_json["prompt_cache_key"] = cache_key
        request_json["prompt_cache_options"] = {"mode": "implicit", "ttl": "30m"}
    if safe_identifier:
        request_json["safety_identifier"] = safe_identifier

    response = _post_with_retry(
        post,
        OPENAI_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        json=request_json,
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
            if not isinstance(payload, dict):
                return {}
            return payload | {
                "_provider_receipt": {
                    "provider": config.provider,
                    "model": config.model,
                    "reasoning_effort": effective_effort,
                    "prompt_cache_key": cache_key,
                    "cached_tokens": _cached_tokens(body.get("usage")),
                    "usage": body.get("usage") if isinstance(body.get("usage"), dict) else {},
                    **_response_telemetry(response),
                }
            }
    raise ValueError(f"OpenAI response did not include a {tool['name']} function call.")


def _cached_tokens(usage: Any) -> int:
    """Extract the provider's cache-hit count without assuming one usage shape."""

    if not isinstance(usage, Mapping):
        return 0
    details = usage.get("input_tokens_details")
    if not isinstance(details, Mapping):
        details = usage.get("prompt_tokens_details")
    if not isinstance(details, Mapping):
        return 0
    try:
        return max(0, int(details.get("cached_tokens") or 0))
    except (TypeError, ValueError):
        return 0


def _post_with_retry(
    post: Callable[..., Any],
    url: str,
    *,
    timeout: int,
    attempts: int = 3,
    **kwargs: Any,
) -> Any:
    """Retry bounded transient provider failures without masking a final error.

    A newsroom run can make several sequential structured calls. A single
    transient rate-limit or gateway response should not turn the whole issue
    into silent deterministic fallback content, but retries must remain bounded
    so a real provider failure returns to the editor receipt promptly.
    """

    response: Any = None
    started = time.monotonic()
    for attempt in range(max(1, int(attempts))):
        response = post(url, timeout=timeout, **kwargs)
        # ``requests.Response`` permits instance attributes and the test
        # doubles do too. Keeping retry timing on the response means the
        # provider adapter can expose one safe receipt shape without changing
        # the caller-facing return contract.
        try:
            response._front_office_attempts = attempt + 1
            response._front_office_elapsed_ms = round((time.monotonic() - started) * 1000)
        except (AttributeError, TypeError):
            pass
        status_code = getattr(response, "status_code", None)
        if status_code not in _RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
            return response
        delay = _retry_after_seconds(response, attempt)
        time.sleep(delay)
    return response


def _response_telemetry(response: Any) -> dict[str, Any]:
    """Extract safe request telemetry without persisting prompts or payloads."""

    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        headers = {}
    request_id = (
        headers.get("x-request-id")
        or headers.get("request-id")
        or headers.get("X-Request-ID")
        or ""
    )
    processing_ms = headers.get("openai-processing-ms") or headers.get("x-processing-ms") or ""
    try:
        processing_ms = int(processing_ms) if str(processing_ms).strip() else None
    except (TypeError, ValueError):
        processing_ms = None
    receipt: dict[str, Any] = {
        "request_id": str(request_id or ""),
        "attempts": int(getattr(response, "_front_office_attempts", 1) or 1),
        "elapsed_ms": int(getattr(response, "_front_office_elapsed_ms", 0) or 0),
    }
    if processing_ms is not None:
        receipt["processing_ms"] = processing_ms
    return receipt


def _retry_after_seconds(response: Any, attempt: int) -> float:
    """Return a small, capped delay from a provider receipt."""

    try:
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After", "") if hasattr(headers, "get") else ""
        if retry_after:
            return min(10.0, max(1.0, float(retry_after)))
    except (TypeError, ValueError):
        pass
    return float(min(10, 2 ** (attempt + 1)))


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
