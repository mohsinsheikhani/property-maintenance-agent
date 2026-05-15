"""Cat 1 baseline judge: defensible urgency given physical facts.

UNVALIDATED. Treat its verdicts as illustrative, not as a gate. To become
trustworthy this judge needs:
- TPR/TNR > 90% on a held-out labeled set (~80 examples)
- Few-shot examples drawn from a training split (not dev/test)

Prompt: evals/graders/prompts/urgency_judge.md (four-component structure:
task, definitions, examples, output schema). Examples are hand-authored and
do not overlap the dataset, so the judge does not get a free ride on dev.

Input: subject + body + the urgency the agent picked.
Output: critique (string), result ("Pass"|"Fail").
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from jinja2 import Template
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from . import GraderResult

NAME = "classify.urgency.judge_defensible.unvalidated"
_MODEL = "gpt-4o"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "urgency_judge.md.jinja"


class _JudgeOutput(BaseModel):
    critique: str = Field(description="reasoning grounded in specific phrases from the email")
    result: Literal["Pass", "Fail"]


_TEMPLATE = Template(_PROMPT_PATH.read_text())
_judge_chain = None


def _get_chain():
    global _judge_chain
    if _judge_chain is None:
        _judge_chain = ChatOpenAI(model=_MODEL, temperature=0).with_structured_output(_JudgeOutput)
    return _judge_chain


async def grade(expected: dict, final_state: dict) -> GraderResult:
    classify = (expected or {}).get("classify") or {}
    if "urgency" not in classify or classify["urgency"] is None:
        return GraderResult(name=NAME, status="skipped", reason="no expected.classify.urgency")

    actual_urgency = (final_state or {}).get("urgency")
    if actual_urgency is None:
        return GraderResult(
            name=NAME, status="skipped", reason="agent did not produce an urgency"
        )

    prompt = _TEMPLATE.render(
        subject=(final_state or {}).get("subject", ""),
        body=(final_state or {}).get("body", ""),
        actual_urgency=actual_urgency,
    )

    verdict: _JudgeOutput = await _get_chain().ainvoke([
        {"role": "user", "content": prompt},
    ])

    status = "pass" if verdict.result == "Pass" else "fail"
    return GraderResult(
        name=NAME,
        status=status,
        expected=classify["urgency"],
        actual=actual_urgency,
        reason=verdict.critique,
    )
