# Prebuilts and Functional API

Two ways to skip hand-writing graph topology when the shape is standard.

## `create_react_agent` / `create_agent`

The canonical "LLM-with-tools loop" packaged as a compiled graph. Newer code uses `from langchain.agents import create_agent`; older code uses `from langgraph.prebuilt import create_react_agent`. Both return a compiled graph with the same lifecycle (checkpointer, streaming, interrupts).

```python
from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

@tool
def get_weather(location: str) -> str:
    """Get weather for a location."""
    return f"{location}: 72°F"

agent = create_agent(
    model="anthropic:claude-haiku-4-5-20251001",
    tools=[get_weather],
    prompt="You are a helpful assistant.",
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "s-1"}}
agent.invoke({"messages": [{"role": "user", "content": "weather in NYC?"}]}, config)
```

The compiled agent **is** a graph — embed it as a node in a larger StateGraph, or call it directly. Use it when the loop is "LLM picks tools until it answers." Reach for a hand-written StateGraph when the workflow has a richer shape.

### Multi-agent with prebuilts

Wrap one agent in a `@tool` and call from another:

```python
@tool
def ask_fruit_expert(question: str) -> str:
    """Use for fruit questions."""
    resp = fruit_agent.invoke({"messages": [{"role": "user", "content": question}]})
    return resp["messages"][-1].content

supervisor = create_agent(model=..., tools=[ask_fruit_expert, ask_veggie_expert], ...)
```

Only the outer (top-level) agent should have the checkpointer. Subagents inherit it via the call stack. Configuring two creates duplicate persistence.

## `ToolNode` and `tools_condition`

Drop-in tool execution + routing for hand-written graphs.

```python
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START, END

tool_node = ToolNode(tools=[multiply, add], handle_tool_errors=True)

builder = StateGraph(MessagesState)
builder.add_node("agent", call_model)
builder.add_node("tools", tool_node)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
builder.add_edge("tools", "agent")
graph = builder.compile()
```

`tools_condition` reads the last AI message; routes to `"tools"` if it has tool_calls, else `END`. `handle_tool_errors=True` converts tool exceptions to `ToolMessage` content so the loop continues.

## Functional API: `@entrypoint` and `@task`

Write durable workflows as plain functions when graph topology is overkill. Each `@task` is a checkpointed unit; `@entrypoint` is the top-level workflow.

```python
from langgraph.func import entrypoint, task
from langgraph.checkpoint.memory import InMemorySaver

@task
def call_llm_1(topic: str): return llm.invoke(f"joke about {topic}").content

@task
def call_llm_2(topic: str): return llm.invoke(f"story about {topic}").content

@task
def aggregate(topic, joke, story): return f"{topic}\n{joke}\n{story}"

@entrypoint(checkpointer=InMemorySaver())
def parallel(topic: str):
    j = call_llm_1(topic)
    s = call_llm_2(topic)
    return aggregate(topic, j.result(), s.result()).result()

config = {"configurable": {"thread_id": "abc"}}
parallel.invoke("cats", config)
```

Tasks return futures; `.result()` resolves. Calling tasks in sequence runs them sequentially; calling them and resolving futures later runs them in parallel. The whole workflow is checkpointed at task boundaries — process can crash and resume.

`get_stream_writer()` works inside `@task` for custom stream events. `interrupt()` works inside `@entrypoint` for HITL. Compose Functional API workflows with StateGraphs by wrapping the entrypoint as a node.

### When Functional API beats StateGraph

- Pure pipelines with no state-shape complexity.
- Loops with arbitrary Python control flow that would be awkward as conditional edges.
- Quick prototypes that you'll later promote to a graph if the structure becomes valuable to inspect.

### When StateGraph beats Functional API

- Workflow has named, evaluable nodes you want to inspect / replay individually.
- HITL with multiple interrupt sites.
- Multi-agent supervisor patterns.
- You need the topology to be visible for debugging (`graph.get_graph().draw_mermaid()`).

## Pitfalls

- **Two checkpointers** in a multi-agent stack — only outer `create_agent` keeps one.
- **Mixing `create_agent` versions** — `langgraph.prebuilt.create_react_agent` (older) and `langchain.agents.create_agent` (newer) are similar but not identical. Pick one per project.
- **`@task` results are not awaited automatically** — call `.result()` or you'll return a future.
- **Forgetting `handle_tool_errors=True`** on `ToolNode` — a single tool exception breaks the loop.
