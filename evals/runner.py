"""Run the agent against records from a dataset JSONL and dump per-record runs.

Goes through the same `NormalizedEmail` → `persist_email` seam the webhook uses
(see CLAUDE.md: "one ingest seam"), then invokes the compiled graph directly so
the run is awaitable and the final state is capturable.

Output:
    evals/runs/<run_id>/run.jsonl   — one line per record: {id, expected, final_state, messages, error}
    evals/runs/<run_id>/meta.json   — dataset path, limit, timestamp

Langfuse traces are tagged with `metadata.run_id` and `metadata.dataset_id` so
the whole run can be filtered in the UI.

Usage:
    uv run python -m evals.runner --limit 10
    uv run python -m evals.runner --dataset datasets/e2e/dev.jsonl --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage
from sqlmodel import select

# Export .env into os.environ before any SDK (OpenAI, Langfuse) imports it.
# `agent.settings.Settings` reads .env into a pydantic object, not into env vars.
load_dotenv()

from agent.db.engine import async_session_factory, init_db
from agent.db.models import Client
from agent.ingest.persist import persist_email
from agent.ingest.schemas import NormalizedEmail

# Importing the graph triggers `asyncio.run(load_mcp_tools())` at module level
# (see CLAUDE.md gotcha). Must happen before we enter our own asyncio.run().
from agent.graph.graph import graph

DEFAULT_DATASET = Path("datasets/e2e/dev.jsonl")
RUNS_DIR = Path("evals/runs")
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


def _serialize_message(msg: Any) -> dict[str, Any]:
    if isinstance(msg, BaseMessage):
        out: dict[str, Any] = {
            "type": msg.type,
            "content": msg.content,
        }
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            out["tool_calls"] = [
                {"name": tc.get("name"), "args": tc.get("args"), "id": tc.get("id")}
                for tc in tool_calls
            ]
        name = getattr(msg, "name", None)
        if name:
            out["name"] = name
        return out
    return {"type": "unknown", "repr": repr(msg)}


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in state.items():
        if k == "messages":
            out[k] = [_serialize_message(m) for m in (v or [])]
        else:
            out[k] = v
    # email_id may be a UUID
    if "email_id" in out and not isinstance(out["email_id"], str):
        out["email_id"] = str(out["email_id"])
    return out


async def run(dataset_path: Path, limit: int, skip: int = 0, only_id: str | None = None) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    run_path = out_dir / "run.jsonl"

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

    print(f"Running {len(records)} records → {run_path}")

    n_ok = 0
    n_err = 0
    with run_path.open("w") as out_fh:
        for record in records:
            dataset_id = record["id"]
            normalized = _record_to_normalized(record)

            async with async_session_factory() as session:
                client = await _get_or_create_seed_client(session)
                email_row = await persist_email(client, normalized, session)

            initial_state = {
                "email_id": str(email_row.id),
                "from_address": email_row.from_address,
                "subject": email_row.subject,
                "body": email_row.body,
                "messages": [],
            }

            line_out: dict[str, Any] = {
                "id": dataset_id,
                "email_id": str(email_row.id),
                "expected": record.get("expected"),
                "metadata": record.get("metadata"),
            }

            try:
                final_state = await graph.ainvoke(
                    initial_state,
                    config={
                        "metadata": {
                            "run_id": run_id,
                            "dataset_id": dataset_id,
                            "dataset_path": str(dataset_path),
                        },
                        "tags": ["eval", f"run:{run_id}"],
                    },
                )
                line_out["final_state"] = _serialize_state(final_state)
                line_out["error"] = None
                n_ok += 1
                print(f"  [ok]  {dataset_id}")
            except Exception as exc:
                line_out["final_state"] = None
                line_out["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
                n_err += 1
                print(f"  [err] {dataset_id}: {type(exc).__name__}: {exc}")

            out_fh.write(json.dumps(line_out) + "\n")
            out_fh.flush()

    meta = {
        "run_id": run_id,
        "dataset": str(dataset_path),
        "limit": limit,
        "skip": skip,
        "n_records": len(records),
        "n_ok": n_ok,
        "n_err": n_err,
        "started_at": run_id,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\nDone: {n_ok} ok, {n_err} errored. Run dir: {out_dir}")
    return run_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--id", dest="only_id", help="run a single record by id, e.g. e2e-E12")
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.limit, args.skip, args.only_id))


if __name__ == "__main__":
    main()
