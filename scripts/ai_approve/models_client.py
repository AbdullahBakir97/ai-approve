"""Thin HTTP wrapper for GitHub Models inference.

Endpoint: https://models.inference.ai.azure.com/chat/completions
Auth: Bearer GITHUB_TOKEN
Free tier; rate-limited via x-ratelimit-* headers.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
import requests


ENDPOINT = "https://models.inference.ai.azure.com/chat/completions"
TIMEOUT_SECS = 90


class ModelsHTTPError(Exception):
    """Any non-200 non-429 response from GitHub Models."""


class RateLimitedError(Exception):
    """HTTP 429 from GitHub Models."""


class ModelsSchemaError(Exception):
    """Response didn't match the requested JSON schema."""


@dataclass
class ModelsResult:
    content: str | None
    tool_calls: list[dict] | None
    input_tokens: int
    output_tokens: int
    rate_limit_remaining: int | None
    rate_limit_total: int | None
    raw: dict


def chat_completion(
    *,
    model: str,
    messages: list[dict],
    token: str,
    tools: list[dict] | None,
    response_format: dict | None = None,
    temperature: float = 0.0,
    timeout: int = TIMEOUT_SECS,
) -> ModelsResult:
    """POST a chat completion request. Raise on 4xx/5xx (with 429 typed).

    `response_format` accepts OpenAI structured-outputs shape, e.g.:
        {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools is not None:
        payload["tools"] = tools
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=timeout)

    if resp.status_code == 429:
        raise RateLimitedError(f"GitHub Models rate-limited ({resp.status_code}): {resp.text[:300]}")
    if resp.status_code >= 400:
        raise ModelsHTTPError(f"GitHub Models {resp.status_code}: {resp.text[:500]}")

    body = resp.json()
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}

    def _to_int(s: str | None) -> int | None:
        try:
            return int(s) if s is not None else None
        except (TypeError, ValueError):
            return None

    return ModelsResult(
        content=msg.get("content"),
        tool_calls=msg.get("tool_calls"),
        input_tokens=(body.get("usage") or {}).get("prompt_tokens", 0),
        output_tokens=(body.get("usage") or {}).get("completion_tokens", 0),
        rate_limit_remaining=_to_int(resp.headers.get("x-ratelimit-remaining-requests")),
        rate_limit_total=_to_int(resp.headers.get("x-ratelimit-limit-requests")),
        raw=body,
    )
