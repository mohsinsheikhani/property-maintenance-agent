"""Cat 2 judge: does the clarify ask cover every missing field?

UNVALIDATED. Verdicts are illustrative, not a CI gate. To promote:
- TPR/TNR > 90% on a held-out labeled set (~80 examples)
- Few-shot examples drawn from a training split (not dev/test)

A code grader cannot answer this question. "Could you tell us where in the
apartment this is happening" covers `location_in_unit` without containing
those literal words; a regex per field would false-fail on paraphrase and
false-pass when a missing field is silently dropped.

Reads the latest clarify_messages row for the email; if no clarify row exists
the grader skips (the agent did not enter the clarify branch on this record,
so there is nothing to judge).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from jinja2 import Template
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlmodel import select

from agent.db.engine import async_session_factory
from agent.db.models import ClarifyMessage

from . import GraderResult

NAME = "clarify.ask.judge_covers_missing.unvalidated"
_MODEL = "gpt-4o"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "clarify_ask_judge.md.jinja"


class _JudgeOutput(BaseModel):
    critique: str = Field(description="reasoning that names specific phrases from the reply")
    result: Literal["Pass", "Fail"]


_TEMPLATE = Template(_PROMPT_PATH.read_text())
_judge_chain = None


def _get_chain():
    global _judge_chain
    if _judge_chain is None:
        _judge_chain = ChatOpenAI(model=_MODEL, temperature=0).with_structured_output(_JudgeOutput)
    return _judge_chain


async def _latest_clarify(email_id) -> ClarifyMessage | None:
    async with async_session_factory() as session:
        result = await session.execute(
            select(ClarifyMessage)
            .where(ClarifyMessage.email_id == email_id)
            .order_by(ClarifyMessage.attempt.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def grade(expected: dict, final_state: dict) -> GraderResult:
    extract = (expected or {}).get("extract") or {}
    classify = (expected or {}).get("classify") or {}
    insufficient = bool(extract.get("insufficient_info") or classify.get("insufficient_info"))
    if not insufficient:
        return GraderResult(name=NAME, status="skipped", reason="expected does not flag insufficient_info")

    email_id = (final_state or {}).get("email_id")
    if not email_id:
        return GraderResult(name=NAME, status="skipped", reason="final_state has no email_id")

    latest = await _latest_clarify(email_id)
    if latest is None:
        return GraderResult(
            name=NAME,
            status="fail",
            expected="clarify_messages row written",
            actual=None,
            reason="agent never wrote a clarify ask despite insufficient_info=true",
        )

    missing = (final_state or {}).get("missing_fields") or latest.missing_fields or []

    prompt = _TEMPLATE.render(
        subject=(final_state or {}).get("subject", ""),
        body=(final_state or {}).get("body", ""),
        missing_fields=list(missing),
        clarify_reply=latest.body,
    )

    verdict: _JudgeOutput = await _get_chain().ainvoke([
        {"role": "user", "content": prompt},
    ])

    status = "pass" if verdict.result == "Pass" else "fail"
    return GraderResult(
        name=NAME,
        status=status,
        expected=f"reply covers {list(missing)}",
        actual=latest.body,
        reason=verdict.critique,
    )
