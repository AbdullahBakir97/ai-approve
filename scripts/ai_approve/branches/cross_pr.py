"""Cross-PR conflict awareness — pure Python, no LLM call.

Lists currently-open PRs on the same base branch, computes file overlap with
the current PR, posts informational comments per overlap.
"""
from __future__ import annotations

import json
import subprocess


def _gh_list_open_prs(repo: str, base: str) -> list[dict]:
    """Return list of open PR dicts on the given base branch."""
    r = subprocess.run(
        [
            "gh", "pr", "list",
            "--repo", repo,
            "--base", base,
            "--state", "open",
            "--json", "number,title,files",
            "--limit", "100",
        ],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(r.stdout or "[]")


def find_conflicting_prs(
    *, repo: str, base: str, current_pr: int, current_files: set[str],
) -> list[dict]:
    """Return [{pr_number, title, overlapping_files}] for each other open PR
    whose file list intersects current_files (excluding current_pr itself)."""
    others = _gh_list_open_prs(repo, base)
    conflicts: list[dict] = []
    for pr in others:
        if pr.get("number") == current_pr:
            continue
        other_paths = {f["path"] for f in pr.get("files") or []}
        overlap = sorted(current_files & other_paths)
        if overlap:
            conflicts.append({
                "pr_number": pr["number"],
                "title": pr.get("title") or "",
                "overlapping_files": overlap,
            })
    return conflicts


def run_cross_pr_branch(
    *, repo: str, base: str, current_pr: int, current_files: set[str],
) -> dict:
    """Run the cross-PR conflict awareness branch.

    Returns {"comments": [...]} — no verdict field (aggregator ignores).
    """
    try:
        conflicts = find_conflicting_prs(
            repo=repo, base=base, current_pr=current_pr, current_files=current_files,
        )
    except Exception:
        return {"comments": []}

    comments: list[dict] = []
    for c in conflicts:
        n = len(c["overlapping_files"])
        severity = "warn" if n >= 5 else "info"
        files_str = ", ".join(c["overlapping_files"][:5]) + (
            f" (+{n - 5} more)" if n > 5 else ""
        )
        claim = (
            f"Overlaps with PR #{c['pr_number']} ('{c['title']}'). "
            f"Shared files ({n}): {files_str}. Merge order matters — coordinate."
        )
        comments.append({
            "file": c["overlapping_files"][0],
            "line": 1,
            "expected_text": "",
            "claim": claim,
            "severity": severity,
        })

    return {"comments": comments}
