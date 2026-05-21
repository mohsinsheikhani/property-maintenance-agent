"""Cat 8 graders: risk_flags recall and precision (`unsupported_risk_flag_added`).

risk_flags is a set prediction, so one "exact match" grader would conflate two
very different failures into a single FAIL. I split them so CI can tell
which kind of regression it's looking at.

Recall: did I catch every flag I should have?
  missing = want - got. Pass when missing is empty.
  Fails when the agent under-flags: expected {fire_hazard}, got {}. This is
  the dangerous one, I might end up missing a real risk.

Precision: is every flag I produced actually warranted?
  extra = got - want. Pass when extra is empty.
  Fails when the agent over-flags: expected {} on a locksmith
  case, got {security_risk} attached from the category shape alone. Less
  dangerous than under-flagging (I'm adding noise rather than missing a
  real risk)

Why not just set-equality? With one grader, missing-fire-hazard and
adding-an-extra-security-risk both render as FAIL and I can't tell from
the dashboard whether I'm missing real risks or just being noisy. Those
warrant very different responses, so I keep the signal separate.

Both graders skip when expected.classify.risk_flags is absent. An empty
list is a valid expected value (means "no flags should fire") and passes
when actual is also empty.
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
