"""Load MCP tools from the property_maintenance_mcp server into LangChain BaseTools.

Connects via streamable_http to the MCP server running in docker compose. The
client and tool list are cached per process so we don't reconnect on every
node invocation.

Override the URL with MCP_SERVER_URL (e.g. for tests or alternate deployments).
"""

import os
from typing import Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

_MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

_client: Optional[MultiServerMCPClient] = None
_tools: Optional[list[BaseTool]] = None


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


async def get_mcp_tools() -> list[BaseTool]:
    """Return the cached list of MCP-backed LangChain tools.

    The first call connects to the MCP server and asks for its tool list;
    subsequent calls reuse the cached tools.
    """
    global _tools
    if _tools is None:
        _tools = await _get_client().get_tools()
    return _tools


def get_mcp_tools_sync() -> list[BaseTool]:
    """Sync accessor for already-loaded MCP tools.

    Raises if get_mcp_tools() hasn't run yet — the graph module primes the cache
    at compile time, so this is safe to call from sync contexts after that.
    """
    if _tools is None:
        raise RuntimeError("MCP tools not loaded yet — call get_mcp_tools() first")
    return _tools
