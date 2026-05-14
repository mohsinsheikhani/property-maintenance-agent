"""Generate a markdown notes file for trace review.

One section per record: the email, what `expected` says, what the agent
actually did (key fields + tool calls), and blank Verdict / Notes lines for
the reviewer to fill in.

Usage:
    uv run python -m evals.make_notes evals/runs/<run_id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _fmt_dict(d: dict | None) -> str:
    if not d:
        return "  _(none)_"
    return "\n".join(f"  - `{k}`: `{json.dumps(v, ensure_ascii=False)}`" for k, v in d.items())


def _tool_calls(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            out.append(tc)
    return out


def render(record: dict) -> str:
    rid = record["id"]
    expected = record.get("expected") or {}
    fs = record.get("final_state") or {}
    meta = record.get("metadata") or {}
    err = record.get("error")

    # Reach back into the dataset for the email body via raw payload? It's not
    # in run.jsonl. Pull subject/from/body from final_state which the runner
    # copied into the initial state.
    subject = fs.get("subject", "")
    from_addr = fs.get("from_address", "")
    body = fs.get("body", "")

    agent_view = {
        "pre_filter_decision": fs.get("pre_filter_decision"),
        "unit_number": fs.get("unit_number"),
        "location_in_unit": fs.get("location_in_unit"),
        "category": fs.get("category"),
        "urgency": fs.get("urgency"),
        "risk_flags": fs.get("risk_flags"),
        "work_order_id": fs.get("work_order_id"),
    }
    tool_calls = _tool_calls(fs.get("messages") or [])
    tc_lines = "\n".join(
        f"  - `{tc.get('name')}`({json.dumps(tc.get('args'), ensure_ascii=False)[:200]})"
        for tc in tool_calls
    ) or "  _(none)_"

    err_block = ""
    if err:
        err_block = f"\n**Error:** `{err.get('type')}: {err.get('message')}`\n"

    return f"""## {rid} — {meta.get("category", "?")}{f' / {meta["failure_mode"]}' if meta.get("failure_mode") else ""}

**Rationale (from dataset):** {meta.get("rationale", "")}

**Email** — From: `{from_addr}` — Subject: `{subject}`
```
{body}
```

**Expected:**
{_fmt_dict(expected)}

**Agent did:**
{_fmt_dict(agent_view)}

**Tool calls:**
{tc_lines}
{err_block}
**Verdict:** [ ] pass  [ ] fail

**Notes:**
-

---
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path, help="evals/runs/<run_id>")
    args = parser.parse_args()

    run_path = args.run_dir / "run.jsonl"
    records = [json.loads(line) for line in run_path.read_text().splitlines() if line.strip()]

    out = [f"# Trace review — {args.run_dir.name}\n",
           f"_{len(records)} records. Judge each by gut, write what went wrong in free text. No pre-defined categories._\n",
           "---\n"]
    for rec in records:
        out.append(render(rec))

    notes_path = args.run_dir / "notes.md"
    notes_path.write_text("\n".join(out))
    print(f"Wrote {notes_path}")


if __name__ == "__main__":
    main()
