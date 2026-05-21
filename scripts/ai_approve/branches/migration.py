"""Migration deep-inspection branch — analyzes Django migration safety.

Triggered when PR touches `backend/project/apps/*/migrations/*.py`.
Reads migration file + affected models, asks Llama 3.1 405B to simulate
the schema change and flag dangerous patterns.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import validate as jsonschema_validate

from ..models_client import chat_completion

HERE = Path(__file__).parent.parent
PROMPT_PATH = HERE / "prompts" / "branch_migration_system.md"
SCHEMA_PATH = HERE / "schemas" / "branch_migration.json"

# `openai/gpt-4.1` from the original spec doesn't exist on GitHub Models.
# Llama 3.1 405B is the largest-context (128K) model actually available.
MODEL = "Meta-Llama-3.1-405B-Instruct"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def detect_migration_files(paths: list[str]) -> list[str]:
    """Return paths matching Django migration pattern."""
    return [
        p for p in paths
        if re.match(r"backend/project/apps/[^/]+/migrations/\d+_.+\.py$", p)
    ]


def _read_safe(repo_root: str, rel_path: str, max_chars: int = 30000) -> str:
    p = Path(repo_root) / rel_path
    if not p.exists() or not p.is_file():
        return f"<file not found: {rel_path}>"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception as e:
        return f"<could not read {rel_path}: {e}>"


def _comment_partial(summary: str) -> dict:
    return {
        "verdict": "COMMENT",
        "confidence": 0.0,
        "certainty": "significant_uncertainty",
        "summary": summary,
        "comments": [],
    }


def run_migration_branch(*, pr: dict, repo_root: str, token: str) -> dict:
    """Run the migration deep-inspection branch."""
    paths = pr.get("changed_files") or []
    migration_paths = detect_migration_files(paths)
    if not migration_paths:
        return {"comments": []}

    body = (pr.get("body") or "").lower()
    if "[skip-migration-check]" in body:
        return {"comments": []}

    affected_apps = sorted({
        re.match(r"backend/project/apps/([^/]+)/migrations/", p).group(1)
        for p in migration_paths
    })
    sections: list[str] = []
    for mp in migration_paths:
        sections.append(f"=== MIGRATION: {mp} ===\n{_read_safe(repo_root, mp)}")
    for app in affected_apps:
        models_path = f"backend/project/apps/{app}/models.py"
        sections.append(f"=== MODELS ({app}): {models_path} ===\n{_read_safe(repo_root, models_path)}")

    user_prompt = "\n\n".join(sections)
    system = PROMPT_PATH.read_text(encoding="utf-8")
    schema = _load_schema()

    try:
        result = chat_completion(
            model=MODEL, token=token,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            tools=None,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "branch_migration_v1", "schema": schema, "strict": True},
            },
            temperature=0.0,
        )
        if not result.content or not result.content.strip():
            return _comment_partial("Migration deep-inspection unavailable — empty LLM response.")
        parsed = json.loads(result.content)
        jsonschema_validate(instance=parsed, schema=schema)
    except Exception:
        return _comment_partial(
            "Migration deep-inspection unavailable, defaulting to hard-block per `migrations` rule."
        )

    return parsed
