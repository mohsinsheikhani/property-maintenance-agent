"""Load MCP tools from the property_maintenance_mcp server into LangChain BaseTools.

Connects via streamable_http to the MCP server running in docker compose. The
client and tool list are cached per process so we don't reconnect on every
node invocation — langchain-mcp-adapters does no caching of its own, every
get_tools() call opens a fresh MCP session.

Override the URL with MCP_SERVER_URL (e.g. for tests or alternate deployments).
"""

import os
from typing import Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

_MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

# Tool groups — single source of truth for which LLM step sees which tools.
ROUTE_TOOL_NAMES = ("create_work_order", "assign_to_pm_queue", "archive_email")
VENDOR_TOOL_NAMES = ("search_vendors", "dispatch_vendor")

_client: Optional[MultiServerMCPClient] = None
_tools_by_name: Optional[dict[str, BaseTool]] = None


def _get_client() -> MultiServerMCPClient:
    global _client
    if _client is None:
        _client = MultiServerMCPClient(
            {
                "maintenance": {
                    "transport": "streamable_http",
                    "url": _MCP_SERVER_URL,
                },
            }
        )
    return _client


async def load_mcp_tools() -> dict[str, BaseTool]:
    """Connect to the MCP server once and cache tools keyed by name."""
    global _tools_by_name
    if _tools_by_name is None:
        tools = await _get_client().get_tools()
        _tools_by_name = {t.name: t for t in tools}
    return _tools_by_name


def _tools_by_name_sync() -> dict[str, BaseTool]:
    if _tools_by_name is None:
        raise RuntimeError("MCP tools not loaded yet — call load_mcp_tools() first")
    return _tools_by_name


def _pick(names: tuple[str, ...], tools: dict[str, BaseTool]) -> list[BaseTool]:
    return [tools[n] for n in names if n in tools]


async def get_route_tools() -> list[BaseTool]:
    return _pick(ROUTE_TOOL_NAMES, await load_mcp_tools())


async def get_vendor_tools() -> list[BaseTool]:
    return _pick(VENDOR_TOOL_NAMES, await load_mcp_tools())


def get_route_tools_sync() -> list[BaseTool]:
    return _pick(ROUTE_TOOL_NAMES, _tools_by_name_sync())


def get_vendor_tools_sync() -> list[BaseTool]:
    return _pick(VENDOR_TOOL_NAMES, _tools_by_name_sync())
