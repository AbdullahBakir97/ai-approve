"""Tests for calibration.record_run() — verify the JSON evolves correctly."""
import json
from pathlib import Path

import pytest

from ai_approve import calibration


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    p = tmp_path / "docs" / "ai-approve" / "calibration.json"
    monkeypatch.setattr(calibration, "CALIBRATION_PATH", p)
    yield


def test_first_run_creates_file_with_one_verdict():
    pass2 = {"comments": []}
    calibration.record_run(verdict="APPROVE", pass2=pass2, changed_files=[])
    assert calibration.CALIBRATION_PATH.exists()
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert data["total_reviews"] == 1
    assert data["verdicts"]["APPROVE"]["count"] == 1


def test_subsequent_run_increments_existing_counts():
    calibration.record_run(verdict="APPROVE", pass2={"comments": []}, changed_files=[])
    calibration.record_run(verdict="REQUEST_CHANGES", pass2={"comments": [{}, {}]}, changed_files=[])
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert data["total_reviews"] == 2
    assert data["verdicts"]["APPROVE"]["count"] == 1
    assert data["verdicts"]["REQUEST_CHANGES"]["count"] == 1
    assert data["comments"]["posted"] == 2


def test_per_app_accumulator():
    calibration.record_run(
        verdict="APPROVE", pass2={"comments": []},
        changed_files=[
            "backend/project/apps/users/views.py",
            "backend/project/apps/users/services.py",
        ],
    )
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert data["by_app"]["apps/users"]["reviews"] == 1


def test_changed_files_without_app_dont_create_app_entry():
    calibration.record_run(
        verdict="COMMENT", pass2={"comments": []},
        changed_files=["docs/foo.md"],
    )
    data = json.loads(calibration.CALIBRATION_PATH.read_text())
    assert data["by_app"] == {}
