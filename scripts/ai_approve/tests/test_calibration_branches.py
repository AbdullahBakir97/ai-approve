"""Tests for Plan 2 calibration extensions."""
import json

import pytest

from ai_approve import calibration


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    p = tmp_path / "docs" / "ai-approve" / "calibration.json"
    monkeypatch.setattr(calibration, "CALIBRATION_PATH", p)
    yield


def test_record_branch_run_increments_count():
    calibration.record_branch_run(branch="standard", duration_s=30.0, tokens_in=15000)
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert data["branch_runs"]["standard"]["count"] == 1
    assert data["branch_runs"]["standard"]["avg_duration_s"] == 30.0
    assert data["branch_runs"]["standard"]["avg_tokens_in"] == 15000


def test_record_branch_run_computes_incremental_average():
    calibration.record_branch_run(branch="standard", duration_s=20.0, tokens_in=10000)
    calibration.record_branch_run(branch="standard", duration_s=40.0, tokens_in=20000)
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert data["branch_runs"]["standard"]["count"] == 2
    assert data["branch_runs"]["standard"]["avg_duration_s"] == pytest.approx(30.0)
    assert data["branch_runs"]["standard"]["avg_tokens_in"] == pytest.approx(15000)


def test_record_branch_disagreement_appends_entry():
    calibration.record_branch_disagreement(
        pr=88,
        verdicts={"standard": "APPROVE", "security": "REQUEST_CHANGES"},
        resolved_as="REQUEST_CHANGES",
    )
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert len(data["branch_disagreements"]) == 1
    assert data["branch_disagreements"][0]["pr"] == 88
    assert data["branch_disagreements"][0]["resolved_as"] == "REQUEST_CHANGES"


def test_load_creates_v2_default_when_file_missing():
    data = calibration.load()
    assert data["schema_version"] == 2
    assert "branch_runs" in data
    assert "branch_disagreements" in data


def test_load_migrates_v1_to_v2():
    # Write a v1-shaped file manually
    v1_data = {
        "schema_version": 1, "generated_at": None, "total_reviews": 0,
        "verdicts": {"APPROVE": {"count": 0, "merged_cleanly": 0, "human_overrode": 0},
                     "REQUEST_CHANGES": {"count": 0, "human_dismissed": 0, "led_to_fix": 0},
                     "COMMENT": {"count": 0}},
        "comments": {"posted": 0, "resolved_with_fix": 0, "resolved_without_fix": 0, "still_open": 0},
        "calibration": {}, "hot_dismissed_categories": [], "by_app": {},
    }
    calibration.CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    calibration.CALIBRATION_PATH.write_text(json.dumps(v1_data))
    data = calibration.load()
    assert data["schema_version"] == 2
    assert data["branch_runs"]["standard"]["count"] == 0
