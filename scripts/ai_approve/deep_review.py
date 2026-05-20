"""Pass 2 — Deep review with agentic tool loop. Max 10 tool calls.

The LLM may call read_file/grep/list_dir up to 10 times to gather
evidence before producing its final structured verdict.

If it hits the tool budget, we force a finalize call: append a system
message telling it to produce the JSON now with whatever evidence it has,
and the conservative_gate will downgrade verdict via tool_calls_exhausted.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

from .models_client import ModelsHTTPError, RateLimitedError, chat_completion
from .tools import TOOL_SCHEMAS, dispatch

HERE = Path(__file__).parent
PROMPT_PATH = HERE / "prompts" / "pass2_deep_review_system.md"
SCHEMA_PATH = HERE / "schemas" / "pass2_deep_review.json"

# Plan 2: gpt-4.1 has 1M context; Llama 3.1 405B (128K) is the fallback when
# OpenAI quota is exhausted. Both support function tool use.
MODEL = "openai/gpt-4.1"
FALLBACK_MODEL = "meta/Meta-Llama-3.1-405B-Instruct"
MAX_TOOL_CALLS = 10


def _chat_with_fallback(**kwargs):
    """Try primary MODEL; on rate-limit or 5xx, retry once with FALLBACK_MODEL."""
    try:
        return chat_completion(model=MODEL, **kwargs)
    except (RateLimitedError, ModelsHTTPError):
        return chat_completion(model=FALLBACK_MODEL, **kwargs)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _system_prompt(lessons_md: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace(
        "{{LESSONS_FILE_CONTENT_INSERTED_HERE_AT_RUNTIME}}",
        lessons_md or "(no project-specific lessons recorded yet)",
    )


def _user_prompt(pr: dict, deep_files_content: dict[str, str]) -> str:
    # Note: CLAUDE.md is deliberately NOT included here. It's ~33KB
    # (~8K tokens) — alone exceeds the GitHub Models free-tier 8K
    # request limit. Project-specific conventions are funneled through
    # the lessons.md injection in the SYSTEM prompt instead, which
    # grows over time as the retrospective adds them.
    deep_block = "\n\n".join(
        f"=== {path} ===\n{content}" for path, content in deep_files_content.items()
    ) or "(none)"
    audit = pr.get("audit_doc") or "(none referenced)"
    body = pr.get("body") or "(empty)"
    return (
        f"PR #{pr['pr_number']}: {pr['title']}\n\n"
        f"Body:\n{body}\n\n"
        f"Linked audit doc:\n{audit}\n\n"
        f"=== DIFF ===\n{pr['diff']}\n\n"
        f"=== DEEP-REVIEW FILES ===\n{deep_block}\n"
    )


def run_deep_review(
    *,
    pr: dict,
    lessons_md: str,
    deep_files_content: dict[str, str],
    repo_root: Path,
    token: str,
) -> dict:
    """Run the agentic loop and return parsed structured output.

    Returns dict with all Pass 2 schema fields + meta:
      tokens_in_total, tokens_out_total, tool_calls_used,
      rate_limit_remaining, tool_calls_exhausted (bool)
    """
    system = _system_prompt(lessons_md)
    user = _user_prompt(pr, deep_files_content)
    schema = _load_schema()

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    tokens_in = 0
    tokens_out = 0
    tool_calls_used = 0
    rate_limit_remaining = None
    tool_calls_exhausted = False

    # ─── PHASE 1: tools-only loop ─────────────────────────────────────
    # Model gathers evidence via read_file / grep / list_dir. No
    # response_format here — OpenAI's strict json_schema is incompatible
    # with tool use, and we don't need structured output mid-loop.
    #
    # Exit conditions:
    #   - Model stops calling tools (with or without content) → break to finalize
    #   - Tool budget exhausted → break to finalize with the exhausted flag
    for iteration in range(MAX_TOOL_CALLS):
        result = _chat_with_fallback(
            token=token,
            messages=messages,
            tools=TOOL_SCHEMAS,
            response_format=None,
            temperature=0.0,
        )
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        rate_limit_remaining = result.rate_limit_remaining

        if not result.tool_calls:
            # Model is done investigating (or refused without tool use).
            # Append whatever it said for context, then break to finalize.
            if result.content:
                messages.append({"role": "assistant", "content": result.content})
            break

        messages.append({
            "role": "assistant",
            "content": result.content,
            "tool_calls": result.tool_calls,
        })
        for call in result.tool_calls:
            tool_calls_used += 1
            fn = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_result = dispatch(fn, args, repo_root=repo_root)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": tool_result[:10000],  # cap per-tool output
            })
    else:
        # for/else: ran the full MAX_TOOL_CALLS iterations without breaking.
        # Means the model called tools every single round — out of budget.
        tool_calls_exhausted = True

    # ─── PHASE 2: explicit finalize ────────────────────────────────────
    # Always runs. Forces structured JSON via response_format.
    if tool_calls_exhausted:
        messages.append({
            "role": "system",
            "content": (
                f"TOOL CALL BUDGET EXHAUSTED ({MAX_TOOL_CALLS}/{MAX_TOOL_CALLS}). "
                "Return your final structured JSON verdict NOW based on the "
                "evidence you have. Set certainty='significant_uncertainty' "
                "and verdict='REQUEST_CHANGES'."
            ),
        })
    else:
        messages.append({
            "role": "system",
            "content": (
                "Return your final structured JSON verdict NOW. It MUST match "
                "the deep_review_v1 schema (verdict, confidence, certainty, "
                "summary, comments, fixes_to_push)."
            ),
        })

    finalize = _chat_with_fallback(
        token=token,
        messages=messages,
        tools=None,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "deep_review_v1", "schema": schema, "strict": True},
        },
        temperature=0.0,
    )
    tokens_in += finalize.input_tokens
    tokens_out += finalize.output_tokens
    rate_limit_remaining = finalize.rate_limit_remaining

    if not finalize.content or not finalize.content.strip():
        raise RuntimeError("deep_review finalize returned empty content")
    try:
        parsed = json.loads(finalize.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"deep_review finalize returned non-JSON: {e}") from e
    try:
        jsonschema_validate(instance=parsed, schema=schema)
    except ValidationError as e:
        raise RuntimeError(f"deep_review finalize schema validation failed: {e.message}") from e

    parsed["tokens_in_total"] = tokens_in
    parsed["tokens_out_total"] = tokens_out
    parsed["tool_calls_used"] = tool_calls_used
    parsed["rate_limit_remaining"] = rate_limit_remaining
    parsed["tool_calls_exhausted"] = tool_calls_exhausted
    return parsed
