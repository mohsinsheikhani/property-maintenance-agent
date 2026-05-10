# Control flow: edges, Command, Send, recursion

LangGraph has four ways to route between nodes. Use the most specific one that fits.

## 1. Static edges

```python
builder.add_edge("a", "b")
builder.add_edge(START, "a")
builder.add_edge("b", END)
```

For unconditional sequencing.

## 2. Conditional edges

A function `(state) -> next_node` (or `list[next_node]`). The third arg lists possible destinations so the compiler can validate.

```python
from typing import Literal

def route(state) -> Literal["urgent", "normal", "__end__"]:
    if "urgent" in state["input"]:
        return "urgent"
    return "normal"

builder.add_conditional_edges("triage", route, ["urgent", "normal", END])
```

The destination list can also be a `dict[str, str]` mapping function output to node name — useful when reusing a generic router (e.g. `tools_condition`):

```python
builder.add_conditional_edges("agent", tools_condition, {"tools": "retrieve", END: END})
```

## 3. `Command` returned from a node

```python
from langgraph.types import Command

def plan(state) -> Command[Literal["research", "answer"]]:
    return Command(update={"plan": "..."}, goto="research")
```

Pros: routing decision and state update are co-located. The function's return-type annotation is the destination set.

`Command` fields:
- `update` — partial state dict (subject to reducers).
- `goto` — destination node name (or list for fan-out within the same graph).
- `graph` — `Command.PARENT` to route in the enclosing graph (only one level up).
- `resume` — used by callers when resuming an interrupt; not from inside a node.

## 4. `Send` — dynamic fan-out / map-reduce

`Send(node_name, partial_state)` invokes `node_name` once with that partial state. A conditional edge that returns `list[Send]` spawns N parallel invocations.

```python
from langgraph.types import Send

class State(TypedDict):
    items: list[str]
    results: Annotated[list, operator.add]   # reducer required

def fan_out(state):
    return [Send("worker", {"item": item}) for item in state["items"]]

def worker(state):                # receives {"item": ...}
    return {"results": [process(state["item"])]}

builder.add_conditional_edges("plan", fan_out, ["worker"])
builder.add_edge("worker", "aggregate")
```

Workers run concurrently. Their writes to `results` are merged by the reducer. Use `Send` for:
- Map-reduce (per-document summarization, etc.)
- Per-section writers in a long document
- Parallel research queries with merged results
- Anything shaped like "do X for each Y"

Each `Send` carries its own state — workers see only what you put in the `Send` payload, **not** the full graph state. They write back into the parent state via reducers.

## Mixing routing kinds in one node

A node can return `Command(update=..., goto=...)` and the conditional edge from that node is ignored. A node can return a plain dict and let `add_conditional_edges`/static edges decide. Pick one per node — mixing both is confusing.

## Cycles and the recursion limit

LangGraph counts each super-step toward `recursion_limit` (default **25**). When exceeded, `GraphRecursionError` is raised.

```python
from langgraph.errors import GraphRecursionError

try:
    graph.invoke(inputs, config={"recursion_limit": 100})
except GraphRecursionError:
    ...
```

Bump it for:
- Long ReAct loops (LLM ↔ tools)
- Wide `Send` fan-out followed by per-worker loops
- Iterative refinement until quality threshold

Set it as low as feasible — it's a safety net against infinite loops, not a free knob.

## Conditional edges from `START`

```python
builder.add_conditional_edges(START, router, ["path_a", "path_b", END])
```

Useful for input-driven routing without a dedicated entry node.

## Pitfalls

- **`Send` worker can't read graph state** — only the payload you send. Pre-compute everything the worker needs in the fan-out function.
- **Missing reducer on the fan-in key** — workers' writes overwrite each other.
- **Wide `Send` fan-out hits `recursion_limit`** — N workers count as N+ steps. Raise the limit or batch.
- **Returning `Command` *and* having a static `add_edge` from the node** — the static edge is overridden silently. Don't add one.
- **`Literal` annotation drifting from real `goto` value** — compiler validates at compile time; mismatches raise immediately, but runtime-computed destinations bypass the check. Keep them aligned.
