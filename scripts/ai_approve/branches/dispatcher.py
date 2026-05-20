"""Branch dispatcher — selects which specialized review branches run per PR.

Pure function; no I/O. See design spec §9.
"""
from __future__ import annotations

import re


def _is_security_sensitive(path: str) -> bool:
    """Return True if `path` matches any auth/security-relevant pattern."""
    path_lower = path.lower()
    if "auth" in path_lower:
        return True
    if path.endswith(("serializers.py", "permissions.py")):
        return True
    if "middleware" in path_lower:
        return True
    if path.endswith("settings.py"):
        return True
    if re.search(r"raw_sql", path, re.IGNORECASE):
        # Path-level only — actual SQL-injection content scanning lives
        # in branches/security.py (which reads the file and looks for
        # cursor.execute(...), RawSQL(...), extra(...) etc.)
        return True
    return False


def select_branches(pr_metadata: dict) -> list[str]:
    """Return list of branch IDs to run for this PR.

    Always-on: standard, cross_pr_conflict, test_stubs.
    Path-triggered: migration_deep, security.
    """
    paths = pr_metadata.get("changed_files") or []
    branches = ["standard"]

    if any(re.match(r"backend/project/apps/[^/]+/migrations/", p) for p in paths):
        branches.append("migration_deep")

    if any(_is_security_sensitive(p) for p in paths):
        branches.append("security")

    branches.append("cross_pr_conflict")
    branches.append("test_stubs")

    return branches
