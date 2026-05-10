# Deployment and observability

LangGraph runs three ways: as library code in your own server, on **LangGraph Platform** (managed), or self-hosted via the LangGraph server image. All three are driven by the same `langgraph.json`.

## `langgraph.json`

The project manifest. At minimum:

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./src/agent.py:agent"
  },
  "env": ".env"
}
```

Fields:
- `dependencies` — list of pip-installable items. `"."` installs the local project; you can also list packages or path specs (`"./your_package"`, `"langchain_openai"`).
- `graphs` — map from `assistant_id` to `path/to/file.py:variable`. The variable must be a **compiled** graph (`builder.compile(...)`).
- `env` — path to a dotenv file or a dict; values become environment variables at runtime.
- `python_version` (optional) — pin the runtime.
- `dockerfile_lines` (optional) — extra `RUN`/`COPY` lines for `langgraph build`.

Multiple graphs:

```json
{
  "graphs": {
    "support": "./src/agents/support.py:graph",
    "billing": "./src/agents/billing.py:graph"
  }
}
```

## Local dev — `langgraph dev`

```bash
pip install "langgraph-cli[inmem]"
langgraph dev
```

Spins up an in-memory server with checkpointer + store, hot-reload, and an OpenAPI UI. Use this for fast iteration; do **not** use the in-memory backend in prod (lost on restart).

## Build — `langgraph build`

Generates a Dockerfile and image:

```bash
langgraph build -t my-agent:latest
docker run -p 8000:8000 --env-file .env my-agent:latest
```

The image exposes `/runs`, `/threads`, `/runs/stream`, `/store`, etc. Calling pattern:

```bash
curl -s -X POST $URL/runs/stream \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $LANGSMITH_API_KEY" \
  -d '{"assistant_id":"agent","input":{"messages":[{"role":"human","content":"hi"}]},"stream_mode":"updates"}'
```

`assistant_id` is the key from `langgraph.json#graphs`.

## LangGraph Platform vs self-host

| Capability | Platform | Self-host |
|---|---|---|
| Managed Postgres checkpointer + store | Built-in | Bring your own |
| Scheduling / cron runs | Built-in | Roll your own |
| Auth hooks (`@auth.on.*`) | Built-in | Available, you wire it |
| Auto-scaling | Built-in | K8s / Fargate / etc. |
| `/runs`, `/threads` REST API | Built-in | Built-in (same server) |
| Cost | Per-run pricing | Infra cost |

Choose Platform for time-to-prod and HITL/scheduling out of the box. Choose self-host for VPC isolation, custom auth/middleware, or unusual deployment topologies.

## Auth on Platform

```python
from langgraph_sdk.auth import Auth
auth = Auth()

@auth.authenticate
async def authenticate(authorization: str | None) -> dict:
    user = verify_jwt(authorization)
    return {"identity": user.id, "permissions": user.scopes}

@auth.on.threads.create
async def threads_create(ctx, value):
    value["metadata"] = {**value.get("metadata", {}), "owner": ctx.user.identity}
```

Reference auth file in `langgraph.json`:

```json
{ "auth": { "path": "./src/auth.py:auth" } }
```

Patterns: `@auth.on.threads.*`, `@auth.on.runs.*`, `@auth.on.store`, `@auth.on.assistants.*`.

## Observability — LangSmith

Free tracing of every node, edge, and LLM call. Set env vars:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=my-agent   # optional
```

Add per-run tags and metadata:

```python
graph.invoke(
    inputs,
    config={
        "configurable": {"thread_id": "t1"},
        "tags": ["prod", "v1.2"],
        "metadata": {"user_id": "u-42", "feature": "billing"},
    },
)
```

Tags filter traces; metadata is searchable. Use `metadata` for stable IDs (user, session, feature flag) and `tags` for environments and versions.

## Production checklist

- [ ] Async checkpointer + store wired with a single shared connection pool.
- [ ] `setup()` run at deploy time, not per request.
- [ ] LangSmith env vars set.
- [ ] `recursion_limit` chosen explicitly (not the default 25 if you fan-out / loop).
- [ ] `RetryPolicy` on every node that hits an external service.
- [ ] `EncryptedSerializer` if state contains PII.
- [ ] Auth hook scopes store namespaces to caller identity.
- [ ] `langgraph.json` committed; `langgraph build` reproducible from clean checkout.
- [ ] Per-tenant `thread_id` scheme that can never collide across users.
- [ ] Tags/metadata on every invocation for traceability.

## Pitfalls

- **In-memory checkpointer in prod** — silently drops state on restart.
- **Multiple workers without shared Postgres** — threads scattered across worker memory.
- **`langgraph build` from a dirty workspace** — version drift between local dev and image.
- **Unscoped store namespaces** — one bug leaks data across users.
- **Forgetting `assistant_id`** in API calls — request 404s with a confusing message.
