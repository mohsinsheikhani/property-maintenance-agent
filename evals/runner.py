"""Run the agent against records from a dataset JSONL.

Goes through the same `NormalizedEmail` → `persist_email` seam the webhook uses
(see CLAUDE.md: "one ingest seam"), then invokes the compiled graph directly.

Traces land in Langfuse, tagged with `metadata.run_id` and `metadata.dataset_id`
so the whole run can be filtered in the UI. No local artifacts are written;
Langfuse is the source of truth for run outputs.

For records that exercise the clarify gate, the runner reads `clarify_turns`
off the record and feeds replies back into the paused graph via Command(resume).
If `clarify_turns` is shorter than the number of asks, the tenant is treated as
having gone silent and the escalation branch fires.

Usage:
    uv run python -m evals.runner --limit 10
    uv run python -m evals.runner --dataset datasets/e2e/dev.jsonl --limit 10
    uv run python -m evals.runner --id e2e-E14
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langgraph.types import Command
from sqlmodel import select

# Export .env into os.environ before any SDK (OpenAI, Langfuse) imports it.
load_dotenv()

from agent.db.engine import async_session_factory, init_db
from agent.db.models import Client
from agent.ingest.persist import persist_email
from agent.ingest.schemas import NormalizedEmail

# Importing the graph triggers `asyncio.run(load_mcp_tools())` at module level
# (see CLAUDE.md gotcha). Must happen before we enter our own asyncio.run().
from agent.graph.graph import compile_with_checkpointer
from agent.graph.checkpointer import open_checkpointer

DEFAULT_DATASET = Path("datasets/e2e/dev.jsonl")
SEED_CLIENT_GMAIL = "maintenance+seed@example.com"
SEED_CLIENT_NAME = "Seed Property Manager (fixture)"


async def _get_or_create_seed_client(session) -> Client:
    result = await session.execute(
        select(Client).where(Client.gmail_address == SEED_CLIENT_GMAIL)
    )
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


def _record_to_normalized(record: dict) -> NormalizedEmail:
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


def _initial_state(record: dict, email_row) -> dict:
    """Seed the graph state, including `thread` with the original tenant email.

    The producer-seeds-thread contract (spec): extract should never have to
    rebuild the thread from subject/body. By the time the graph runs, the first
    turn is already in state.
    """
    return {
        "email_id": str(email_row.id),
        "from_address": email_row.from_address,
        "subject": email_row.subject,
        "body": email_row.body,
        "thread": [{
            "role": "tenant",
            "subject": email_row.subject,
            "body": email_row.body,
        }],
        "clarify_attempts": 0,
        "messages": [],
    }


async def _persist_clarify_reply(client, parent_email, record_id: str, attempt: int, reply_body: str):
    """Persist an injected tenant reply through the one ingest seam.

    Same `persist_email` call the webhook uses. Idempotency is (client_id, source,
    source_message_id); using a deterministic source_message_id makes dataset
    replays no-op safely.
    """
    normalized = NormalizedEmail(
        source="fixture",  # the canonical enum; the per-attempt id is what distinguishes
        source_message_id=f"{record_id}-clarify-{attempt}",
        from_address=parent_email.from_address,
        subject=f"Re: {parent_email.subject}",
        body=reply_body,
        received_at=datetime.now(timezone.utc),
        raw_payload={"clarify_attempt": attempt, "parent_email_id": str(parent_email.id)},
    )
    async with async_session_factory() as session:
        return await persist_email(client, normalized, session)


async def _run_one(graph, client, record: dict, email_row, run_id: str) -> None:
    """Drive a single record. Handles clarify pauses by resuming with replies."""
    dataset_id = record["id"]
    thread_id = f"{run_id}-{dataset_id}"
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "run_id": run_id,
            "dataset_id": dataset_id,
        },
        "tags": ["eval", f"run:{run_id}"],
    }

    state = _initial_state(record, email_row)
    clarify_turns = record.get("clarify_turns") or []
    attempts = 0

    result = await graph.ainvoke(state, config=config)

    while "__interrupt__" in result and attempts < len(clarify_turns):
        # Pause at clarify. Inject the next scripted reply.
        reply_body = clarify_turns[attempts]["reply_body"]
        attempts += 1
        await _persist_clarify_reply(client, email_row, dataset_id, attempts, reply_body)
        result = await graph.ainvoke(
            Command(resume={"body": reply_body}),
            config=config,
        )

    if "__interrupt__" in result:
        # Tenant ran out of replies. Resume with empty body so clarify can finish
        # bookkeeping; the next gate visit will hit the attempt cap and escalate.
        await graph.ainvoke(Command(resume={"body": ""}), config=config)


async def run(dataset_path: Path, limit: int, skip: int = 0, only_id: str | None = None) -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    await init_db()

    records: list[dict] = []
    seen = 0
    with dataset_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if only_id is not None:
                if record["id"] == only_id:
                    records.append(record)
                    break
                continue
            if seen < skip:
                seen += 1
                continue
            records.append(record)
            if len(records) >= limit:
                break

    if only_id is not None and not records:
        raise SystemExit(f"no record with id={only_id!r} in {dataset_path}")

    print(f"Running {len(records)} records (run_id={run_id}) — traces in Langfuse")

    async with open_checkpointer() as checkpointer:
        graph = compile_with_checkpointer(checkpointer)

        n_ok = 0
        n_err = 0
        for record in records:
            dataset_id = record["id"]
            normalized = _record_to_normalized(record)

            async with async_session_factory() as session:
                client = await _get_or_create_seed_client(session)
                email_row = await persist_email(client, normalized, session)

            try:
                await _run_one(graph, client, record, email_row, run_id)
                n_ok += 1
                print(f"  [ok]  {dataset_id}")
            except Exception as exc:
                n_err += 1
                print(f"  [err] {dataset_id}: {type(exc).__name__}: {exc}")

    print(f"\nDone: {n_ok} ok, {n_err} errored. run_id={run_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--id", dest="only_id", help="run a single record by id, e.g. e2e-E14")
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.limit, args.skip, args.only_id))


if __name__ == "__main__":
    main()
