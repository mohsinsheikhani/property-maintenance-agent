import asyncio
import uuid
from typing import Literal

from langchain_core.messages import AIMessage
from langfuse.langchain import CallbackHandler
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from agent.graph.state import EmailState
from agent.graph.nodes import (
    pre_filter,
    archive,
    extract,
    classify,
    clarify_draft,
    clarify_pause,
    route,
    capture_work_order,
    vendor_llm,
)
from agent.graph.tools import get_route_tools_sync, get_vendor_tools_sync, load_mcp_tools
from agent.settings import settings


# Cap on clarify cycles. Beyond this, the gate stops asking and escalates.
_MAX_CLARIFY_ATTEMPTS = 2


def _route_after_pre_filter(state: EmailState) -> Literal["archive", "extract"]:
    if state["pre_filter_decision"] == "archive":
        return "archive"
    return "extract"


def _route_after_classify(state: EmailState) -> Literal["route", "clarify_draft", "escalate"]:
    """Gate: maintenance-vs-not first, then field-presence, then default path.

    Ordering matters. A lease question is missing `description` in the maintenance
    sense too; if we asked field-presence first we'd send clarify messages to people
    who never wanted maintenance. Classify reads raw email and decides that case
    cleanly before the gate considers `insufficient_info`.
    """
    if state.get("not_a_maintenance_request"):
        return "route"
    if state.get("insufficient_info"):
        if (state.get("clarify_attempts") or 0) >= _MAX_CLARIFY_ATTEMPTS:
            return "escalate"
        return "clarify_draft"
    return "route"


async def escalate(state: EmailState) -> dict:
    """Cap-hit branch: synthesize an assign_to_pm_queue tool call to the `review` bucket.

    Reuses the existing route_tools path. Not a dedicated `clarify_failed` queue —
    we do not yet know how often this branch fires; add a bucket when the data says so.
    """
    tool_call = {
        "id": f"escalate-{uuid.uuid4().hex[:8]}",
        "name": "assign_to_pm_queue",
        "args": {"params": {
            "email_id": state.get("email_id"),
            "queue": "review",
            "reason": (
                f"Clarify exhausted after {state.get('clarify_attempts')} attempt(s); "
                f"missing: {state.get('missing_fields') or []}"
            ),
        }},
    }
    return {
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "clarify_outcome": "escalated",
    }


def _route_after_route(state: EmailState) -> Literal["route_tools", "__end__"]:
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        return "route_tools"
    return END


def _route_after_capture(state: EmailState) -> Literal["vendor_llm", "__end__"]:
    return "vendor_llm" if state.get("work_order_id") else END


def _route_after_vendor_llm(state: EmailState) -> Literal["vendor_tools", "__end__"]:
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        return "vendor_tools"
    return END


# ToolNode needs the tool list at build time. Prime the cache once,
# synchronously, then pick groups from it. Any failure (MCP server down,
# missing tools) is fatal — silent fallback to empty ToolNodes would only
# surface as confusing "is not a valid tool" errors mid-run.
asyncio.run(load_mcp_tools())
_route_tool_objs = get_route_tools_sync()
_vendor_tool_objs = get_vendor_tools_sync()

_missing_route = set(("create_work_order", "assign_to_pm_queue", "archive_email")) - {
    t.name for t in _route_tool_objs
}
_missing_vendor = set(("search_vendors", "dispatch_vendor")) - {
    t.name for t in _vendor_tool_objs
}
if _missing_route or _missing_vendor:
    raise RuntimeError(
        f"MCP server is missing expected tools: route={_missing_route}, vendor={_missing_vendor}"
    )

builder = StateGraph(EmailState)

builder.add_node("pre_filter", pre_filter)
builder.add_node("archive", archive)
builder.add_node("extract", extract)
builder.add_node("classify", classify)
builder.add_node("clarify_draft", clarify_draft)
builder.add_node("clarify_pause", clarify_pause)
builder.add_node("escalate", escalate)
builder.add_node("route", route)
builder.add_node("route_tools", ToolNode(_route_tool_objs))
builder.add_node("capture_work_order", capture_work_order)
builder.add_node("vendor_llm", vendor_llm)
builder.add_node("vendor_tools", ToolNode(_vendor_tool_objs))

builder.add_edge(START, "pre_filter")
builder.add_conditional_edges("pre_filter", _route_after_pre_filter, ["archive", "extract"])
builder.add_edge("archive", END)
builder.add_edge("extract", "classify")
builder.add_conditional_edges("classify", _route_after_classify, ["route", "clarify_draft", "escalate"])
# After clarify_pause resumes with a tenant reply, re-extract the richer thread.
builder.add_edge("clarify_draft", "clarify_pause")
builder.add_edge("clarify_pause", "extract")
builder.add_edge("escalate", "route_tools")
builder.add_conditional_edges("route", _route_after_route, ["route_tools", END])
builder.add_edge("route_tools", "capture_work_order")
builder.add_conditional_edges(
    "capture_work_order", _route_after_capture, ["vendor_llm", END]
)
builder.add_conditional_edges("vendor_llm", _route_after_vendor_llm, ["vendor_tools", END])
builder.add_edge("vendor_tools", "vendor_llm")

_langfuse_handler = CallbackHandler()


# Default graph: no checkpointer, fine for langgraph dev and one-shot paths that
# never hit clarify. Callers that need pause/resume use compile_with_checkpointer.
graph = builder.compile().with_config({"callbacks": [_langfuse_handler]})


def compile_with_checkpointer(checkpointer):
    """Recompile the graph with a checkpointer attached.

    Use when a run may hit `clarify` (clarify calls interrupt(), which is a no-op
    without a checkpointer and would break resume).
    """
    return builder.compile(checkpointer=checkpointer).with_config(
        {"callbacks": [_langfuse_handler]}
    )
