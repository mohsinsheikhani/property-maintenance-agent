"""Cat 3 graders: risk_flags recall and precision.

Split into two graders rather than set-equality so the CI gate can treat
recall regressions (under-flagging: missing `fire_hazard` etc.) as stop-the-line
and precision regressions (over-flagging / reflex-tagging) as investigate-and-fix.
See evals/fix_vs_eval.md (Category 3: classify_reflex_tagging).

Both graders skip when `expected.classify.risk_flags` is absent. An empty
list is a valid expected value (means "no flags should fire") and is graded
as a pass when actual is also empty.
"""

from __future__ import annotations

from . import GraderResult

RECALL_NAME = "classify.risk_flags.recall"
PRECISION_NAME = "classify.risk_flags.precision"


def _flags(d: dict, key: str) -> set[str] | None:
    classify = (d or {}).get("classify") if key == "expected" else d
    if classify is None:
        return None
    flags = classify.get("risk_flags") if key == "expected" else d.get("risk_flags")
    if flags is None:
        return None
    return set(flags)


def grade_recall(expected: dict, final_state: dict) -> GraderResult:
    classify = (expected or {}).get("classify") or {}
    if "risk_flags" not in classify:
        return GraderResult(name=RECALL_NAME, status="skipped", reason="no expected.classify.risk_flags")

    want = set(classify["risk_flags"] or [])
    got = set((final_state or {}).get("risk_flags") or [])
    missing = want - got
    status = "pass" if not missing else "fail"
    reason = "" if status == "pass" else f"missing: {sorted(missing)}"
    return GraderResult(name=RECALL_NAME, status=status, expected=sorted(want), actual=sorted(got), reason=reason)


def grade_precision(expected: dict, final_state: dict) -> GraderResult:
    classify = (expected or {}).get("classify") or {}
    if "risk_flags" not in classify:
        return GraderResult(name=PRECISION_NAME, status="skipped", reason="no expected.classify.risk_flags")

    want = set(classify["risk_flags"] or [])
    got = set((final_state or {}).get("risk_flags") or [])
    extra = got - want
    status = "pass" if not extra else "fail"
    reason = "" if status == "pass" else f"unexpected: {sorted(extra)}"
    return GraderResult(name=PRECISION_NAME, status=status, expected=sorted(want), actual=sorted(got), reason=reason)
