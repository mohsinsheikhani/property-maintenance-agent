# Trace review interface

A local annotation UI for the Hamel "look at traces" step: read each run, judge
pass/fail by gut, write free-text notes, before any grader exists. It reads the
run dumps under `evals/runs/`, renders each trace (email as an email, the
agent's pipeline decisions, the ground truth one toggle away), and writes labels
that export back to the same schema as
`evals/error_analysis/round_1/trace_labels.csv`.

## Run it

```bash
uv run python -m evals.review.server      # merges evals/runs/*, serves on :8765
```

Then open **http://127.0.0.1:8765** in a browser.

> Open the served URL, not the `index.html` file. Opened as a `file://` the page
> loads its chrome but can't reach `/api/traces`, so it hangs on "loading
> traces…". The page now says so instead of spinning silently.

Options:

```bash
uv run python -m evals.review.server --runs evals/runs/20260516T082403Z/run.jsonl
uv run python -m evals.review.server --labels /tmp/scratch.json --port 9000
```

`--runs` takes a single `run.jsonl` or a directory of run dirs (default
`evals/runs/`, merged with latest-run-wins per trace id).

## Labels

Labels autosave to `evals/review/labels.json` on every action (gitignored;
working state). On first run it seeds from `round_1/trace_labels.csv` so a
session continues prior work rather than starting blank. Malformed seed rows (a
couple have an unquoted comma in `user_query`) are skipped, so they show as
unlabeled and get re-reviewed.

Export to the round_1 CSV schema any time at
[`/api/export.csv`](http://127.0.0.1:8765/api/export.csv) (the "export csv"
button), which is how a review session merges back into the taxonomy.

## Keyboard

```
← / →   prev / next        1   pass        2   fail
D       defer              U   undo last    Cmd/Ctrl+Enter   next
```

The label schema mirrors the CSV: verdict, `first_failed_span`, free-text notes,
and the per-criterion `urgency_correct` / `sentiment_correct` / `clarify_correct`
tri-states. No predefined failure-mode tags yet, by design — those get added once
the round-3 taxonomy is settled.

## Why a standalone stdlib server

It deliberately imports nothing from `agent.*`. Pulling in a node drags the
Settings + MCP import chain (see the root `CLAUDE.md` gotchas), and this tool
only ever reads run dumps off disk. Run dumps are the contract here, not the
live graph.

## Testing

`uv add --dev playwright && uv run playwright install chromium`, start the
server, then drive a headless browser through the full annotation workflow
(click/keyboard verdicts, notes, autosave-across-reload, collapse toggles). The
server side (seed, POST persistence, CSV export) is checkable with plain `curl`.
