# Cross-thread memory: Store

The checkpointer persists **one thread**. The Store persists data **across threads** — per-user memories, shared knowledge, anything that should outlive a single conversation. Both can be attached to the same compiled graph.

## Anatomy

A `BaseStore` is a key/value store with namespaces:
- **Namespace**: a `tuple[str, ...]` (e.g. `(user_id, "memories")`). Acts like a folder.
- **Key**: a string (use UUIDs).
- **Value**: a JSON-serializable dict.

Optional **semantic search** when configured with an embedding model.

## Backends

| Backend | Import | Use |
|---|---|---|
| `InMemoryStore` | `langgraph.store.memory` | Tests, dev. Lost on exit. |
| `PostgresStore` | `langgraph.store.postgres` | Sync prod. |
| `AsyncPostgresStore` | `langgraph.store.postgres.aio` | Async prod. |

Run `.setup()` (or `await store.setup()`) **once per fresh DB** to create tables.

## Wiring it up

The Store is accessed inside nodes via the `Runtime` parameter — declare a `context_schema` so per-invocation context (like `user_id`) flows through cleanly.

```python
from dataclasses import dataclass
from langgraph.runtime import Runtime
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
import uuid

@dataclass
class Context:
    user_id: str

async def call_model(state: MessagesState, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    ns = (user_id, "memories")

    hits = await runtime.store.asearch(ns, query=state["messages"][-1].content, limit=3)
    info = "\n".join(d.value["data"] for d in hits)

    # store new memory
    await runtime.store.aput(ns, str(uuid.uuid4()), {"data": "User prefers dark mode"})
    ...

DB_URI = "postgresql://..."
async with (
    AsyncPostgresStore.from_conn_string(DB_URI) as store,
    AsyncPostgresSaver.from_conn_string(DB_URI) as cp,
):
    builder = StateGraph(MessagesState, context_schema=Context)
    builder.add_node(call_model)
    builder.add_edge(START, "call_model")
    graph = builder.compile(checkpointer=cp, store=store)

    config = {"configurable": {"thread_id": "1"}}
    await graph.ainvoke(inputs, config, context=Context(user_id="u-42"))
```

Pass `context=` at invocation time. It is **not** state — it doesn't persist across runs and isn't serialized into the checkpoint.

## Core operations

```python
# put
store.put(namespace, key, value)              # value is a dict
await store.aput(namespace, key, value)

# get a single record
item = store.get(namespace, key)              # Item with .value, .key, .created_at, .updated_at

# search (semantic if embeddings configured, else lexical)
hits = store.search(namespace, query="...", limit=10, filter={"category": "x"})

# list keys
items = store.list(namespace, limit=100)

# delete
store.delete(namespace, key)
```

Async variants: `aput`, `aget`, `asearch`, `alist`, `adelete`.

## Namespacing patterns

| Goal | Namespace |
|---|---|
| Per-user memories | `(user_id, "memories")` |
| Per-org shared knowledge | `(org_id, "knowledge")` |
| Per-user, per-conversation summaries | `(user_id, "summaries", conversation_id)` |
| Global system prompts | `("system", "prompts")` |

Always lead with the tenant key (`user_id` / `org_id`) so listing/searching is cheap and access control is straightforward.

## Auth scoping (LangGraph Platform)

When deployed on LangGraph Platform, use the `@auth.on.store` hook to force store access into the caller's namespace:

```python
from langgraph_sdk.auth import Auth, AuthContext
auth = Auth()

@auth.on.store
def scope_store(ctx: AuthContext, value):
    ns = tuple(value["namespace"]) if value.get("namespace") else ()
    if not ns or ns[0] != ctx.user.identity:
        ns = (ctx.user.identity, *ns)
    value["namespace"] = ns
```

Without this, a buggy node could read another user's memories. Apply defense-in-depth even though application code already namespaces by `user_id`.

## Pitfalls

- **Putting per-conversation state in the Store** — that's what the checkpointer is for. Store is for facts that should survive across threads.
- **Forgetting `context_schema=Context`** when compiling — `runtime.context` will be empty.
- **Two `setup()` calls in a hot path** — idempotent but slow. Run once at deploy.
- **Storing non-JSON-serializable values** — fails on write. Encode binary as base64 or store a pointer to object storage.
- **No semantic-search index when `search(query=...)` is called** — falls back to lexical / no results. Configure embeddings at store init when you need semantic recall.
