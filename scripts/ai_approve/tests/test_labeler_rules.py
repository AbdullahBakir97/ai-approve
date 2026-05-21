"""Unit tests for labeler_rules — mirrors actions/labeler@v5 semantics."""
from __future__ import annotations

import pytest

from ai_approve.labeler_rules import select_category_labels

# --- Helper: standard config matching the project's actual labeler.yml ----

CFG = {
    "backend": [{"changed-files": [{"any-glob-to-any-file": "backend/**"}]}],
    "frontend": [{"changed-files": [{"any-glob-to-any-file": "frontend/**"}]}],
    "fullstack": [{
        "all": [
            {"changed-files": [{"any-glob-to-any-file": "backend/**"}]},
            {"changed-files": [{"any-glob-to-any-file": "frontend/**"}]},
        ],
    }],
    "docs": [{"changed-files": [{"any-glob-to-any-file": [
        "docs/**", "**/README.md", "CLAUDE.md", "CONTRIBUTING.md",
    ]}]}],
    "audit": [{"changed-files": [{"any-glob-to-any-file": "docs/audit/**"}]}],
    "tooling": [{"changed-files": [{"any-glob-to-any-file": [
        "tools/**", ".githooks/**",
    ]}]}],
    "ci": [{"changed-files": [{"any-glob-to-any-file": ".github/workflows/**"}]}],
    "deps": [{"changed-files": [{"any-glob-to-any-file": [
        "backend/requirements*.txt", "pyproject.toml",
        "**/package.json", "**/package-lock.json", "**/yarn.lock",
    ]}]}],
    "api": [{"changed-files": [{"any-glob-to-any-file": "backend/project/apps/*/api/**"}]}],
    "p0": [{"head-branch": "^feat/(backend|frontend|fullstack)/p0-"}],
    "p1": [{"head-branch": "^feat/(backend|frontend|fullstack)/p1-"}],
    "p2": [{"head-branch": "^feat/(backend|frontend|fullstack)/p2-"}],
    "p3": [{"head-branch": "^feat/(backend|frontend|fullstack)/p3-"}],
}


# --- Single-area matches ---------------------------------------------------

def test_backend_only_pr_gets_backend():
    out = select_category_labels(CFG, ["backend/project/apps/users/views.py"], "feat/backend/foo")
    assert "backend" in out
    assert "frontend" not in out
    assert "fullstack" not in out


def test_frontend_only_pr_gets_frontend():
    out = select_category_labels(CFG, ["frontend/storefront/src/App.vue"], "feat/frontend/foo")
    assert "frontend" in out
    assert "backend" not in out
    assert "fullstack" not in out


def test_cross_cutting_pr_gets_all_three():
    out = select_category_labels(
        CFG,
        ["backend/foo.py", "frontend/bar.vue"],
        "feat/fullstack/foo",
    )
    assert {"backend", "frontend", "fullstack"} <= out


# --- Docs + audit ----------------------------------------------------------

def test_docs_glob_matches_docs_dir():
    out = select_category_labels(CFG, ["docs/some.md"], "main")
    assert "docs" in out


def test_docs_glob_matches_readme_anywhere():
    out = select_category_labels(CFG, ["frontend/something/README.md"], "main")
    assert "docs" in out


def test_docs_glob_matches_claude_md_at_root():
    out = select_category_labels(CFG, ["CLAUDE.md"], "main")
    assert "docs" in out


def test_audit_dir_also_gets_docs():
    out = select_category_labels(CFG, ["docs/audit/2026-05-17-backend-audit-backlog.md"], "main")
    assert "audit" in out
    assert "docs" in out


# --- Tooling / CI / deps ---------------------------------------------------

def test_tools_dir_gets_tooling():
    out = select_category_labels(CFG, ["tools/some_script.py"], "main")
    assert "tooling" in out


def test_workflows_get_ci():
    out = select_category_labels(CFG, [".github/workflows/labeler.yml"], "main")
    assert "ci" in out


def test_requirements_change_gets_deps():
    out = select_category_labels(CFG, ["backend/requirements.txt"], "main")
    assert "deps" in out


def test_package_lock_anywhere_gets_deps():
    out = select_category_labels(CFG, ["frontend/storefront/package-lock.json"], "main")
    assert "deps" in out


def test_api_subfolder_gets_api():
    out = select_category_labels(
        CFG, ["backend/project/apps/users/api/serializers.py"], "main",
    )
    assert "api" in out
    assert "backend" in out  # also matches the broader backend rule


# --- Priority labels via head-branch regex --------------------------------

def test_p0_head_branch_matches():
    out = select_category_labels(CFG, [], "feat/backend/p0-critical-fix")
    assert "p0" in out


def test_p1_head_branch_matches():
    out = select_category_labels(CFG, [], "feat/frontend/p1-something")
    assert "p1" in out


def test_no_priority_when_branch_doesnt_match():
    out = select_category_labels(CFG, [], "feat/backend/no-priority-prefix")
    assert not any(p in out for p in ("p0", "p1", "p2", "p3"))


# --- Cross-cutting `all:` composite ---------------------------------------

def test_all_composite_requires_both_clauses():
    """fullstack only fires when BOTH backend AND frontend files touched."""
    just_backend = select_category_labels(CFG, ["backend/x.py"], "feat/fullstack/foo")
    just_frontend = select_category_labels(CFG, ["frontend/x.vue"], "feat/fullstack/foo")
    both = select_category_labels(CFG, ["backend/x.py", "frontend/y.vue"], "feat/fullstack/foo")
    assert "fullstack" not in just_backend
    assert "fullstack" not in just_frontend
    assert "fullstack" in both


# --- Robustness -----------------------------------------------------------

def test_empty_files_and_branch_returns_empty_set():
    assert select_category_labels(CFG, [], "") == set()


def test_empty_config_returns_empty_set():
    assert select_category_labels({}, ["backend/x.py"], "feat/backend/foo") == set()


def test_non_dict_config_handled_gracefully():
    assert select_category_labels(None, ["x.py"], "main") == set()  # type: ignore[arg-type]
    assert select_category_labels([], ["x.py"], "main") == set()  # type: ignore[arg-type]


def test_unknown_rule_keys_skipped():
    """Unknown clause keys (e.g. base-branch which we don't support) won't
    blow up — just don't match."""
    out = select_category_labels(
        {"weird": [{"base-branch": "main"}]},
        ["x.py"], "main",
    )
    assert out == set()


@pytest.mark.parametrize("branch,expected", [
    ("feat/backend/p0-foo", {"p0"}),
    ("feat/backend/p3-foo", {"p3"}),
    ("docs/something", set()),
])
def test_priority_branch_table(branch, expected):
    out = select_category_labels(CFG, [], branch)
    priority_only = out & {"p0", "p1", "p2", "p3"}
    assert priority_only == expected


def test_realistic_full_pr():
    """A realistic cross-cutting fullstack PR with audit docs + ci updates."""
    files = [
        "backend/project/apps/users/views.py",
        "frontend/storefront/src/components/Login.vue",
        "docs/audit/2026-05-17-backend-audit-backlog.md",
        ".github/workflows/labeler.yml",
    ]
    out = select_category_labels(CFG, files, "feat/fullstack/p1-add-auth")
    assert {"backend", "frontend", "fullstack", "docs", "audit", "ci", "p1"} <= out
