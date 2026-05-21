"""Validate the urgency judge against human Pass/Fail labels (TPR/TNR).

The judge (`classify.urgency.judge_defensible.unvalidated`) answers "is the
urgency the agent picked defensible for this email?". This script checks how
often its verdict matches a human's, on a fixed set of (email, picked_urgency)
pairs we labeled by hand in urgency_judge_labels.csv.

Picked tiers come from the round-1 (pre-fix) agent run, which over-escalated
enough to give us real Fail cases without fabricating any. Labels are the
human's defensibility call, NOT pick==expected; that distinction is the whole
reason a judge exists over the exact-match grader.

No train/dev/test split: at ~15 examples a split leaves nothing to measure.
We report TPR/TNR over the whole labeled set and treat it as a single small
holdout. The number is a sanity gate, not a calibrated estimate; the sample is
too small for a meaningful confidence interval, so we skip bias correction.

Usage:
    uv run python -m evals.validation.validate_urgency_judge
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from evals.graders.urgency_judge import grade as grade_urgency

DATASET = Path("datasets/e2e/dev.jsonl")
LABELS = Path(__file__).parent / "urgency_judge_labels.csv"


def _load_emails() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with DATASET.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["id"]] = r
    return out


def _load_labels() -> list[dict]:
    with LABELS.open() as fh:
        return list(csv.DictReader(fh))


async def main() -> None:
    emails = _load_emails()
    labels = _load_labels()

    # confusion matrix cells, Pass = positive class
    tp = fp = tn = fn = 0
    disagreements: list[str] = []

    print(f"Validating urgency judge on {len(labels)} labeled pairs\n")
    for row in labels:
        tid = row["trace_id"]
        picked = row["picked_urgency"]
        human = row["human_verdict"]
        record = emails[tid]
        query = record["query"]

        state = {
            "subject": query.get("subject", ""),
            "body": query.get("body", ""),
            "urgency": picked,
        }
        # expected only gates the skip path; the value isn't used in the verdict
        expected = {"classify": {"urgency": picked}}

        result = await grade_urgency(expected, state)
        judge = "Pass" if result.status == "pass" else "Fail"
        agree = judge == human

        if human == "Pass" and judge == "Pass":
            tp += 1
        elif human == "Pass" and judge == "Fail":
            fn += 1
        elif human == "Fail" and judge == "Fail":
            tn += 1
        else:
            fp += 1

        mark = "ok  " if agree else "DIFF"
        print(f"  [{mark}] {tid:<10} pick={picked:<7} human={human:<5} judge={judge}")
        if not agree:
            disagreements.append(f"{tid} pick={picked}: human={human} judge={judge} :: {result.reason}")

    tpr = tp / (tp + fn) if (tp + fn) else None
    tnr = tn / (tn + fp) if (tn + fp) else None

    print(f"\nconfusion (Pass=positive): tp={tp} fn={fn} tn={tn} fp={fp}")
    print(f"TPR (human Pass -> judge Pass): {tpr:.0%}" if tpr is not None else "TPR: n/a")
    print(f"TNR (human Fail -> judge Fail): {tnr:.0%}" if tnr is not None else "TNR: n/a")

    if disagreements:
        print("\ndisagreements:")
        for d in disagreements:
            print(f"  - {d}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
