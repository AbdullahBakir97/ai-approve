"""Tests for skip_checks.should_skip() — the first decision point."""
from ai_approve.skip_checks import should_skip


def base_pr(**overrides):
    p = {
        "labels": [],
        "is_draft": False,
        "author_login": "AbdullahBakir97",
        "head_sha": "abc123",
        "last_reviewed_sha": None,
        "changed_files": ["backend/project/apps/users/views.py"],
    }
    p.update(overrides)
    return p


def test_no_reasons_to_skip_on_normal_pr():
    skip, reason = should_skip(base_pr())
    assert skip is False
    assert reason is None


def test_needs_human_label_skips():
    skip, reason = should_skip(base_pr(labels=["needs-human"]))
    assert skip is True
    assert "needs-human" in reason


def test_draft_skips():
    skip, reason = should_skip(base_pr(is_draft=True))
    assert skip is True
    assert "draft" in reason


def test_wip_label_skips():
    skip, reason = should_skip(base_pr(labels=["wip"]))
    assert skip is True
    assert "wip" in reason


def test_dependabot_author_skips():
    skip, reason = should_skip(base_pr(author_login="dependabot[bot]"))
    assert skip is True
    assert "dependabot" in reason


def test_github_actions_bot_author_skips():
    skip, reason = should_skip(base_pr(author_login="github-actions[bot]"))
    assert skip is True
    assert "bot" in reason.lower()


def test_already_reviewed_sha_skips():
    skip, reason = should_skip(base_pr(head_sha="abc123", last_reviewed_sha="abc123"))
    assert skip is True
    assert "already-reviewed" in reason


def test_new_sha_after_review_does_not_skip():
    skip, reason = should_skip(base_pr(head_sha="def456", last_reviewed_sha="abc123"))
    assert skip is False


def test_needs_human_wins_over_other_conditions():
    # If both needs-human AND another reason apply, needs-human is reported
    # (it's the most informative — tells you the user opted out).
    skip, reason = should_skip(base_pr(labels=["needs-human"], is_draft=True))
    assert skip is True
    assert "needs-human" in reason


# ───────────────────────────────────────────────────────────────────────
# Regression tests added during code review
# ───────────────────────────────────────────────────────────────────────


def test_should_skip_with_completely_empty_dict_does_not_raise():
    # Defensive: should_skip should never raise on missing keys.
    # An empty dict should produce (False, None) — nothing matched any rule.
    skip, reason = should_skip({})
    assert skip is False
    assert reason is None


def test_should_skip_with_last_reviewed_set_but_head_sha_missing_does_not_raise():
    # Regression: previously `pr["head_sha"]` would KeyError when
    # last_reviewed_sha was set but head_sha was missing. Now both use .get().
    skip, reason = should_skip({"last_reviewed_sha": "abc123"})
    assert skip is False  # last_sha != None but head_sha is None, so they aren't equal
    assert reason is None


def test_should_skip_with_only_labels_field():
    skip, reason = should_skip({"labels": ["needs-human"]})
    assert skip is True
    assert "needs-human" in reason
