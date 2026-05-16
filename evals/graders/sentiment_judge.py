"""Cat 4 judge: defensible tenant sentiment given the writing.

UNVALIDATED. Treat its verdicts as illustrative, not as a gate. To become
trustworthy this judge needs:
- TPR/TNR > 90% on a held-out labeled set (~80 examples)
- Few-shot examples drawn from a training split (not dev/test)

Prompt: evals/graders/prompts/sentiment_judge.md.jinja (same four-component
structure as urgency_judge: task, definitions, examples, output schema).
Examples are hand-authored and do not overlap the dataset, so the judge does
not get a free ride on dev.

Input: subject + body + the sentiment the agent picked (or null).
Output: critique (string), result ("Pass"|"Fail").
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from jinja2 import Template
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from . import GraderResult

NAME = "extract.tenant_sentiment.judge_defensible.unvalidated"
_MODEL = "gpt-4o"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "sentiment_judge.md.jinja"


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
    extract = (expected or {}).get("extract") or {}
    if "tenant_sentiment" not in extract:
        return GraderResult(name=NAME, status="skipped", reason="no expected.extract.tenant_sentiment")

    actual_sentiment = (final_state or {}).get("tenant_sentiment")

    prompt = _TEMPLATE.render(
        subject=(final_state or {}).get("subject", ""),
        body=(final_state or {}).get("body", ""),
        actual_sentiment=actual_sentiment if actual_sentiment is not None else "null",
    )

    verdict: _JudgeOutput = await _get_chain().ainvoke([
        {"role": "user", "content": prompt},
    ])

    status = "pass" if verdict.result == "Pass" else "fail"
    return GraderResult(
        name=NAME,
        status=status,
        expected=extract["tenant_sentiment"],
        actual=actual_sentiment,
        reason=verdict.critique,
    )
