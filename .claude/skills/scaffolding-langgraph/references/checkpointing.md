# Checkpointing

A checkpointer persists graph state after every super-step, keyed by `thread_id`. It is what enables resume-after-restart, human-in-the-loop, time travel, and per-thread memory.

## Choosing a backend

| Backend | Import | When |
|---|---|---|
| `InMemorySaver` | `langgraph.checkpoint.memory` | Tests, local dev, ephemeral demos. Lost on process exit. |
| `PostgresSaver` | `langgraph.checkpoint.postgres` | Sync prod workloads. Battle-tested. |
| `AsyncPostgresSaver` | `langgraph.checkpoint.postgres.aio` | Async prod workloads (FastAPI, etc.). |
| `SqliteSaver` / `AsyncSqliteSaver` | `langgraph.checkpoint.sqlite[.aio]` | Single-process prod, embedded apps. |

For LangGraph Platform deployments, the platform provides a managed checkpointer — don't pass one when compiling.

## Postgres setup (sync)

```python
from langgraph.checkpoint.postgres import PostgresSaver

DB_URI = "postgresql://user:pw@host:5432/db?sslmode=require"

with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    # checkpointer.setup()   # ONCE per database; creates tables + indexes
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke(inputs, {"configurable": {"thread_id": "t-1"}})
```

`from_conn_string` returns a context manager that owns the underlying connection pool. For long-lived servers, manage the pool yourself:

```python
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

pool = ConnectionPool(DB_URI, max_size=20, kwargs={"autocommit": True, "prepare_threshold": 0})
checkpointer = PostgresSaver(pool)
checkpointer.setup()   # once
graph = builder.compile(checkpointer=checkpointer)
```

## Postgres setup (async)

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
    # await checkpointer.setup()  # once
    graph = builder.compile(checkpointer=checkpointer)
    async for chunk in graph.astream(inputs, config, stream_mode="values"):
        ...
```

For FastAPI, build the pool at app startup, wrap it in `AsyncPostgresSaver(pool)`, and inject the compiled graph as a dependency.

## Threads and config

A `thread_id` is the unit of conversation/run isolation. Pass it through `configurable`:

```python
config = {"configurable": {"thread_id": "user-42:conv-7"}}
```

Use a stable, meaningful key (e.g. `f"{user_id}:{conversation_id}"`) so threads can be reattached. **Never** reuse a thread_id across unrelated logical sessions — replays will surprise you.

## Inspecting threads

```python
snapshot = graph.get_state(config)            # latest StateSnapshot
snapshot.values        # current state dict
snapshot.next          # tuple of nodes scheduled to run next (empty if done)
snapshot.interrupts    # any pending interrupts on this thread
snapshot.config        # config including checkpoint_id

history = list(graph.get_state_history(config))  # newest first
```

Each `StateSnapshot.config` carries a `checkpoint_id`. Pass that config back to `invoke` / `stream` to **fork** from that point:

```python
target = next(s for s in history if s.next == ("write_joke",))
graph.invoke(None, target.config)   # re-runs from before write_joke
```

Forking creates a sibling history; the original is preserved.

## Encryption at rest

```python
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.postgres import PostgresSaver

serde = EncryptedSerializer.from_pycryptodome_aes()  # uses LANGGRAPH_AES_KEY env var
checkpointer = PostgresSaver.from_conn_string(DB_URI, serde=serde)
checkpointer.setup()
```

Set `LANGGRAPH_AES_KEY` to a base64 32-byte key. Rotate by re-serializing — there's no built-in re-encrypt loop.

## Long-running / cross-process resume

The whole point of a durable checkpointer: a worker can crash mid-graph and another worker can `invoke(None, config)` against the same `thread_id` to continue from the last checkpoint. There's nothing to do beyond using the same DB and thread_id.

For HITL pauses lasting hours/days, just send `Command(resume=...)` whenever the human responds — no background job needed; the graph is fully serialized to Postgres in the meantime.

## Pitfalls

- **`.setup()` is idempotent but slow.** Run it as a deploy step, not on every cold start.
- **`from_conn_string` opens its own pool.** Inside a request handler, prefer a shared pool created at startup.
- **The default JSON serializer can't handle every Python object.** Stick to JSON-friendly types in state, or supply a custom serde.
- **`get_state` returns the *latest* checkpoint, even if execution is paused at an interrupt.** Check `snapshot.interrupts` and `snapshot.next` before assuming the run is complete.
