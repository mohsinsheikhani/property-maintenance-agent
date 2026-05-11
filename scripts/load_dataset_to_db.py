"""Load `datasets/e2e/dev.jsonl` into the `emails` table.

Same persist path the production webhook uses — the only difference is the source
of the NormalizedEmail (a JSONL record instead of a Gmail message). Re-running is
safe: the unique constraint on (client_id, source, source_message_id) makes it
idempotent.

Usage:
    uv run python -m scripts.load_dataset_to_db
    uv run python -m scripts.load_dataset_to_db --dataset datasets/e2e/dev.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import select

from agent.db.engine import async_session_factory, init_db
from agent.db.models import Client
from agent.ingest.persist import persist_email
from agent.ingest.schemas import NormalizedEmail

DEFAULT_DATASET = Path("datasets/e2e/dev.jsonl")
SEED_CLIENT_NAME = "Seed Property Manager (fixture)"
SEED_CLIENT_GMAIL = "maintenance+seed@example.com"


async def _get_or_create_seed_client(session) -> Client:
    result = await session.execute(select(Client).where(Client.gmail_address == SEED_CLIENT_GMAIL))
    client = result.scalar_one_or_none()
    if client is not None:
        return client

    client = Client(
        name=SEED_CLIENT_NAME,
        gmail_address=SEED_CLIENT_GMAIL,
        tone_guide="Direct, warm, no jargon.",
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client


def _record_to_normalized_email(record: dict) -> NormalizedEmail:
    query = record["query"]
    return NormalizedEmail(
        source="fixture",
        source_message_id=record["id"],
        from_address=query["from"],
        subject=query["subject"],
        body=query["body"],
        received_at=datetime.now(timezone.utc),
        raw_payload=record,
    )


async def load(dataset_path: Path) -> None:
    await init_db()

    async with async_session_factory() as session:
        client = await _get_or_create_seed_client(session)

        loaded = 0
        with dataset_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                normalized = _record_to_normalized_email(record)
                await persist_email(client, normalized, session)
                loaded += 1

        print(f"Loaded {loaded} fixture emails for client {client.id} ({client.gmail_address}).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    asyncio.run(load(args.dataset))


if __name__ == "__main__":
    main()
