"""Tests for reasoning.evaluate_borderline — mocked DeepSeek-R1."""
import json
from unittest.mock import MagicMock, patch

from ai_approve.reasoning import evaluate_borderline


def test_proceed_returns_false_for_hard_block():
    fake = MagicMock(
        content=json.dumps({"decision": "proceed", "reasoning": "looks fine"}),
        tool_calls=None,
        input_tokens=200,
        output_tokens=80,
        rate_limit_remaining=None,
        raw={},
    )
    with patch("ai_approve.reasoning.chat_completion", return_value=fake):
        decision = evaluate_borderline(
            borderline_reasons=["large_diff at 48 files"],
            pr={"title": "x", "files_changed": 48, "lines_changed": 1900},
            token="t",
        )
    assert decision["should_hard_block"] is False


def test_escalate_returns_true_for_hard_block():
    fake = MagicMock(
        content=json.dumps(
            {
                "decision": "escalate_to_hard_block",
                "reasoning": "diff spans 48 unrelated apps",
            }
        ),
        tool_calls=None,
        input_tokens=200,
        output_tokens=80,
        rate_limit_remaining=None,
        raw={},
    )
    with patch("ai_approve.reasoning.chat_completion", return_value=fake):
        decision = evaluate_borderline(
            borderline_reasons=["large_diff"],
            pr={"title": "x"},
            token="t",
        )
    assert decision["should_hard_block"] is True
    assert "unrelated apps" in decision["reasoning"]


def test_llm_crash_defaults_to_hard_block_conservative():
    with patch(
        "ai_approve.reasoning.chat_completion", side_effect=Exception("crash")
    ):
        decision = evaluate_borderline(
            borderline_reasons=["large_diff"],
            pr={"title": "x"},
            token="t",
        )
    assert decision["should_hard_block"] is True
    assert "unavailable" in decision["reasoning"].lower()
