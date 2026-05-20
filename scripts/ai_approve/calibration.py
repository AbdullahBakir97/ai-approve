"""Step 8 (also) — append this run's outcome to docs/ai-approve/calibration.json."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

CALIBRATION_PATH = Path("docs/ai-approve/calibration.json")


def load() -> dict:
    if not CALIBRATION_PATH.exists():
        return {
            "schema_version": 2,
            "generated_at": None,
            "total_reviews": 0,
            "verdicts": {
                "APPROVE":         {"count": 0, "merged_cleanly": 0, "human_overrode": 0},
                "REQUEST_CHANGES": {"count": 0, "human_dismissed": 0, "led_to_fix": 0},
                "COMMENT":         {"count": 0},
            },
            "comments": {"posted": 0, "resolved_with_fix": 0, "resolved_without_fix": 0, "still_open": 0},
            "calibration": {},
            "hot_dismissed_categories": [],
            "by_app": {},
            "branch_runs": {
                "standard":          {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
                "migration_deep":    {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
                "security":          {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
                "cross_pr_conflict": {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
                "test_stubs":        {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
            },
            "branch_disagreements": [],
        }
    data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    # Plan 2: migrate v1 → v2 (add branch_runs + branch_disagreements if missing)
    if data.get("schema_version", 1) < 2:
        data["schema_version"] = 2
        data.setdefault("branch_runs", {
            "standard":          {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
            "migration_deep":    {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
            "security":          {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
            "cross_pr_conflict": {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
            "test_stubs":        {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0},
        })
        data.setdefault("branch_disagreements", [])
    return data


def save(data: dict) -> None:
    data["generated_at"] = datetime.now(UTC).isoformat()
    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _detect_app(changed_files: list[str]) -> str | None:
    """Pick the dominant app under backend/project/apps/<name>/ if any."""
    apps: dict[str, int] = {}
    for f in changed_files:
        parts = f.split("/")
        if len(parts) >= 4 and parts[0] == "backend" and parts[1] == "project" and parts[2] == "apps":
            apps[parts[3]] = apps.get(parts[3], 0) + 1
    if not apps:
        return None
    return f"apps/{max(apps, key=apps.get)}"


def record_run(*, verdict: str, pass2: dict, changed_files: list[str]) -> None:
    """Update the persistent calibration file with this run's snapshot."""
    data = load()
    data["total_reviews"] = data.get("total_reviews", 0) + 1
    bucket = data["verdicts"][verdict]
    bucket["count"] = bucket.get("count", 0) + 1
    data["comments"]["posted"] = data["comments"].get("posted", 0) + len(pass2.get("comments", []))

    # Per-app accumulator
    app = _detect_app(changed_files)
    if app:
        by_app = data.setdefault("by_app", {})
        a = by_app.setdefault(app, {"reviews": 0, "accuracy": 1.0})
        a["reviews"] = a.get("reviews", 0) + 1

    save(data)


def record_branch_run(*, branch: str, duration_s: float, tokens_in: int) -> None:
    """Update per-branch metrics (avg duration + avg tokens, incremental)."""
    data = load()
    runs = data.setdefault("branch_runs", {})
    b = runs.setdefault(branch, {"count": 0, "avg_duration_s": 0, "avg_tokens_in": 0})
    n = b["count"]
    # Incremental average: new_avg = old_avg + (new_val - old_avg) / (n+1)
    b["avg_duration_s"] = b["avg_duration_s"] + (duration_s - b["avg_duration_s"]) / (n + 1)
    b["avg_tokens_in"] = b["avg_tokens_in"] + (tokens_in - b["avg_tokens_in"]) / (n + 1)
    b["count"] = n + 1
    save(data)


def record_branch_disagreement(*, pr: int, verdicts: dict, resolved_as: str) -> None:
    """Log when branches disagreed on verdict — informs Plan 3 retrospective."""
    data = load()
    data.setdefault("branch_disagreements", []).append({
        "pr": pr, **verdicts, "resolved_as": resolved_as,
    })
    save(data)
