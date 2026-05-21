"""Cat 7 grader: archive-vs-pass exact match (`non_tenant_email_archived_instead_of_routed`).

Considered a judge here ("was archiving this email defensible?") and dropped it:
expected.pre_filter.action IS the human's call on spam-vs-real. A judge would
be a second LLM second-guessing the human, not a check on the agent.

Cat 7 is a reason-2 guardrail per `evals/fix_vs_eval_2.md`: the failure
(archiving a vendor invoice or other operational non-tenant mail) is silent
in production, since nobody emails to say "you ignored my invoice". The
grader runs even after the prompt fix closes the failure today.
"""

from __future__ import annotations

from . import GraderResult

NAME = "pre_filter.decision.exact_match"


def grade(expected: dict, final_state: dict) -> GraderResult:
    pf = (expected or {}).get("pre_filter") or {}
    if "action" not in pf:
        return GraderResult(name=NAME, status="skipped", reason="no expected.pre_filter.action")

    want = pf["action"]
    got = (final_state or {}).get("pre_filter_decision")
    status = "pass" if got == want else "fail"
    return GraderResult(name=NAME, status=status, expected=want, actual=got)
