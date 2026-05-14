# Property Maintenance Triage Agent

A property maintenance triage agent built eval-first. Tenants email a shared maintenance inbox, the agent reads the email, decides whether the request is even a maintenance request or belongs in a human queue, extracts the structured details, classifies category and urgency, picks a vendor from the client's pre-approved list, and drafts the outbound communication for human approval. When information is missing the agent emails the tenant back to ask, then resumes when the reply arrives. After a job is dispatched the agent stays attached to the work order and reacts to vendor and tenant replies until the job closes.

The interesting part isn't the agent. It's the eval system around it. Most AI products ship with vibes-based eval — a few demos, some happy-path tests, and a hope that the model behaves in production. This project does the opposite. Failure modes get catalogued from real traces before any prompt gets tuned, judges are validated with TPR and TNR on a held-out set before they're trusted, and a CI gate blocks regressions on every change. That discipline is the actual difference between an AI demo and an AI product.

## Results

The numbers land here as each week of the eval work completes. Until then, the slots that matter:

- **Failure modes found by trace reading.** Five to seven named modes with prevalence percentages, each tagged to one of the Three Gulfs (Comprehension, Specification, Generalization).
- **LLM judge calibration.** TPR and TNR per judge on a held-out 30-trace validation set, with misclassified cases analyzed.
- **CI gate.** Pass-rate trend on the golden dataset across pull requests.
- **Cost and latency.** Dollars per triaged ticket and p50/p95/p99 latency per step, on the Pareto frontier across model choices.
- **Production drift.** Rolling override rate from human corrections in the approval queue.

Each of these turns into a section in `docs/` as it lands.

## Why this exists

The business problem is that shared maintenance inboxes don't scale. A property manager running a 500-unit portfolio gets 30 to 50 maintenance emails a day, mixed in with rent questions, lease disputes, scams, and noise complaints. Every email needs a category, a priority, a vendor, and a reply. Done by hand, the labor scales linearly with the portfolio — a manager handling 400 lots can't handle 800 without hiring. Done badly by AI, it creates worse problems than it solves: a missed water-damage flag floods downstairs, a misrouted noise complaint dispatches a plumber for nothing, a hallucinated unit number sends a vendor to the wrong address.

The AI-engineering problem is that the gap between an AI demo and an AI product is almost entirely the eval system. The model can be the same. The prompts can be the same. What separates the two is whether anyone can answer the question *"how do you know it's working?"* with real numbers instead of anecdotes. Most teams still answer that question with anecdotes. This project answers it with numbers.

Property maintenance is a particularly good domain to build that discipline against. The decisions are high-stakes (a missed risk flag costs more than the model does), genuinely subjective in places (urgency varies by jurisdiction, building, and tenant), and structurally varied enough that no single eval technique covers all of it — code-based for extraction grounding, LLM-as-judge for urgency calibration, multi-turn for clarification flows, session-level for long-running job tracking. Every eval pattern an AI engineer needs to know how to ship has a place in this one project.

## How the agent works

Nine steps. Each one is a separate eval surface.

1. **Ingest.** A new email lands in the maintenance inbox. FastAPI receives the Gmail Pub/Sub push, normalizes the payload, and invokes the graph. No model call.
2. **Pre-filter.** Binary check before any structured processing: is this spam, phishing, or completely off-topic? If yes, archive it with a reason and stop — no further model calls, no data extracted. Protects against feeding attacker-controlled text into downstream prompts.
3. **Extract.** Pull structured fields directly from the email text — unit number, location in unit, problem description, duration mentioned, tenant email. Eval question: is each field actually grounded in the source?
4. **Classify.** Map the extracted facts to predefined buckets: category (plumbing, electrical, HVAC, locksmith, general, pest, appliance), urgency (high, medium, low), and risk flags (water damage, fire hazard, security, habitability). None of these values appear in the email — the agent is making a judgment against a documented rubric.
5. **Route.** The email has passed the pre-filter — now decide what kind of legitimate email it is. Maintenance requests continue through Steps 6–9. Lease questions, owner queries, rent payments, and noise complaints each get routed to the correct human queue. Routing is always a tool call: `create_work_order`, `assign_to_pm_queue`, or `archive_email` — all database writes, all auditable. Routing errors are silent and catastrophic: a misrouted noise complaint dispatches a plumber for nothing.
6. **Vendor selection.** Query the client's vendor table by trade, zone, and historical performance. The LLM never invents a vendor; the database call is deterministic.
7. **Draft.** Write three messages — the vendor dispatch, the tenant acknowledgment, and the property manager's internal log. Each is for a different audience and has its own faithfulness and tone constraints.
8. **Clarify.** When critical information is missing, email the tenant back, pause the graph, and resume when the reply arrives with the new information merged in.
9. **Track.** After dispatch, stay attached to the work order. Wake up on time-based and event-based triggers — vendor silent for four hours, tenant replied, scheduled time has passed — and decide what to do next. State persists across days.

