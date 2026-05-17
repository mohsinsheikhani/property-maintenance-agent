import json
import uuid
from pathlib import Path
from pydantic import BaseModel
from typing import Literal, Optional, List

from jinja2 import Template
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from sqlalchemy import update

from agent.db.engine import async_session_factory
from agent.db.models import ClarifyMessage, Email
from agent.graph.state import EmailState, Turn
from agent.graph.tools import get_vendor_tools_sync


_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    # rstrip("\n") so the system prompt is byte-identical to the previous
    # triple-quoted form, which did not include a trailing newline.
    return (_PROMPTS_DIR / f"{name}.md").read_text().rstrip("\n")


def _load_template(name: str) -> Template:
    return Template((_PROMPTS_DIR / name).read_text())


_EXTRACT_USER_TEMPLATE = _load_template("extract_user.md.jinja")


def _thread_or_seed(state: EmailState) -> List[Turn]:
    """Use the seeded thread; fall back to subject/body for back-compat with callers
    that have not been migrated to seed `thread` themselves."""
    thread = state.get("thread")
    if thread:
        return list(thread)
    return [
        {
            "role": "tenant",
            "subject": state.get("subject"),
            "body": state.get("body") or "",
        }
    ]


class _PreFilterOutput(BaseModel):
    decision: Literal["pass", "archive"]
    reason: str


_pre_filter_chain = None


def _get_pre_filter_chain():
    global _pre_filter_chain
    if _pre_filter_chain is None:
        _pre_filter_chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            _PreFilterOutput
        )
    return _pre_filter_chain

_PREFILTER_SYSTEM_PROMPT = _load_prompt("pre_filter")


async def pre_filter(state: EmailState) -> dict:
    result: _PreFilterOutput = await _get_pre_filter_chain().ainvoke([
        {"role": "system", "content": _PREFILTER_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"From: {state.get('from_address', '')}\n"
            f"Subject: {state.get('subject', '')}\n\n"
            f"{state.get('body', '')}"
        )},
    ])
    return {
        "pre_filter_decision": result.decision,
        "pre_filter_reason": result.reason,
    }


async def archive(state: EmailState) -> dict:
    if email_id := state.get("email_id"):
        async with async_session_factory() as session:
            await session.execute(
                update(Email).where(Email.id == email_id).values(status="archived")
            )
            await session.commit()
    return {}


class _ExtractOutput(BaseModel):
    unit_number: Optional[str]
    location_in_unit: Optional[str]
    duration_mentioned: Optional[str]
    description: Optional[str]
    related_unit: Optional[str]       # secondary unit involved (e.g. leak from upstairs)
    diy_attempted: Optional[str]      # any fix the tenant already tried
    callback_phone: Optional[str]     # phone number if provided
    tenant_framing: Optional[str]     # how tenant described urgency ("no rush", "asap")
    tenant_sentiment: Optional[Literal["neutral", "calm", "anxious", "hostile", "polite", "panicked"]]
    lease_question_present: bool = False  # true if email also contains a lease/tenancy question
    insufficient_info: bool = False
    missing_fields: List[Literal["unit_number", "location_in_unit", "description"]] = []


_extract_chain = None


def _get_extract_chain():
    global _extract_chain
    if _extract_chain is None:
        _extract_chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            _ExtractOutput
        )
    return _extract_chain


_EXTRACT_SYSTEM_PROMPT = _load_prompt("extract")


