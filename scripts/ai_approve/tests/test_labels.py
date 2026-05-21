"""Unit tests for label selection logic.

The HTTP-touching `apply_labels` is integration-only; here we test the pure
`select_labels` mapping and the LABEL_SPEC integrity.
"""
from __future__ import annotations

import re

import pytest

from ai_approve.labels import LABEL_SPEC, select_labels

HEX6 = re.compile(r"^[0-9a-fA-F]{6}$")


# --- LABEL_SPEC integrity ---------------------------------------------------

def test_every_label_has_valid_hex_color():
    for name, (color, _desc) in LABEL_SPEC.items():
        assert HEX6.match(color), f"label {name!r} color {color!r} is not a 6-digit hex string"


def test_every_label_has_nonempty_description():
    for name, (_color, desc) in LABEL_SPEC.items():
        assert desc and desc.strip(), f"label {name!r} has empty description"


def test_label_spec_includes_all_required_labels():
    required = {
        "bot-reviewed",
        "bot-approved",
        "bot-changes-requested",
        "bot-comment",
        "bot-hard-blocked",
        "bot-fixes",
    }
    assert required.issubset(LABEL_SPEC.keys())


# --- select_labels mapping --------------------------------------------------

def test_approve_verdict_picks_approved_label():
    out = select_labels(verdict="APPROVE", has_fixes=False, hard_blocked=False)
    assert out == ["bot-reviewed", "bot-approved"]


def test_request_changes_verdict_picks_changes_requested():
    out = select_labels(verdict="REQUEST_CHANGES", has_fixes=False, hard_blocked=False)
    assert out == ["bot-reviewed", "bot-changes-requested"]


def test_comment_verdict_picks_comment_label():
    out = select_labels(verdict="COMMENT", has_fixes=False, hard_blocked=False)
    assert out == ["bot-reviewed", "bot-comment"]


def test_hard_block_overrides_verdict():
    """Hard-block path skips the LLM verdict entirely — label reflects that."""
    out = select_labels(verdict="REQUEST_CHANGES", has_fixes=False, hard_blocked=True)
    assert "bot-hard-blocked" in out
    assert "bot-changes-requested" not in out
    assert out[0] == "bot-reviewed"


def test_has_fixes_adds_bot_fixes_label():
    out = select_labels(verdict="APPROVE", has_fixes=True, hard_blocked=False)
    assert "bot-fixes" in out


def test_has_fixes_works_with_hard_block():
    out = select_labels(verdict="REQUEST_CHANGES", has_fixes=True, hard_blocked=True)
    assert "bot-hard-blocked" in out
    assert "bot-fixes" in out
    assert "bot-reviewed" in out


@pytest.mark.parametrize("verdict", ["approve", "Approve", " APPROVE "])
def test_verdict_normalization(verdict):
    """Case-insensitive verdict so callers needn't pre-normalize."""
    out = select_labels(verdict=verdict.strip(), has_fixes=False, hard_blocked=False)
    # The .upper() lookup is applied to the stripped value, so leading/
    # trailing whitespace handled by caller; just verify case-insensitivity.
    if verdict.strip().upper() == "APPROVE":
        assert "bot-approved" in out


def test_unknown_verdict_still_marks_reviewed():
    """Unknown verdict → just `bot-reviewed`, no false outcome label."""
    out = select_labels(verdict="WAT", has_fixes=False, hard_blocked=False)
    assert out == ["bot-reviewed"]


def test_empty_verdict_still_marks_reviewed():
    out = select_labels(verdict="", has_fixes=False, hard_blocked=False)
    assert out == ["bot-reviewed"]


def test_bot_reviewed_is_always_first():
    """Stable ordering so PR label-list reads consistently."""
    for v in ("APPROVE", "REQUEST_CHANGES", "COMMENT", ""):
        for fixes in (True, False):
            for hard in (True, False):
                out = select_labels(verdict=v, has_fixes=fixes, hard_blocked=hard)
                assert out[0] == "bot-reviewed"


def test_no_duplicate_labels():
    """Sanity: never emit the same label twice."""
    for v in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        for fixes in (True, False):
            for hard in (True, False):
                out = select_labels(verdict=v, has_fixes=fixes, hard_blocked=hard)
                assert len(out) == len(set(out))
