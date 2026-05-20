"""Tests for branches.migration — mocked LLM."""
import json
from unittest.mock import MagicMock, patch

from ai_approve.branches.migration import (
    detect_migration_files,
    run_migration_branch,
)


def test_detect_migration_files_returns_django_migrations():
    paths = [
        "backend/project/apps/users/migrations/0042_add_field.py",
        "backend/project/apps/users/models.py",
        "backend/project/apps/orders/migrations/0010_initial.py",
        "frontend/almalakia/src/views/Cart.vue",
    ]
    found = detect_migration_files(paths)
    assert len(found) == 2
    assert "backend/project/apps/users/migrations/0042_add_field.py" in found


def test_detect_migration_files_returns_empty_when_none():
    assert detect_migration_files(["backend/project/apps/users/models.py"]) == []


def test_run_migration_branch_short_circuits_when_no_migration_files():
    pr = {"changed_files": ["backend/project/apps/users/models.py"]}
    with patch("ai_approve.branches.migration.chat_completion") as mock_chat:
        result = run_migration_branch(pr=pr, repo_root=".", token="t")
    mock_chat.assert_not_called()
    assert result.get("comments", []) == []


def test_run_migration_branch_calls_llm_when_migration_present(tmp_path):
    (tmp_path / "backend/project/apps/users/migrations").mkdir(parents=True)
    (tmp_path / "backend/project/apps/users/migrations/0042_add.py").write_text(
        "from django.db import migrations\n"
    )
    pr = {"changed_files": ["backend/project/apps/users/migrations/0042_add.py"]}
    fake_response = MagicMock(content=json.dumps({
        "verdict": "APPROVE",
        "confidence": 0.9,
        "certainty": "fully_understood",
        "summary": "Migration looks safe.",
        "comments": [],
    }), tool_calls=None, input_tokens=500, output_tokens=80, rate_limit_remaining=None, raw={})
    with patch("ai_approve.branches.migration.chat_completion", return_value=fake_response):
        result = run_migration_branch(pr=pr, repo_root=str(tmp_path), token="t")
    assert result["verdict"] == "APPROVE"
    assert result["confidence"] == 0.9


def test_llm_crash_returns_comment_partial(tmp_path):
    (tmp_path / "backend/project/apps/users/migrations").mkdir(parents=True)
    (tmp_path / "backend/project/apps/users/migrations/0042_add.py").write_text("# m\n")
    pr = {"changed_files": ["backend/project/apps/users/migrations/0042_add.py"]}
    with patch("ai_approve.branches.migration.chat_completion", side_effect=Exception("crash")):
        result = run_migration_branch(pr=pr, repo_root=str(tmp_path), token="t")
    assert result["verdict"] == "COMMENT"
    assert "deep-inspection unavailable" in result["summary"].lower()


def test_skip_token_in_pr_body_disables_branch(tmp_path):
    (tmp_path / "backend/project/apps/users/migrations").mkdir(parents=True)
    (tmp_path / "backend/project/apps/users/migrations/0042_add.py").write_text("# m\n")
    pr = {
        "changed_files": ["backend/project/apps/users/migrations/0042_add.py"],
        "body": "Routine. [skip-migration-check]",
    }
    with patch("ai_approve.branches.migration.chat_completion") as mock_chat:
        result = run_migration_branch(pr=pr, repo_root=str(tmp_path), token="t")
    mock_chat.assert_not_called()
    assert result.get("comments", []) == []
