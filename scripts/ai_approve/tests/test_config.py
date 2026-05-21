"""Tests for tier-aware trim caps (config.py)."""
from __future__ import annotations

import pytest

from ai_approve.config import FREE_CAPS, PAID_CAPS, TrimCaps, trim_caps


def test_free_caps_fit_8k_token_envelope():
    """Sum of all free-tier trim limits stays under ~32K chars (~8K tokens)."""
    worst_case = (
        FREE_CAPS.claude_md
        + FREE_CAPS.audit_doc
        + FREE_CAPS.diff_pass2
        + FREE_CAPS.deep_file * FREE_CAPS.deep_files
        + FREE_CAPS.body
    )
    assert worst_case <= 32_000, (
        f"Free-tier worst-case prompt = {worst_case} chars; exceeds the "
        "~32K-char (~8K-token) safety envelope for GH Models free tier."
    )


def test_free_caps_drop_claude_md():
    """CLAUDE.md is too big for the 8K cap — must be 0 on free tier."""
    assert FREE_CAPS.claude_md == 0


def test_paid_caps_lift_envelope():
    """Paid caps must be strictly larger across every dimension."""
    for field in ("claude_md", "audit_doc", "diff_pass2", "deep_file", "deep_files", "body"):
        assert getattr(PAID_CAPS, field) > getattr(FREE_CAPS, field), (
            f"PAID_CAPS.{field} ({getattr(PAID_CAPS, field)}) must exceed "
            f"FREE_CAPS.{field} ({getattr(FREE_CAPS, field)})"
        )


def test_trim_caps_defaults_to_free(monkeypatch):
    monkeypatch.delenv("AI_APPROVE_TIER", raising=False)
    assert trim_caps() is FREE_CAPS


def test_trim_caps_picks_paid_when_env_set(monkeypatch):
    monkeypatch.setenv("AI_APPROVE_TIER", "paid")
    assert trim_caps() is PAID_CAPS


@pytest.mark.parametrize("val", ["PAID", " paid ", "Paid"])
def test_trim_caps_normalizes_env_value(monkeypatch, val):
    monkeypatch.setenv("AI_APPROVE_TIER", val)
    assert trim_caps() is PAID_CAPS


@pytest.mark.parametrize("val", ["free", "", "unknown", "premium"])
def test_trim_caps_falls_back_to_free_on_unknown(monkeypatch, val):
    """Anything that isn't 'paid' (case-insensitive) means free — safe default."""
    monkeypatch.setenv("AI_APPROVE_TIER", val)
    assert trim_caps() is FREE_CAPS


def test_trim_caps_is_frozen_dataclass():
    """Caps must be immutable so callers can't mutate the shared profile."""
    with pytest.raises((AttributeError, TypeError)):
        FREE_CAPS.claude_md = 9999  # type: ignore[misc]


def test_trim_caps_returns_trimcaps_instance():
    assert isinstance(trim_caps(), TrimCaps)
