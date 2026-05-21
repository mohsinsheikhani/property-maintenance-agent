"""Regression gate over the component evals.

Runs the same node + grader pairs the per-component evals run (classify,
extract, pre_filter), collects one pass-rate per grader, and diffs that
scoreboard against a committed baseline. Code graders gate the build; judges
are report-only.

Why component evals and not the e2e graph: the gate has to run inside a GitHub
Action with nothing but OPENAI_API_KEY. The nodes are pure functions of state,
so they run without the MCP server, Neon, or the checkpointer. The e2e graph
needs all three and writes only to Langfuse, so it stays a manual/local sweep.
See evals/README.md ("Regression gate").

The thresholds follow the Agent Factory regression model: a per-criterion drop
(criterion_threshold) and an overall drop (overall_threshold), with
block_on_regression deciding whether a regression fails the build. Judges are
report-only because their pass-rate is a biased, slightly noisy number (see the
validate-evaluator skill on judge bias); they guard, they do not gate.

Usage:
    uv run python -m evals.run_evals                       # gate against evals/baseline.json
    uv run python -m evals.run_evals --baseline path.json  # diff against a specific baseline
    uv run python -m evals.run_evals --update-baseline     # rewrite the baseline from this run
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agent.graph.nodes import classify, extract, pre_filter
from evals.components.classify_eval import GRADERS as CLASSIFY_GRADERS
from evals.components.extract_eval import GRADERS as EXTRACT_GRADERS
from evals.components.pre_filter_eval import GRADERS as PRE_FILTER_GRADERS

DEFAULT_DATASET = Path("datasets/e2e/dev.jsonl")
DEFAULT_BASELINE = Path(__file__).parent / "baseline.json"

# Agent Factory regression thresholds: a single criterion may drop this much,
# and the overall code-grader rate may drop this much, before it is a regression.
CRITERION_THRESHOLD = 0.10
OVERALL_THRESHOLD = 0.05
BLOCK_ON_REGRESSION = True

# (label, node, graders) — reuses each component eval's GRADERS list so the gate
# can never drift from what the component evals themselves run.
COMPONENTS = [
    ("classify", classify, CLASSIFY_GRADERS),
    ("extract", extract, EXTRACT_GRADERS),
    ("pre_filter", pre_filter, PRE_FILTER_GRADERS),
]


def _is_judge(grader_name: str) -> bool:
    return ".judge" in grader_name


async def _apply(grader, expected, actual):
    if inspect.iscoroutinefunction(grader):
        return await grader(expected, actual)
    return grader(expected, actual)


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


async def _score(dataset_path: Path) -> dict[str, dict]:
    """Run every component over the dataset and return a scoreboard keyed by grader name."""
    records = _load_jsonl(dataset_path)
    board: dict[str, dict] = {}

    for label, node, graders in COMPONENTS:
        print(f"running {label} on {len(records)} records")
        for record in records:
            trace_id = record["id"]
            expected = record.get("expected") or {}
            query = record.get("query") or {}
            state = {
                "email_id": trace_id,
                "from_address": query.get("from", ""),
                "subject": query.get("subject", ""),
                "body": query.get("body", ""),
                "messages": [],
            }
            try:
                output = await node(state)
            except Exception as exc:
                print(f"  [err] {trace_id} {label}: {type(exc).__name__}: {exc}")
                output = {}

            # Graders see node output merged with the inputs, so judges that need
            # subject/body can read them (same contract as the component evals).
            actual = {"subject": state["subject"], "body": state["body"], **output}

            for grader in graders:
                result = await _apply(grader, expected, actual)
                cell = board.setdefault(
                    result.name,
                    {"is_judge": _is_judge(result.name), "pass": 0, "fail": 0, "skipped": 0, "failing": []},
                )
                if result.status == "pass":
                    cell["pass"] += 1
                elif result.status == "fail":
                    cell["fail"] += 1
                    cell["failing"].append(trace_id)
                else:
                    cell["skipped"] += 1

    for cell in board.values():
        applicable = cell["pass"] + cell["fail"]
        cell["applicable"] = applicable
        cell["rate"] = (cell["pass"] / applicable) if applicable else None
    return board


def _scoreboard_to_baseline(board: dict[str, dict], dataset_path: Path) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "graders": {
            name: {
                "is_judge": cell["is_judge"],
                "rate": cell["rate"],
                "pass": cell["pass"],
                "applicable": cell["applicable"],
                "failing": sorted(cell["failing"]),
            }
            for name, cell in board.items()
        },
    }


def _overall_code_rate(board: dict[str, dict]) -> float | None:
    """Aggregate pass-rate across code graders only (judges excluded from the gate)."""
    n_pass = sum(c["pass"] for c in board.values() if not c["is_judge"])
    n_app = sum(c["applicable"] for c in board.values() if not c["is_judge"])
    return (n_pass / n_app) if n_app else None


def _fmt_rate(rate: float | None) -> str:
    return f"{rate:.0%}" if rate is not None else "n/a"


def _gate(board: dict[str, dict], baseline: dict) -> bool:
    """Print the diff and return True if a code-grader regression should block."""
    base_graders = baseline.get("graders", {})
    regressions: list[str] = []
    warnings: list[str] = []

    print("\nper-grader diff (current vs baseline):")
    for name in sorted(board):
        cell = board[name]
        tag = "judge" if cell["is_judge"] else "code "
        cur = cell["rate"]
        base = base_graders.get(name, {}).get("rate")
        if base is None:
            print(f"  [{tag}] {name}: {_fmt_rate(cur)} (new, no baseline)")
            warnings.append(f"{name} is new")
            continue

        delta = (cur - base) if (cur is not None and base is not None) else None
        delta_str = f"{delta:+.0%}" if delta is not None else "n/a"
        mark = "ok"
        if delta is not None and delta < -CRITERION_THRESHOLD:
            mark = "REGRESSED" if not cell["is_judge"] else "drop (report-only)"
            if cell["is_judge"]:
                warnings.append(f"{name} judge dropped {delta_str}")
            else:
                regressions.append(f"{name} {delta_str} ({_fmt_rate(base)} -> {_fmt_rate(cur)})")

        print(f"  [{tag}] {name}: {_fmt_rate(cur)} (base {_fmt_rate(base)}, {delta_str}) {mark}")

        # Surface which records changed sides, like the docs' PR diff.
        base_fail = set(base_graders.get(name, {}).get("failing", []))
        cur_fail = set(cell["failing"])
        newly_failing = sorted(cur_fail - base_fail)
        newly_passing = sorted(base_fail - cur_fail)
        if newly_failing:
            print(f"        newly failing: {', '.join(newly_failing)}")
        if newly_passing:
            print(f"        newly passing: {', '.join(newly_passing)}")

    for name in sorted(set(base_graders) - set(board)):
        warnings.append(f"{name} present in baseline but not in this run")

    cur_overall = _overall_code_rate(board)
    base_overall = baseline.get("overall_code_rate")
    if base_overall is not None and cur_overall is not None:
        delta = cur_overall - base_overall
        print(f"\noverall code-grader rate: {_fmt_rate(cur_overall)} (base {_fmt_rate(base_overall)}, {delta:+.0%})")
        if delta < -OVERALL_THRESHOLD:
            regressions.append(f"overall code rate {delta:+.0%} ({_fmt_rate(base_overall)} -> {_fmt_rate(cur_overall)})")
    else:
        print(f"\noverall code-grader rate: {_fmt_rate(cur_overall)} (no baseline)")

    if warnings:
        print("\nwarnings (not blocking):")
        for w in warnings:
            print(f"  - {w}")

    if regressions:
        print("\nBLOCK: code-grader regressions beyond threshold:")
        for r in regressions:
            print(f"  - {r}")
        return BLOCK_ON_REGRESSION

    print("\nSHIP: no code-grader regression beyond threshold.")
    return False


async def run(dataset_path: Path, baseline_path: Path, update_baseline: bool) -> int:
    board = await _score(dataset_path)
    baseline = _scoreboard_to_baseline(board, dataset_path)
    baseline["overall_code_rate"] = _overall_code_rate(board)

    if update_baseline:
        baseline_path.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"\nwrote baseline -> {baseline_path}")
        return 0

    if not baseline_path.exists():
        raise SystemExit(
            f"no baseline at {baseline_path}. Generate one on main with --update-baseline."
        )

    prior = json.loads(baseline_path.read_text())
    should_block = _gate(board, prior)
    return 1 if should_block else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the baseline from this run instead of gating (run this on main)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.dataset, args.baseline, args.update_baseline)))


if __name__ == "__main__":
    main()
