"""Tests for hard_blocks borderline detection (Plan 2 addition)."""
from ai_approve.hard_blocks import evaluate


def base_pr(files_n: int = 0, lines_n: int = 0, **overrides):
    p = {
        "changed_files": [],
        "diff_added_lines": [],
        "diff_removed_lines": [],
        "files_changed": files_n,
        "lines_changed": lines_n,
    }
    p.update(overrides)
    return p


def test_normal_pr_not_borderline():
    result = evaluate(base_pr(files_n=10, lines_n=200))
    assert result["borderline"] is False
    assert result["borderline_reasons"] == []


def test_files_at_45_is_borderline():
    result = evaluate(base_pr(files_n=45, lines_n=100))
    assert result["borderline"] is True
    assert result["hard_blocked"] is False
    assert any("large-diff" in r for r in result["borderline_reasons"])


def test_lines_at_1800_is_borderline():
    result = evaluate(base_pr(files_n=10, lines_n=1800))
    assert result["borderline"] is True
    assert result["hard_blocked"] is False


def test_files_at_50_still_borderline_not_hard_block():
    # 50 is still in borderline range; > 50 hard-blocks
    result = evaluate(base_pr(files_n=50, lines_n=100))
    assert result["borderline"] is True
    assert result["hard_blocked"] is False


def test_files_at_51_hard_blocks_not_borderline():
    result = evaluate(base_pr(files_n=51, lines_n=100))
    assert result["hard_blocked"] is True
    assert result["borderline"] is False  # hard-block dominates


def test_hard_block_from_other_rule_clears_borderline_flag():
    # Even with borderline size, an actual hard-block elsewhere overrides
    pr = base_pr(files_n=46, lines_n=100,
                 changed_files=["backend/project/apps/users/migrations/0001.py"])
    result = evaluate(pr)
    assert result["hard_blocked"] is True
    assert result["borderline"] is False  # any hard block clears borderline
