"""Self-critique — gpt-4o-mini second-opinion on Pass 2's comments.

Receives Pass 2 output + the actual file excerpts at each cited line.
Returns {drops: [...], concerns: [...]}. Drops are applied; non-empty
concerns set self_critique_flagged_concerns=True in the verifier state.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

from .models_client import chat_completion

HERE = Path(__file__).parent
PROMPT_PATH = HERE / "prompts" / "critique_system.md"
SCHEMA_PATH = HERE / "schemas" / "critique.json"
MODEL = "openai/gpt-4.1-mini"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _excerpt(file_reader, file: str, line: int, context: int = 3) -> str:
    """Return ±context lines around the cited line, prefixed with line numbers."""
    try:
        lines = file_reader(file)
    except Exception:
        return f"<could not read {file}>"
    start = max(0, line - 1 - context)
    end = min(len(lines), line + context)
    out = []
    for i in range(start, end):
        prefix = ">>" if (i + 1) == line else "  "
        out.append(f"{prefix} {i + 1:5d} | {lines[i]}")
    return "\n".join(out)


def _user_prompt(pass2: dict, file_reader) -> str:
    sections = []
    for idx, c in enumerate(pass2.get("comments", [])):
        ex = _excerpt(file_reader, c["file"], c["line"])
        sections.append(
            f"=== comment {idx}: {c['file']}:{c['line']} ===\n"
            f"reviewer claim: {c['claim']}\n"
            f"expected_text:  {c['expected_text']!r}\n"
            f"actual excerpt:\n{ex}\n"
        )
    return (
        "Original review (JSON):\n"
        + json.dumps(
            {k: v for k, v in pass2.items() if k in ("verdict", "summary", "comments")},
            indent=2,
        )
        + "\n\nFile excerpts at each cited location:\n\n"
        + ("\n\n".join(sections) if sections else "(no comments to verify)")
    )


def run_critique(*, pass2: dict, file_reader, token: str) -> dict:
    system = PROMPT_PATH.read_text(encoding="utf-8")
    schema = _load_schema()
    user = _user_prompt(pass2, file_reader)

    result = chat_completion(
        model=MODEL, token=token,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=None,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "critique_v1", "schema": schema, "strict": True},
        },
        temperature=0.0,
    )
    if result.content is None:
        return {"drops": [], "concerns": ["critique returned empty content"]}
    try:
        parsed = json.loads(result.content)
        jsonschema_validate(instance=parsed, schema=schema)
    except (json.JSONDecodeError, ValidationError) as e:
        return {"drops": [], "concerns": [f"critique malformed: {e}"]}
    parsed["tokens_in"] = result.input_tokens
    parsed["tokens_out"] = result.output_tokens
    return parsed
