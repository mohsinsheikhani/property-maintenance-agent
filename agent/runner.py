"""Poll pending emails and run them through the triage graph."""

import asyncio
import uuid
from dotenv import load_dotenv

load_dotenv()

from sqlmodel import select

from agent.db.engine import async_session_factory, init_db
from agent.db.models import Email
from agent.graph.graph import graph, _langfuse_handler  # handler reads env vars at import time


async def _process_email(email: Email) -> None:
    state = {
        "email_id": str(email.id),
        "from_address": email.from_address,
        "subject": email.subject,
        "body": email.body,
        "pre_filter_decision": None,
        "pre_filter_reason": None,
    }

    config = {
        "configurable": {"thread_id": str(uuid.uuid4())},
        "callbacks": [_langfuse_handler],
        "metadata": {"email_id": str(email.id), "source": email.source},
    }

    await graph.ainvoke(state, config=config)


async def run_once() -> int:
    """Process all pending emails. Returns count processed."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Email).where(Email.status == "pending").limit(50)
        )
        emails = result.scalars().all()

        # Mark as processing before invoking to avoid double-pick-up
        for email in emails:
            email.status = "processing"
        session.add_all(emails)
        await session.commit()

    for email in emails:
        await _process_email(email)

    return len(emails)


async def main() -> None:
    await init_db()
    print("Runner started — polling for pending emails every 10s")
    while True:
        count = await run_once()
        if count:
            print(f"Processed {count} email(s)")
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
