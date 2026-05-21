"""Apply professional `bot-*` labels to PRs based on review outcome.

Labels are auto-created on first use (idempotent). The label set:

  bot-reviewed              — always added when the bot posts any review
  bot-approved              — verdict == APPROVE
  bot-changes-requested     — verdict == REQUEST_CHANGES (LLM path)
  bot-comment               — verdict == COMMENT
  bot-hard-blocked          — deterministic hard-block fired (Pass 2 skipped)
  bot-fixes                 — auto-fix pushed commits to the PR head

Idempotent: re-running on the same PR replaces stale `bot-*` labels with the
current outcome. Non-bot labels on the PR are left alone.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

# Label name -> (color hex without leading #, description).
# Colors picked from GitHub's standard palette for clarity.
LABEL_SPEC: dict[str, tuple[str, str]] = {
    "bot-reviewed":              ("0366d6", "AI-approve bot posted a review on this PR."),
    "bot-approved":              ("0e8a16", "AI-approve bot APPROVED this PR."),
    "bot-changes-requested":     ("b60205", "AI-approve bot REQUEST_CHANGES on this PR (LLM path)."),
    "bot-comment":               ("6e7681", "AI-approve bot posted a COMMENT (no verdict pressure)."),
    "bot-hard-blocked":          ("d93f0b", "Deterministic gate fired — Pass 2 LLM was skipped."),
    "bot-fixes":                 ("5319e7", "AI-approve bot auto-pushed fixes to this PR."),
}

# Verdict → outcome-specific label. `bot-reviewed` is always added on top.
_VERDICT_LABELS: dict[str, str] = {
    "APPROVE": "bot-approved",
    "REQUEST_CHANGES": "bot-changes-requested",
    "COMMENT": "bot-comment",
}


@dataclass(frozen=True)
class LabelResult:
    applied: list[str]
    removed: list[str]


def _gh(args: list[str], token: str) -> subprocess.CompletedProcess:
    """Run a `gh` subprocess with the bot's App token in env."""
    env = {"GH_TOKEN": token, "PATH": os.environ.get("PATH", "")}
    return subprocess.run(args, capture_output=True, text=True, env=env, check=False)


def _ensure_label_exists(repo: str, name: str, color: str, description: str, token: str) -> None:
    """Create the label if missing, or update color/description if drifted.

    Uses the REST API directly so we get explicit 200/201/422 codes; 422 means
    the label already exists with the right shape and is treated as success.
    """
    create = _gh([
        "gh", "api", f"repos/{repo}/labels",
        "--method", "POST",
        "-f", f"name={name}",
        "-f", f"color={color}",
        "-f", f"description={description}",
    ], token)
    if create.returncode == 0:
        return
    # If create failed with "already_exists", attempt a PATCH to sync color/desc.
    if "already_exists" in (create.stderr or "") or "already_exists" in (create.stdout or ""):
        _gh([
            "gh", "api", f"repos/{repo}/labels/{name}",
            "--method", "PATCH",
            "-f", f"new_name={name}",
            "-f", f"color={color}",
            "-f", f"description={description}",
        ], token)
        return
    # Other failure (permissions, repo missing, etc.) — fail open, the label
    # add step will surface a clearer error if it's a real blocker.


def _list_current_labels(repo: str, pr_number: int, token: str) -> list[str]:
    r = _gh(["gh", "api", f"repos/{repo}/issues/{pr_number}/labels"], token)
    if r.returncode != 0:
        return []
    try:
        return [lab["name"] for lab in json.loads(r.stdout or "[]")]
    except (json.JSONDecodeError, TypeError, KeyError):
        return []


def _remove_label(repo: str, pr_number: int, name: str, token: str) -> bool:
    r = _gh([
        "gh", "api", f"repos/{repo}/issues/{pr_number}/labels/{name}",
        "--method", "DELETE",
    ], token)
    return r.returncode == 0


def _add_labels(repo: str, pr_number: int, names: list[str], token: str) -> bool:
    if not names:
        return True
    args = ["gh", "api", f"repos/{repo}/issues/{pr_number}/labels", "--method", "POST"]
    for n in names:
        args.extend(["-f", f"labels[]={n}"])
    r = _gh(args, token)
    return r.returncode == 0


def select_labels(*, verdict: str, has_fixes: bool, hard_blocked: bool) -> list[str]:
    """Pure function: outcome → label set. Useful for tests."""
    out = ["bot-reviewed"]
    if hard_blocked:
        out.append("bot-hard-blocked")
    else:
        v = (verdict or "").upper()
        if v in _VERDICT_LABELS:
            out.append(_VERDICT_LABELS[v])
    if has_fixes:
        out.append("bot-fixes")
    return out


def apply_labels(
    *,
    repo: str,
    pr_number: int,
    verdict: str,
    has_fixes: bool,
    hard_blocked: bool,
    token: str,
    extra_labels: set[str] | None = None,
    managed_extra_labels: set[str] | None = None,
) -> LabelResult:
    """Idempotently apply both `bot-*` outcome labels and (optionally)
    category/priority labels to the PR.

    - Ensures every `bot-*` label in LABEL_SPEC exists (create or sync
      color/desc). Category labels are NOT auto-created here — the
      bot trusts the consumer repo to have defined them already (the
      existing actions/labeler workflow created them); foreign labels
      added to a PR are also untouched.
    - Removes stale `bot-*` labels currently on the PR that aren't in
      this run's outcome set, so re-running the bot replaces them cleanly.
    - If `managed_extra_labels` is given (typically the full set of names
      defined in the consumer's `.github/labeler.yml`), category labels in
      that namespace that aren't in `extra_labels` are also pruned.
      Without `managed_extra_labels` provided, category labels are
      additive-only (safer when the bot doesn't know the full universe
      of category labels — won't accidentally remove a hand-applied tag).
    - Adds whatever's missing from the union of bot + extra.
    """
    bot_want = set(select_labels(
        verdict=verdict, has_fixes=has_fixes, hard_blocked=hard_blocked,
    ))
    extras = set(extra_labels or ())
    want = bot_want | extras

    # Create only the bot-* labels (we own those). Trust category labels
    # already exist in the repo (the labeler workflow created them).
    for name in bot_want:
        if name in LABEL_SPEC:
            color, desc = LABEL_SPEC[name]
            _ensure_label_exists(repo, name, color, desc, token)

    current = set(_list_current_labels(repo, pr_number, token))

    # Stale bot-* labels (always managed by the bot)
    stale = {lab for lab in current if lab in LABEL_SPEC and lab not in bot_want}
    # Stale category labels (only managed when explicit universe given)
    if managed_extra_labels:
        stale |= {lab for lab in current if lab in managed_extra_labels and lab not in extras}
    new = sorted(want - current)

    removed: list[str] = []
    for name in sorted(stale):
        if _remove_label(repo, pr_number, name, token):
            removed.append(name)

    applied: list[str] = []
    if new and _add_labels(repo, pr_number, new, token):
        applied = new

    return LabelResult(applied=applied, removed=removed)
