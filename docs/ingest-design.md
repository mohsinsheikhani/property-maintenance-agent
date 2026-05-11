# Ingest layer design

## What ingest has to do

Ingest takes "a new email exists" as input and produces a normalized, persisted email row in Postgres with enough metadata that the rest of the agent pipeline can pick it up and start working. It does not call the model, does not classify, does not route. It receives, normalizes, and records.

This is Step 1 of the nine-step pipeline in `plan/project_plan.md`. Everything from Step 2 (pre-filter) onwards reads from the `emails` table; ingest is what fills that table.

## The dual-mode reality

The ingest layer serves two callers:

1. **Production.** Gmail Pub/Sub pushes a notification to a FastAPI webhook when a new email arrives in a watched inbox.
2. **Offline / eval mode.** A dataset loader replays records from `datasets/e2e/dev.jsonl` as if Gmail had just pushed them.

Both paths converge on the same `persist_email(...)` function. That is the most important design decision in this layer. If the production webhook and the fixture loader take different code paths to get an email into the DB, the eval dataset stops exercising the real pipeline — graders pass on fixtures and fail in production, or vice versa, and nobody catches it until something breaks live. One persist function, two callers, eval and production identical from that point on.

This is the same logic the appendix gives for component evals: the seam between "data arrives" and "agent runs" has to be the same seam in test and in production, otherwise the test is testing the wrong thing.

## The Gmail Pub/Sub reality

The Gmail push notification does not contain the email body. It contains a `historyId` — a version number for the mailbox. To get the actual email, the handler has to:

1. Receive the push and return 200 fast (Pub/Sub retries aggressively on slow responses).
2. Look up the client by the watched inbox address in the push payload.
3. Call `users.history.list(startHistoryId=last_seen_history_id)` to find which message IDs are new since the last push.
4. Call `users.messages.get(id=...)` for each new message.
5. Normalize and persist (via the shared function).

Steps 3–5 cannot block the 200. The webhook handler enqueues a "fetch and persist" job, returns 200, and a background task does the Gmail API calls. FastAPI's `BackgroundTasks` is the chosen mechanism — work runs in the same process after the response has been flushed. Good enough until volume justifies a durable worker.

For offline mode, none of this matters. The JSONL record already contains `from`, `subject`, `body`, so persistence is direct.

## Postgres schema

Two tables to start. Everything else (`work_orders`, `pm_queue`, `langgraph_checkpoints`, `processing_runs`) gets added later as the pipeline grows. Ingest only needs these:

```
clients
  id                uuid pk
  name              text
  gmail_address     text          -- the watched inbox
  gmail_history_id  bigint        -- last seen Pub/Sub history pointer
  oauth_tokens      jsonb         -- encrypted later; null in offline mode
  vendor_table      jsonb         -- pre-loaded vendor list for this client
  urgency_policy    jsonb
  tone_guide        text
  created_at        timestamptz default now()

emails
  id                uuid pk
  client_id         uuid fk → clients(id)
  source            text          -- 'gmail' | 'fixture'
  source_message_id text          -- Gmail message ID or fixture record ID (e.g. 'e2e-T01')
  from_address      text
  subject           text
  body              text
  raw_payload       jsonb         -- the original payload for debugging / audit
  received_at       timestamptz
  ingested_at       timestamptz default now()
  status            text          -- 'pending' | 'processing' | 'done' | 'failed'

  unique (client_id, source, source_message_id)
```

Two notes on this.

**`status` is the queue.** A separate worker (eventually the LangGraph runner) polls `WHERE status = 'pending'`, sets it to `processing`, and proceeds. Postgres handles this fine at the volume a property maintenance inbox has — single digits of emails per minute at the absolute peak. Pulling in Redis or Celery here would be premature.

**The unique constraint is the idempotency key.** Gmail Pub/Sub will duplicate notifications. The same email arriving twice must INSERT once and no-op the second time. The unique constraint on `(client_id, source, source_message_id)` is what makes the webhook safe to call repeatedly. Offline-mode fixtures get the same protection — replaying `dev.jsonl` twice doesn't double-ingest.

## FastAPI app structure

Mirroring the `agent/` skeleton from `plan/week1_appendix.md`:

```
agent/
├── __init__.py
├── main.py                    # FastAPI app, mounts routers
├── settings.py                # Pydantic Settings — env vars (DATABASE_URL, GMAIL_*, etc.)
├── db/
│   ├── __init__.py
│   ├── engine.py              # async engine + get_session dependency
│   ├── models.py              # SQLModel: Client, Email
│   └── migrations/            # Alembic — added once schema stabilizes
├── ingest/
│   ├── __init__.py
│   ├── routes.py              # POST /webhooks/gmail
│   ├── schemas.py             # Pydantic: GmailPushPayload, NormalizedEmail
│   ├── gmail_client.py        # Gmail API wrapper (history.list, messages.get)
│   ├── normalize.py           # Gmail message dict → NormalizedEmail
│   └── persist.py             # The shared persist function
└── prompts/                   # later
```

