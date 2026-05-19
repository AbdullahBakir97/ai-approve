"""Step 1 of pipeline: deterministic skip checks. See spec §5 / §6.

Pure function. No I/O. Caller passes a dict with the fields below.
"""
from __future__ import annotations

BOT_AUTHORS_TO_SKIP = frozenset({
    "dependabot[bot]",
    "github-actions[bot]",
    "renovate[bot]",
})


def should_skip(pr: dict) -> tuple[bool, str | None]:
    """Return (skip, reason_message_or_None).

    pr keys:
      - labels: list[str]
      - is_draft: bool
      - author_login: str
      - head_sha: str
      - last_reviewed_sha: str | None
      - changed_files: list[str]   (unused here, kept for future rules)
    """
    labels = set(pr.get("labels") or [])

    # needs-human wins over everything (most informative reason)
    if "needs-human" in labels:
        return True, "needs-human label present"

    if pr.get("is_draft"):
        return True, "PR is draft"

    if "wip" in labels:
        return True, "wip label present"

    author = pr.get("author_login")
    if author in BOT_AUTHORS_TO_SKIP:
        return True, f"author is {author} (bot — not reviewing bots)"

    # `.get()` on both sides so a missing head_sha can't KeyError. If
    # last_reviewed_sha is None or absent, the short-circuit returns False.
    last_sha = pr.get("last_reviewed_sha")
    if last_sha and last_sha == pr.get("head_sha"):
        return True, "already-reviewed at this head SHA"

    return False, None
