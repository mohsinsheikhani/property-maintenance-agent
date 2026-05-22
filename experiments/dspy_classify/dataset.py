"""Step 2: load datasets/e2e/dev.jsonl as dspy.Example list for the classify step.

Each E2E record carries the expected behavior for every pipeline step; we slice
out the `classify` part. Records where classify never ran (no expected.classify,
e.g. pre-filter archived the email) are dropped. That leaves 92 of 103 records.

The thread input is rendered with the same jinja template the production node
uses, so the model sees the same input in eval and prod.

All four scored labels are closed sets, so unlike extract we keep every one:
category, urgency, risk_flags, not_a_maintenance_request. pm_queue is loaded but
not scored (only 2 records label it, no signal to grade).
"""

import json
from pathlib import Path
from typing import Iterator

import dspy
from jinja2 import Template

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _REPO_ROOT / "agent" / "graph" / "prompts"
_DEV_JSONL = _REPO_ROOT / "datasets" / "e2e" / "dev.jsonl"

# Same template the live node renders; reused so eval input == prod input.
_THREAD_TEMPLATE = Template((_PROMPTS_DIR / "extract_user.md.jinja").read_text())


def _render_thread(query: dict) -> str:
    return _THREAD_TEMPLATE.render(
        from_address=query.get("from", ""),
        thread=[{"role": "tenant", "subject": query.get("subject"), "body": query.get("body", "")}],
    )


def _records() -> Iterator[dict]:
    with _DEV_JSONL.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_examples() -> list[dspy.Example]:
    examples: list[dspy.Example] = []
    for rec in _records():
        expected = rec.get("expected") or {}
        classify = expected.get("classify")
        if classify is None:
            continue  # classify never ran for this record (e.g. pre-filter archived)

        ex = dspy.Example(
            id=rec["id"],
            thread=_render_thread(rec["query"]),
            category=classify.get("category"),
            urgency=classify.get("urgency"),
            risk_flags=list(classify.get("risk_flags") or []),
            not_a_maintenance_request=bool(classify.get("not_a_maintenance_request", False)),
        ).with_inputs("thread")
        examples.append(ex)
    return examples
