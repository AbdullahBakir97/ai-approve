"""Tests for branches.test_stubs — mocked LLM."""
import json
from unittest.mock import MagicMock, patch

from ai_approve.branches.test_stubs import (
    find_new_public_functions,
    run_test_stubs_branch,
)


def test_find_new_public_functions_extracts_def_lines():
    diff = """diff --git a/x.py b/x.py
@@ -0,0 +1,6 @@
+def apply_coupon(cart, coupon):
+    return cart
+def _private_helper():
+    return None
+    def nested_method(self):
+        return 1
"""
    funcs = find_new_public_functions(diff)
    names = [f["name"] for f in funcs]
    assert "apply_coupon" in names
    assert "_private_helper" not in names      # underscore prefix
    assert "nested_method" not in names         # indented (method)


def test_find_new_public_functions_includes_file_and_line():
    diff = """diff --git a/apps/carts/services.py b/apps/carts/services.py
@@ -10,0 +11,3 @@
+def apply_coupon(cart, coupon):
+    return cart
"""
    funcs = find_new_public_functions(diff)
    assert len(funcs) == 1
    assert funcs[0]["file"] == "apps/carts/services.py"
    assert funcs[0]["line"] == 11
    assert funcs[0]["name"] == "apply_coupon"


def test_no_new_functions_returns_empty_branch():
    diff = "diff --git a/x.py b/x.py\n+# just a comment change\n"
    with patch("ai_approve.branches.test_stubs.chat_completion") as mock_chat:
        result = run_test_stubs_branch(diff=diff, token="t")
    mock_chat.assert_not_called()
    assert result == {"comments": []}


def test_llm_call_made_when_functions_found():
    diff = """diff --git a/apps/carts/services.py b/apps/carts/services.py
@@ -10,0 +11,2 @@
+def apply_coupon(cart, coupon):
+    return cart
"""
    fake_response = MagicMock(content=json.dumps({
        "stubs": [{
            "for_file": "apps/carts/services.py",
            "for_line": 11,
            "for_function": "apply_coupon",
            "stub_code": "def test_apply_coupon():\n    assert apply_coupon(None, None) is None\n",
        }]
    }), tool_calls=None, input_tokens=200, output_tokens=80, rate_limit_remaining=None, raw={})
    with patch("ai_approve.branches.test_stubs.chat_completion", return_value=fake_response):
        result = run_test_stubs_branch(diff=diff, token="t")
    assert len(result["comments"]) == 1
    assert result["comments"][0]["severity"] == "info"


def test_branch_returns_no_verdict_field():
    diff = "diff --git a/x.py b/x.py\n"
    result = run_test_stubs_branch(diff=diff, token="t")
    assert "verdict" not in result


def test_llm_crash_yields_empty_silently():
    diff = """diff --git a/apps/carts/services.py b/apps/carts/services.py
@@ -0,0 +1,2 @@
+def f():
+    pass
"""
    with patch("ai_approve.branches.test_stubs.chat_completion", side_effect=Exception("api down")):
        result = run_test_stubs_branch(diff=diff, token="t")
    assert result == {"comments": []}
