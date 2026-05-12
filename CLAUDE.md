# Property Maintenance Triage Agent

Eval-first LangGraph agent that triages tenant maintenance emails. The agent is the *system under test*; the eval harness around it is the actual deliverable. See `README.md` for the full project framing and `docs/framework-choice.md` for why LangGraph.

## Commands

```bash
uv sync                                   # install / refresh deps
uv run langgraph dev                      # LangGraph Studio against ./agent/graph/graph.py:graph
uv run fastapi dev agent/main.py          # Gmail Pub/Sub webhook
uv run python -m mcp_server.server        # MCP tool server (stdio)
docker compose up --build                 # MCP server over streamable_http on :8000
uv run python scripts/load_dataset_to_db.py   # replay datasets/e2e/dev.jsonl as if pushed by Gmail
uv run python scripts/seed_vendors.py     # seed vendor table

# Evals (harness not built yet — this is the next chunk of work)
uv run pytest evals/                      # will exist; will gate CI
```

Python 3.14+. Always `uv run …`, never bare `python`. **Never hand-edit `pyproject.toml` or `uv.lock` to add dependencies** — run `uv add <pkg>` (or `uv add --dev <pkg>`) so the lockfile and `pyproject.toml` stay in sync. Same for removals: `uv remove <pkg>`.

## Stack

- **Orchestration:** LangGraph 1.x — one node per pipeline step. Nodes are async pure functions of `EmailState` (`agent/graph/state.py`). Component evals depend on this purity; keep it.
- **Tools:** MCP server (`mcp_server/server.py`, FastMCP) exposes the destructive tools the LLM may call: `create_work_order`, `assign_to_pm_queue`, `archive_email`, `search_vendors`, `dispatch_vendor`. The graph loads them once at import time via `langchain-mcp-adapters` (`agent/graph/tools.py`).
- **DB:** Postgres on **Neon (remote)** — read `DATABASE_URL` from `.env`. There is no local Postgres in `compose.yaml`; only the MCP server is containerized. SQLModel for models (`agent/db/models.py`), async via `asyncpg`.
- **Ingest:** FastAPI webhook for Gmail Pub/Sub, normalized via `NormalizedEmail`, persisted by a single `persist_email(...)` function that both the webhook and the fixture loader call. **Do not bifurcate this seam** — eval and prod must share the same code path from `NormalizedEmail` onwards.
- **Tracing:** Langfuse (`CallbackHandler` is wired into the compiled graph). Every model call should appear in a trace.
- **Models:** OpenAI via `langchain-openai`. Currently `gpt-4o-mini` with `temperature=0` and structured output. Don't switch models or providers without a reason that ends up in `docs/`.

## How the agent is wired

Nine steps in `README.md`; the implemented ones live in `agent/graph/`:

- `pre_filter → archive | extract → classify → route → route_tools → capture_work_order → vendor_llm ⇄ vendor_tools`
- `route` and `vendor_llm` are LLM-with-bound-tools nodes; `route_tools` / `vendor_tools` are `ToolNode`s wrapping MCP tools.
- `capture_work_order` lifts `work_order_id` out of the latest `create_work_order` ToolMessage into state — this is how Step 5 hands off to Step 6.

The graph compile in `agent/graph/graph.py` calls `asyncio.run(load_mcp_tools())` and **raises** if expected tools are missing. **Start the MCP server before importing the graph** (or `langgraph dev` will fail at import). This is deliberate — silent fallback to empty `ToolNode`s produces confusing mid-run errors.

## Eval-first conventions (load-bearing)

This project's whole reason to exist is the eval system. A few rules follow from that and must hold:

- **Nodes stay addressable.** Each graph node must remain a pure function of `EmailState` so component evals can call it directly with constructed state. Don't hide cross-node coupling in module-level singletons beyond the existing LLM-chain caches.
- **One ingest seam.** All paths into the system go through `NormalizedEmail` → `persist_email`. New email sources are new producers; never write a parallel persistence path for tests or fixtures.
- **Datasets are the contract.** Every record in `datasets/**/*.jsonl` follows the `{id, query, expected, metadata}` schema documented in `datasets/README.md`. `metadata.rationale` is required — records without a real "why is this case here" get dropped, not kept.
- **Code-based grader first, LLM judge second.** If a check can be a schema validator, regex, or tool-arg comparison, write it as code. Reserve judges for genuinely subjective calls (urgency, tone, faithfulness), and validate them with TPR/TNR on a held-out set before trusting them. See `plan/my_evals_work.md` for the reasoning.
- **Synthetic data only.** No real tenant emails, ever. Seed data is grounded in public renter-complaint patterns; phone numbers, addresses, and units are fake.

## Code style

The codebase already shows the style — match it. A few things worth saying explicitly:

- Comments explain **why**, not what. Don't add docstrings to obvious functions. Don't narrate the diff.
- Don't add backwards-compat shims, feature flags, or "TODO when X" stubs unless asked. Internal code can change.
- Don't add error handling for paths that can't happen. Trust the framework guarantees (FastAPI validation, Pydantic, SQLModel).
- Prompts live next to the node that uses them (`_SYSTEM_PROMPT` in `agent/graph/nodes.py`). They will move to versioned markdown later; don't pre-emptively restructure.

## Common gotchas

- `asyncio.run(load_mcp_tools())` at module import means **importing `agent.graph.graph` requires the MCP server to be reachable.** Tests that exercise the graph should start the MCP server (or stub the client) in a fixture.
- `langgraph dev` reads `langgraph.json` which points at `./agent/graph/graph.py:graph`. The hot reloader will re-run the module-level MCP load; if the server restarts, restart `langgraph dev`.
- Gmail Pub/Sub retries aggressively — the webhook returns 200 *before* fetching messages, and the actual fetch runs in a `BackgroundTasks` task in the same process. Don't move work into the request path.
- The `(client_id, source, source_message_id)` unique constraint on `emails` is the idempotency key. Both Gmail (duplicate pushes) and the fixture loader (replays of `dev.jsonl`) rely on it.

## Out of scope right now

- Steps 7–9 (Draft, Clarify, Track) — not implemented. Don't scaffold them speculatively.
- Real Gmail OAuth flow for production tenants — the path exists but isn't load-tested.
- Outlook / non-Gmail providers — `NormalizedEmail` will accept them later.
- Photo / attachment handling — deferred until multimodal extraction lands.
- Migrations — using `SQLModel.metadata.create_all()` until the schema stabilizes; Alembic comes in on the first destructive change.

## When in doubt

Read `plan/project_plan.md` for the original scope and `plan/my_evals_work.md` for the eval methodology. The four canonical references for *how* this project thinks about evals are linked in that file (Hamel, Three Gulfs, etc.) — those are the standard, not whatever pattern is convenient.
