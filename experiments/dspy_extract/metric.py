"""Step 3: a code-based metric for the extract step.

Scores only the fields dev.jsonl labels cleanly and that code can check without
interpretation. The fuzzy fields (location/duration content, sentiment, framing)
are not scored here; they need trace review and a later judge.

extract_metric collapses the per-field breakdown to a [0,1] float for dspy.Evaluate
and the optimizer. The optimizer maximizes this float, so any field not in the dict
is a field it cannot see.
"""

from .signature import derive_gate


def _norm(s) -> str:
    return (s or "").strip().casefold()


def _present(s) -> bool:
    return bool(s and str(s).strip())


def field_scores(example, pred) -> dict[str, bool]:
    gate_insufficient, gate_missing = derive_gate(pred)
    return {
        # Unit must match verbatim (modulo case/whitespace); it's a literal token.
        "unit": _norm(pred.unit_number) == _norm(example.unit),
        # The dataset only knows if a description exists, not its text.
        "description_present": _present(pred.description) == example.description_present,
        "lease_question_present": bool(pred.lease_question_present) == example.lease_question_present,
        # Phone: presence only, since formatting varies.
        "callback_phone": _present(pred.callback_phone) == _present(example.callback_phone),
        # The derived gate: did we agree on whether to ask, and about what.
        "gate_insufficient": gate_insufficient == example.gate_insufficient,
        "gate_missing": sorted(gate_missing) == sorted(example.gate_missing),
    }


def extract_metric(example, pred, trace=None) -> float:
    scores = field_scores(example, pred)
    return sum(scores.values()) / len(scores)
