"""Tests for branches.cross_pr — pure logic given a stubbed gh CLI."""
from unittest.mock import patch

from ai_approve.branches.cross_pr import find_conflicting_prs, run_cross_pr_branch


def test_no_other_open_prs_returns_empty():
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=[]):
        conflicts = find_conflicting_prs(
            repo="x/y", base="main", current_pr=42, current_files={"a.py", "b.py"},
        )
    assert conflicts == []


def test_no_overlap_with_other_prs_returns_empty():
    other = [{"number": 43, "title": "other", "files": [{"path": "c.py"}, {"path": "d.py"}]}]
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=other):
        conflicts = find_conflicting_prs(
            repo="x/y", base="main", current_pr=42, current_files={"a.py", "b.py"},
        )
    assert conflicts == []


def test_overlap_returns_conflict_info():
    other = [{"number": 43, "title": "shared edit", "files": [{"path": "a.py"}, {"path": "c.py"}]}]
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=other):
        conflicts = find_conflicting_prs(
            repo="x/y", base="main", current_pr=42, current_files={"a.py", "b.py"},
        )
    assert len(conflicts) == 1
    assert conflicts[0]["pr_number"] == 43
    assert conflicts[0]["overlapping_files"] == ["a.py"]


def test_current_pr_excluded_from_overlap_check():
    other = [
        {"number": 42, "title": "this PR", "files": [{"path": "a.py"}]},
        {"number": 43, "title": "real other", "files": [{"path": "b.py"}]},
    ]
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=other):
        conflicts = find_conflicting_prs(
            repo="x/y", base="main", current_pr=42, current_files={"a.py", "b.py"},
        )
    assert len(conflicts) == 1
    assert conflicts[0]["pr_number"] == 43


def test_severity_bumps_to_warn_with_5plus_overlap():
    other_files = [{"path": f"file_{i}.py"} for i in range(5)]
    current_files = {f"file_{i}.py" for i in range(5)}
    other = [{"number": 43, "title": "heavy overlap", "files": other_files}]
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=other):
        result = run_cross_pr_branch(
            repo="x/y", base="main", current_pr=42, current_files=current_files,
        )
    assert any(c["severity"] == "warn" for c in result["comments"])


def test_severity_is_info_with_small_overlap():
    other = [{"number": 43, "title": "small overlap", "files": [{"path": "a.py"}]}]
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=other):
        result = run_cross_pr_branch(
            repo="x/y", base="main", current_pr=42, current_files={"a.py"},
        )
    assert any(c["severity"] == "info" for c in result["comments"])


def test_run_cross_pr_branch_returns_no_verdict_field():
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", return_value=[]):
        result = run_cross_pr_branch(repo="x/y", base="main", current_pr=42, current_files=set())
    assert "verdict" not in result
    assert "comments" in result


def test_gh_failure_yields_empty_branch_silently():
    with patch("ai_approve.branches.cross_pr._gh_list_open_prs", side_effect=Exception("gh down")):
        result = run_cross_pr_branch(repo="x/y", base="main", current_pr=42, current_files={"a.py"})
    assert result["comments"] == []
