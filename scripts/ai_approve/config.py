"""Tier-aware configuration for AI-approve.

GitHub Models free tier caps every model at 8000 input tokens / 4000 output
tokens per request, regardless of the model's advertised context window
(verified live 2026-05-21 against gpt-4o-mini, gpt-4o, Meta-Llama-3.1-405B).
Paid tier lifts this cap (per maintainer KateCatlin in community discussion
149698: "rates are unlimited and context window limits are larger").

Trim caps must therefore be sized for the active tier. Set AI_APPROVE_TIER=paid
in the workflow env after upgrading the GitHub Models subscription; otherwise
the free profile keeps the Pass 2 deep-review prompt safely under 8K input.

Docs: https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TrimCaps:
    """Pass 2 deep-review prompt trim limits, in characters.

    `claude_md=0` means drop CLAUDE.md entirely from the user prompt; any
    other value caps it to that many chars before truncation marker is
    appended.
    """
    claude_md: int
    audit_doc: int
    diff_pass2: int
    deep_file: int
    deep_files: int
    body: int


# Free tier (8K input cap, uniform across all models). Worst-case prompt:
#   audit (800) + 2*deep_file (4000) + diff (5000) + body (1200)
#   = ~11K chars = ~2.75K tokens, comfortably under 8K with system+tools.
# CLAUDE.md is dropped — even truncated it crowds out the diff.
FREE_CAPS = TrimCaps(
    claude_md=0,
    audit_doc=800,
    diff_pass2=5000,
    deep_file=2000,
    deep_files=2,
    body=1200,
)

# Paid tier (no 8K cap). Sized for ~100K input token requests, leaving room
# for system prompt, tool schemas, and multi-turn agentic conversation.
# CLAUDE.md rides along so the bot sees full project conventions.
PAID_CAPS = TrimCaps(
    claude_md=30000,
    audit_doc=20000,
    diff_pass2=200000,
    deep_file=30000,
    deep_files=10,
    body=4000,
)


def trim_caps() -> TrimCaps:
    """Return trim caps for the active tier (AI_APPROVE_TIER env var)."""
    tier = os.environ.get("AI_APPROVE_TIER", "free").strip().lower()
    return PAID_CAPS if tier == "paid" else FREE_CAPS
