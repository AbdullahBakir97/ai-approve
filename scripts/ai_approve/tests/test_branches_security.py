"""Tests for branches.security — mocked LLM."""
import json
from unittest.mock import MagicMock, patch

from ai_approve.branches.security import (
    detect_security_files,
    run_security_branch,
)


def test_detect_security_files_picks_serializers_and_auth():
    paths = [
        "backend/project/apps/users/serializers.py",
        "backend/project/apps/users/auth_views.py",
        "backend/project/project/settings.py",
        "backend/project/apps/products/views.py",
    ]
    found = detect_security_files(paths)
    assert "backend/project/apps/users/serializers.py" in found
    assert "backend/project/apps/users/auth_views.py" in found
    assert "backend/project/project/settings.py" in found
    assert "backend/project/apps/products/views.py" not in found


def test_run_security_branch_short_circuits_when_no_security_files():
    pr = {"changed_files": ["backend/project/apps/products/views.py"]}
    with patch("ai_approve.branches.security.chat_completion") as mock_chat:
        result = run_security_branch(pr=pr, repo_root=".", token="t")
    mock_chat.assert_not_called()
    assert result.get("comments", []) == []


def test_run_security_branch_calls_llm_when_security_file_present(tmp_path):
    (tmp_path / "backend/project/apps/users").mkdir(parents=True)
    (tmp_path / "backend/project/apps/users/serializers.py").write_text(
        "class UserSerializer(serializers.ModelSerializer):\n    class Meta:\n        fields = '__all__'\n"
    )
    pr = {"changed_files": ["backend/project/apps/users/serializers.py"]}
    fake_response = MagicMock(
        content=json.dumps({
            "verdict": "REQUEST_CHANGES",
            "confidence": 0.85,
            "certainty": "fully_understood",
            "summary": "Mass-assignment risk in UserSerializer.",
            "comments": [{
                "file": "backend/project/apps/users/serializers.py",
                "line": 3,
                "expected_text": "        fields = '__all__'",
                "claim": "Mass assignment: fields='__all__' exposes sensitive fields.",
                "suggested_text": None,
                "severity": "blocker",
            }],
        }),
        tool_calls=None,
        input_tokens=600,
        output_tokens=180,
        rate_limit_remaining=None,
        raw={},
    )
    with patch("ai_approve.branches.security.chat_completion", return_value=fake_response):
        result = run_security_branch(pr=pr, repo_root=str(tmp_path), token="t")
    assert result["verdict"] == "REQUEST_CHANGES"
    assert len(result["comments"]) == 1
    assert result["comments"][0]["severity"] == "blocker"


def test_skip_token_in_pr_body_disables_branch(tmp_path):
    (tmp_path / "backend/project/apps/users").mkdir(parents=True)
    (tmp_path / "backend/project/apps/users/serializers.py").write_text("# s\n")
    pr = {
        "changed_files": ["backend/project/apps/users/serializers.py"],
        "body": "[skip-security-check] approved upstream",
    }
    with patch("ai_approve.branches.security.chat_completion") as mock_chat:
        result = run_security_branch(pr=pr, repo_root=str(tmp_path), token="t")
    mock_chat.assert_not_called()
    assert result.get("comments", []) == []


def test_llm_crash_returns_comment_partial(tmp_path):
    (tmp_path / "backend/project/apps/users").mkdir(parents=True)
    (tmp_path / "backend/project/apps/users/serializers.py").write_text("# s\n")
    pr = {"changed_files": ["backend/project/apps/users/serializers.py"]}
    with patch(
        "ai_approve.branches.security.chat_completion",
        side_effect=Exception("crash"),
    ):
        result = run_security_branch(pr=pr, repo_root=str(tmp_path), token="t")
    assert result["verdict"] == "COMMENT"
    assert "security review unavailable" in result["summary"].lower()
