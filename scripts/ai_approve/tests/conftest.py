"""Shared pytest fixtures for ai_approve tests."""
import pytest


@pytest.fixture
def minimal_pr():
    """Empty PR metadata — all rules should pass."""
    return {
        "changed_files": [],
        "diff_added_lines": [],
        "diff_removed_lines": [],
        "files_changed": 0,
        "lines_changed": 0,
    }
