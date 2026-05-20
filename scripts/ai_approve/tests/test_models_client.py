"""Tests for models_client — thin GitHub Models HTTP wrapper.

We mock `requests.post`. The wrapper is responsible for:
- Building the request (URL, headers, body)
- Parsing the JSON response
- Returning a typed result with rate-limit info
- Raising on transport errors
"""
from unittest.mock import MagicMock, patch

import pytest

from ai_approve.models_client import (
    ModelsHTTPError,
    ModelsResult,
    ModelsSchemaError,
    RateLimitedError,
    chat_completion,
)


def make_response(status=200, json_body=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = json_body or {}
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"http {status}")
    return r


def test_successful_call_returns_parsed_content():
    body = {
        "choices": [{"message": {"content": '{"complexity": "trivial"}'}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    with patch("ai_approve.models_client.requests.post", return_value=make_response(json_body=body)):
        result = chat_completion(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], token="t", tools=None,
        )
    assert isinstance(result, ModelsResult)
    assert result.content == '{"complexity": "trivial"}'
    assert result.input_tokens == 100
    assert result.output_tokens == 20


def test_429_raises_rate_limited_error():
    with patch("ai_approve.models_client.requests.post", return_value=make_response(status=429)):
        with pytest.raises(RateLimitedError):
            chat_completion(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}], token="t", tools=None,
            )


def test_500_raises_http_error():
    with patch("ai_approve.models_client.requests.post", return_value=make_response(status=500)):
        with pytest.raises(ModelsHTTPError):
            chat_completion(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}], token="t", tools=None,
            )


def test_rate_limit_headers_captured():
    body = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    headers = {
        "x-ratelimit-remaining-requests": "47",
        "x-ratelimit-limit-requests": "50",
    }
    with patch("ai_approve.models_client.requests.post", return_value=make_response(json_body=body, headers=headers)):
        result = chat_completion(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], token="t", tools=None,
        )
    assert result.rate_limit_remaining == 47
    assert result.rate_limit_total == 50


def test_tool_call_response_returns_tool_calls():
    body = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}
                ],
            }
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }
    with patch("ai_approve.models_client.requests.post", return_value=make_response(json_body=body)):
        result = chat_completion(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], token="t",
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["function"]["name"] == "read_file"


def test_response_format_included_in_payload():
    # Regression: if a refactor accidentally drops the `response_format`
    # passthrough, structured-output Pass 1/2/critique calls would silently
    # degrade to free-form JSON. This test captures the actual call kwargs
    # and asserts the field made it into the POST body.
    body = {"choices": [{"message": {"content": "{}"}}], "usage": {}}
    fmt = {"type": "json_schema", "json_schema": {"name": "out", "schema": {"type": "object"}}}
    with patch("ai_approve.models_client.requests.post", return_value=make_response(json_body=body)) as mock_post:
        chat_completion(
            model="gpt-4o-mini", messages=[], token="t", tools=None, response_format=fmt,
        )
    sent = mock_post.call_args.kwargs["json"]
    assert sent["response_format"] == fmt


def test_response_format_omitted_when_not_passed():
    body = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    with patch("ai_approve.models_client.requests.post", return_value=make_response(json_body=body)) as mock_post:
        chat_completion(
            model="gpt-4o-mini", messages=[], token="t", tools=None,
        )
    sent = mock_post.call_args.kwargs["json"]
    assert "response_format" not in sent
