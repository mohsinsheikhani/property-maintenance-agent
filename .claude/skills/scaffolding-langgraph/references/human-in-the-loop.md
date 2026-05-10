# Human-in-the-loop with `interrupt()`

`interrupt()` pauses graph execution mid-node, persists state, and surfaces a payload to the caller. The graph is fully serialized to the checkpointer; the process can exit and the run can resume hours or days later from a different worker. Resume by invoking with `Command(resume=value)` and the same `thread_id` — `interrupt()` returns that value and execution continues.

**Hard requirement:** the graph must be compiled with a checkpointer.

## Anatomy

```python
from langgraph.types import Command, interrupt

def review_node(state):
    payload = {
        "kind": "approval",
        "summary": state["plan_summary"],
        "options": ["approve", "reject", "edit"],
    }
    answer = interrupt(payload)   # pauses here on first call
    if answer == "approve":
        return {"status": "approved"}
    if answer == "reject":
        return {"status": "rejected"}
    return {"plan_summary": answer["edited_summary"], "status": "approved"}
```

When the graph hits this node:

```python
result = graph.invoke({"plan_summary": "..."}, config)
# result["__interrupt__"] is a list of pending Interrupts:
#   [Interrupt(value={"kind":"approval", ...}, resumable=True, ns=[...])]
```

Resume:

```python
graph.invoke(Command(resume="approve"), config)
# review_node re-runs from the top; interrupt(...) returns "approve"
```

Important: when a node resumes, it **re-executes from the start** of the node up to the `interrupt()` call. Do not perform side effects before `interrupt()` — they will run twice. Side effects belong *after* the interrupt, or in a separate node.

## Common patterns

### 1. Approve / reject a generated artifact

```python
def approve(state) -> Command[Literal["execute", "rewrite"]]:
    decision = interrupt({"kind": "approve", "draft": state["draft"]})
    return Command(goto="execute" if decision == "yes" else "rewrite")
```

Returning `Command(goto=...)` couples the human's answer directly to routing — no separate conditional edge needed.

### 2. Edit-the-state

```python
def edit_step(state):
    edited = interrupt({"kind": "edit", "current": state["draft"]})
    return {"draft": edited}   # human's edited text replaces the draft
```

### 3. Clarification mid-conversation

```python
def maybe_clarify(state):
    if needs_clarification(state):
        answer = interrupt({"kind": "clarify", "question": "Which account?"})
        return {"clarification": answer}
    return {}
```

### 4. Interrupt inside a tool

`interrupt()` works from inside `@tool`-decorated functions used by `create_agent` or by your own ToolNode. The pause propagates up through the LLM step to the top-level invoke.

```python
from langchain.tools import tool
from langgraph.types import interrupt

@tool
def transfer_funds(amount: float, to: str) -> str:
    """Transfer money. REQUIRES human approval."""
    ok = interrupt({"kind": "confirm_transfer", "amount": amount, "to": to})
    if not ok:
        return "Transfer cancelled by user."
    # ... real call
    return "Transferred."
```

Resume with `Command(resume=True)` or `False`.

### 5. Multi-turn HITL (collect several answers)

Each `interrupt()` is independent. If a node needs two pieces of info, call `interrupt()` twice — but split into two nodes when possible, since the whole node re-runs on resume.

## Inspecting pending interrupts

```python
state = graph.get_state(config)
state.interrupts   # tuple of Interrupt objects on the latest checkpoint
state.next         # ("review_node",) — what's about to run on resume
```

Surface these to your UI to render the right HITL widget.

## Static vs. dynamic interrupts

- **Dynamic (`interrupt()`):** triggered programmatically inside a node. Carries arbitrary payload. The recommended approach.
- **Static (`interrupt_before` / `interrupt_after` on `compile`):** pause unconditionally before/after a named node. No payload. Useful for debugging or always-on approval gates.

```python
graph = builder.compile(checkpointer=cp, interrupt_before=["execute"])
```

Prefer dynamic interrupts; they let you decide *based on state* whether to pause and what to ask.

## Gotchas

- **No checkpointer = `interrupt()` raises.** Always compile with one, even in tests.
- **Side effects before `interrupt()` run twice.** Perform them after, or move them into a downstream node.
- **`Command(resume=...)` value is whatever you pass.** Match its shape to what `interrupt()` returns to the node — agree on a schema.
- **Subgraph interrupts surface at the top level.** A `__interrupt__` from a deeply nested subgraph still appears in the outer `invoke` result.
- **The thread_id must match exactly** when resuming. Mismatches silently start a new thread.
