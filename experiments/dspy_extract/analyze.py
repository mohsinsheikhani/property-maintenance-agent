"""Look step: per-field pass rates + mismatch dump for the extract baseline.

The aggregate (59.7%) is a mean over 6 fields and hides which field drags it.
This runs the val set, prints pass rate PER FIELD, then dumps every per-field
miss as predicted-vs-expected so you can read traces and categorize.

    uv run python -m experiments.dspy_extract.analyze

Uses the same val split as baseline.py (seed=0, frac=0.5) so the rows line up.
"""

from collections import defaultdict

from .baseline import _split
from .config import configure_lm
from .dataset import load_examples
from .metric import field_scores
from .signature import derive_gate, extract


def _pred_values(pred) -> dict:
    """What the model actually produced, keyed to match field_scores."""
    gate_insufficient, gate_missing = derive_gate(pred)
    return {
        "unit": pred.unit_number,
        "description_present": bool(pred.description and str(pred.description).strip()),
        "lease_question_present": pred.lease_question_present,
        "callback_phone": pred.callback_phone,
        "gate_insufficient": gate_insufficient,
        "gate_missing": gate_missing,
    }


def main() -> None:
    configure_lm()
    _, valset = _split(load_examples())

    passes: dict[str, int] = defaultdict(int)
    misses: dict[str, list[tuple]] = defaultdict(list)
    fields: list[str] = []

    for ex in valset:
        pred = extract(thread=ex.thread)
        got = _pred_values(pred)
        scores = field_scores(ex, pred)
        fields = list(scores)
        for field, ok in scores.items():
            if ok:
                passes[field] += 1
            else:
                misses[field].append((ex.id, got[field], ex.get(field)))

    n = len(valset)
    print(f"\n=== per-field pass rate ({n} val examples) ===")
    for field in fields:
        print(f"  {field:24s} {passes[field]:2d}/{n}  ({passes[field] / n:.0%})")

    print("\n=== mismatches (id: predicted -> expected) ===")
    for field, rows in misses.items():
        if rows:
            print(f"\n--- {field} ({len(rows)} misses) ---")
            for ex_id, got, want in rows:
                print(f"  {ex_id}: {got!r} -> {want!r}")


if __name__ == "__main__":
    main()
