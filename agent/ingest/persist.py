from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from agent.db.models import Client, Email
from agent.ingest.schemas import NormalizedEmail


async def persist_email(
    client: Client,
    email: NormalizedEmail,
    session: AsyncSession,
) -> Email:
    """Persist a NormalizedEmail. The only path emails enter the database.

    Idempotent on (client_id, source, source_message_id) — Pub/Sub may duplicate
    notifications and fixture replays should be safe to re-run.
    """

    insert_stmt = pg_insert(Email).values(
        client_id=client.id,
        source=email.source,
        source_message_id=email.source_message_id,
        from_address=email.from_address,
        subject=email.subject,
        body=email.body,
        raw_payload=email.raw_payload,
        received_at=email.received_at,
        status="pending",
    )
    on_conflict = insert_stmt.on_conflict_do_nothing(
        index_elements=["client_id", "source", "source_message_id"]
    )
    await session.execute(on_conflict)
    await session.commit()

    result = await session.execute(
        select(Email).where(
            Email.client_id == client.id,
            Email.source == email.source,
            Email.source_message_id == email.source_message_id,
        )
    )
    return result.scalar_one()