async def extract(state: EmailState) -> dict:
    user_msg = _EXTRACT_USER_TEMPLATE.render(
        from_address=state.get("from_address", ""),
        thread=_thread_or_seed(state),
    )
    result: _ExtractOutput = await _get_extract_chain().ainvoke([
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    return {
        "unit_number": result.unit_number,
        "location_in_unit": result.location_in_unit,
        "duration_mentioned": result.duration_mentioned,
        "description": result.description,
        "related_unit": result.related_unit,
        "diy_attempted": result.diy_attempted,
        "callback_phone": result.callback_phone,
        "tenant_framing": result.tenant_framing,
        "tenant_sentiment": result.tenant_sentiment,
        "lease_question_present": result.lease_question_present,
        "insufficient_info": result.insufficient_info,
        "missing_fields": list(result.missing_fields),
    }


class _ClassifyOutput(BaseModel):
    category: Optional[Literal["plumbing", "electrical", "hvac", "locksmith", "general", "pest", "appliance"]]
    urgency: Optional[Literal["high", "medium", "low"]]
    risk_flags: List[str]
    not_a_maintenance_request: bool = False
    pm_queue: Optional[Literal["tenancy", "dispute", "accounting", "owner", "review"]] = None


_classify_chain = None


def _get_classify_chain():
    global _classify_chain
    if _classify_chain is None:
        _classify_chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            _ClassifyOutput
        )
    return _classify_chain


_CLASSIFY_SYSTEM_PROMPT = _load_prompt("classify")


async def classify(state: EmailState) -> dict:
    result: _ClassifyOutput = await _get_classify_chain().ainvoke([
        {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"From: {state.get('from_address', '')}\n"
            f"Subject: {state.get('subject', '')}\n\n"
            f"{state.get('body', '')}"
        )},
    ])
    return {
        "category": result.category,
        "urgency": result.urgency,
        "risk_flags": result.risk_flags,
        "not_a_maintenance_request": result.not_a_maintenance_request,
        "pm_queue": result.pm_queue,
    }


_CLARIFY_SYSTEM_PROMPT = _load_prompt("clarify")
_clarify_chain = None


def _get_clarify_chain():
    global _clarify_chain
    if _clarify_chain is None:
        # Plain prose, no structured output. The reply will be sent to the tenant.
        _clarify_chain = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return _clarify_chain


def _format_thread_for_clarify(thread: List[Turn]) -> str:
    parts = []
    for turn in thread:
        label = "TENANT" if turn["role"] == "tenant" else "AGENT (clarify ask)"
        subj = turn.get("subject")
        head = f"--- {label}"
        if subj:
            head += f"\nSubject: {subj}"
        parts.append(f"{head}\n{turn.get('body', '')}")
    return "\n\n".join(parts)


