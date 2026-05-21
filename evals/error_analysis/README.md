# Error analysis

The Hamel workflow artifacts: run the agent, read the traces, label pass/fail
by gut, group the notes into named failure modes, then decide fix vs grader.
One folder per review round.

Each round holds the same three files:

- `trace_labels` — per-trace pass/fail notes, written before any grader exists.
- `failure_taxonomy.md` — the notes grouped into named failure modes, with
  prevalence, gulf tag, and a code-or-judge call.
- `fix_vs_eval.md` — per-mode decision: just fix it, or also build a grader.

## Rounds

- `round_1/` — the first pass over 20 traces. Five categories. Bundle A
  (Cat 1+3+5), Cat 4, and Cat 2 fixes shipped out of this round.
- `round_2/` — the second pass after those fixes landed and the agent was
  re-run. Ten failed traces re-coded into fresh categories.

The earliest scratch drafts (open-coding raw material, the clarify-gate spec)
live under `evals/runs/` alongside the run dumps they came from.
