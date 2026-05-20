"""Deterministic hard-block evaluator. Pure function; no I/O; no LLM.

Run BEFORE any LLM call. Cannot be overridden by the LLM. See spec §8.
"""
from __future__ import annotations

import re

HARD_BLOCK_RULES: list[dict] = [
    {
        "id": "migrations",
        "kind": "paths",
        "check": lambda paths: any(
            re.match(r"^backend/project/apps/[^/]+/migrations/", p)
            for p in paths
        ),
        "reason": (
            "Touches database migrations — irreversible. "
            "Human review required."
        ),
    },
    {
        "id": "settings",
        "kind": "paths",
        "check": lambda paths: any(
            p == "backend/project/project/settings.py"
            or p.startswith("backend/project/project/settings/")
            for p in paths
        ),
        "reason": "Touches Django settings — security-sensitive surface.",
    },
    {
        "id": "secrets_pattern",
        "kind": "added_lines",
        "check": lambda added: any(
            re.search(
                r"(?i)\b\w*(SECRET|API[_-]?KEY|PASSWORD|PRIVATE[_-]?KEY|"
                r"BEARER|TOKEN|AUTH[_-]?TOKEN|CLIENT[_-]?SECRET)\w*\s*[=:]",
                line,
            )
            for line in added
        ),
        "reason": (
            "Diff contains credential-shaped string — possible secret leak."
        ),
    },
    {
        "id": "dependencies",
        "kind": "paths",
        "check": lambda paths: any(
            re.match(
                r"^(backend/requirements.*\.txt|"
                r"(.*/)?pyproject\.toml|"
                r".*/package\.json|"
                r".*/package-lock\.json|"
                r".*/yarn\.lock|"
                r".*/pnpm-lock\.yaml)$",
                p,
            )
            for p in paths
        ),
        "reason": "Modifies dependencies — supply-chain risk.",
    },
    {
        "id": "ci_workflows",
        "kind": "paths",
        "check": lambda paths: any(
            p.startswith(".github/workflows/")
            or p in (
                ".github/ai-approve.yml",
                ".github/labeler.yml",
                ".github/commit-craft.yml",
                ".github/pr-coach.yml",
                ".github/ai-gate.yml",
            )
            for p in paths
        ),
        "reason": (
            "Modifies CI / bot config — the bot cannot approve "
            "changes to its own gates."
        ),
    },
    {
        "id": "test_deletion",
        "kind": "test_signal",
        "check": lambda removed, added: (
            any(re.match(r"^\s*def test_\w+", line) for line in removed)
            or any(re.search(
                r"@(pytest\.mark\.skip|pytest\.mark\.xfail|unittest\.skip)",
                line,
            ) for line in added)
        ),
        "reason": "Removes or disables tests — hollows out coverage.",
    },
    {
        "id": "audit_baselines",
        "kind": "audit_signal",
        # Hard-block when the audit baseline is touched AS THE PRIMARY
        # change (no accompanying source code). The normal "close audit
        # item alongside the fix" pattern — code change + a `✓ done`
        # marker in the backlog — should not trigger; that's how every
        # audit-resolution PR is structured.
        "check": lambda paths: (
            any(p.startswith("docs/audit/") for p in paths)
            and not any(
                p.endswith((".py", ".vue", ".ts", ".tsx", ".js", ".jsx", ".sql"))
                and not p.startswith("docs/")
                for p in paths
            )
        ),
        "reason": (
            "Modifies audit baselines as the primary change (no "
            "accompanying source-code edits) — must be human-reviewed "
            "(these define 'done')."
        ),
    },
    {
        "id": "large_diff",
        "kind": "size",
        # Returns True (hard-block), "borderline" (near threshold), or False
        "check": lambda files_n, lines_n: (
            True if (files_n > 50 or lines_n > 2000)
            else ("borderline" if (files_n >= 45 or lines_n >= 1800) else False)
        ),
        "reason": (
            "PR exceeds 50 files or 2000 lines — too large for "
            "safe auto-review."
        ),
        "borderline_reason": (
            "PR near the large-diff threshold (45-50 files or 1800-2000 lines) — "
            "borderline; escalating to reasoning model."
        ),
    },
]


def evaluate(pr_metadata: dict) -> dict:
    """Return {hard_blocked, reasons, rule_ids, borderline, borderline_reasons}."""
    triggered: list[dict] = []
    borderline_rules: list[dict] = []
    paths = pr_metadata["changed_files"]
    added = pr_metadata["diff_added_lines"]
    removed = pr_metadata["diff_removed_lines"]
    files_n = pr_metadata["files_changed"]
    lines_n = pr_metadata["lines_changed"]

    for rule in HARD_BLOCK_RULES:
        kind = rule["kind"]
        if kind == "paths":
            hit = rule["check"](paths)
        elif kind == "added_lines":
            hit = rule["check"](added)
        elif kind == "test_signal":
            hit = rule["check"](removed, added)
        elif kind == "audit_signal":
            hit = rule["check"](paths)
        elif kind == "size":
            hit = rule["check"](files_n, lines_n)
        else:
            raise ValueError(f"unknown rule kind: {kind!r}")

        if hit is True:
            triggered.append(rule)
        elif hit == "borderline":
            borderline_rules.append(rule)

    return {
        "hard_blocked": bool(triggered),
        "reasons": [r["reason"] for r in triggered],
        "rule_ids": [r["id"] for r in triggered],
        "borderline": bool(borderline_rules) and not bool(triggered),
        "borderline_reasons": [r.get("borderline_reason", r["reason"]) for r in borderline_rules],
    }
