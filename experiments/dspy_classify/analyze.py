"""Look step: per-field mean score + mismatch dump for the classify baseline.

The aggregate score is a mean over 4 fields and hides which one drags it down.
This runs the val set, prints the score per field (so urgency stands alone),
then dumps every miss as predicted vs expected for trace review.

    uv run python -m experiments.dspy_classify.analyze

Uses the same val split as baseline.py (seed=0, frac=0.5) so the rows line up.
Sort each urgency miss into "model wrong" vs "label arguable" before trusting
the number.
"""

from collections import defaultdict

from .baseline import _split
from .config import configure_lm
from .dataset import load_examples
from .metric import field_scores
from .signature import classify


def _pred_values(pred) -> dict:
    """What the model actually produced, keyed to match field_scores."""
    return {
        "category": pred.category,
        "urgency": pred.urgency,
        "risk_flags": sorted(pred.risk_flags or []),
        "not_a_maintenance_request": pred.not_a_maintenance_request,
    }


def _expected_values(ex) -> dict:
    return {
        "category": ex.category,
        "urgency": ex.urgency,
        "risk_flags": sorted(ex.risk_flags or []),
        "not_a_maintenance_request": ex.not_a_maintenance_request,
    }


def main() -> None:
    configure_lm()
    _, valset = _split(load_examples())

    totals: dict[str, float] = defaultdict(float)
    misses: dict[str, list[tuple]] = defaultdict(list)
    fields: list[str] = []

    for ex in valset:
        pred = classify(thread=ex.thread)
        got = _pred_values(pred)
        want = _expected_values(ex)
        scores = field_scores(ex, pred)
        fields = list(scores)
        for field, score in scores.items():
            totals[field] += score
            if score < 1.0:  # partial credit on risk_flags still counts as a miss to read
                misses[field].append((ex.id, got[field], want[field]))

    n = len(valset)
    print(f"\n=== per-field mean score ({n} val examples) ===")
    for field in fields:
        print(f"  {field:28s} {totals[field] / n:.0%}")

    print("\n=== mismatches (id: predicted -> expected) ===")
    for field, rows in misses.items():
        if rows:
            print(f"\n--- {field} ({len(rows)} misses) ---")
            for ex_id, got, want in rows:
                print(f"  {ex_id}: {got!r} -> {want!r}")


if __name__ == "__main__":
    main()
