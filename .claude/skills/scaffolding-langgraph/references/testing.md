# Testing LangGraph agents

Explicit state is the testing payoff. A node is just `(state) -> partial_state`, and a checkpointer lets you seed the graph at any point. Lean on these properties — don't write tests that drive the whole graph end-to-end when you only care about one step.

## Layers of test

| Layer | What you assert | How |
|---|---|---|
| Node unit test | A single node's transform is correct | Call the function with a hand-built state dict |
| Edge / routing test | Conditional edge picks the right branch | Call the routing function directly |
| Component test | A slice of the graph (nodes A→B→C) produces expected state | `update_state(as_node=...)` then `invoke(None, ..., interrupt_after=...)` |
| End-to-end | Full happy path | `invoke(inputs, config)` |
| Replay regression | A captured trace still terminates the same way | `invoke(None, captured_checkpoint_config)` |

## Unit-testing a node

```python
def test_summarize_node_returns_summary():
    out = summarize_node({"messages": [HumanMessage("a long thing...")]})
    assert "summary" in out
    assert len(out["summary"]) < 200
```

No graph, no checkpointer, fast. This is the bulk of your test suite.

## Routing function

```python
def test_should_continue_branches_to_tools():
    state = {"messages": [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])]}
    assert should_continue(state) == "tools"
```

## Component test from a checkpoint

Seed the graph as if `node_a` has just finished, then run only `node_b`:

```python
from langgraph.checkpoint.memory import InMemorySaver

def test_node_b_after_node_a():
    g = build_graph().compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    g.update_state(cfg, values={"my_key": "from_a"}, as_node="node_a")
    result = g.invoke(None, cfg, interrupt_after="node_b")
    assert result["my_key"] == "expected_after_b"
```

`as_node="node_a"` writes the checkpoint as if `node_a` produced it, so the next scheduled node is `node_b`. `interrupt_after="node_b"` stops execution before downstream nodes.

## Mocking the LLM

The cleanest approach is to inject the model as a dependency:

```python
def make_graph(model):
    def llm_node(state):
        return {"messages": [model.invoke(state["messages"])]}
    ...

# In tests
from langchain_core.language_models.fake_chat_models import FakeListChatModel
model = FakeListChatModel(responses=["mocked answer"])
graph = make_graph(model).compile()
```

For tool-calling, use `FakeToolCallingChatModel` from `langchain_core.language_models.fake_chat_models` and supply tool-call payloads in order.

## HITL tests

```python
def test_approval_flow():
    g = build_graph().compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "hitl-1"}}

    first = g.invoke({"plan": "p"}, cfg)
    assert "__interrupt__" in first

    final = g.invoke(Command(resume="approve"), cfg)
    assert final["status"] == "approved"
```

Verify both branches (`approve`, `reject`) and any edit-the-state variants.

## Replay regression tests

Capture a checkpoint config from a known-good run, store the value, and assert that resuming from it still produces the same output. Catches regressions caused by changes to downstream nodes.

```python
def test_replay_from_before_summarize():
    g = build_graph().compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "r1"}}
    g.invoke(SEED_INPUTS, cfg)
    history = list(g.get_state_history(cfg))
    pre_summarize = next(s for s in history if s.next == ("summarize",))
    again = g.invoke(None, pre_summarize.config)
    assert again["summary"] == EXPECTED_SUMMARY
```

## Per-node evals

Because nodes are addressable, you can build datasets keyed by node name and run a grader on each node's `(input_state, output_state)` pair. This pairs naturally with the `agent-evals` skill — use it to design the grading rubric and dataset structure, then implement the dataset as one example per node.

Hooks for per-node eval data:

```python
async for mode, chunk in graph.astream(inputs, cfg, stream_mode="updates"):
    # mode == "updates"; chunk is {node_name: partial_state}
    log_for_eval(node_name=next(iter(chunk)), update=chunk)
```

## Pytest conventions

- One thread_id per test (use `uuid.uuid4().hex` or the test name).
- Build a fresh `InMemorySaver` per test — never share across tests.
- Avoid `asyncio.run` in tests; use `pytest-asyncio` and async test functions for `astream` / `ainvoke`.
- Mark long-running real-LLM tests with `@pytest.mark.live` and exclude from default CI.

## Pitfalls

- **Asserting on full state dicts.** Reducers and message ids make equality brittle. Assert on the keys you care about.
- **Reusing `thread_id`.** Old checkpoints leak into new tests and produce phantom replays.
- **Driving end-to-end when a node test would do.** Slow, flaky, and obscures the actual failure point.
- **Mocking by patching internal modules.** Inject the model/tool dependency instead — patches break across LangGraph versions.
