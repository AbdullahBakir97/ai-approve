"""Tests for verify.py — strips comments whose expected_text doesn't match."""
from ai_approve.verify import (
    FORBIDDEN_PHRASES,
    has_forbidden_phrase,
    verify_comments,
)


def file_reader_factory(file_contents: dict):
    """Make a fake reader that returns lines from a dict."""
    def read(path: str) -> list[str]:
        return file_contents[path].splitlines()
    return read


def test_comment_with_matching_expected_text_survives():
    contents = {"app/views.py": "line one\nimport os\nline three"}
    reader = file_reader_factory(contents)
    comments = [{
        "file": "app/views.py",
        "line": 2,
        "expected_text": "import os",
        "claim": "unused import",
        "severity": "warn",
    }]
    kept, dropped = verify_comments(comments, reader)
    assert len(kept) == 1
    assert len(dropped) == 0


def test_comment_with_mismatched_expected_text_dropped():
    contents = {"app/views.py": "line one\nimport sys\nline three"}
    reader = file_reader_factory(contents)
    comments = [{
        "file": "app/views.py",
        "line": 2,
        "expected_text": "import os",
        "claim": "unused import",
        "severity": "warn",
    }]
    kept, dropped = verify_comments(comments, reader)
    assert len(kept) == 0
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "expected_text_mismatch"


def test_comment_with_missing_file_dropped():
    reader = file_reader_factory({})  # file not in dict
    comments = [{
        "file": "app/missing.py",
        "line": 1,
        "expected_text": "x",
        "claim": "y",
        "severity": "warn",
    }]
    kept, dropped = verify_comments(comments, reader)
    assert len(kept) == 0
    assert dropped[0]["reason"] == "file_not_found"


def test_comment_with_line_out_of_range_dropped():
    contents = {"app/views.py": "only_line"}
    reader = file_reader_factory(contents)
    comments = [{
        "file": "app/views.py",
        "line": 99,
        "expected_text": "x",
        "claim": "y",
        "severity": "warn",
    }]
    kept, dropped = verify_comments(comments, reader)
    assert len(kept) == 0
    assert dropped[0]["reason"] == "line_out_of_range"


def test_leading_whitespace_in_expected_text_is_significant():
    # Strict match — whitespace matters. Forces the LLM to be precise.
    contents = {"app/views.py": "    return 1"}
    reader = file_reader_factory(contents)
    comments = [{
        "file": "app/views.py",
        "line": 1,
        "expected_text": "return 1",  # missing indent
        "claim": "y",
        "severity": "warn",
    }]
    kept, dropped = verify_comments(comments, reader)
    assert len(kept) == 0
    assert dropped[0]["reason"] == "expected_text_mismatch"


def test_forbidden_phrase_detection_picks_up_presumably():
    body = "This change presumably handles edge cases."
    assert has_forbidden_phrase(body) is True


def test_forbidden_phrase_detection_picks_up_seems_to():
    body = "The function seems to validate input correctly."
    assert has_forbidden_phrase(body) is True


def test_forbidden_phrase_detection_case_insensitive():
    body = "PRESUMABLY this is correct."
    assert has_forbidden_phrase(body) is True


def test_forbidden_phrase_detection_clean_text_passes():
    # Use words that are unlikely to ever join FORBIDDEN_PHRASES so this
    # test stays a true negative even as the list grows.
    body = "I read apps/users/views.py line 42 and confirmed it calls check_phone()."
    assert has_forbidden_phrase(body) is False


def test_forbidden_phrases_list_includes_required_words():
    required = {"presumably", "likely", "typically", "probably", "seems to"}
    listed = {p.lower() for p in FORBIDDEN_PHRASES}
    assert required.issubset(listed)


# ───────────────────────────────────────────────────────────────────────
# Regression tests added during code review
# ───────────────────────────────────────────────────────────────────────


def test_forbidden_phrase_does_not_match_seems_to_inside_seems_toaster():
    # The regex uses `\b(seems to|...)\b`. The trailing `\b` lands between
    # `o` (end of "seems to") and `a` (start of "aster"), which are both
    # word chars — so NOT a word boundary, so no match. Verified empirically
    # before the test was written. This locks in the correct behavior in
    # case anyone refactors the regex later.
    assert has_forbidden_phrase("seems toaster on the counter") is False


def test_forbidden_phrase_does_not_match_inside_a_word():
    # presumablyfoo and foopresumably should NOT match — \b prevents
    # mid-word matches on either side.
    assert has_forbidden_phrase("presumablyfoo bar") is False
    assert has_forbidden_phrase("foopresumably bar") is False


def test_verify_comments_handles_empty_list():
    kept, dropped = verify_comments([], lambda p: [""])
    assert kept == []
    assert dropped == []


def test_verify_comments_drops_negative_line():
    # If the LLM hallucinates line: 0 or line: -1, line_idx becomes -1
    # which should be rejected by the line_out_of_range guard, NOT silently
    # indexed into the last line via Python's negative indexing.
    contents = {"app/x.py": "one\ntwo"}
    reader = file_reader_factory(contents)
    for bad_line in (0, -1):
        kept, dropped = verify_comments(
            [{"file": "app/x.py", "line": bad_line, "expected_text": "two", "claim": "y", "severity": "warn"}],
            reader,
        )
        assert len(kept) == 0
        assert dropped[0]["reason"] == "line_out_of_range", f"line={bad_line}"


def test_verify_comments_caches_per_file():
    # Two comments on the same file should trigger ONE reader call.
    calls = []
    def counting_reader(path):
        calls.append(path)
        return ["import os"]
    comments = [
        {"file": "app/x.py", "line": 1, "expected_text": "import os", "claim": "c1", "severity": "nit"},
        {"file": "app/x.py", "line": 1, "expected_text": "import os", "claim": "c2", "severity": "nit"},
    ]
    kept, dropped = verify_comments(comments, counting_reader)
    assert len(kept) == 2
    assert len(dropped) == 0
    assert calls == ["app/x.py"], f"expected 1 read, got {len(calls)}"


def test_verify_comments_caches_failed_read_as_none():
    # Once the reader raises, subsequent comments for the same path get
    # file_not_found without re-attempting (cached as None).
    calls = []
    def failing_reader(path):
        calls.append(path)
        raise OSError("transient")
    comments = [
        {"file": "app/x.py", "line": 1, "expected_text": "x", "claim": "c1", "severity": "nit"},
        {"file": "app/x.py", "line": 1, "expected_text": "y", "claim": "c2", "severity": "nit"},
    ]
    kept, dropped = verify_comments(comments, failing_reader)
    assert len(kept) == 0
    assert len(dropped) == 2
    assert all(d["reason"] == "file_not_found" for d in dropped)
    assert calls == ["app/x.py"], f"expected 1 attempted read (then cached as None), got {len(calls)}"


def test_verify_comments_normalizes_trailing_newline_in_actual_line():
    # If a reader returns lines WITH trailing \n (e.g. readlines()), the
    # verifier should still match against LLM expected_text without \n.
    def newline_reader(path):
        return ["import os\n", "line two\n"]
    comments = [{
        "file": "app/x.py", "line": 1,
        "expected_text": "import os",
        "claim": "y", "severity": "warn",
    }]
    kept, dropped = verify_comments(comments, newline_reader)
    assert len(kept) == 1
    assert len(dropped) == 0
