import asyncio
from typing import Literal

from langfuse.langchain import CallbackHandler
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from agent.graph.state import EmailState
from agent.graph.nodes import (
    pre_filter,
    archive,
    extract,
    classify,
    route,
    capture_work_order,
    vendor_llm,
)
from agent.graph.tools import get_mcp_tools
from agent.settings import settings


def _route_after_pre_filter(state: EmailState) -> Literal["archive", "extract"]:
    if state["pre_filter_decision"] == "archive":
        return "archive"
    return "extract"


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


# ToolNode needs the tool list at build time. Load it once, synchronously,
# from the MCP server. If the server isn't reachable yet, fall back to an
# empty ToolNode — the route node will fail loudly when it tries to bind.
try:
    _mcp_tools = asyncio.run(get_mcp_tools())
except Exception:
    _mcp_tools = []

_route_tool_names = {"create_work_order", "assign_to_pm_queue", "archive_email"}
_vendor_tool_names = {"search_vendors", "dispatch_vendor"}

_route_tool_objs = [t for t in _mcp_tools if t.name in _route_tool_names]
_vendor_tool_objs = [t for t in _mcp_tools if t.name in _vendor_tool_names]

builder = StateGraph(EmailState)

builder.add_node("pre_filter", pre_filter)
builder.add_node("archive", archive)
builder.add_node("extract", extract)
builder.add_node("classify", classify)
builder.add_node("route", route)
builder.add_node("route_tools", ToolNode(_route_tool_objs))
builder.add_node("capture_work_order", capture_work_order)
builder.add_node("vendor_llm", vendor_llm)
builder.add_node("vendor_tools", ToolNode(_vendor_tool_objs))

builder.add_edge(START, "pre_filter")
builder.add_conditional_edges("pre_filter", _route_after_pre_filter, ["archive", "extract"])
builder.add_edge("archive", END)
builder.add_edge("extract", "classify")
builder.add_edge("classify", "route")
builder.add_conditional_edges("route", _route_after_route, ["route_tools", END])
builder.add_edge("route_tools", "capture_work_order")
builder.add_conditional_edges(
    "capture_work_order", _route_after_capture, ["vendor_llm", END]
)
builder.add_conditional_edges("vendor_llm", _route_after_vendor_llm, ["vendor_tools", END])
builder.add_edge("vendor_tools", "vendor_llm")

_langfuse_handler = CallbackHandler()

graph = builder.compile().with_config({"callbacks": [_langfuse_handler]})
