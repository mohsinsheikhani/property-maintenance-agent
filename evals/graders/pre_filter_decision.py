"""Cat 2 / pre-filter grader: archive-vs-pass exact match.

Considered a judge here ("was archiving this email defensible?") and dropped it:
expected.pre_filter.action IS the human's call on spam-vs-real. A judge would
be a second LLM second-guessing the human, not a check on the agent.

This is a Cat 2 grader because the failure mode it guards — archiving a
vague-but-real tenant email — is exactly what the clarify gate redirect is
supposed to prevent.
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
