"""Step 3: a code-based metric for the classify step.

Every field here is a closed set, so all four checks are plain code, no judge.

field_scores returns the per-field result so analyze.py can print each field on
its own line. That keeps urgency visible, which matters because it is the one
field with a real judgment call: read its misses by hand and sort "model wrong"
vs "label arguable" before trusting the number.

classify_metric collapses the per-field dict to a [0,1] float for dspy.Evaluate
and the optimizer. Note the optimizer maximizes this float, so any field not in
the dict is a field it cannot see (pm_queue is left out, it is unlabeled).
"""

from .signature import classify  # noqa: F401  (re-export so callers import from one place)


def _norm(s) -> str:
    return (s or "").strip().casefold()


def _jaccard(a, b) -> float:
    # Partial credit for flag sets: overlap / union. Both empty scores 1.0, since
    # flagging nothing when nothing applies is a right answer.
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def field_scores(example, pred) -> dict[str, float]:
    return {
        "category": float(_norm(pred.category) == _norm(example.category)),
        # Exact match. Boundary cases are a label question for trace review, not
        # a grading problem.
        "urgency": float(_norm(pred.urgency) == _norm(example.urgency)),
        # Partial credit so 1-of-2 flags scores above zero.
        "risk_flags": _jaccard(pred.risk_flags, example.risk_flags),
        "not_a_maintenance_request": float(
            bool(pred.not_a_maintenance_request) == example.not_a_maintenance_request
        ),
    }


def classify_metric(example, pred, trace=None) -> float:
    scores = field_scores(example, pred)
    return sum(scores.values()) / len(scores)
