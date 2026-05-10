# Subgraphs and multi-agent composition

A subgraph is a compiled `StateGraph` used as a node inside another graph. Composition is how multi-agent systems (supervisor + specialists, planner + worker, parallel branches) are built in LangGraph.

## Two ways to embed a subgraph

### 1. Add the compiled subgraph as a node (shared schema)

Cleanest when parent and subgraph share the same state shape (or overlapping keys with reducers).

```python
sub = sub_builder.compile()

parent = StateGraph(ParentState)
parent.add_node("sub", sub)
parent.add_edge(START, "sub")
parent.add_edge("sub", END)
```

Any keys present in both schemas are merged via the parent's reducers. Keys only in the subgraph schema stay scoped to the subgraph.

### 2. Wrap the subgraph in a function node (different schemas)

Use when state shapes differ and you need to translate.

```python
def call_sub(parent_state):
    sub_input = {"query": parent_state["user_question"]}
    sub_result = sub.invoke(sub_input)
    return {"answer": sub_result["final_answer"]}

parent.add_node("sub", call_sub)
```

## `Command` with `graph=Command.PARENT`

From inside a subgraph node, route to a node in the parent:

```python
from typing import Literal
from langgraph.types import Command

def hand_off(state) -> Command[Literal["next_in_parent"]]:
    return Command(
        update={"foo": "value"},
        goto="next_in_parent",
        graph=Command.PARENT,
    )
```

The destination must be a node in the immediate parent graph, not a deeper ancestor. State updates apply to the parent — the key must exist in the parent schema (and have a reducer if multiple nodes write it).

## Reducers across boundaries

If parent and subgraph both write the same key, that key **must** have a reducer in the parent schema, otherwise the parent's value will be overwritten by the subgraph's. Example: tracking `foo` as an accumulating string:

```python
class State(TypedDict):
    foo: Annotated[str, operator.add]
```

Now both graphs append safely.

## Streaming from subgraphs

Pass `subgraphs=True` to surface events from inside compiled subgraphs:

```python
async for chunk in graph.astream(inputs, config, stream_mode="updates", subgraphs=True):
    ...
```

Without this flag, only top-level node events are emitted.

## Checkpointing in subgraphs

Compile **subgraphs without a checkpointer** when they're embedded in a parent that has one — the parent's checkpointer is inherited. Setting one on both creates two independent persistence layers and confuses thread state.

For `create_agent` subagents called from tools, the same rule applies: only the outer agent needs a checkpointer.

## Multi-agent supervisor pattern

```python
supervisor = StateGraph(SupervisorState)
supervisor.add_node("planner", planner_node)
supervisor.add_node("researcher", research_subgraph)   # compiled subgraph
supervisor.add_node("writer", writer_subgraph)
supervisor.add_node("reviewer", reviewer_node)

def route(state) -> Literal["researcher", "writer", "reviewer", END]:
    return state["next_specialist"]

supervisor.add_edge(START, "planner")
supervisor.add_conditional_edges("planner", route, ["researcher", "writer", "reviewer", END])
supervisor.add_edge("researcher", "planner")
supervisor.add_edge("writer", "planner")
supervisor.add_edge("reviewer", END)
```

The planner sets `next_specialist` based on the current state; the supervisor routes accordingly. Each specialist is a self-contained, separately testable subgraph.

For richer multi-agent design (supervisor vs. swarm vs. hierarchical), consult the `multi-agent-patterns` skill before implementing.

## Pitfalls

- **Two checkpointers.** Don't compile a subgraph with its own checkpointer if the parent already has one.
- **Missing reducer on a shared key.** Concurrent writes from parent and subgraph collide silently.
- **`Command.PARENT` from too deep.** It only ascends one level. For deeper hops, ascend step by step.
- **Forgetting `subgraphs=True`** when streaming events from inside a subgraph — the UI goes silent during specialist work.
