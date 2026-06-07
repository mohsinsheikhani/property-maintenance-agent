"""Pull cost/latency/token metrics back out of Langfuse for the cost-eval scorecard.

The runner writes no local metric artifacts — Langfuse is the source of truth
(see evals/runner.py docstring). This module is the read side: given a `run_id`
(the runner stamps it onto `tags=["eval", "run:<run_id>"]` and `metadata.run_id`),
it reconstructs per-trace cost/latency/token rows and the per-model aggregate.

Why two code paths against Langfuse, not one Metrics-API call:

  - The Metrics API (`/v2/metrics`) does percentiles server-side but REFUSES to
    group by `traceId` (high-cardinality). It can only aggregate per model. So it
    gives the scorecard's headline row per model, never the per-record table.
  - The `$ per pass` column needs cost joined to pass/fail PER record, so we pull
    one row per trace from the trace list (which carries `metadata.dataset_id`,
    the join key) and compute percentiles locally. That also dodges the unit trap
    below.

Unit trap (verified live, not in the docs): trace-level and observation-level
`latency` are in SECONDS; the Metrics API `latency` measure is in MILLISECONDS.
We normalise everything to ms here so the scorecard is internally consistent.

Usage:
    uv run python -m evals.metrics --run-id 20260519T121633Z
    uv run python -m evals.metrics --run-id <id> --tokens   # also fetch token totals (N+1 GETs)
"""

from __future__ import annotations

import argparse
import base64
import os
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

load_dotenv()

_HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
_AUTH = base64.b64encode(
    f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
).decode()
_HEADERS = {"Authorization": f"Basic {_AUTH}"}


@dataclass
class TraceMetrics:
    """One eval record's measured cost/latency/tokens, keyed by dataset_id."""

    trace_id: str
    dataset_id: str
    latency_ms: float
    cost_usd: float
    # Token totals are summed across the trace's GENERATION observations. Only
    # populated when `--tokens` is requested; the trace list endpoint omits them.
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in 0..100). Matches numpy's default."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    rank = (q / 100) * (len(xs) - 1)
    lo = int(rank)
    frac = rank - lo
    if lo + 1 >= len(xs):
        return xs[lo]
    return xs[lo] + frac * (xs[lo + 1] - xs[lo])


