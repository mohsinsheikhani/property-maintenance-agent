"""Component eval for the pre_filter node.

Calls `agent.graph.nodes.pre_filter` live, per dataset record, and applies the
pre_filter_decision grader. No graph, no run.jsonl, no MCP server needed;
pre_filter only reads from_address/subject/body from state.

Skips records where expected.pre_filter.action is absent.

Usage:
    uv run python -m evals.components.pre_filter_eval
    uv run python -m evals.components.pre_filter_eval --dataset datasets/e2e/dev.jsonl --limit 5
    uv run python -m evals.components.pre_filter_eval --id e2e-ER06
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

from agent.graph.nodes import pre_filter
from evals.graders.pre_filter_decision import grade as grade_pre_filter

DEFAULT_DATASET = Path("datasets/e2e/dev.jsonl")
GRADERS = [grade_pre_filter]


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
    return await pre_filter(state)


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

    print(f"Running pre_filter on {len(records)} records from {dataset_path}\n")
    for record in records:
        trace_id = record["id"]
        expected = record.get("expected") or {}
        query = record.get("query") or {}
        try:
            pre_filter_output = await _run_one(record)
        except Exception as exc:
            print(f"  [err] {trace_id}: {type(exc).__name__}: {exc}")
            pre_filter_output = {}

        actual = {
            "subject": query.get("subject", ""),
            "body": query.get("body", ""),
            **pre_filter_output,
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
    parser.add_argument("--id", dest="only_id", help="run a single record by id, e.g. e2e-ER06")
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.limit, args.only_id))


if __name__ == "__main__":
    main()
