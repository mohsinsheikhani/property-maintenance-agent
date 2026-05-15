"""Cat 1 grader: urgency exact match.

Ships before the classify prompt fix as an upfront guard (high-stakes:
under-tiering fire/flood, over-tiering benign requests). See
evals/fix_vs_eval.md and evals/failure_taxonomy.md (urgency_from_tone_not_facts).

Strict equality of expected.classify.urgency vs final_state.urgency.
Abstains when expected has no urgency (archive/not-a-maintenance-request cases).
"""

from __future__ import annotations

from . import GraderResult

NAME = "classify.urgency.exact_match"


def grade(expected: dict, final_state: dict) -> GraderResult:
    classify = (expected or {}).get("classify") or {}
    if "urgency" not in classify or classify["urgency"] is None:
        return GraderResult(name=NAME, status="skipped", reason="no expected.classify.urgency")

    want = classify["urgency"]
    got = (final_state or {}).get("urgency")
    status = "pass" if got == want else "fail"
    return GraderResult(name=NAME, status=status, expected=want, actual=got)
