"""Pass 1 — Triage. Single gpt-4o-mini call, no tools, structured output.

Returns:
  {
    "complexity": "trivial" | "standard" | "risky",
    "deep_review_files": list[str],
    "reasoning": str,
    "tokens_in": int,
    "tokens_out": int,
    "rate_limit_remaining": int | None,
  }
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

from .models_client import chat_completion

HERE = Path(__file__).parent
PROMPT_PATH = HERE / "prompts" / "pass1_triage_system.md"
SCHEMA_PATH = HERE / "schemas" / "pass1_triage.json"

# GitHub Models slug. Plan 2: nano has bigger context + generous low-tier quota.
MODEL = "openai/gpt-4.1-nano"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _user_prompt(pr: dict, hard_blocked: bool, hard_block_reasons: list[str]) -> str:
    files_block = "\n".join(f"  {p}" for p in pr["changed_files"]) or "  (none)"
    commits_block = "\n".join(f"  {m}" for m in pr["commit_messages"]) or "  (none)"
    body = pr.get("body") or "(empty)"
    reasons = ", ".join(hard_block_reasons) or "(none)"

    return (
        f"PR #{pr['pr_number']}: {pr['title']}\n\n"
        f"Body:\n{body}\n\n"
        f"Hard-blocked: {hard_blocked}\n"
        f"Hard-block reasons: {reasons}\n\n"
        f"Changed files ({pr['files_changed']}):\n{files_block}\n\n"
        f"Commit messages on branch:\n{commits_block}\n"
    )


def run_triage(*, pr: dict, hard_blocked: bool, hard_block_reasons: list[str], token: str) -> dict:
    system = PROMPT_PATH.read_text(encoding="utf-8")
    schema = _load_schema()
    user = _user_prompt(pr, hard_blocked, hard_block_reasons)

    result = chat_completion(
        model=MODEL,
        token=token,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=None,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "triage_v1", "schema": schema, "strict": True},
        },
        temperature=0.0,
    )

    if result.content is None:
        raise RuntimeError("triage returned empty content")
    try:
        parsed = json.loads(result.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"triage returned non-JSON: {e}") from e
    try:
        jsonschema_validate(instance=parsed, schema=schema)
    except ValidationError as e:
        raise RuntimeError(f"triage schema validation failed: {e.message}") from e

    if hard_blocked and parsed["complexity"] != "risky":
        # Enforce: hard-blocked => risky, regardless of what the LLM returned
        parsed["complexity"] = "risky"
        parsed["reasoning"] = "(forced risky by hard-block override) " + parsed["reasoning"]

    parsed["tokens_in"] = result.input_tokens
    parsed["tokens_out"] = result.output_tokens
    parsed["rate_limit_remaining"] = result.rate_limit_remaining
    return parsed
