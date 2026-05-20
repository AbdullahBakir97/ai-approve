"""Final-verdict gate — the bot's single safety contract.

Pure function. Every code path leading to "post a review" funnels through
final_verdict(). Any failure mode that we did not anticipate defaults to
COMMENT (the safest non-blocking option). See spec §12.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VerifierState:
    """Aggregated state from the pipeline's verifier + observability layer.

    Every field defaults to "no problem" — callers explicitly set to True
    only when a problem is detected. This makes additions backward-compatible.
    """
    llm_crashed: bool = False
    timed_out: bool = False
    rate_limited: bool = False
    tool_calls_exhausted: bool = False
    forbidden_phrase_present: bool = False
    schema_validation_failed: bool = False
    self_critique_flagged_concerns: bool = False
    comments_with_severity_blocker: int = 0
    comments_with_severity_major: int = 0
    fixes_resolve_that_major_comment: bool = False


def final_verdict(
    pass2_output: dict,
    hard_blocked: bool,
    vs: VerifierState,
) -> str:
    """Return one of 'APPROVE' | 'REQUEST_CHANGES' | 'COMMENT'.

    This function NEVER returns APPROVE unless every safety check passes.
    """
    # Deterministic NOs (hard block, infra failure, signal failure).
    #
    # Verdict semantics for failure cases:
    #
    #   COMMENT          = the bot has NO trustworthy signal (infra was
    #                      down, output was unparseable). Does not block
    #                      auto-merge — a human approval can still merge
    #                      the PR. Use when the bot itself failed.
    #
    #   REQUEST_CHANGES  = the bot HAS signal but it points to a problem
    #                      (forbidden phrase, tool budget exhausted while
    #                      actively investigating, hard-block triggered).
    #                      Blocks auto-merge until human dismisses.
    #
    # `hard_blocked` wins over everything else (deterministic policy beats
    # any LLM judgment, including a coincident infra failure).
    if hard_blocked:
        return "REQUEST_CHANGES"
    if vs.llm_crashed:
        return "COMMENT"
    if vs.timed_out:
        return "COMMENT"
    if vs.rate_limited:
        return "COMMENT"
    if vs.schema_validation_failed:
        return "COMMENT"
    if vs.tool_calls_exhausted:
        return "REQUEST_CHANGES"
    if vs.forbidden_phrase_present:
        return "REQUEST_CHANGES"

    # Defensive `.get()` with FAIL-CLOSED defaults: any missing field
    # collapses to the strictest interpretation (REQUEST_CHANGES /
    # zero confidence / significant uncertainty). A malformed pass2_output
    # cannot accidentally produce APPROVE. Schema validation upstream
    # should make these defaults unreachable in practice — they're a
    # belt-and-braces guarantee, not the primary contract.
    verdict = pass2_output.get("verdict", "REQUEST_CHANGES")
    if verdict != "APPROVE":
        return verdict

    # APPROVE only survives if every confidence/severity check passes
    if pass2_output.get("confidence", 0.0) < 0.85:
        return "REQUEST_CHANGES"
    if pass2_output.get("certainty", "significant_uncertainty") != "fully_understood":
        return "REQUEST_CHANGES"
    if vs.self_critique_flagged_concerns:
        return "REQUEST_CHANGES"
    if vs.comments_with_severity_blocker > 0:
        return "REQUEST_CHANGES"
    if vs.comments_with_severity_major >= 2:
        return "REQUEST_CHANGES"
    if vs.comments_with_severity_major == 1 and not vs.fixes_resolve_that_major_comment:
        return "REQUEST_CHANGES"

    return "APPROVE"
