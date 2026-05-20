"""Aggregator — merges multiple branch outputs into one Pass-2-shaped verdict.

Strictest-wins on verdict (any REQUEST_CHANGES → final REQUEST_CHANGES;
COMMENT beats APPROVE; APPROVE only if all branches agree).
Minimum confidence; max certainty rank (most uncertain wins).
Comments and fixes concatenated + deduped.
"""
from __future__ import annotations

_VERDICT_RANK = {"APPROVE": 0, "COMMENT": 1, "REQUEST_CHANGES": 2}
_CERTAINTY_RANK = {
    "fully_understood": 0,
    "minor_uncertainty": 1,
    "significant_uncertainty": 2,
}


def _dedupe_comments(comments: list[dict]) -> list[dict]:
    """Drop duplicates by (file, line, claim) — preserves order."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for c in comments:
        key = (c.get("file"), c.get("line"), c.get("claim"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _dedupe_fixes(fixes: list[dict]) -> list[dict]:
    """Drop duplicates by (tool, target_path)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for f in fixes:
        key = (f.get("tool"), f.get("target_path"))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def aggregate_branch_verdicts(branches: dict[str, dict]) -> dict:
    """Merge multiple branch outputs into one Pass-2-shaped result.

    Each branch value: {verdict?, confidence?, certainty?, summary?, comments, fixes_to_push?}

    Branches without `verdict` (e.g. cross_pr_conflict, test_stubs) contribute
    comments only — they don't influence the verdict/confidence aggregation.
    """
    verdicts = [b["verdict"] for b in branches.values() if "verdict" in b]
    final_verdict = max(verdicts, key=_VERDICT_RANK.get, default="COMMENT")

    confidences = [b.get("confidence", 1.0) for b in branches.values() if "verdict" in b]
    final_confidence = min(confidences, default=1.0)

    certainties = [b.get("certainty", "fully_understood") for b in branches.values() if "verdict" in b]
    final_certainty = max(certainties, key=_CERTAINTY_RANK.get, default="fully_understood")

    all_comments: list[dict] = []
    for b in branches.values():
        all_comments.extend(b.get("comments") or [])
    final_comments = _dedupe_comments(all_comments)

    all_fixes: list[dict] = []
    for b in branches.values():
        all_fixes.extend(b.get("fixes_to_push") or [])
    final_fixes = _dedupe_fixes(all_fixes)

    summary_parts = []
    for name, b in branches.items():
        s = (b.get("summary") or "").strip()
        if s:
            summary_parts.append(f"**{name}**: {s}")
    final_summary = "\n\n".join(summary_parts) if summary_parts else "(no branch produced a summary)"

    return {
        "verdict": final_verdict,
        "confidence": final_confidence,
        "certainty": final_certainty,
        "summary": final_summary,
        "comments": final_comments,
        "fixes_to_push": final_fixes,
    }
