"""Postgres checkpointer for pause/resume across the clarify gate.

Clarify pauses can sit for hours or days waiting on a tenant reply. In-memory
checkpoints wouldn't survive a deploy or process restart, so we use the same
Neon database that holds the rest of the system's state.

LangGraph's AsyncPostgresSaver wants a `postgresql://...` URL with psycopg
(not asyncpg). It manages its own pool, separate from our SQLModel engine.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.settings import settings


def _psycopg_url(url: str) -> str:
    """Strip any `+asyncpg` driver suffix so psycopg picks the URL up cleanly."""
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme.startswith("postgresql+"):
        scheme = "postgresql"
    elif scheme == "postgres":
        scheme = "postgresql"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


@asynccontextmanager
async def open_checkpointer():
    """Open an AsyncPostgresSaver and run setup() once.

    `setup()` is idempotent — it creates the checkpoint tables if missing. Safe
    to call on every start; cheap when tables already exist.
    """
    url = _psycopg_url(settings.database_url)
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
        yield saver
