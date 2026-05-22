"""Step 4 (run this) + step 5 stub (don't run until the baseline is read).

    uv run python -m experiments.dspy_classify.baseline             # step 4: baseline only
    uv run python -m experiments.dspy_classify.baseline --optimize  # step 5: + MIPROv2

Step 4 measures the lean signature unoptimized so step 5 has something to beat.
The single number is not the result. Read the per-field breakdown (analyze.py)
first, per the project's run -> look -> categorize -> grade rule.

Step 5 (MIPROv2) is gated behind --optimize on purpose. Don't run it until you
have read the baseline traces and sorted the urgency misses into "model wrong"
vs "label arguable". The metric is MIPRO's target, so noisy labels teach the
prompt to copy debatable judgment calls.
"""

import argparse

import dspy

from .config import configure_lm
from .dataset import load_examples
from .metric import classify_metric
from .signature import classify


def _split(examples, frac=0.5, seed=0):
    """Train/val split so step 5's final number is on data MIPRO never saw."""
    import random

    shuffled = list(examples)
    random.Random(seed).shuffle(shuffled)
    cut = int(len(shuffled) * frac)
    return shuffled[:cut], shuffled[cut:]


def main(optimize: bool) -> None:
    configure_lm()
    examples = load_examples()
    trainset, valset = _split(examples)

    evaluate = dspy.Evaluate(
        devset=valset, metric=classify_metric, num_threads=8, display_table=15, display_progress=True
    )

    print(f"\n=== Step 4: baseline (lean signature, unoptimized) on {len(valset)} val examples ===")
    baseline_score = evaluate(classify)
    print(f"baseline val score: {baseline_score}")

    if not optimize:
        return

    from dspy.teleprompt import MIPROv2

    print(f"\n=== Step 5: MIPROv2 compile on {len(trainset)} train examples ===")
    optimizer = MIPROv2(metric=classify_metric, auto="light")
    optimized = optimizer.compile(classify, trainset=trainset)

    print("\n=== Step 5: optimized score on the SAME val set ===")
    optimized_score = evaluate(optimized)
    print(f"baseline: {baseline_score}  ->  optimized: {optimized_score}")
    optimized.save("experiments/dspy_classify/compiled_classify.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--optimize", action="store_true", help="run step 5 (MIPROv2) after the baseline")
    main(parser.parse_args().optimize)
