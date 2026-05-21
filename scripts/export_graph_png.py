"""Render the compiled graph to graph.png at the repo root.

Importing agent.graph.graph runs load_mcp_tools() at import time, so the MCP
server must be reachable (docker compose up) before running this.

    uv run python -m scripts.export_graph_png
"""

from pathlib import Path

from agent.graph.graph import graph

OUT = Path(__file__).resolve().parents[1] / "graph.png"


def main() -> None:
    png = graph.get_graph().draw_mermaid_png()
    OUT.write_bytes(png)
    print(f"wrote {OUT} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
