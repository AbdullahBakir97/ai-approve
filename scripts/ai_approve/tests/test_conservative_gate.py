"""Tests for conservative_gate.final_verdict() — the single point of truth.

This is the safety contract that makes the bot fail-closed. Every
condition that could let an unsafe APPROVE through must be covered here.
"""
import pytest
from ai_approve.conservative_gate import final_verdict, VerifierState


def make_pass2(verdict="APPROVE", confidence=0.95, certainty="fully_understood"):
    return {
        "verdict": verdict,
        "confidence": confidence,
        "certainty": certainty,
        "summary": "ok",
        "comments": [],
        "fixes_to_push": [],
    }


def make_state(**overrides):
    defaults = {
        "llm_crashed": False,
        "timed_out": False,
        "rate_limited": False,
        "tool_calls_exhausted": False,
        "forbidden_phrase_present": False,
        "schema_validation_failed": False,
        "self_critique_flagged_concerns": False,
        "comments_with_severity_blocker": 0,
        "comments_with_severity_major": 0,
        "fixes_resolve_that_major_comment": False,
    }
    defaults.update(overrides)
    return VerifierState(**defaults)


def test_clean_approve_passes_through():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state()) == "APPROVE"


def test_hard_blocked_forces_request_changes():
    assert final_verdict(make_pass2(), hard_blocked=True, vs=make_state()) == "REQUEST_CHANGES"


def test_llm_crash_forces_comment():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(llm_crashed=True)) == "COMMENT"


def test_timeout_forces_comment():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(timed_out=True)) == "COMMENT"


def test_rate_limit_forces_comment():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(rate_limited=True)) == "COMMENT"


def test_tool_calls_exhausted_forces_request_changes():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(tool_calls_exhausted=True)) == "REQUEST_CHANGES"


def test_forbidden_phrase_forces_request_changes():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(forbidden_phrase_present=True)) == "REQUEST_CHANGES"


def test_schema_validation_failure_forces_comment():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(schema_validation_failed=True)) == "COMMENT"


def test_explicit_request_changes_honored():
    p = make_pass2(verdict="REQUEST_CHANGES")
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "REQUEST_CHANGES"


def test_explicit_comment_honored():
    p = make_pass2(verdict="COMMENT")
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "COMMENT"


def test_low_confidence_downgrades_approve_to_request_changes():
    p = make_pass2(confidence=0.7)
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "REQUEST_CHANGES"


def test_minor_uncertainty_downgrades_approve():
    p = make_pass2(certainty="minor_uncertainty")
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "REQUEST_CHANGES"


def test_significant_uncertainty_downgrades_approve():
    p = make_pass2(certainty="significant_uncertainty")
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "REQUEST_CHANGES"


def test_self_critique_concerns_downgrade_approve():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(self_critique_flagged_concerns=True)) == "REQUEST_CHANGES"


def test_any_blocker_severity_downgrades_approve():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(comments_with_severity_blocker=1)) == "REQUEST_CHANGES"


def test_two_major_comments_downgrade_approve():
    assert final_verdict(make_pass2(), hard_blocked=False, vs=make_state(comments_with_severity_major=2)) == "REQUEST_CHANGES"


def test_one_major_unresolved_downgrades_approve():
    vs = make_state(comments_with_severity_major=1, fixes_resolve_that_major_comment=False)
    assert final_verdict(make_pass2(), hard_blocked=False, vs=vs) == "REQUEST_CHANGES"


def test_confidence_at_threshold_approves():
    # 0.85 is the exact threshold — `< 0.85` should NOT fire.
    p = make_pass2(confidence=0.85)
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "APPROVE"


def test_confidence_just_below_threshold_blocks():
    p = make_pass2(confidence=0.8499)
    assert final_verdict(p, hard_blocked=False, vs=make_state()) == "REQUEST_CHANGES"


def test_hard_blocked_wins_over_llm_crash():
    # hard_blocked is deterministic policy; infra failures must not
    # downgrade it to a non-blocking COMMENT.
    vs = make_state(llm_crashed=True)
    assert final_verdict(make_pass2(), hard_blocked=True, vs=vs) == "REQUEST_CHANGES"


def test_hard_blocked_wins_over_schema_validation_failure():
    vs = make_state(schema_validation_failed=True)
    assert final_verdict(make_pass2(), hard_blocked=True, vs=vs) == "REQUEST_CHANGES"


def test_one_major_resolved_by_fixes_allows_approve():
    vs = make_state(comments_with_severity_major=1, fixes_resolve_that_major_comment=True)
    assert final_verdict(make_pass2(), hard_blocked=False, vs=vs) == "APPROVE"
