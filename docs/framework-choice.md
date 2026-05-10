# Framework choice: LangGraph

## The project

This is the AI triage layer for a property maintenance operations platform. The product it sits inside is used by property managers running 200–1,500-unit portfolios, and the pain it removes is the shared maintenance inbox. Tenants email in with leaks, broken ovens, lockouts, noise complaints, rent questions, and scams, and a property manager spends their morning sorting that mess by hand.

The agent reads each incoming email, decides whether it's actually a maintenance request, extracts the structured details, classifies category and urgency, picks a vendor from the client's pre-approved list, and drafts the outbound communication for human approval. When critical information is missing it emails the tenant back to ask, then resumes when the reply arrives. After a job is dispatched it stays attached to the work order and reacts to vendor and tenant replies until the job closes.

## Product decisions already locked in

Several decisions from the customer conversation are fixed and shape the architecture.

Vendor selection is deterministic. The LLM never invents a vendor — it produces a category and an urgency, and the backend queries the client's vendor table to find matches. The system is multi-tenant from day one, with each client having their own vendor list, urgency policy, tone guide, and Gmail connection, but onboarding is manual for the MVP. Nothing the agent produces gets sent automatically; every outbound message goes to a human approval queue first. Integration with existing PM software is out of scope — the agent works as an email-inbox assistant and nothing more for now.

The eval system is what this project is really about. The agent has to be good enough to evaluate, not feature-complete.

## The shape of the work

The agent's job is a branched sequential pipeline with two loops bolted on. The main path is: ingest, extract structured fields, classify category and urgency, decide whether this is even a maintenance request, pick a vendor, draft the outbound messages. The first loop is multi-turn clarification — when there isn't enough information, the agent pauses, sends a question to the tenant, and resumes when the reply comes in. The second loop is long-running tracking — after dispatch the agent stays alive for the lifetime of the work order, waking up on time-based and event-based triggers and deciding what to do next.

This isn't a conversational agent. It's a state machine with explicit branches, deterministic guardrails on tool calls, and two places where it has to wait for an external event before continuing.

## Why LangGraph

LangGraph treats agents as graphs of nodes with explicit shared state and conditional edges between them. That's the right abstraction for the work above, for four reasons.

First, the eight steps map directly onto nodes and edges. The "if maintenance, go to vendor selection, otherwise go to a human queue" decision is a single conditional edge. There's no fight with the framework to express the structure that already exists.

Second, LangGraph has first-class support for pausing the graph mid-execution and resuming later. The `interrupt()` primitive is exactly the multi-turn clarification pattern — the graph stops on a question, the FastAPI webhook receives the tenant's reply hours later, and the same graph picks up where it left off with the new state merged in. No need to invent a state-rehydration mechanism on top of a chat loop.

Third, checkpointing. The long-running tracking phase needs persistence — the graph might be paused for two days while a vendor schedules a visit, and when a webhook fires the system needs to load the exact state and continue. LangGraph's `PostgresSaver` does this directly. Without it that means writing a custom serialization and replay layer, which is real work and an easy place to introduce bugs.

Fourth, and the one that matters most given the goal of this project, explicit nodes make component evals tractable. The eval plan calls for testing each step in isolation with ground-truth upstream state — feeding the classifier the *correct* extracted fields, not whatever extraction produced live, so each component's quality can be measured independently of cascading failures. With LangGraph, a component eval is calling one node function with a constructed state object. With a more implicit orchestration model the same eval would require either elaborate mocking or running the full pipeline and trying to back out which step actually caused the failure.

## Why not OpenAI Agents SDK

Agents SDK is built around a different shape: one or more agents that converse, decide which tool to call next, and hand off control to specialist sub-agents when needed. That model fits open-ended conversational agents and multi-specialist systems where the orchestration itself is an LLM decision.

This orchestration is not an LLM decision. The pipeline order — extract before classify, classify before route, route before vendor pick — is fixed, and the branching logic is deterministic code, not a model judgment. Expressing that in Agents SDK means either chaining agents in a way that hides the structure, or constraining the agent loop tightly enough that almost none of the framework's value is being used.

The other thing Agents SDK doesn't model is long-running, externally-triggered stateful behavior. The agent loop assumes the conversation runs to completion in one pass. Step 8 wakes up days after the original email on a webhook from a vendor SMS or a cron timer, with no live conversation to attach to. Bolting persistence and resume-from-checkpoint onto Agents SDK is fighting the framework. LangGraph treats that as the default case.

There's one tradeoff worth naming honestly. Agents SDK is simpler to get running, and if the agent were a chatbot with tools the LangGraph learning curve would cost a few days for nothing. But the eval system this project builds requires that each step be addressable in isolation, which means explicit structure beats framework magic. LangGraph's structure is the asset, not the cost.

## What this means concretely

FastAPI exposes the webhook that Gmail Pub/Sub calls when a new email arrives. The webhook normalizes the payload and invokes the LangGraph. LangGraph nodes do the per-step work, with OpenAI structured outputs inside the nodes for the actual model calls — framework choice and model SDK choice are independent. Postgres holds the multi-tenant config, the vendor tables, the work order state, and LangGraph's own checkpoints. Celery or RQ handles Step 8's wake-up triggers: a cron job or webhook fires, loads the checkpoint, invokes the graph from the saved state, and the graph decides what to do next. Langfuse traces every node execution and holds the eval datasets and scores.

That stack matches what the customer asked for and gives the eval system the structural hooks it needs.
