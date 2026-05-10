# Runtime policies: retry, cache, timeout, durability, errors

Production knobs you set per-node or per-invocation.

## Per-node policies on `add_node`

```python
from langgraph.types import RetryPolicy, CachePolicy, TimeoutPolicy

builder.add_node(
    "call_model",
    call_model,
    retry_policy=RetryPolicy(max_attempts=3),
    cache_policy=CachePolicy(ttl=120),
    timeout=TimeoutPolicy(idle_timeout=30),
)
```

All three are optional; combine as needed.

### `RetryPolicy`

Retries on exception. Common shapes:

```python
import sqlite3
from langgraph.types import RetryPolicy

# Retry only on a specific exception
RetryPolicy(retry_on=sqlite3.OperationalError)

# Bound attempts
RetryPolicy(max_attempts=5)

# Combine
RetryPolicy(max_attempts=5, retry_on=(TimeoutError, ConnectionError))
```

Attempt-aware fallbacks (langgraph >= 1.1.5):

```python
from langgraph.runtime import Runtime

def my_node(state, runtime: Runtime):
    if runtime.execution_info.node_attempt > 1:
        return {"result": call_fallback_api()}
    return {"result": call_primary_api()}

builder.add_node("my_node", my_node, retry_policy=RetryPolicy(max_attempts=3))
```

### `CachePolicy`

```python
from langgraph.types import CachePolicy
builder.add_node("expensive", expensive_node, cache_policy=CachePolicy(ttl=120))
```

Caches the node's output keyed by its input state for `ttl` seconds. Useful for deterministic, expensive nodes (deep retrieval, structured-output LLM calls). Don't cache nodes with side effects — replays will skip them.

### `TimeoutPolicy`

`TimeoutPolicy(idle_timeout=...)` cancels the node after `idle_timeout` seconds of no progress. Combine with `RetryPolicy` for "try, give up, retry" semantics.

## Durability modes

Set on `invoke` / `stream`:

```python
graph.invoke(inputs, config, durability="async")   # default
```

| Mode | Persistence | Performance | Use |
|---|---|---|---|
| `exit` | Only at workflow end / error / interrupt | Best | Fast batch jobs, no mid-run recovery needed |
| `async` (default) | Background, between steps | Good | Most production agents |
| `sync` | Block until checkpoint written | Worst | Compliance / financial workloads where every step must be durable |

Pick `async` unless you have a reason. Switch to `sync` only for steps that must survive an immediate crash.

## `recursion_limit`

```python
graph.invoke(inputs, config={"recursion_limit": 100})
```

Defaults to **25** super-steps. Each node execution counts as one step; `Send` fan-out counts as one step per worker plus the aggregation step. Bump for ReAct loops, fan-out, iterative refinement.

```python
from langgraph.errors import GraphRecursionError
try:
    graph.invoke(inputs, config={"recursion_limit": 4})
except GraphRecursionError:
    ...
```

Treat it as a safety net, not a tunable. If a graph routinely needs hundreds of steps, the topology is probably wrong (split into subgraphs, batch with `Send`, or use a Functional API loop).

## Runtime context

Pass per-invocation context (user_id, model choice, feature flags) without polluting state:

```python
@dataclass
class Context:
    user_id: str
    llm: str = "anthropic"

graph = StateGraph(State, context_schema=Context).compile()
graph.invoke(inputs, config={"recursion_limit": 50}, context=Context(user_id="u1", llm="anthropic"))
```

Inside a node:

```python
def node(state, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    runtime.store           # the configured store, if any
    runtime.execution_info  # node_attempt, etc.
```

## Async config propagation

In Python <3.11, callbacks (LangSmith tracing, streaming) require manual config propagation. Accept `config` as the second arg and pass it through to `ainvoke`:

```python
async def call_model(state, config):
    return {"messages": [await model.ainvoke(state["messages"], config)]}
```

Python 3.11+ propagates automatically.

## Error handling

| Error | Source | Action |
|---|---|---|
| `GraphRecursionError` | `langgraph.errors` | Raise `recursion_limit` or fix topology |
| Tool exceptions | inside a tool | Use `ToolNode(handle_tool_errors=True)` to convert to `ToolMessage` |
| Reducer raises | bad state shape | Fix the state schema or the node return value |
| Checkpointer write fails | DB issue | Surface to caller; the run is **not** durable |
| Interrupt during a non-durable run | missing checkpointer | Compile with one |

Wrap top-level invokes with try/except for `GraphRecursionError` and DB errors. Inside nodes, prefer letting the framework retry (`RetryPolicy`) over hand-rolled try/except — retries integrate with checkpointing and tracing.

## Concurrency hygiene

- Use the **async** variants (`ainvoke`, `astream`, `AsyncPostgresSaver`, `AsyncPostgresStore`) end-to-end. Mixing sync and async causes blocking and weird stack traces.
- Reuse a single connection pool for the checkpointer and store; create it at app startup.
- For high-throughput servers, set `prepare_threshold=0` on `psycopg` connections (LangGraph's recommendation) to avoid wasted plan caches under bursty traffic.

## Pitfalls

- **Caching a node with side effects** — a re-invocation will silently skip the side effect.
- **Retrying a node with side effects on transient errors** — same issue. Make nodes idempotent or split side effects into a dedicated downstream node that runs once.
- **`durability="exit"` with HITL** — interrupts force a flush regardless, but mid-run crashes lose work. Stay on `async` for HITL workflows.
- **Bumping `recursion_limit` to silence a runaway loop** — find the real cycle (usually a stuck conditional edge or LLM that won't stop calling tools).
