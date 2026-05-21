"""Cat 2 grader: required-fields gate.

If the dataset's expected.extract says `insufficient_info=true` (i.e. one of
`unit_number`, `location_in_unit`, `description` is missing), the agent must
NOT have fired `create_work_order` or `dispatch_vendor`. Either one means a
truck rolls / a contractor is dispatched against incomplete information.

Symmetric direction is intentionally not enforced: when expected says false,
the work-order path *may* fire but doesn't have to (the email might also be
non-maintenance). That assertion belongs in the maintenance-boolean grader.
"""

from __future__ import annotations

from . import GraderResult

NAME = "extract.insufficient_info.gate_holds"

_DESTRUCTIVE_TOOLS = {"create_work_order", "dispatch_vendor"}


def _tool_calls_fired(final_state: dict) -> set[str]:
    fired: set[str] = set()
    for msg in (final_state or {}).get("messages") or []:
        calls = getattr(msg, "tool_calls", None) or []
        for call in calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                fired.add(name)
    return fired


def grade(expected: dict, final_state: dict) -> GraderResult:
    extract = (expected or {}).get("extract") or {}
    classify = (expected or {}).get("classify") or {}
    # Dataset uses two shapes for "insufficient info": expected.extract.insufficient_info
    # (the new shape) and the legacy expected.classify.insufficient_info on a few
    # E* records authored before the move. Honour both until the dataset migrates.
    insufficient = bool(
        extract.get("insufficient_info") or classify.get("insufficient_info")
    )
    if not insufficient:
        return GraderResult(name=NAME, status="skipped", reason="expected.extract.insufficient_info is false")

    fired = _tool_calls_fired(final_state)
    leaked = fired & _DESTRUCTIVE_TOOLS
    if leaked:
        return GraderResult(
            name=NAME,
            status="fail",
            expected="no create_work_order/dispatch_vendor",
            actual=sorted(leaked),
            reason="destructive tool fired despite insufficient_info=true",
        )
    return GraderResult(name=NAME, status="pass", expected=False, actual=False)