Plus a script at `scripts/load_dataset_to_db.py` that reads `datasets/e2e/dev.jsonl`, builds a `NormalizedEmail` from each record, and calls `persist.persist_email(...)` — the same function the webhook calls. That script is what lets eval runs work without a real Gmail connection.

## Request and response shapes

Two Pydantic models worth declaring up front because they are the contract:

- **`GmailPushPayload`** — exactly what Gmail Pub/Sub sends. Opaque base64 message blob, decoded inside the handler.
- **`NormalizedEmail`** — the canonical "an email" shape. `from`, `subject`, `body`, `received_at`, `source`, `source_message_id`.

`NormalizedEmail` is the seam. Everything upstream (Gmail webhook, fixture loader, hypothetical Outlook integration later) produces a `NormalizedEmail`. Everything downstream (`persist_email`, eventually the agent graph) consumes one. Adding a new email source is a new producer, not a rewrite of persistence.

## The webhook handler flow

```
POST /webhooks/gmail
  1. validate Pub/Sub verification token (header)
  2. decode the base64 message blob from the push payload
  3. extract email_address and history_id
  4. find client by gmail_address
  5. background_tasks.add_task(fetch_and_persist, client, history_id)
  6. return 200 immediately

fetch_and_persist(client, history_id):
  1. call Gmail history.list since client.gmail_history_id
  2. for each new message_id:
       - fetch via Gmail messages.get
       - normalize to NormalizedEmail
       - call persist_email(client, normalized_email)
  3. update client.gmail_history_id = history_id
```

The 200 returns in milliseconds. Gmail is happy. The actual work happens after the response has been flushed.

## Settings and config

Pydantic `BaseSettings` reading from `.env`. Values ingest needs:

- `DATABASE_URL` — Postgres connection string
- `GMAIL_PUBSUB_VERIFICATION_TOKEN` — to validate incoming pushes
- `GMAIL_OAUTH_CLIENT_ID` / `GMAIL_OAUTH_CLIENT_SECRET` — for the API calls
- `LANGFUSE_*` — present at this layer because trace instrumentation should wrap `persist_email` from day one. Langfuse traces are the trace object the graders consume, per the appendix.

Per-client OAuth refresh tokens live in `clients.oauth_tokens`, not in env. Env is for app-level credentials only.

## Locked-in decisions

- **SQLModel over plain SQLAlchemy + Pydantic.** One class definition covers both the DB table and the API schema. The FastAPI ecosystem treats this as the default; deviating would cost ergonomics without buying anything for an MVP at this scale.
- **FastAPI `BackgroundTasks` over Celery / RQ.** In-process, dies if the worker restarts mid-fetch. Fine for property maintenance volume and offline eval work. The swap to a durable worker later is a local change (`background_tasks.add_task(fn, ...)` becomes "insert into `jobs` table; separate worker polls"), not an architectural rewrite.
- **Postgres `status` column over a real queue (Redis / RabbitMQ).** Same volume argument. Postgres handles single-digit emails-per-minute polling without breaking a sweat.
- **`agent/` as the single top-level for the system under test.** Matches the appendix and the eval system's assumptions. Splitting into `app/` and `agent/` adds an import boundary with no real concern split underneath.

## Decisions still open

- **Alembic migrations vs `SQLModel.metadata.create_all()` for the first weeks.** Migrations are right long-term; `create_all()` is faster on day one while the schema is in flux. Default plan: start with `create_all()`, add Alembic the first time a destructive schema change is needed.
- **Encryption-at-rest for `clients.oauth_tokens`.** Plain `jsonb` is fine for offline development. Before any real customer's tokens land in the table, this column needs to be encrypted (column-level via `pgcrypto`, or app-level with a KMS key). Tracked as a TODO on the schema, not a blocker for ingest itself.

## Out of scope for the ingest layer

- **The agent graph.** Ingest stops at "row in `emails` with `status='pending'`". A separate `agent/graph/` module (LangGraph) picks up pending rows. Keeping these separate lets ingest ship and be tested independently of the model layer.
- **Outlook / Microsoft Graph.** The `NormalizedEmail` shape will accept it later; not in the MVP.
- **Multi-tenant onboarding UX.** The customer confirmed manual onboarding. A `clients` row is inserted by hand or by a seed script — no signup flow, no admin dashboard.
- **Photo and attachment handling.** Out of scope until multimodal extraction is wired up in the agent layer.