Steps 1, 6, and parts of 9 are deterministic code. Everything else is a model call.

The framework choice (LangGraph over OpenAI Agents SDK) and the reasoning behind it are in [`docs/framework-choice.md`](docs/framework-choice.md).

## How the eval system is built

Five layers, each with its own doc in `docs/` as it lands.

**Trace reading and failure taxonomy.** The first 120 traces get hand-labeled. Free-text notes cluster into five to seven named failure modes, each with prevalence, example traces, and which of the Three Gulfs it belongs to. The gulf assignment determines the fix — Comprehension means read more traces, Specification means rewrite the prompt, Generalization means change the architecture.

**Code-based graders.** The default. Schema validation, entity grounding, tool-argument correctness, termination bounds. Roughly 60–70% of useful evaluators in a real production system are code-based, and they run on 100% of traffic synchronously.

**LLM-as-judge graders, validated.** Reserved for genuinely subjective judgments — urgency calibration, risk flag completeness, tone faithfulness. Each judge is iterated on a 30-trace dev set, then measured once on a held-out 30-trace validation set. TPR and TNR get reported separately because agreement is reward-hackable by class imbalance — a judge that always says "pass" gets 90% accuracy on a 10%-failure-rate distribution and is useless. Both TPR and TNR target above 0.85; gaps between dev and validation indicate overfit prompts.

**Component evals versus E2E evals.** Component evals test one step in isolation with ground-truth upstream state — feeding the classifier the *correct* extracted fields, not whatever extraction produced live, so each component's quality can be measured independently of cascading failures. E2E evals run the full pipeline and gate ship decisions. Component evals localize bugs; E2E evals decide whether a change is shippable. Both are needed.

**CI gate and production drift.** A frozen golden dataset of 30 curated traces — happy paths, known-bad-and-caught, edge cases — runs on every pull request, scored by the full grader suite, and compared pairwise to the baseline from `main`. Pull requests fail if any code-based eval regresses, any LLM judge's pass rate drops by more than five percentage points, or the absolute pass rate falls below the floor. In production, the same graders run on a sample of live traffic and rolling pass-rate trends feed a drift dashboard.

## Run it locally

```bash
# Prerequisites: Python 3.14+, Postgres, a Langfuse instance (cloud or self-hosted)
uv sync
cp .env.example .env  # fill in OPENAI_API_KEY, LANGFUSE_*, DATABASE_URL

# Run the FastAPI webhook
uv run fastapi dev main.py

# Fire a test email through the agent
uv run python scripts/send_test_email.py --fixture leak_kitchen_no_unit

# Run the agent against the first 10 records of the E2E dev set
# (MCP server must be up first: `docker compose up --build`)
uv run python -m evals.runner --dataset datasets/e2e/dev.jsonl --limit 10

# Resume with the next 10 records (skip the first 10, process 11–20)
uv run python -m evals.runner --dataset datasets/e2e/dev.jsonl --limit 10 --skip 10
```

Traces appear in Langfuse under the project name set in `.env`, tagged with `run_id` / `dataset_id`. Cumulative eval artifacts live at the `evals/` top level: `evals/labels.csv` (pass/fail labels per trace) and `evals/taxonomy.md` (named failure modes with prevalence, gulf, and grader). The eval suite runs with `uv run pytest evals/`.

## What's real, what's synthetic, what's not built yet

The agent runs against synthetic and scraped tenant emails — generated with diversity prompts (typos, multiple languages, multi-issue, vague, urgent, polite, hostile), pulled from public renter complaint forums, and hand-crafted for known edge cases. It does not run against real customer data, and that's a deliberate choice worth flagging honestly rather than pretending otherwise.

The Gmail OAuth flow and Pub/Sub webhook are wired up but the production push notifications haven't been load-tested. Multi-tenancy is in the schema but onboarding is manual, as agreed with the customer. Step 8's wake-up triggers are sketched in the graph but the production scheduler isn't fully wired yet — that's the next chunk of work.

## Repo map

- `agent/` — the LangGraph application, one node per step, prompts versioned as markdown
- `datasets/` — eval data, split by E2E and component scope, dev/validation/golden lifecycle
- `graders/` — code-based and LLM-judge evaluators, each a pure function of a trace
- `evals/` — eval runner, open-coding scaffold, cumulative `labels.csv` and `taxonomy.md`, pytest grader suite
- `judge_validation/` — TPR/TNR reports per judge
- `scripts/` — operational scripts (generate traces, run evals, promote production traces to the dataset)
- `docs/` — architecture decisions, eval methodology, weekly postmortems
- `plan/` — the curriculum and project plans this work was scoped against
