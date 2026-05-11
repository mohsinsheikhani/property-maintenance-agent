import json
from pydantic import BaseModel
from typing import Literal, Optional, List

from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import update

from agent.db.engine import async_session_factory
from agent.db.models import Email
from agent.graph.state import EmailState
from agent.graph.tools import get_mcp_tools


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

_SYSTEM_PROMPT = """You are a pre-filter for a property maintenance triage system.
Decide if the email is a legitimate maintenance request or should be archived.

Archive if: spam, phishing, job applications, marketing, or completely off-topic.
Pass if: tenant reporting an issue, landlord question, contractor reply, anything property-related.

Be permissive — when in doubt, pass it through."""


async def pre_filter(state: EmailState) -> dict:
    result: _PreFilterOutput = await _get_pre_filter_chain().ainvoke([
        {"role": "system", "content": _SYSTEM_PROMPT},
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
    tenant_sentiment: Optional[str]   # emotional tone ("hostile", "calm", "distressed")
    lease_question_present: bool = False  # true if email also contains a lease/tenancy question


_extract_chain = None


def _get_extract_chain():
    global _extract_chain
    if _extract_chain is None:
        _extract_chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            _ExtractOutput
        )
    return _extract_chain


_EXTRACT_SYSTEM_PROMPT = """Extract structured fields from a property maintenance email.
Return null for any field not clearly stated in the email.

Fields:
- unit_number: the tenant's unit or apartment number
- location_in_unit: where in the unit the problem is (e.g. "kitchen sink", "bathroom")
- duration_mentioned: how long the problem has been occurring, as stated by the tenant
- description: a brief description of the problem"""


async def extract(state: EmailState) -> dict:
    result: _ExtractOutput = await _get_extract_chain().ainvoke([
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"From: {state.get('from_address', '')}\n"
            f"Subject: {state.get('subject', '')}\n\n"
            f"{state.get('body', '')}"
        )},
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
    }


class _ClassifyOutput(BaseModel):
    category: Optional[Literal["plumbing", "electrical", "hvac", "locksmith", "general", "pest", "appliance"]]
    urgency: Optional[Literal["high", "medium", "low"]]
    risk_flags: List[str]
    not_a_maintenance_request: bool = False
    insufficient_info: bool = False


_classify_chain = None


def _get_classify_chain():
    global _classify_chain
    if _classify_chain is None:
        _classify_chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            _ClassifyOutput
        )
    return _classify_chain


_CLASSIFY_SYSTEM_PROMPT = """Classify a property maintenance request.

category: plumbing, electrical, hvac, locksmith, general, pest, appliance
urgency: high, medium, low
risk_flags (include all that apply): water_damage_potential, fire_hazard, security_risk, habitability_violation

If the email is not a maintenance request, set not_a_maintenance_request=true and leave category/urgency null.
If there is not enough information to classify, set insufficient_info=true."""


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
        "insufficient_info": result.insufficient_info,
    }


_ROUTE_SYSTEM_PROMPT = """Route a tenant email to the right tool.

- create_work_order: maintenance request
- assign_to_pm_queue: non-maintenance (queues: tenancy, dispute, accounting, owner, review)

Use the email_id provided."""


async def route(state: EmailState) -> dict:
    tools = await get_mcp_tools()
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(tools)

    user_content = (
        f"email_id: {state.get('email_id')}\n"
        f"from: {state.get('from_address')}\n"
        f"subject: {state.get('subject')}\n\n"
        f"{state.get('body')}\n\n"
        f"category={state.get('category')} urgency={state.get('urgency')} "
        f"risk_flags={state.get('risk_flags')} "
        f"not_a_maintenance_request={state.get('not_a_maintenance_request')} "
        f"insufficient_info={state.get('insufficient_info')}"
    )

    ai_msg = await llm.ainvoke(
        [
            {"role": "system", "content": _ROUTE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
    )
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


_VENDOR_LLM_SYSTEM_PROMPT = """Pick a vendor for a maintenance work order and dispatch them.

- search_vendors: list candidates for the trade
- dispatch_vendor: assign one to the work order"""


async def vendor_llm(state: EmailState) -> dict:
    """One iteration of the vendor ReAct loop: bind vendor tools, ask the LLM."""
    from agent.graph.tools import get_mcp_tools_sync

    vendor_tools = [
        t for t in get_mcp_tools_sync() if t.name in {"search_vendors", "dispatch_vendor"}
    ]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(vendor_tools)

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
