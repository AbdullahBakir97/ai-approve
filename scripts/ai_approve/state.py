"""Persistent bot state encoded inside a hidden PR comment marker.

A single comment per PR. The bot looks for a comment whose body matches
the marker; if absent, writes a new one. If present, edits it. This
gives the bot stable memory across workflow runs without using GitHub
Actions artifacts (which have retention limits).

The comment body looks like:

    AI-Approve internal state — do not edit.

    <!-- ai-approve-state-start
    {...json...}
    ai-approve-state-end -->
"""
from __future__ import annotations

import json
import re

MARKER_START = "<!-- ai-approve-state-start"
MARKER_END = "ai-approve-state-end -->"

_EXTRACT_RE = re.compile(
    re.escape(MARKER_START) + r"\s*(.*?)\s*" + re.escape(MARKER_END),
    flags=re.DOTALL,
)


def empty_state(pr_number: int) -> dict:
    """Return the canonical empty state for a fresh PR."""
    return {
        "schema_version": 1,
        "pr": pr_number,
        "fix_attempts": [],            # list of {sha, issue_count_before, issue_count_after, tools}
        "total_bot_fixes": 0,          # since last_human_sha
        "last_human_sha": None,        # resets fix_attempts when changes
        "last_reviewed_sha": None,     # for idempotency in skip_checks
    }


def serialize_state(state: dict) -> str:
    """Compact JSON for embedding."""
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


def parse_state(raw_json: str) -> dict:
    """Inverse of serialize_state. Raises ValueError if input is not JSON."""
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"state JSON parse failed: {e}") from e


def embed_in_comment(state: dict) -> str:
    """Return a PR comment body containing the marker-wrapped state."""
    body = serialize_state(state)
    return (
        "AI-Approve internal state — do not edit.\n\n"
        f"{MARKER_START}\n{body}\n{MARKER_END}\n"
    )


def extract_from_comment(comment_body: str) -> dict | None:
    """Return state dict if marker is present, else None."""
    m = _EXTRACT_RE.search(comment_body)
    if not m:
        return None
    return parse_state(m.group(1))
