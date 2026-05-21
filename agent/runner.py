"""Poll pending emails and run them through the triage graph."""

import asyncio
import uuid
from dotenv import load_dotenv

load_dotenv()

from sqlmodel import select

from agent.db.engine import async_session_factory, init_db
from agent.db.models import Email
from agent.graph.checkpointer import open_checkpointer
from agent.graph.graph import compile_with_checkpointer, _langfuse_handler  # handler reads env at import


async def _process_email(graph, email: Email) -> None:
    state = {
        "email_id": str(email.id),
        "from_address": email.from_address,
        "subject": email.subject,
        "body": email.body,
        "thread": [{
            "role": "tenant",
            "subject": email.subject,
            "body": email.body,
        }],
        "clarify_attempts": 0,
        "pre_filter_decision": None,
        "pre_filter_reason": None,
    }

    config = {
        "configurable": {"thread_id": str(uuid.uuid4())},
        "callbacks": [_langfuse_handler],
        "metadata": {"email_id": str(email.id), "source": email.source},
    }

    # NB: clarify-reply detection / resume-on-reply is the PR3 Gmail-side work.
    # Until then, every poll-tick starts a fresh graph run for the email row;
    # the checkpointer is wired only to keep clarify pauses durable, not yet to
    # marry an inbound reply to a paused parent.
    await graph.ainvoke(state, config=config)


async def run_once(graph) -> int:
    """Process all pending emails. Returns count processed."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Email).where(Email.status == "pending").limit(50)
        )
        emails = result.scalars().all()

        for email in emails:
            email.status = "processing"
        session.add_all(emails)
        await session.commit()

    for email in emails:
        await _process_email(graph, email)

    return len(emails)


async def main() -> None:
    await init_db()
    async with open_checkpointer() as checkpointer:
        graph = compile_with_checkpointer(checkpointer)
        print("Runner started — polling for pending emails every 10s")
        while True:
            count = await run_once(graph)
            if count:
                print(f"Processed {count} email(s)")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