def fetch_trace_rows(run_id: str, *, with_tokens: bool = False) -> list[TraceMetrics]:
    """Per-trace cost + wall-clock latency for one runner pass.

    Paginates the trace list filtered to this run's tag. `latency` and `totalCost`
    come straight off the trace — these ARE Block-1's `total_latency_ms` (×1000)
    and `total_cost_usd`, no client-side math. Tokens, if asked for, require a GET
    per trace because the list endpoint doesn't carry usage.
    """
    rows: list[TraceMetrics] = []
    with httpx.Client(base_url=_HOST, headers=_HEADERS, timeout=30) as client:
        page = 1
        while True:
            resp = client.get(
                "/api/public/traces",
                params={"tags": f"run:{run_id}", "limit": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            if not data:
                break
            for t in data:
                row = TraceMetrics(
                    trace_id=t["id"],
                    dataset_id=(t.get("metadata") or {}).get("dataset_id", t["id"]),
                    latency_ms=(t.get("latency") or 0.0) * 1000,  # trace latency is in seconds
                    cost_usd=t.get("totalCost") or 0.0,
                )
                if with_tokens:
                    _attach_tokens(client, row)
                rows.append(row)
            page += 1
    return rows


def _attach_tokens(client: httpx.Client, row: TraceMetrics) -> None:
    """Sum input/output/cached tokens across the trace's GENERATION observations."""
    detail = client.get(f"/api/public/traces/{row.trace_id}")
    detail.raise_for_status()
    inp = out = cached = 0
    for obs in detail.json().get("observations", []):
        if obs.get("type") != "GENERATION":
            continue
        usage = obs.get("usageDetails") or {}
        inp += usage.get("input", 0)
        out += usage.get("output", 0)
        cached += usage.get("input_cache_read", 0)  # OpenAI cached-prompt tokens
    row.input_tokens, row.output_tokens, row.cached_tokens = inp, out, cached


def fetch_model_aggregate(run_id: str) -> list[dict]:
    """Per-model aggregate via the Metrics API — the server-side percentile path.

    Cross-check for the locally-computed scorecard, and the right tool once a
    bake-off run mixes models in one trace set (group by providedModelName).
    NOTE: latency here is in MILLISECONDS already; field names are
    `<aggregation>_<measure>` (e.g. p95_latency), NOT the order the public docs show.
    """
    query = {
        "view": "observations",
        "dimensions": [{"field": "providedModelName"}],
        "metrics": [
            {"measure": "totalCost", "aggregation": "sum"},
            {"measure": "latency", "aggregation": "p50"},
            {"measure": "latency", "aggregation": "p95"},
            {"measure": "latency", "aggregation": "p99"},
            {"measure": "totalTokens", "aggregation": "sum"},
            {"measure": "count", "aggregation": "count"},
        ],
        # Filter to this run. metadata is a stringObject column keyed by run_id.
        "filters": [
            {
                "column": "metadata",
                "operator": "contains",
                "key": "run_id",
                "value": run_id,
                "type": "stringObject",
            }
        ],
        # Window must bracket the run; widen if your runs are older.
        "fromTimestamp": "2025-01-01T00:00:00Z",
        "toTimestamp": "2030-01-01T00:00:00Z",
        "rowLimit": 50,
    }
    with httpx.Client(base_url=_HOST, headers=_HEADERS, timeout=30) as client:
        import json

        resp = client.get(
            "/api/public/v2/metrics", params={"query": json.dumps(query)}
        )
        resp.raise_for_status()
        return resp.json()["data"]


@dataclass
class Scorecard:
    model: str
    n: int
    pass_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    mean_cost_usd: float
    p95_cost_usd: float
    cost_per_pass_usd: float  # mean_cost / pass_rate — the headline trade-off number
    rows: list[TraceMetrics] = field(default_factory=list)


def build_scorecard(
    rows: list[TraceMetrics], passes: dict[str, bool], *, model: str
) -> Scorecard:
    """Block-3 scorecard for one model. `passes` maps dataset_id -> pass/fail.

    Pass/fail comes from your existing graders (evals/graders, evals/components)
    or human labels (evals/review/labels.json) — this module deliberately doesn't
    grade, it only joins. Records with no grade are excluded from pass_rate so a
    missing label can't masquerade as a failure.
    """
    graded = [r for r in rows if r.dataset_id in passes]
    n_pass = sum(passes[r.dataset_id] for r in graded)
    pass_rate = n_pass / len(graded) if graded else 0.0
    latencies = [r.latency_ms for r in rows]
    costs = [r.cost_usd for r in rows]
    mean_cost = sum(costs) / len(costs) if costs else 0.0
    return Scorecard(
        model=model,
        n=len(rows),
        pass_rate=pass_rate,
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        p99_latency_ms=_percentile(latencies, 99),
        mean_cost_usd=mean_cost,
        p95_cost_usd=_percentile(costs, 95),
        # Expected cost to obtain one correct answer. Infinite if nothing passes.
        cost_per_pass_usd=(mean_cost / pass_rate) if pass_rate else float("inf"),
        rows=rows,
    )


def _print_table(sc: Scorecard) -> None:
    print(f"\nModel: {sc.model}   (n={sc.n}, graded pass rate={sc.pass_rate:.1%})")
    print(
        f"{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}"
        f"{'mean $':>11}{'p95 $':>11}{'$/pass':>11}"
    )
    print(
        f"{sc.p50_latency_ms:>9.0f}{sc.p95_latency_ms:>9.0f}{sc.p99_latency_ms:>9.0f}"
        f"{sc.mean_cost_usd:>11.5f}{sc.p95_cost_usd:>11.5f}{sc.cost_per_pass_usd:>11.5f}"
    )


def _print_comparison(cards: list[Scorecard]) -> None:
    """Block-3 efficiency scorecard: one row per model in a single table.

    Latency is kept (p95 especially) as a guardrail, not a headline — this is an
    async email workflow, so the decision columns are pass rate and $/pass (the
    expected cost of one correct triage). A slow-but-cheap model still wins here;
    p95 only flags a model that loops or runs away on tool calls.
    """
    print(
        f"\n{'Model':<16}{'Pass':>7}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}"
        f"{'mean $':>11}{'p95 $':>11}{'$/pass':>11}"
    )
    print("-" * 83)
    for sc in cards:
        print(
            f"{sc.model:<16}{sc.pass_rate:>6.0%} {sc.p50_latency_ms:>8.0f}"
            f"{sc.p95_latency_ms:>9.0f}{sc.p99_latency_ms:>9.0f}"
            f"{sc.mean_cost_usd:>11.5f}{sc.p95_cost_usd:>11.5f}{sc.cost_per_pass_usd:>11.5f}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", help="runner run_id (the `run:<id>` tag)")
    ap.add_argument("--model", default="gpt-4o-mini", help="label for the scorecard row")
    ap.add_argument(
        "--compare", action="append", metavar="MODEL=RUN_ID",
        help="add a row to the bake-off table; repeat per model "
             "(e.g. --compare gpt-4o-mini=20260603T153358Z --compare gemini-flash=<run>)",
    )
    ap.add_argument("--tokens", action="store_true", help="also fetch token totals (N+1 GETs)")
    ap.add_argument("--aggregate", action="store_true", help="print Metrics-API per-model cross-check")
    args = ap.parse_args()

    if args.compare:
        cards = []
        for pair in args.compare:
            model, _, run_id = pair.partition("=")
            rows = fetch_trace_rows(run_id)
            print(f"Pulled {len(rows)} traces for {model} (run {run_id})")
            # Stub pass=True until graders land (see build_scorecard docstring); with
            # everything passing, $/pass collapses to mean cost. Honest placeholder.
            passes = {r.dataset_id: True for r in rows}
            cards.append(build_scorecard(rows, passes, model=model))
        _print_comparison(cards)
        return

    if not args.run_id:
        ap.error("provide --run-id (single model) or --compare MODEL=RUN_ID (table)")

    rows = fetch_trace_rows(args.run_id, with_tokens=args.tokens)
    print(f"Pulled {len(rows)} traces for run {args.run_id}")

    # No grader wired in here yet — every record counts as a pass so the latency/cost
    # columns are usable on their own. Replace with your graders' verdicts for $/pass.
    passes = {r.dataset_id: True for r in rows}
    _print_table(build_scorecard(rows, passes, model=args.model))

    if args.tokens:
        ti = sum(r.input_tokens or 0 for r in rows)
        to = sum(r.output_tokens or 0 for r in rows)
        tc = sum(r.cached_tokens or 0 for r in rows)
        print(f"\nTokens: input={ti} output={to} cached={tc}")

    if args.aggregate:
        print("\nMetrics-API per-model cross-check (latency already in ms):")
        for d in fetch_model_aggregate(args.run_id):
            print(f"  {d}")


if __name__ == "__main__":
    main()
