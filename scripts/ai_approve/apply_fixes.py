"""Step 6 — Run allowed mechanical fixers, commit, push.

Implements smart-hybrid cadence: first attempt always runs; subsequent
attempts gated by monotonic-improvement, attempt cap, and same-tool-loop
guard (see spec §9). State lives in the hidden PR comment via state.py.

Allowed tools (v1 allowlist):
  ruff_format, ruff_fix, isort, i18n_linter
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

ALLOWED_TOOLS = {"ruff_format", "ruff_fix", "isort", "i18n_linter"}
MAX_BOT_FIXES_PER_PR = 3   # since last human commit
COMMIT_AUTHOR_NAME = "github-actions[bot]"
COMMIT_AUTHOR_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def _safe_target(target: str) -> bool:
    """Reject absolute, .., and variable-shaped paths."""
    if not target:
        return False
    if target.startswith("/"):
        return False
    if ".." in Path(target).parts:
        return False
    if "$" in target:
        return False
    return True


def _run_tool(tool: str, target: str, repo_root: Path) -> bool:
    """Run one fixer. Returns True if it executed cleanly (exit 0)."""
    target_abs = (repo_root / target).resolve()
    try:
        target_abs.relative_to(repo_root.resolve())
    except ValueError:
        # Path escapes repo root — same CVE-class fix applied in tools.py
        return False

    if tool == "ruff_format":
        cmd = ["ruff", "format", str(target_abs)]
    elif tool == "ruff_fix":
        cmd = ["ruff", "check", "--fix", "--select=I,F,E,W", str(target_abs)]
    elif tool == "isort":
        cmd = ["isort", str(target_abs)]
    elif tool == "i18n_linter":
        cmd = ["python", str(repo_root / "tools" / "i18n_lint.py"), "--fix", str(target_abs)]
    else:
        return False

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root))
    return r.returncode == 0


def _decide_proceed(state: dict, current_issue_count: int) -> tuple[bool, str | None]:
    """Smart-hybrid cadence gate. Return (proceed, stop_reason_if_not)."""
    attempts = state.get("fix_attempts", [])

    # Attempt cap
    if state.get("total_bot_fixes", 0) >= MAX_BOT_FIXES_PER_PR:
        return False, f"auto-fix attempt cap reached ({MAX_BOT_FIXES_PER_PR}) — please human-review"

    if not attempts:
        return True, None  # first attempt always proceeds

    last = attempts[-1]

    # Monotonic improvement: previous after-count must be < before-count
    # AND current count must be < last after-count
    if last["issue_count_after"] >= last["issue_count_before"]:
        return False, "previous auto-fix did not reduce issue count — please human-review"
    if current_issue_count >= last["issue_count_after"]:
        return False, "auto-fix not converging (issue count plateau or growing) — please human-review"

    # Same-tool-twice-in-a-row producing no net-new resolved
    if len(attempts) >= 2:
        a, b = attempts[-2], attempts[-1]
        if (set(a.get("tools", [])) == set(b.get("tools", []))
            and a["issue_count_after"] == b["issue_count_after"]):
            return False, "same fixer ran twice without progress — please human-review"

    return True, None


def apply_fixes(
    *,
    fixes_to_push: list[dict],
    state: dict,
    pr_branch: str,
    repo_root: Path,
    current_issue_count: int,
    bot_already_fixed_label_present: bool,
) -> dict:
    """Run allowed fixers, commit, push. Update state in place.

    Returns dict with:
      acted: bool                 # did we push a commit?
      stop_reason: str | None     # if not acted because of cadence guard
      tools_used: list[str]
      files_changed: int
      stop_loop_for_now: bool     # caller should exit without posting review
    """
    if bot_already_fixed_label_present:
        # ai-fixed label is the second-layer guard
        # (state should also say total_bot_fixes >= 1 — defensive)
        proceed, reason = False, "ai-fixed label present (already fixed once for this PR)"
    else:
        proceed, reason = _decide_proceed(state, current_issue_count)

    if not proceed:
        return {
            "acted": False,
            "stop_reason": reason,
            "tools_used": [],
            "files_changed": 0,
            "stop_loop_for_now": False,
        }

    # Filter to allowlist + path-safe
    valid: list[dict] = []
    for f in fixes_to_push:
        if f.get("tool") in ALLOWED_TOOLS and _safe_target(f.get("target_path", "")):
            valid.append(f)

    if not valid:
        return {
            "acted": False,
            "stop_reason": "no valid fixes to push",
            "tools_used": [],
            "files_changed": 0,
            "stop_loop_for_now": False,
        }

    # Run each fixer
    tools_used: set[str] = set()
    for f in valid:
        ok = _run_tool(f["tool"], f["target_path"], repo_root)
        if ok:
            tools_used.add(f["tool"])

    # See if anything changed
    diff_check = subprocess.run(
        ["git", "diff", "--quiet"], cwd=str(repo_root), capture_output=True,
    )
    if diff_check.returncode == 0:
        # No changes
        return {
            "acted": False,
            "stop_reason": "fixers ran but produced no changes",
            "tools_used": list(tools_used),
            "files_changed": 0,
            "stop_loop_for_now": False,
        }

    # Stage ONLY files that were targets of fixers (defensive)
    targets = sorted({f["target_path"] for f in valid})
    subprocess.run(["git", "config", "user.name", COMMIT_AUTHOR_NAME], cwd=str(repo_root), check=True)
    subprocess.run(["git", "config", "user.email", COMMIT_AUTHOR_EMAIL], cwd=str(repo_root), check=True)
    subprocess.run(["git", "add", "--", *targets], cwd=str(repo_root), check=True)

    staged_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(repo_root), capture_output=True,
    )
    if staged_check.returncode == 0:
        # Out-of-scope edits only — drop them
        subprocess.run(["git", "checkout", "--", "."], cwd=str(repo_root), check=False)
        return {
            "acted": False,
            "stop_reason": "fixers modified out-of-scope files only — discarded",
            "tools_used": list(tools_used),
            "files_changed": 0,
            "stop_loop_for_now": False,
        }

    files_count = int(subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=str(repo_root), capture_output=True, text=True,
    ).stdout.strip().count("\n") + 1)

    tools_summary = ", ".join(sorted(tools_used))
    msg = (
        f"chore(ai): auto-fix — {tools_summary}\n\n"
        f"Applied tools: {tools_summary}\n"
        f"Files: {files_count}\n\n"
        f"Auto-fix from .github/workflows/ai-approve.yml.\n"
        f"The next Backend Tests run will verify these changes pass.\n"
    )

    subprocess.run(["git", "commit", "-m", msg], cwd=str(repo_root), check=True)
    push = subprocess.run(
        ["git", "push", "origin", f"HEAD:{pr_branch}"],
        cwd=str(repo_root), capture_output=True, text=True,
    )

    if push.returncode != 0:
        # Push rejected — undo the local commit and signal "convert to suggestions"
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=str(repo_root), check=False)
        return {
            "acted": False,
            "stop_reason": f"push rejected: {push.stderr[:200]}",
            "tools_used": list(tools_used),
            "files_changed": files_count,
            "stop_loop_for_now": False,
        }

    # Record into state
    state.setdefault("fix_attempts", []).append({
        "sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True,
        ).stdout.strip(),
        "issue_count_before": current_issue_count,
        "issue_count_after": max(0, current_issue_count - len(valid)),  # estimate
        "tools": sorted(tools_used),
    })
    state["total_bot_fixes"] = state.get("total_bot_fixes", 0) + 1

    return {
        "acted": True,
        "stop_reason": None,
        "tools_used": sorted(tools_used),
        "files_changed": files_count,
        "stop_loop_for_now": True,  # exit; next workflow_run will post review
    }
