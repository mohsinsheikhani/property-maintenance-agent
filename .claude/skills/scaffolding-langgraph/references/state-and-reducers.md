# State schemas and reducers

State is the contract between nodes. Get this right and the rest of the graph mostly designs itself.

## TypedDict (default)

```python
from typing import Annotated
from typing_extensions import TypedDict, NotRequired
import operator

class State(TypedDict):
    user_input: str                                      # overwrite (default)
    messages: Annotated[list, add_messages]              # append + dedupe by id
    drafts: Annotated[list[str], operator.add]           # accumulate
    metadata: NotRequired[dict]                          # optional key
```

`NotRequired` (Python 3.11+) marks keys that may be absent from initial input. Without it, the runtime treats every key as required at start.

## Pydantic state schemas

Use `BaseModel` when you want runtime validation and richer types. Inputs are validated; node return values are still merged as dicts.

```python
from pydantic import BaseModel

class Nested(BaseModel):
    value: str

class State(BaseModel):
    text: str
    count: int
    nested: Nested

def node(state: State):
    # state is a validated Pydantic instance
    return {"text": state.text + " ok", "count": state.count + 1}

graph = StateGraph(State).add_node(node).add_edge(START, "node").compile()
graph.invoke(State(text="hi", count=0, nested=Nested(value="x")))
```

Pydantic state pays a serialization cost per super-step. Reach for it when external inputs are untrusted; stick with TypedDict for high-throughput internal graphs.

## `MessagesState`

```python
from langgraph.graph import MessagesState

class State(MessagesState):    # inherits messages: Annotated[list, add_messages]
    summary: str
```

Subclass for any chat-shaped agent. Avoids re-declaring the messages reducer.

## Reducers

A reducer is `(current_value, update) -> new_value`. Defaults to "replace with update". Annotate with `Annotated[T, reducer_fn]`:

| Reducer | Use for | Import |
|---|---|---|
| `add_messages` | Chat history (appends, dedupes by `id`, supports message updates by id) | `langgraph.graph.message` |
| `operator.add` | Lists/strings to concatenate | stdlib |
| `operator.or_` | Dicts to merge | stdlib |
| Custom callable | Sets, max, deep-merge, schema-aware merge | yours |

### Custom reducer

```python
def merge_dicts(current: dict, update: dict) -> dict:
    return {**current, **update}

class State(TypedDict):
    facts: Annotated[dict, merge_dicts]
```

Reducers must be **pure** and **deterministic** — they run after each node and during checkpoint replay.

## Input / output / private schemas

Split the schema to hide internals:

```python
class InputState(TypedDict):
    user_input: str

class OutputState(TypedDict):
    graph_output: str

class OverallState(TypedDict):
    user_input: str
    graph_output: str
    foo: str   # internal-only

class PrivateState(TypedDict):
    bar: str   # local to one segment of the graph

builder = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
```

`invoke` accepts an `InputState` and returns an `OutputState`; nodes can still read/write `OverallState`. Use `PrivateState` as a node's annotated arg type to scope keys to a sub-region.

## Choosing reducers — checklist

- Multiple nodes write the key in parallel? **Reducer required.**
- Key holds chat messages? **`add_messages`.**
- Key is a growing list? **`operator.add`.**
- Key holds a single latest value (status, current step)? **No reducer (overwrite).**
- Key is a dict that nodes contribute fragments to? **Custom merge or `operator.or_`.**

## Pitfalls

- **Forgetting a reducer on a list/dict** — second writer silently overwrites the first.
- **Mutating state in place** inside a node — undefined behavior. Always return a new dict; let the reducer apply it.
- **Using a non-pure reducer** (calls APIs, uses `time.time()`) — breaks replay determinism.
- **Pydantic with non-JSON-serializable fields** — checkpointers can't persist them. Stick to JSON-friendly types or supply a custom serde.