async def clarify_draft(state: EmailState) -> dict:
    """Draft the clarify ask and persist it to `clarify_messages`.

    Split from `clarify_pause` so the LLM call and the DB insert only run once
    per clarify cycle. If they sat before `interrupt()` in a single node, the
    node would re-execute from the top on resume — re-billing the LLM and
    duplicating the `clarify_messages` row.
    """
    missing = state.get("missing_fields") or []
    thread = _thread_or_seed(state)
    attempt = (state.get("clarify_attempts") or 0) + 1

    user_msg = (
        f"missing_fields: {missing}\n\n"
        f"Original tenant email (and any prior turns):\n"
        f"{_format_thread_for_clarify(thread)}"
    )
    ai_reply = await _get_clarify_chain().ainvoke([
        {"role": "system", "content": _CLARIFY_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    reply_body = ai_reply.content if hasattr(ai_reply, "content") else str(ai_reply)

    email_id = state.get("email_id")
    if email_id:
        async with async_session_factory() as session:
            session.add(ClarifyMessage(
                email_id=email_id,
                attempt=attempt,
                body=reply_body,
                missing_fields=list(missing),
            ))
            await session.commit()

    return {"pending_clarify_body": reply_body}


async def clarify_pause(state: EmailState) -> dict:
    """Wait for the tenant reply, then fold both turns into `thread`.

    Pure pre-interrupt logic: re-running this node on resume only re-reads
    state, no LLM call, no DB write.
    """
    missing = state.get("missing_fields") or []
    thread = _thread_or_seed(state)
    attempt = (state.get("clarify_attempts") or 0) + 1
    reply_body = state.get("pending_clarify_body") or ""

    reply = interrupt({"clarify_attempt": attempt, "missing_fields": list(missing)})

    if isinstance(reply, dict):
        reply_text = reply.get("body") or reply.get("reply_body") or ""
        reply_subject = reply.get("subject")
    else:
        reply_text = str(reply or "")
        reply_subject = None

    new_thread = thread + [
        {"role": "agent", "subject": None, "body": reply_body},
        {"role": "tenant", "subject": reply_subject, "body": reply_text},
    ]
    return {
        "thread": new_thread,
        "clarify_attempts": attempt,
        "clarify_outcome": "resumed",
        "pending_clarify_body": None,
    }


async def route(state: EmailState) -> dict:
    """Deterministic dispatch: read classify's flags, synthesize a tool call.

    The maintenance vs PM-queue decision is owned by classify (`not_a_maintenance_request`
    and `pm_queue`). Route's only job is to translate that into the right tool call so
    the existing ToolNode can execute it. No LLM here — that decision used to overlap
    with classify's and produced disagreement failures (Cat 3).
    """
    email_id = state.get("email_id")
    tool_call_id = f"route-{uuid.uuid4().hex[:8]}"

    # MCP tools take a single `params` object (CreateWorkOrderInput / AssignToPmQueueInput).
    # langchain-mcp-adapters flattens this for LLM tool calls, but we are synthesizing
    # the call by hand so we have to wrap the args ourselves.
    if state.get("not_a_maintenance_request"):
        queue = state.get("pm_queue") or "review"
        reason = (state.get("description") or state.get("pre_filter_reason")
                  or "Non-maintenance email; needs human handling.")
        tool_call = {
            "id": tool_call_id,
            "name": "assign_to_pm_queue",
            "args": {"params": {"email_id": email_id, "queue": queue, "reason": reason}},
        }
    else:
        tool_call = {
            "id": tool_call_id,
            "name": "create_work_order",
            "args": {"params": {
                "email_id": email_id,
                "category": state.get("category"),
                "urgency": state.get("urgency"),
                "risk_flags": state.get("risk_flags") or [],
                "description": state.get("description") or state.get("subject") or "",
                "location_in_unit": state.get("location_in_unit"),
                "unit_number": state.get("unit_number"),
            }},
        }

    ai_msg = AIMessage(content="", tool_calls=[tool_call])
    return {"messages": [ai_msg]}


def _tool_message_text(msg: ToolMessage) -> str:
    """ToolMessage.content can be a string or a list of content blocks; flatten to text."""
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


async def capture_work_order(state: EmailState) -> dict:
    """Pull work_order_id out of the latest create_work_order ToolMessage, if any.

    The route step emits an AIMessage with tool_calls; ToolNode appends one
    ToolMessage per call. We walk back through them to find the create_work_order
    result and lift its id into state for vendor selection.
    """
    # Map tool_call_id → tool name from the most recent AIMessage with tool_calls.
    name_by_id: dict[str, str] = {}
    for m in reversed(state.get("messages", [])):
        if isinstance(m, AIMessage) and m.tool_calls:
            name_by_id = {tc["id"]: tc["name"] for tc in m.tool_calls}
            break

    for m in reversed(state.get("messages", [])):
        if isinstance(m, ToolMessage) and name_by_id.get(m.tool_call_id) == "create_work_order":
            try:
                payload = json.loads(_tool_message_text(m))
            except json.JSONDecodeError:
                return {}
            if payload.get("ok") and payload.get("work_order_id"):
                return {"work_order_id": payload["work_order_id"]}
            return {}
    return {}


_VENDOR_LLM_SYSTEM_PROMPT = _load_prompt("vendor_llm")


async def vendor_llm(state: EmailState) -> dict:
    """One iteration of the vendor ReAct loop: bind vendor tools, ask the LLM."""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(get_vendor_tools_sync())

    messages = state.get("messages") or []
    # First entry into vendor_llm: prime with the work-order context.
    if not any(
        isinstance(m, AIMessage) and any(tc["name"] in {"search_vendors", "dispatch_vendor"} for tc in (m.tool_calls or []))
        for m in messages
    ):
        primer = (
            f"work_order_id: {state.get('work_order_id')}\n"
            f"trade: {state.get('category')}\n"
            f"urgency: {state.get('urgency')}"
        )
        ai_msg = await llm.ainvoke(
            [{"role": "system", "content": _VENDOR_LLM_SYSTEM_PROMPT}]
            + list(messages)
            + [{"role": "user", "content": primer}]
        )
        return {"messages": [{"role": "user", "content": primer}, ai_msg]}

    ai_msg = await llm.ainvoke(
        [{"role": "system", "content": _VENDOR_LLM_SYSTEM_PROMPT}] + list(messages)
    )
    return {"messages": [ai_msg]}
