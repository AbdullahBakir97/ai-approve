"""Tests for branches.aggregator.aggregate_branch_verdicts()."""
from ai_approve.branches.aggregator import aggregate_branch_verdicts


def make_branch(verdict="APPROVE", confidence=0.95, certainty="fully_understood",
                summary="ok", comments=None, fixes=None):
    return {
        "verdict": verdict,
        "confidence": confidence,
        "certainty": certainty,
        "summary": summary,
        "comments": comments or [],
        "fixes_to_push": fixes or [],
    }


def test_single_branch_passes_through():
    result = aggregate_branch_verdicts({"standard": make_branch()})
    assert result["verdict"] == "APPROVE"
    assert result["confidence"] == 0.95


def test_strictest_verdict_wins_request_changes_over_approve():
    branches = {
        "standard": make_branch(verdict="APPROVE", confidence=0.95),
        "security": make_branch(verdict="REQUEST_CHANGES", confidence=0.80),
    }
    assert aggregate_branch_verdicts(branches)["verdict"] == "REQUEST_CHANGES"


def test_strictest_verdict_wins_comment_over_approve():
    branches = {
        "standard": make_branch(verdict="APPROVE"),
        "security": make_branch(verdict="COMMENT"),
    }
    assert aggregate_branch_verdicts(branches)["verdict"] == "COMMENT"


def test_strictest_verdict_wins_request_changes_over_comment():
    branches = {
        "standard": make_branch(verdict="COMMENT"),
        "migration_deep": make_branch(verdict="REQUEST_CHANGES"),
    }
    assert aggregate_branch_verdicts(branches)["verdict"] == "REQUEST_CHANGES"


def test_minimum_confidence_chosen():
    branches = {
        "standard": make_branch(verdict="APPROVE", confidence=0.95),
        "security": make_branch(verdict="APPROVE", confidence=0.75),
    }
    assert aggregate_branch_verdicts(branches)["confidence"] == 0.75


def test_comments_concatenate():
    branches = {
        "standard": make_branch(comments=[{"file": "a.py", "line": 1, "claim": "x", "severity": "warn"}]),
        "security": make_branch(comments=[{"file": "b.py", "line": 2, "claim": "y", "severity": "blocker"}]),
    }
    assert len(aggregate_branch_verdicts(branches)["comments"]) == 2


def test_duplicate_comments_deduped():
    same = {"file": "a.py", "line": 1, "claim": "unused import", "severity": "warn"}
    branches = {
        "standard": make_branch(comments=[same]),
        "security": make_branch(comments=[same]),
    }
    assert len(aggregate_branch_verdicts(branches)["comments"]) == 1


def test_branch_without_verdict_contributes_comments_only():
    branches = {
        "standard": make_branch(verdict="APPROVE", confidence=0.95),
        "cross_pr_conflict": {"comments": [{"file": "x.py", "line": 1, "claim": "overlaps PR #99", "severity": "info"}]},
    }
    result = aggregate_branch_verdicts(branches)
    assert result["verdict"] == "APPROVE"  # standard's verdict survives
    assert len(result["comments"]) == 1


def test_certainty_strictest_wins():
    branches = {
        "standard": make_branch(certainty="fully_understood"),
        "security": make_branch(certainty="minor_uncertainty"),
    }
    assert aggregate_branch_verdicts(branches)["certainty"] == "minor_uncertainty"


def test_fixes_dedupe_by_tool_and_target():
    branches = {
        "standard": make_branch(fixes=[{"tool": "ruff_format", "target_path": "x.py"}]),
        "security": make_branch(fixes=[{"tool": "ruff_format", "target_path": "x.py"}]),
    }
    assert len(aggregate_branch_verdicts(branches)["fixes_to_push"]) == 1


def test_empty_branches_dict():
    result = aggregate_branch_verdicts({})
    assert result["verdict"] == "COMMENT"
    assert result["confidence"] == 1.0
    assert result["comments"] == []


def test_aggregator_propagates_standard_telemetry():
    branches = {
        "standard": {
            "verdict": "APPROVE", "confidence": 0.9, "certainty": "fully_understood",
            "summary": "ok", "comments": [], "fixes_to_push": [],
            "tokens_in_total": 12345, "tokens_out_total": 678,
            "tool_calls_used": 5, "rate_limit_remaining": 47,
            "tool_calls_exhausted": False,
        },
        "security": {
            "verdict": "APPROVE", "confidence": 0.9, "certainty": "fully_understood",
            "summary": "ok", "comments": [], "fixes_to_push": [],
        },
    }
    result = aggregate_branch_verdicts(branches)
    assert result["tokens_in_total"] == 12345
    assert result["tokens_out_total"] == 678
    assert result["tool_calls_used"] == 5
    assert result["rate_limit_remaining"] == 47
    assert result["tool_calls_exhausted"] is False


def test_aggregator_handles_unknown_certainty_value_without_crashing():
    branches = {
        "standard": make_branch(certainty="fully_understood"),
        "security": make_branch(certainty="future_value_not_in_schema"),
    }
    # Should not raise TypeError. Unknown values rank as max-uncertain.
    result = aggregate_branch_verdicts(branches)
    assert result["certainty"] == "future_value_not_in_schema"
