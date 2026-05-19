"""Tests for hard_blocks.py — deterministic evaluator (no LLM).

Each rule gets a positive test (triggers when expected) and a negative
test (does NOT trigger on a similar-looking but legitimate diff).
"""
from ai_approve.hard_blocks import evaluate


def test_no_rules_trigger_on_empty_pr(minimal_pr):
    result = evaluate(minimal_pr)
    assert result["hard_blocked"] is False
    assert result["reasons"] == []
    assert result["rule_ids"] == []


def test_migrations_rule_triggers(minimal_pr):
    minimal_pr["changed_files"] = ["backend/project/apps/users/migrations/0042_add_field.py"]
    result = evaluate(minimal_pr)
    assert result["hard_blocked"] is True
    assert "migrations" in result["rule_ids"]


def test_migrations_rule_does_not_trigger_on_model_change(minimal_pr):
    minimal_pr["changed_files"] = ["backend/project/apps/users/models.py"]
    result = evaluate(minimal_pr)
    assert "migrations" not in result["rule_ids"]


def test_settings_rule_triggers_on_settings_py(minimal_pr):
    minimal_pr["changed_files"] = ["backend/project/project/settings.py"]
    result = evaluate(minimal_pr)
    assert "settings" in result["rule_ids"]


def test_settings_rule_triggers_on_settings_module(minimal_pr):
    minimal_pr["changed_files"] = ["backend/project/project/settings/base.py"]
    result = evaluate(minimal_pr)
    assert "settings" in result["rule_ids"]


def test_settings_rule_does_not_trigger_on_unrelated_file(minimal_pr):
    minimal_pr["changed_files"] = ["backend/project/apps/users/views.py"]
    result = evaluate(minimal_pr)
    assert "settings" not in result["rule_ids"]


def test_secrets_pattern_triggers_on_api_key(minimal_pr):
    minimal_pr["diff_added_lines"] = ['STRIPE_API_KEY = "sk_live_abc"']
    result = evaluate(minimal_pr)
    assert "secrets_pattern" in result["rule_ids"]


def test_secrets_pattern_triggers_on_password_assignment(minimal_pr):
    minimal_pr["diff_added_lines"] = ['PASSWORD: str = "hunter2"']
    result = evaluate(minimal_pr)
    assert "secrets_pattern" in result["rule_ids"]


def test_secrets_pattern_does_not_trigger_on_word_in_comment(minimal_pr):
    # Just mentioning TOKEN in a non-assignment context shouldn't fire.
    minimal_pr["diff_added_lines"] = ["# refactored TOKEN handling"]
    result = evaluate(minimal_pr)
    assert "secrets_pattern" not in result["rule_ids"]


def test_dependencies_rule_triggers_on_requirements_txt(minimal_pr):
    minimal_pr["changed_files"] = ["backend/requirements.txt"]
    result = evaluate(minimal_pr)
    assert "dependencies" in result["rule_ids"]


def test_dependencies_rule_triggers_on_package_lock(minimal_pr):
    minimal_pr["changed_files"] = ["frontend/almalakia-storefront/package-lock.json"]
    result = evaluate(minimal_pr)
    assert "dependencies" in result["rule_ids"]


def test_ci_workflows_rule_triggers(minimal_pr):
    minimal_pr["changed_files"] = [".github/workflows/backend-tests.yml"]
    result = evaluate(minimal_pr)
    assert "ci_workflows" in result["rule_ids"]


def test_ci_workflows_rule_triggers_on_ai_approve_yml(minimal_pr):
    minimal_pr["changed_files"] = [".github/ai-approve.yml"]
    result = evaluate(minimal_pr)
    assert "ci_workflows" in result["rule_ids"]


def test_test_deletion_rule_triggers_on_removed_test_def(minimal_pr):
    minimal_pr["diff_removed_lines"] = ["    def test_user_can_login():"]
    result = evaluate(minimal_pr)
    assert "test_deletion" in result["rule_ids"]


