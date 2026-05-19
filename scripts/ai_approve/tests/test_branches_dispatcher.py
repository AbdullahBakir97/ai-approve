"""Tests for branches.dispatcher.select_branches() — pure function."""
from ai_approve.branches.dispatcher import _is_security_sensitive, select_branches


def base_pr(**overrides):
    p = {"changed_files": []}
    p.update(overrides)
    return p


def test_standard_always_runs():
    branches = select_branches(base_pr())
    assert "standard" in branches


def test_cross_pr_always_runs():
    branches = select_branches(base_pr())
    assert "cross_pr_conflict" in branches


def test_test_stubs_always_runs():
    branches = select_branches(base_pr())
    assert "test_stubs" in branches


def test_migration_branch_triggers_on_migration_file():
    pr = base_pr(changed_files=["backend/project/apps/users/migrations/0042_add_field.py"])
    assert "migration_deep" in select_branches(pr)


def test_migration_branch_does_not_trigger_on_models_change():
    pr = base_pr(changed_files=["backend/project/apps/users/models.py"])
    assert "migration_deep" not in select_branches(pr)


def test_security_branch_triggers_on_serializers():
    pr = base_pr(changed_files=["backend/project/apps/users/serializers.py"])
    assert "security" in select_branches(pr)


def test_security_branch_triggers_on_permissions():
    pr = base_pr(changed_files=["backend/project/apps/orders/permissions.py"])
    assert "security" in select_branches(pr)


def test_security_branch_triggers_on_auth_paths():
    pr = base_pr(changed_files=["backend/project/apps/users/auth_views.py"])
    assert "security" in select_branches(pr)


def test_security_branch_triggers_on_middleware():
    pr = base_pr(changed_files=["backend/project/apps/core/middleware/security.py"])
    assert "security" in select_branches(pr)


def test_security_branch_triggers_on_settings():
    pr = base_pr(changed_files=["backend/project/project/settings.py"])
    assert "security" in select_branches(pr)


def test_security_branch_does_not_trigger_on_unrelated():
    pr = base_pr(changed_files=["backend/project/apps/products/forms.py"])
    assert "security" not in select_branches(pr)


def test_multiple_branches_can_trigger():
    pr = base_pr(changed_files=[
        "backend/project/apps/users/migrations/0042_add_field.py",
        "backend/project/apps/users/serializers.py",
        "backend/project/apps/products/views.py",
    ])
    branches = select_branches(pr)
    assert "standard" in branches
    assert "migration_deep" in branches
    assert "security" in branches
    assert "cross_pr_conflict" in branches
    assert "test_stubs" in branches


def test_is_security_sensitive_helper():
    assert _is_security_sensitive("backend/project/apps/users/serializers.py") is True
    assert _is_security_sensitive("backend/project/apps/products/forms.py") is False
