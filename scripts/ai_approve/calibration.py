"""Step 8 (also) — append this run's outcome to docs/ai-approve/calibration.json."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


CALIBRATION_PATH = Path("docs/ai-approve/calibration.json")


def load() -> dict:
    if not CALIBRATION_PATH.exists():
        return {
            "schema_version": 1,
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
        }
    return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
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
