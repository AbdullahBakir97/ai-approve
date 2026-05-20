"""Emit a markdown summary to $GITHUB_STEP_SUMMARY AND to stderr.

Stderr mirroring is intentional: GitHub Actions captures stderr into the
workflow log, which IS queryable via `gh run view --log`. The step
summary itself is only visible in the web UI, with no API endpoint to
fetch it, so without the stderr mirror there's no way to debug a
silently-failing run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def emit(sections: dict[str, str]) -> None:
    """Write a multi-section markdown summary. Mirrors to stderr."""
    lines = []
    for heading, body in sections.items():
        lines.append(f"## {heading}")
        lines.append(body.strip() or "_(empty)_")
        lines.append("")
    blob = "\n".join(lines) + "\n"

    # Always mirror to stderr (so it shows up in `gh run view --log`).
    sys.stderr.write("\n=== AI-Approve summary ===\n" + blob + "===\n")

    # Also append to GitHub Actions step summary if available.
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        Path(path).open("a", encoding="utf-8").write(blob)
