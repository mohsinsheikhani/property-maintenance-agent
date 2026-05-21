"""Cat 3 grader: maintenance boolean exact match.

Catches the wrong-routing failure: a non-maintenance email that still fires
`create_work_order`, or a real maintenance email routed to the PM queue.
See evals/error_analysis/round_1/fix_vs_eval.md (Category 3: classify_reflex_tagging)
and failure_taxonomy.md.

Strict equality on `not_a_maintenance_request`. The dataset omits the field
for normal maintenance cases (implicit false), so we default the expected
side to False rather than skip.
"""

from __future__ import annotations

from . import GraderResult

NAME = "classify.not_a_maintenance_request.exact_match"


def grade(expected: dict, final_state: dict) -> GraderResult:
    classify = (expected or {}).get("classify") or {}
    want = bool(classify.get("not_a_maintenance_request", False))
    got = bool((final_state or {}).get("not_a_maintenance_request", False))
    status = "pass" if got == want else "fail"
    return GraderResult(name=NAME, status=status, expected=want, actual=got)
