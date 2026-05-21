"""Category/priority label rules — read from the consumer repo's
`.github/labeler.yml` and applied alongside the bot's own `bot-*` labels.

Why this lives in the bot:
    The repo already had a separate `actions/labeler@v5` workflow doing
    category labeling on PRs, but that workflow only fires when the
    workflow file exists on the PR's BASE branch — so it silently misses
    PRs against any track branch where the workflow hasn't been propagated.
    Folding the same rule semantics into the bot makes labeling work
    everywhere the bot reviews, with no separate moving part.

Supported subset of actions/labeler@v5 rule shapes
    (matches the rules currently used in this project's labeler.yml):

      changed-files:
        - any-glob-to-any-file: 'glob-or-list'
      head-branch: '^regex'
      all: [<sub-rule>, ...]

A label fires when ANY of its top-level rules matches.

Other actions/labeler features (e.g. `all-globs-to-any-file`,
`any-glob-to-all-files`, `base-branch`) aren't currently used in this
repo so they're not mirrored here. Add them lazily when needed.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def load_labeler_config(repo_root: Path) -> dict:
    """Return parsed `.github/labeler.yml`, or `{}` if missing/unreadable."""
    cfg_path = repo_root / ".github" / "labeler.yml"
    if not cfg_path.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _glob_matches_any(path: str, globs: list[str]) -> bool:
    """Match `actions/labeler@v5` semantics for `any-glob-to-any-file`."""
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        # `**/X` — X anywhere in the tree
        if g.startswith("**/") and fnmatch.fnmatch(path, g[3:]):
            return True
        if g.startswith("**/") and any(
            fnmatch.fnmatch(part, g[3:]) for part in path.split("/")
        ):
            return True
        # `prefix/**` — anything under prefix
        if g.endswith("/**") and (path == g[:-3] or path.startswith(g[:-3] + "/")):
            return True
    return False


def _eval_rule(rule: dict[str, Any], files: list[str], head_branch: str) -> bool:
    """Evaluate one rule clause from labeler.yml. True if it matches."""
    if "changed-files" in rule:
        cf = rule["changed-files"]
        if not isinstance(cf, list):
            cf = [cf]
        for entry in cf:
            globs = entry.get("any-glob-to-any-file") if isinstance(entry, dict) else None
            if globs is None:
                continue
            if isinstance(globs, str):
                globs = [globs]
            if any(_glob_matches_any(p, globs) for p in files):
                return True
        return False
    if "head-branch" in rule:
        pattern = rule["head-branch"]
        patterns = pattern if isinstance(pattern, list) else [pattern]
        return any(re.search(p, head_branch) for p in patterns)
    if "all" in rule:
        return all(_eval_rule(sub, files, head_branch) for sub in rule["all"])
    return False


def select_category_labels(
    labeler_cfg: dict,
    files: list[str],
    head_branch: str,
) -> set[str]:
    """Return the set of category/priority labels that should apply.

    Pure function — does not mutate config and does not touch the network.
    Tested in isolation; the caller (cli.py) feeds the result into
    `labels.apply_labels` via the `extra_labels` parameter.
    """
    out: set[str] = set()
    if not isinstance(labeler_cfg, dict):
        return out
    for label_name, rules in labeler_cfg.items():
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if isinstance(rule, dict) and _eval_rule(rule, files, head_branch):
                out.add(label_name)
                break
    return out