def test_test_deletion_rule_triggers_on_added_skip(minimal_pr):
    minimal_pr["diff_added_lines"] = ["@pytest.mark.skip(reason='flaky')"]
    result = evaluate(minimal_pr)
    assert "test_deletion" in result["rule_ids"]


def test_test_deletion_rule_does_not_trigger_on_renamed_test(minimal_pr):
    # Same function appears in both — net zero
    minimal_pr["diff_removed_lines"] = ["def test_old_name():"]
    minimal_pr["diff_added_lines"] = ["def test_new_name():"]
    result = evaluate(minimal_pr)
    # Current rule treats ANY removed `def test_*` as a trigger.
    # This is intentional — false positives surface for human review.
    assert "test_deletion" in result["rule_ids"]


def test_audit_baselines_rule_triggers_on_audit_doc_alone(minimal_pr):
    minimal_pr["changed_files"] = ["docs/audit/2026-05-17-backend-audit-report.md"]
    result = evaluate(minimal_pr)
    assert "audit_baselines" in result["rule_ids"]


def test_audit_baselines_rule_does_not_trigger_when_code_changes_accompany(minimal_pr):
    # Normal "close audit item alongside the fix" pattern — code changes
    # plus a `done` marker in the audit backlog. Should NOT hard-block.
    minimal_pr["changed_files"] = [
        "docs/audit/2026-05-17-backend-audit-backlog.md",
        "backend/project/apps/carts/services.py",
    ]
    result = evaluate(minimal_pr)
    assert "audit_baselines" not in result["rule_ids"]


def test_audit_baselines_rule_does_not_trigger_with_frontend_code(minimal_pr):
    minimal_pr["changed_files"] = [
        "docs/audit/2026-05-17-backend-audit-backlog.md",
        "frontend/almalakia-storefront/src/views/Cart.vue",
    ]
    result = evaluate(minimal_pr)
    assert "audit_baselines" not in result["rule_ids"]


def test_audit_baselines_rule_still_triggers_with_only_other_docs(minimal_pr):
    # Audit doc + a README change is still "primarily docs/audit" because
    # there's no source code to anchor it.
    minimal_pr["changed_files"] = [
        "docs/audit/2026-05-17-backend-audit-backlog.md",
        "README.md",
    ]
    result = evaluate(minimal_pr)
    assert "audit_baselines" in result["rule_ids"]


def test_large_diff_rule_triggers_on_files(minimal_pr):
    minimal_pr["files_changed"] = 51
    result = evaluate(minimal_pr)
    assert "large_diff" in result["rule_ids"]


def test_large_diff_rule_triggers_on_lines(minimal_pr):
    minimal_pr["lines_changed"] = 2001
    result = evaluate(minimal_pr)
    assert "large_diff" in result["rule_ids"]


def test_dependencies_rule_triggers_on_nested_pyproject(minimal_pr):
    # Regression test: re.match anchors at start, so a bare `pyproject\.toml`
    # branch would miss paths like `backend/pyproject.toml`. We need the
    # `(.*/)?` prefix to allow nested locations.
    minimal_pr["changed_files"] = ["backend/pyproject.toml"]
    result = evaluate(minimal_pr)
    assert "dependencies" in result["rule_ids"]


def test_dependencies_rule_triggers_on_root_pyproject(minimal_pr):
    minimal_pr["changed_files"] = ["pyproject.toml"]
    result = evaluate(minimal_pr)
    assert "dependencies" in result["rule_ids"]


def test_multiple_rules_can_trigger_simultaneously(minimal_pr):
    minimal_pr["changed_files"] = [
        "backend/project/apps/users/migrations/0042_add_field.py",
        "backend/requirements.txt",
        ".github/workflows/backend-tests.yml",
    ]
    result = evaluate(minimal_pr)
    assert result["hard_blocked"] is True
    assert set(["migrations", "dependencies", "ci_workflows"]).issubset(set(result["rule_ids"]))
