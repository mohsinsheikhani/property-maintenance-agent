"""Step 2: load datasets/e2e/dev.jsonl as dspy.Example list for the extract step.

Each E2E record carries the expected behavior for every pipeline step; we slice
out the extract + clarify parts. Records where extract never runs (pre-filter
archived the email) are dropped.

The thread input is rendered with the same jinja template the production node
uses, so the model sees the same input in eval and prod.

Two label notes from reading the data:
- expected.extract.description_present is a bool, not text. We can only score
  whether a description was produced, not its content. Content needs a judge.
- The gate (insufficient_info, missing_fields) is derived here from
  expected.clarify, since that's where dev.jsonl encodes "did we have to ask".
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


def _expected_gate(expected: dict) -> tuple[bool, list[str]]:
    """Derive (insufficient_info, missing_fields) from the clarify slice.

    clarify.triggered == "we couldn't proceed without asking" == insufficient_info.
    missing_fields is only meaningful when triggered; [] otherwise.
    """
    clarify = expected.get("clarify") or {}
    triggered = bool(clarify.get("triggered", False))
    missing = list(clarify.get("missing_fields", [])) if triggered else []
    return triggered, missing


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
        extract = expected.get("extract")
        if extract is None:
            continue  # extract never ran for this record (e.g. pre-filter archived)

        gate_insufficient, gate_missing = _expected_gate(expected)
        ex = dspy.Example(
            id=rec["id"],
            thread=_render_thread(rec["query"]),
            # Only the code-checkable labels. location/duration content and
            # sentiment are left out; they need a judge, not code.
            unit=extract.get("unit"),
            description_present=bool(extract.get("description_present", False)),
            lease_question_present=bool(extract.get("lease_question_present", False)),
            callback_phone=extract.get("callback_phone"),
            gate_insufficient=gate_insufficient,
            gate_missing=gate_missing,
        ).with_inputs("thread")
        examples.append(ex)
    return examples
