"""Step 2 of pipeline: collect PR metadata via `gh` + `git`.

Outputs a single dict consumed by hard_blocks, triage, and deep_review.
"""
from __future__ import annotations
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

# Encoding is explicit so this script behaves the same on Linux CI and a
# Windows dev machine. The repo contains Arabic strings (per CLAUDE.md's
# `--ar` font + Amiri references) and PR bodies can include emoji — both
# of which break under the default Windows CP1252 codepage.
_SUBPROCESS_KWARGS = {
    "capture_output": True,
    "text": True,
    "encoding": "utf-8",
    "check": True,
}


def run_gh(args: list[str]) -> str:
    """Run `gh` with stdout capture. Raises if exit != 0."""
    r = subprocess.run(["gh", *args], **_SUBPROCESS_KWARGS)
    return r.stdout


def run_git(args: list[str]) -> str:
    """Run `git` with stdout capture. Raises if exit != 0.

    Currently used by cli.py for state-comment R/W workflows; kept here
    so all subprocess invocations share the same encoding contract.
    """
    r = subprocess.run(["git", *args], **_SUBPROCESS_KWARGS)
    return r.stdout


def gather(repo: str, pr_number: int) -> dict:
    """Pull everything Pass 1/2 need into one dict.

    Returns:
      {
        "pr_number": int,
        "title": str,
        "body": str,
        "head_sha": str,
        "base_sha": str,
        "labels": list[str],
        "is_draft": bool,
        "author_login": str,
        "changed_files": list[str],
        "diff": str,                  # full unified diff
        "diff_added_lines": list[str],
        "diff_removed_lines": list[str],
        "files_changed": int,
        "lines_changed": int,
        "commit_messages": list[str], # subjects only
        "audit_doc": str | None,      # text if AUDIT-XXX referenced
        "claude_md": str,             # contents of CLAUDE.md
        "diff_truncated": bool,       # True if raw diff exceeded 200 KB
      }

    NOTE: callers run with CWD == repo root (guaranteed by
    actions/checkout in the workflow). The CLAUDE.md and docs/audit/
    lookups are relative to CWD.
    """
    # 1. Core metadata via gh
    meta_json = run_gh([
        "pr", "view", str(pr_number), "--repo", repo,
        "--json",
        "title,body,headRefOid,baseRefOid,labels,isDraft,author,files,commits",
    ])
    meta = json.loads(meta_json)

    head_sha = meta["headRefOid"]
    base_sha = meta["baseRefOid"]
    title = meta.get("title", "")
    body = meta.get("body") or ""
    labels = [l["name"] for l in (meta.get("labels") or [])]
    is_draft = bool(meta.get("isDraft"))
    author_login = (meta.get("author") or {}).get("login") or ""
    changed_files = [f["path"] for f in (meta.get("files") or [])]
    files_changed = len(changed_files)
    commit_messages = [c.get("messageHeadline", "") for c in (meta.get("commits") or [])]

    # 2. Diff (limit to first 200 KB to be safe in the LLM context).
    # Track truncation explicitly so callers (and the LLM, via the review
    # body) know the diff and lines_changed counts are understated.
    diff_raw = run_gh(["pr", "diff", str(pr_number), "--repo", repo])
    MAX_DIFF_BYTES = 200 * 1024
    diff_truncated = len(diff_raw) > MAX_DIFF_BYTES
    if diff_truncated:
        # Log to stderr so the workflow log captures the truncation event.
        print(
            f"gather: PR #{pr_number} diff is {len(diff_raw)} bytes; "
            f"truncating to {MAX_DIFF_BYTES} bytes. lines_changed will be "
            f"understated; downstream consumers should check `diff_truncated`.",
            file=sys.stderr,
        )
    diff = diff_raw[:MAX_DIFF_BYTES]
    diff_added_lines = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    diff_removed_lines = [l[1:] for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    lines_changed = len(diff_added_lines) + len(diff_removed_lines)

    # 3. CLAUDE.md (the project's living convention doc)
    claude_md_path = Path("CLAUDE.md")
    claude_md = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""

    # 4. Referenced audit doc — extract AUDIT-XXX from title OR body
    # (contributors may put the audit ref in either, esp. for follow-ups).
    audit_doc = None
    audit_match = re.search(r"AUDIT-(\d+)", title + "\n" + body)
    if audit_match:
        audit_id = audit_match.group(1)
        audit_dir = Path("docs/audit")
        if audit_dir.exists():
            for path in audit_dir.glob("*.md"):
                content = path.read_text(encoding="utf-8")
                if f"AUDIT-{audit_id}" in content:
                    audit_doc = content
                    break

    return {
        "pr_number": pr_number,
        "title": title,
        "body": body,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "labels": labels,
        "is_draft": is_draft,
        "author_login": author_login,
        "changed_files": changed_files,
        "diff": diff,
        "diff_added_lines": diff_added_lines,
        "diff_removed_lines": diff_removed_lines,
        "files_changed": files_changed,
        "lines_changed": lines_changed,
        "commit_messages": commit_messages,
        "audit_doc": audit_doc,
        "claude_md": claude_md,
        "diff_truncated": diff_truncated,
    }
