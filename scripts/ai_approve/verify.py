"""Comment verifier + forbidden-phrase detector.

verify_comments() is pure given a file reader callable — tests inject
a fake reader; production injects a function that reads from disk.

has_forbidden_phrase() scans for the words/phrases the spec §7 system
prompt forbids. Mechanical regex; no LLM involved. If any matches,
the conservative_gate downgrades verdict.
"""
from __future__ import annotations

import re
from collections.abc import Callable

FORBIDDEN_PHRASES: list[str] = [
    "presumably",
    "likely",
    "typically",
    "usually does",
    "should be",
    "i imagine",
    "it appears",
    "seems to",
    "probably",
    "based on convention",
    "i'd expect",
    "in most cases",
    "by convention",
    "intuitively",
    "must be",
    "would normally",
    "should normally",
]


_FORBIDDEN_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b",
    flags=re.IGNORECASE,
)


def has_forbidden_phrase(text: str) -> bool:
    """Return True if `text` contains any forbidden phrase (case-insensitive)."""
    return bool(_FORBIDDEN_REGEX.search(text))


def verify_comments(
    comments: list[dict],
    file_reader: Callable[[str], list[str]],
) -> tuple[list[dict], list[dict]]:
    """Strip comments whose expected_text doesn't match the actual file.

    Returns (kept, dropped). `dropped` items get a `reason` field for
    transparency in the workflow run summary.

    `file_reader(path)` must return a list of lines (without trailing
    newlines). Raises any exception → reason='file_not_found'.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    cache: dict[str, list[str] | None] = {}

    for c in comments:
        path = c["file"]
        line_idx = c["line"] - 1  # comments use 1-based; lists use 0-based
        expected = c["expected_text"]

        # Read once per file. If the reader raises, cache None so subsequent
        # comments on the same path skip the (expensive) retry. This means
        # transient I/O failures on a single file drop ALL its comments — a
        # deliberate fail-closed trade-off. The dropped-comment list (with
        # reason='file_not_found') surfaces this in the workflow summary, so
        # the human can see WHY comments disappeared.
        if path not in cache:
            try:
                cache[path] = file_reader(path)
            except Exception as exc:
                # Emit to stderr so the workflow log captures the failure.
                # (Stderr is included in GitHub Actions step output.)
                import sys
                print(
                    f"verify_comments: file_reader({path!r}) raised {type(exc).__name__}: {exc}; "
                    f"all comments on this path will be dropped with reason=file_not_found",
                    file=sys.stderr,
                )
                cache[path] = None

        lines = cache[path]
        if lines is None:
            dropped.append({**c, "reason": "file_not_found"})
            continue
        if line_idx < 0 or line_idx >= len(lines):
            dropped.append({**c, "reason": "line_out_of_range"})
            continue
        # Defensive normalization: strip trailing \r and \n so the
        # verifier works whether file_reader uses splitlines() (strips)
        # or readlines() (keeps the trailing newline). expected_text from
        # the LLM should never carry \n, but normalize both sides anyway.
        actual_line = lines[line_idx].rstrip("\r\n")
        expected_line = expected.rstrip("\r\n")
        if actual_line != expected_line:
            dropped.append({**c, "reason": "expected_text_mismatch"})
            continue
        kept.append(c)

    return kept, dropped
