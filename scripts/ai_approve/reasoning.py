"""Borderline reasoner — DeepSeek-R1 decides edge-case hard-block escalation.

Called from cli.py only when hard_blocks.evaluate() returns borderline=True
but hard_blocked=False. Returns: {should_hard_block: bool, reasoning: str}.

If DeepSeek-R1 is unavailable, defaults to should_hard_block=True
(conservative — better to over-block than over-approve borderline PRs).
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate as jsonschema_validate

from .models_client import chat_completion

HERE = Path(__file__).parent
PROMPT_PATH = HERE / "prompts" / "reasoning_borderline_system.md"
SCHEMA_PATH = HERE / "schemas" / "reasoning_borderline.json"

MODEL = "deepseek/DeepSeek-R1"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def evaluate_borderline(
    *,
    borderline_reasons: list[str],
    pr: dict,
    token: str,
) -> dict:
    """Decide whether to hard-block a borderline PR or delegate to Pass 2.

    Returns: {should_hard_block: bool, reasoning: str}.
    """
    system = PROMPT_PATH.read_text(encoding="utf-8")
    schema = _load_schema()
    reasons_block = "\n".join(f"- {r}" for r in borderline_reasons) or "(none)"
    user = (
        f"PR: '{pr.get('title', '(no title)')}'\n"
        f"files_changed: {pr.get('files_changed', '?')}\n"
        f"lines_changed: {pr.get('lines_changed', '?')}\n"
        f"borderline reasons:\n{reasons_block}\n\n"
        f"Decide: should this be hard-blocked, or can the standard Pass 2 "
        f"review handle it?"
    )

    try:
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
                "json_schema": {
                    "name": "reasoning_borderline_v1",
                    "schema": schema,
                    "strict": True,
                },
            },
            temperature=0.0,
        )
        if not result.content or not result.content.strip():
            return {
                "should_hard_block": True,
                "reasoning": (
                    "Reasoning model returned empty — defaulting to hard-block (conservative)."
                ),
            }
        parsed = json.loads(result.content)
        jsonschema_validate(instance=parsed, schema=schema)
        return {
            "should_hard_block": parsed["decision"] == "escalate_to_hard_block",
            "reasoning": parsed["reasoning"],
        }
    except Exception as e:
        return {
            "should_hard_block": True,
            "reasoning": (
                f"Borderline reasoner unavailable ({type(e).__name__}). "
                "Defaulting to hard-block (conservative)."
            ),
        }
