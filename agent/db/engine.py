from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from agent.settings import settings


def _normalize_for_asyncpg(url: str) -> str:
    """Accept a standard libpq URL and rewrite it for SQLAlchemy + asyncpg.

    - `postgresql://...` → `postgresql+asyncpg://...`
    - `sslmode=require` (libpq) → `ssl=require` (asyncpg)
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme == "postgresql":
        scheme = "postgresql+asyncpg"
    elif scheme == "postgres":
        scheme = "postgresql+asyncpg"

    query_pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k == "sslmode":
            query_pairs.append(("ssl", v))
        else:
            query_pairs.append((k, v))

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment))


engine = create_async_engine(
    _normalize_for_asyncpg(settings.database_url),
    echo=False,
    future=True,
    # Neon serverless drops idle connections; ping + short recycle keeps the pool fresh.
    pool_pre_ping=True,
    pool_recycle=300,
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    # Import models so SQLModel.metadata is populated before create_all runs.
    from agent.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
