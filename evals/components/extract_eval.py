"""Component eval for the extract node.

Calls `agent.graph.nodes.extract` live, per dataset record, and applies code
graders and judges to the result. No graph, no run.jsonl, no MCP server
needed; extract only reads from_address/subject/body from state.

Skips records where the relevant `expected.extract.*` field is absent.

Usage:
    uv run python -m evals.components.extract_eval
    uv run python -m evals.components.extract_eval --dataset datasets/e2e/dev.jsonl --limit 5
    uv run python -m evals.components.extract_eval --id e2e-E04
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agent.graph.nodes import extract
from evals.graders.sentiment_judge import grade as grade_sentiment_judge

DEFAULT_DATASET = Path("datasets/e2e/dev.jsonl")
GRADERS = [
    grade_sentiment_judge,
]


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


async def _run_one(record: dict) -> dict:
    query = record["query"]
    state = {
        "email_id": record["id"],
        "from_address": query.get("from", ""),
        "subject": query.get("subject", ""),
        "body": query.get("body", ""),
        "messages": [],
    }
    return await extract(state)


async def run(dataset_path: Path, limit: int | None, only_id: str | None) -> None:
    records = _load_jsonl(dataset_path)
    if only_id is not None:
        records = [r for r in records if r["id"] == only_id]
        if not records:
            raise SystemExit(f"no record with id={only_id!r} in {dataset_path}")
    elif limit is not None:
        records = records[:limit]

    per_grader: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"pass": [], "fail": [], "skipped": []}
    )
    rows: list[dict] = []

    print(f"Running extract on {len(records)} records from {dataset_path}\n")
    for record in records:
        trace_id = record["id"]
        expected = record.get("expected") or {}
        query = record.get("query") or {}
        try:
            extract_output = await _run_one(record)
        except Exception as exc:
            print(f"  [err] {trace_id}: {type(exc).__name__}: {exc}")
            extract_output = {}

        # Graders see extract output merged with the inputs the extract node
        # was called with, so judges that need subject/body can read them.
        actual = {
            "subject": query.get("subject", ""),
            "body": query.get("body", ""),
            **extract_output,
        }

        results = []
        for grader in GRADERS:
            result = await _apply(grader, expected, actual)
            per_grader[result.name][result.status].append(trace_id)
            results.append(asdict(result))
            status_mark = {"pass": "ok ", "fail": "FAIL", "skipped": "skip"}[result.status]
            if result.status == "fail":
                detail = f" expected={result.expected!r} actual={result.actual!r}"
                if result.reason:
                    detail += f"\n        critique: {result.reason}"
                print(f"  [{status_mark}] {trace_id} {result.name}{detail}")
            else:
                print(f"  [{status_mark}] {trace_id} {result.name}")
        rows.append({"id": trace_id, "actual": actual, "results": results})

    print()
    for name, buckets in per_grader.items():
        n_pass = len(buckets["pass"])
        n_fail = len(buckets["fail"])
        n_skip = len(buckets["skipped"])
        n_applicable = n_pass + n_fail
        rate = (n_pass / n_applicable) if n_applicable else None
        rate_str = f"{rate:.0%}" if rate is not None else "n/a"
        print(f"{name}: {n_pass}/{n_applicable} pass ({rate_str}), {n_skip} skipped")
        if buckets["fail"]:
            print(f"  failing: {', '.join(buckets['fail'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", dest="only_id", help="run a single record by id, e.g. e2e-E04")
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.limit, args.only_id))


if __name__ == "__main__":
    main()
