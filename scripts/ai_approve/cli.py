"""CLI entrypoint for the ai-approve pipeline.

Usage (from workflow):
    python -m ai_approve.cli --repo owner/repo --pr 42 --branch feat/...

Returns exit code 0 on success (review posted or skipped intentionally),
non-zero only on UNEXPECTED failure (workflow_run gets red, you investigate).
Expected failure paths (rate limit, schema fail, etc.) still exit 0 — the
review body explains.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from . import calibration, summary
from .apply_fixes import apply_fixes
from .branches.aggregator import aggregate_branch_verdicts
from .branches.cross_pr import run_cross_pr_branch
from .branches.dispatcher import select_branches
from .branches.migration import run_migration_branch
from .branches.security import run_security_branch
from .branches.test_stubs import run_test_stubs_branch
from .config import trim_caps
from .conservative_gate import VerifierState, final_verdict
from .critique import run_critique
from .deep_review import run_deep_review
from .gather import gather
from .hard_blocks import evaluate as evaluate_hard_blocks
from .models_client import ModelsHTTPError, RateLimitedError
from .post_review import inline_body_for_comment, post_review, render_body
from .reasoning import evaluate_borderline
from .skip_checks import should_skip
from .state import embed_in_comment, empty_state, extract_from_comment
from .triage import run_triage
from .verify import has_forbidden_phrase, verify_comments


def _gh_get_state_comment(repo: str, pr_number: int, token: str) -> tuple[int | None, dict | None]:
    """Find the hidden state comment on the PR (if any).

    Returns (comment_id, state_dict) or (None, None).
    """
    import json
    import subprocess
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{pr_number}/comments", "--paginate"],
        capture_output=True, text=True,
        env={"GH_TOKEN": token, "PATH": os.environ.get("PATH", "")},
    )
    if r.returncode != 0:
        return None, None
    try:
        comments = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, None
    for c in comments:
        body = c.get("body") or ""
        st = extract_from_comment(body)
        if st is not None:
            return c["id"], st
    return None, None


def _gh_upsert_state_comment(
    repo: str, pr_number: int, comment_id: int | None,
    state: dict, token: str,
) -> None:
    import subprocess
    body = embed_in_comment(state)
    if comment_id is None:
        cmd = [
            "gh", "api", f"repos/{repo}/issues/{pr_number}/comments",
            "--method", "POST", "-f", f"body={body}",
        ]
    else:
        cmd = [
            "gh", "api", f"repos/{repo}/issues/comments/{comment_id}",
            "--method", "PATCH", "-f", f"body={body}",
        ]
    subprocess.run(cmd, check=False, env={"GH_TOKEN": token, "PATH": os.environ.get("PATH", "")})


def _read_lines(path: str) -> list[str]:
    """File reader for verify_comments — reads from repo root."""
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--branch", required=True, help="PR head branch name (for auto-fix push)")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("FATAL: no GITHUB_TOKEN/GH_TOKEN in env", file=sys.stderr)
        return 2

    repo_root = Path.cwd()
    sections: dict[str, str] = {}
    vs = VerifierState()

    try:
        # 2. GATHER
        pr = gather(args.repo, args.pr)
        sections["Inputs"] = (
            f"- PR #{pr['pr_number']} '{pr['title']}'\n"
            f"- head SHA: {pr['head_sha'][:8]}\n"
            f"- files changed: {pr['files_changed']}, lines: {pr['lines_changed']}"
        )

        # State (hidden PR comment)
        comment_id, state = _gh_get_state_comment(args.repo, args.pr, token)
        if state is None:
            state = empty_state(pr["pr_number"])

        # 1. SKIP CHECKS
        skip, reason = should_skip({
            **{k: pr[k] for k in ("labels", "is_draft", "author_login", "head_sha", "changed_files")},
            "last_reviewed_sha": state.get("last_reviewed_sha"),
        })
        if skip:
            sections["Skip checks"] = f"SKIPPED: {reason}"
            summary.emit(sections)
            return 0

        # 3. HARD BLOCKS
        hb = evaluate_hard_blocks({
            "changed_files": pr["changed_files"],
            "diff_added_lines": pr["diff_added_lines"],
            "diff_removed_lines": pr["diff_removed_lines"],
            "files_changed": pr["files_changed"],
            "lines_changed": pr["lines_changed"],
        })
        sections["Hard blocks"] = (
            f"hard_blocked={hb['hard_blocked']}\n"
            + ("\n".join(f"- {r}" for r in hb["rule_ids"]) if hb["rule_ids"] else "_(no rules triggered)_")
        )

        # 3b. BORDERLINE REASONING (Plan 2): for edge-case PRs near a
        # hard-block threshold, escalate to DeepSeek-R1 for a reasoning-tier
        # decision on whether to hard-block or let Pass 2 handle it.
        if hb.get("borderline") and not hb["hard_blocked"]:
            borderline_decision = evaluate_borderline(
                borderline_reasons=hb["borderline_reasons"],
                pr=pr, token=token,
            )
            if borderline_decision["should_hard_block"]:
                hb["hard_blocked"] = True
                hb["reasons"].append(borderline_decision["reasoning"])
                hb["rule_ids"].append("borderline_escalated")
            sections["Borderline reasoning"] = (
                f"decision={'escalate' if borderline_decision['should_hard_block'] else 'proceed'}\n"
                f"reasoning: {borderline_decision['reasoning']}"
            )

        # 4. PASS 1 — TRIAGE
        try:
            triage = run_triage(
                pr=pr, hard_blocked=hb["hard_blocked"],
                hard_block_reasons=hb["reasons"], token=token,
            )
            sections["Pass 1 (triage)"] = (
                f"complexity={triage['complexity']}, "
                f"deep_review_files={len(triage['deep_review_files'])}, "
                f"in={triage['tokens_in']}/out={triage['tokens_out']}"
            )
        except RateLimitedError:
            vs.rate_limited = True
            triage = {"complexity": "risky", "deep_review_files": []}
            sections["Pass 1 (triage)"] = "RATE LIMITED — skipping deep review"

        # 5. PASS 2 — DEEP REVIEW
        # Skip entirely when:
        #   (a) rate-limited at Pass 1 — no quota to spend, AND
        #   (b) hard_blocked — verdict is forced to REQUEST_CHANGES anyway,
        #       so a Pass 2 call cannot influence the outcome and would just
        #       burn quota (and likely blow the 8K-token request limit on
        #       any large PR with the full CLAUDE.md attached).
        if vs.rate_limited:
            pass2 = {
                "verdict": "COMMENT", "confidence": 0.0,
                "certainty": "significant_uncertainty",
                "summary": "AI deep review unavailable (rate-limited). Re-run via `/ai-review` later or label `needs-human`.",
                "comments": [], "fixes_to_push": [],
                "tokens_in_total": 0, "tokens_out_total": 0,
                "tool_calls_used": 0, "rate_limit_remaining": 0,
                "tool_calls_exhausted": False,
            }
        elif hb["hard_blocked"]:
            # Synthesize a Pass 2 result so the rest of the pipeline runs
            # unchanged. The conservative_gate already forces REQUEST_CHANGES
            # when hard_blocked, so verdict here is mostly cosmetic.
            reasons_block = "\n".join(f"- {r}" for r in hb["reasons"])
            pass2 = {
                "verdict": "REQUEST_CHANGES", "confidence": 1.0,
                "certainty": "fully_understood",
                "summary": (
                    f"This PR was hard-blocked by deterministic rule(s): "
                    f"{', '.join(hb['rule_ids'])}.\n\n"
                    f"{reasons_block}\n\n"
                    "Pass 2 LLM review skipped — verdict is REQUEST_CHANGES "
                    "regardless. Label `needs-human` to silence the bot, "
                    "or address the hard-block reasons and re-trigger."
                ),
                "comments": [], "fixes_to_push": [],
                "tokens_in_total": 0, "tokens_out_total": 0,
                "tool_calls_used": 0, "rate_limit_remaining": None,
                "tool_calls_exhausted": False,
            }
            sections["Pass 2 (deep)"] = "SKIPPED (hard-blocked — synthesized verdict)"
        else:
            lessons_path = Path("docs/ai-approve/lessons.md")
            lessons_md = lessons_path.read_text(encoding="utf-8") if lessons_path.exists() else ""
            # Lessons get injected into the system prompt — cap to keep
            # system+tools+lessons < ~1200 tokens combined.
            if lessons_md and len(lessons_md) > 1500:
                lessons_md = lessons_md[:1500] + "\n[... lessons truncated ...]"

            # Trim caps are tier-aware — see config.py. Free tier (default)
            # fits the 8K-input-token GH Models cap; AI_APPROVE_TIER=paid
            # lifts caps so CLAUDE.md + full diff + deep files all ride along.
            caps = trim_caps()

            if caps.claude_md == 0:
                pr["claude_md"] = ""
            elif pr.get("claude_md") and len(pr["claude_md"]) > caps.claude_md:
                pr["claude_md"] = pr["claude_md"][:caps.claude_md] + "\n[... truncated ...]"
            if pr.get("body") and len(pr["body"]) > caps.body:
                pr["body"] = pr["body"][:caps.body] + "\n[... body truncated ...]"
            if pr.get("audit_doc") and len(pr["audit_doc"]) > caps.audit_doc:
                pr["audit_doc"] = pr["audit_doc"][:caps.audit_doc] + "\n[... truncated ...]"
            if pr.get("diff") and len(pr["diff"]) > caps.diff_pass2:
                pr["diff"] = pr["diff"][:caps.diff_pass2] + "\n[... diff truncated ...]"

            deep_files_content = {}
            for fp in (triage.get("deep_review_files") or [])[:caps.deep_files]:
                p_path = repo_root / fp
                if p_path.exists() and p_path.is_file():
                    deep_files_content[fp] = p_path.read_text(encoding="utf-8", errors="replace")[:caps.deep_file]

            # PLAN 2: dispatch multiple specialized review branches in addition to standard
            selected = select_branches({"changed_files": pr["changed_files"]})
            sections["Branches selected"] = ", ".join(selected)

            branch_outputs: dict[str, dict] = {}

            # standard branch — existing Pass 2 logic
            try:
                branch_outputs["standard"] = run_deep_review(
                    pr=pr, lessons_md=lessons_md,
                    deep_files_content=deep_files_content,
                    repo_root=repo_root, token=token,
                )
                vs.tool_calls_exhausted = branch_outputs["standard"].get("tool_calls_exhausted", False)
            except RateLimitedError:
                vs.rate_limited = True
                branch_outputs["standard"] = {
                    "verdict": "COMMENT", "confidence": 0.0,
                    "certainty": "significant_uncertainty",
                    "summary": "Standard deep review rate-limited.",
                    "comments": [], "fixes_to_push": [],
                }
            except (ModelsHTTPError, RuntimeError) as e:
                vs.llm_crashed = True
                branch_outputs["standard"] = {
                    "verdict": "COMMENT", "confidence": 0.0,
                    "certainty": "significant_uncertainty",
                    "summary": f"Standard deep review crashed: {e}",
                    "comments": [], "fixes_to_push": [],
                }

            # specialized branches
            if "migration_deep" in selected:
                branch_outputs["migration_deep"] = run_migration_branch(
                    pr=pr, repo_root=str(repo_root), token=token,
                )
            if "security" in selected:
                branch_outputs["security"] = run_security_branch(
                    pr=pr, repo_root=str(repo_root), token=token,
                )
            if "cross_pr_conflict" in selected:
                # Most consumer PRs target main; consumer can override later if needed
                base_branch = "main"
                branch_outputs["cross_pr_conflict"] = run_cross_pr_branch(
                    repo=args.repo, base=base_branch,
                    current_pr=pr["pr_number"],
                    current_files=set(pr["changed_files"]),
                )
            if "test_stubs" in selected:
                branch_outputs["test_stubs"] = run_test_stubs_branch(
                    diff=pr.get("diff", ""), token=token,
                )

            # aggregate
            pass2 = aggregate_branch_verdicts(branch_outputs)
            for branch_name, output in branch_outputs.items():
                meta = []
                if "verdict" in output:
                    meta.append(f"verdict={output['verdict']}")
                if "confidence" in output:
                    meta.append(f"confidence={output['confidence']}")
                meta.append(f"comments={len(output.get('comments', []))}")
                sections[f"Branch: {branch_name}"] = " ".join(meta)

        # 6. AUTO-FIX (smart hybrid)
        ai_fixed_label_present = "ai-fixed" in pr["labels"]
        current_issue_count = len(pass2.get("comments", [])) + len(pass2.get("fixes_to_push", []))
        fix_result = apply_fixes(
            fixes_to_push=pass2.get("fixes_to_push", []),
            state=state, pr_branch=args.branch, repo_root=repo_root,
            current_issue_count=current_issue_count,
            bot_already_fixed_label_present=ai_fixed_label_present,
        )
        sections["Auto-fix"] = (
            f"acted={fix_result['acted']}, "
            f"tools={fix_result['tools_used']}, "
            f"files_changed={fix_result['files_changed']}"
            + (f"\n_stop_reason_: {fix_result['stop_reason']}" if fix_result.get("stop_reason") else "")
        )

        if fix_result["stop_loop_for_now"]:
            # We pushed a fix; the next pull_request:synchronize → ai-approve
            # run will post the review. Persist state, label, exit clean.
            import subprocess
            subprocess.run(
                ["gh", "pr", "edit", str(args.pr), "--repo", args.repo, "--add-label", "ai-fixed"],
                check=False, env={"GH_TOKEN": token, "PATH": os.environ.get("PATH", "")},
            )
            _gh_upsert_state_comment(args.repo, args.pr, comment_id, state, token)
            summary.emit(sections)
            return 0

        # 7. VERIFY + SELF-CRITIQUE
        kept, dropped = verify_comments(pass2.get("comments", []), _read_lines)
        if has_forbidden_phrase(pass2.get("summary", "")):
            vs.forbidden_phrase_present = True
        for c in kept:
            if has_forbidden_phrase(c.get("claim", "")):
                vs.forbidden_phrase_present = True
                break
        pass2["comments"] = kept

        # Severity tally
        sev_blocker = sum(1 for c in kept if c.get("severity") == "blocker")
        sev_major = sum(1 for c in kept if c.get("severity") == "major")
        vs.comments_with_severity_blocker = sev_blocker
        vs.comments_with_severity_major = sev_major

        # Self-critique (skip if rate-limited or already crashed)
        if not vs.rate_limited and not vs.llm_crashed and kept:
            try:
                critique = run_critique(pass2=pass2, file_reader=_read_lines, token=token)
                # Apply drops
                drop_idxs = sorted({d["comment_index"] for d in critique.get("drops", [])}, reverse=True)
                for i in drop_idxs:
                    if 0 <= i < len(pass2["comments"]):
                        dropped.append({**pass2["comments"][i], "reason": f"critique:{[d['reason'] for d in critique['drops'] if d['comment_index']==i][0]}"})
                        del pass2["comments"][i]
                if critique.get("concerns"):
                    vs.self_critique_flagged_concerns = True
                sections["Critique"] = (
                    f"drops={len(critique.get('drops', []))}, "
                    f"concerns={len(critique.get('concerns', []))}"
                )
            except (RateLimitedError, ModelsHTTPError, RuntimeError) as e:
                sections["Critique"] = f"skipped: {e}"
        else:
            sections["Critique"] = "skipped (rate-limited/crashed/no kept comments)"

        # 8. CONSERVATIVE GATE + POST
        verdict = final_verdict(pass2, hard_blocked=hb["hard_blocked"], vs=vs)
        sections["Final verdict"] = (
            f"posted={verdict}\n"
            f"kept_comments={len(pass2['comments'])}, dropped={len(dropped)}\n"
            f"hard_blocked={hb['hard_blocked']}, "
            f"forbidden_phrase={vs.forbidden_phrase_present}, "
            f"self_critique_concerns={vs.self_critique_flagged_concerns}"
        )

        body = render_body(
            verdict=verdict, pass2=pass2,
            auto_fix_result=fix_result,
            dropped_comments=dropped,
            critique_concerns=[],  # body shows by section heading above
            hard_block_reasons=hb["reasons"],
            rate_limit_remaining=pass2.get("rate_limit_remaining"),
        )
        inline = [
            {"file": c["file"], "line": c["line"], "body": inline_body_for_comment(c)}
            for c in pass2["comments"]
        ]
        # PR_REVIEW_TOKEN is the optional PAT that unlocks real APPROVE
        # posting. If absent, post_review falls back to COMMENT for APPROVE
        # verdicts (with an explanatory note on the PR).
        review_token = os.environ.get("PR_REVIEW_TOKEN") or None
        try:
            result = post_review(
                repo=args.repo, pr_number=args.pr, head_sha=pr["head_sha"],
                verdict=verdict, body=body, inline_comments=inline,
                token=token, review_token=review_token,
            )
            if result.get("_fallback_from_approve"):
                sections["Post review"] = (
                    "Posted as COMMENT (APPROVE→COMMENT fallback; "
                    "GITHUB_TOKEN cannot approve; set PR_REVIEW_TOKEN to enable)"
                )
            else:
                sections["Post review"] = f"Posted as {verdict}"
        except Exception as e:
            sections["Post review"] = f"FAILED: {e}"
            summary.emit(sections)
            return 0  # don't fail workflow — review will retry on next trigger

        # Persist state + calibration
        state["last_reviewed_sha"] = pr["head_sha"]
        _gh_upsert_state_comment(args.repo, args.pr, comment_id, state, token)
        calibration.record_run(verdict=verdict, pass2=pass2, changed_files=pr["changed_files"])

        summary.emit(sections)
        return 0

    except Exception as e:
        # Unexpected failure — fail the workflow loudly so you investigate
        sections["FATAL"] = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        summary.emit(sections)
        return 1


if __name__ == "__main__":
    sys.exit(main())
