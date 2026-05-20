"""Security-specialized review branch — OWASP top 10 + Django anti-patterns.

Triggered when PR touches files matching auth/serializer/raw-SQL/middleware/
settings patterns. Reads each in full, asks LLM (gpt-4.1) with a
security-focused system prompt.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate as jsonschema_validate

from ..models_client import chat_completion
from .dispatcher import _is_security_sensitive

HERE = Path(__file__).parent.parent
PROMPT_PATH = HERE / "prompts" / "branch_security_system.md"
SCHEMA_PATH = HERE / "schemas" / "branch_security.json"

MODEL = "openai/gpt-4.1"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def detect_security_files(paths: list[str]) -> list[str]:
    """Return paths matching security-sensitive patterns."""
    return [p for p in paths if _is_security_sensitive(p)]


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


def run_security_branch(*, pr: dict, repo_root: str, token: str) -> dict:
    """Run the security-specialized review branch."""
    paths = pr.get("changed_files") or []
    sec_paths = detect_security_files(paths)
    if not sec_paths:
        return {"comments": []}

    body = (pr.get("body") or "").lower()
    if "[skip-security-check]" in body:
        return {"comments": []}

    sections: list[str] = []
    for sp in sec_paths:
        sections.append(f"=== {sp} ===\n{_read_safe(repo_root, sp)}")
    user_prompt = "\n\n".join(sections)
    system = PROMPT_PATH.read_text(encoding="utf-8")
    schema = _load_schema()

    try:
        result = chat_completion(
            model=MODEL,
            token=token,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            tools=None,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "branch_security_v1",
                    "schema": schema,
                    "strict": True,
                },
            },
            temperature=0.0,
        )
        if not result.content or not result.content.strip():
            return _comment_partial("Security review unavailable — empty LLM response.")
        parsed = json.loads(result.content)
        jsonschema_validate(instance=parsed, schema=schema)
    except Exception:
        return _comment_partial(
            "Security review unavailable — please human-review files touching auth/serializers."
        )

    return parsed
