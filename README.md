# Property Maintenance Triage Agent

Built an AI maintenance operations layer for property portfolios: a triage and classification agent, vendor routing, and job tracking that takes a tenant email from inbox to dispatched work order. It reduces request-to-dispatch time to under 30 minutes and handles 60 to 85% of incoming requests without a human touching them.

The harder and more valuable part is not the agent. It is the eval system that proves the agent works, catches it when it breaks, and blocks bad changes before they ship. That is what this repo is really about.

> **A note on what this is.** This is a public, high level view of a project I built for a customer. The agent, the methodology, and the eval harness are real and runnable. The full customer dataset, the production traces, and the calibrated final judge numbers are not exposed here. Where this version uses a smaller synthetic dataset or a dev-split number instead of the full customer result, I say so plainly rather than dressing it up.

**Tech:** Python 3.14, LangGraph, FastAPI, Postgres (Neon), Langfuse, MCP (FastMCP), OpenAI (`gpt-4o-mini`), LiteLLM (model gateway), DSPy (experiment), pytest, GitHub Actions, Docker. Methodology: Hamel Husain's eval workflow, Three Gulfs failure attribution, code graders + validated LLM judges with TPR/TNR splits, regression CI gate.

**Contact:** [linkedin.com/in/mohsin-sheikhani](https://www.linkedin.com/in/mohsin-sheikhani/)

---

## Headline results

The story this repo tells in numbers. Each one links to the file where the work lives.

- **Lifted the urgency LLM judge from `TPR 90% / TNR 53%` to `TPR 95% / TNR 93%`** by reading every disagreement, finding the judge was grading against a looser rubric than the agent's own rules, and rewriting it to grade against the same rubric. Dev-split numbers, and I say so plainly in the writeup. ([details](evals/README.md#validating-the-urgency-judge))
- **The regression CI gate sits at 87% overall code-grader pass rate** across pre-filter, classify, extract. The lowest single grader, urgency exact-match, sits at 67%. I'm not hiding it. It is the hardest call in the pipeline, and a suite at 100% green would just mean the test cases are too easy. ([details](evals/README.md#regression-gate))
- **Trace reading caught 13 mislabeled records in the dataset.** That was during a DSPy experiment where the optimizer never beat the hand-written prompt. The lesson: "should I use DSPy" is the wrong question. The right one is "do I have a metric and labels", and answering that is the same trace-review work the eval system already does. ([details](experiments/README.md))
- **The CI gate reads its baseline from `main` itself, not the branch under review.** A change cannot quietly move its own goalposts. Code graders block on a 10% per-grader or 5% overall drop. Judges report numbers but never fail a build, because a raw judge rate is too noisy to gate on. ([details](evals/README.md#regression-gate))
- **Open coding before graders, every time.** I read every trace by hand and judged pass/fail by gut before any automated scoring existed. This is the step most teams skip, and it is the step that tells you what is actually broken instead of what you assumed was broken. ([details](evals/README.md#open-coding))
- **Ran a cost and latency bake-off through a LiteLLM gateway, and it caught a runaway loop and a 100x cost blow-up that the pass counts hid.** gpt-4o-mini came out both cheaper and faster than Gemini 3.5 Flash on this workload, but the more useful find was that an empty vendor table, not the model, was sending one model into a vendor-search loop until it hit the recursion limit. ([details](#choosing-a-model-the-cost-and-latency-bake-off))
- **Production outcome on the calibrated customer engagement:** request-to-dispatch under 30 minutes, 60 to 85% of incoming requests handled without a human touching them. The calibrated customer numbers are not in this repo by design. The methodology that produced them is.

---

## Table of contents

1. [The problem, in business terms](#the-problem-in-business-terms)
2. [What it does](#what-it-does)
3. [How I know it works (the eval system)](#how-i-know-it-works-the-eval-system)
4. [Choosing a model: the cost and latency bake-off](#choosing-a-model-the-cost-and-latency-bake-off)
5. [Stack at a glance](#stack-at-a-glance)
6. [Run it locally](#run-it-locally)
7. [What is real and what is not](#what-is-real-and-what-is-not)
8. [Repo map](#repo-map)
9. [What's next](#whats-next)
10. [References](#references)

---

## The problem, in business terms

A property manager running a 500-unit portfolio gets 30 to 50 maintenance emails a day, mixed in with rent questions, lease disputes, scam mail, and noise complaints. Every one of them needs a category, a priority, a vendor, and a reply. Done by hand, the work grows with the portfolio, so a team handling 400 units cannot take on 800 without hiring.

Done badly by AI, it is worse than doing nothing. A missed water-damage flag floods the unit below. A misrouted noise complaint sends a plumber out for nothing. A hallucinated unit number puts a vendor at the wrong door. So the real question is not "can a model triage emails." It is "how do you know it is triaging them correctly, and how do you keep knowing that as the system changes."

## What it does

A tenant emails the maintenance inbox. The agent:

1. Decides whether the email is even a maintenance request, or spam, or something that belongs in a human queue.
2. Pulls out the structured details (unit, location, problem, duration).
3. Classifies the category and urgency, and raises risk flags like water damage or a fire hazard.
4. Routes it: opens a work order, or sends it to the right human queue.
5. Picks a vendor from the client's pre-approved list by trade and zone.
6. Drafts the vendor dispatch, the tenant reply, and the manager's internal note for human approval.
7. When something critical is missing, emails the tenant back, pauses, and resumes when they reply.
8. After dispatch, stays attached to the job and reacts to vendor and tenant replies until it closes.

The high-stakes decisions (urgency, risk flags, routing) are model calls. The decisions that must never be guessed (which vendor, what the database says) are deterministic code. The framework choice and the reasoning behind it are in [`docs/framework-choice.md`](docs/framework-choice.md).

## How I know it works (the eval system)

This is the part worth reading if you care about whether someone can ship reliable AI rather than just demo it. The methodology follows Hamel Husain's work on AI evals. The full walkthrough, with one trace traced through every step, is in [`evals/README.md`](evals/README.md).

**I read the traces before I built any grader.** Run the agent across the dataset, read every trace by hand, judge pass or fail by gut, and write free-text notes about what went wrong. No automated scoring until that is done. This is the step most teams skip, and it is the step that tells you what is actually broken instead of what you assumed was broken.

**I grouped failures into named modes and tagged each to a root cause.** The notes cluster into a small set of failure modes, each with a prevalence percentage and a tag for which "gulf" it belongs to. The tag decides the fix: a comprehension gap means read more traces, a specification gap means rewrite the prompt, a generalization gap means change the architecture. You do not guess at fixes, you diagnose them.

**Code graders first, LLM judges only when the call is subjective.** Most useful checks are plain code: does the extracted unit number actually appear in the email, is the tool call well-formed, did the agent stay inside its bounds. Judges are reserved for genuinely subjective calls like whether an urgency rating is defensible.

**Every judge is validated before it is trusted.** A judge that always says "pass" scores 90% on a dataset that is 10% failures, and is useless. So I measure true positive rate and true negative rate separately. The urgency judge started at TPR 90% / TNR 53%, which meant it was rubber-stamping wrong answers. I traced the disagreements, found the judge was grading against a looser rubric than the agent's own rules, rewrote it to grade against the same rubric, and got it to TPR 95% / TNR 93%. (Those are dev-split numbers, and I say so in the writeup. The fully held-out test number was done on the customer project.)

**A CI gate blocks regressions on every change.** A scoreboard runs on every pull request and compares against the baseline on `main`. If a code grader drops more than 10%, or the overall code rate drops more than 5%, the change fails. The gate reads the baseline from `main` itself, not the branch, so a change cannot quietly move its own goalposts. Judges report their numbers but never fail a build, because a raw judge rate is too noisy to gate on.

The lowest grader in the suite, urgency exact-match, sits at 67%. I am not hiding it. It is the hardest call in the pipeline, and a suite sitting at 100% green would just mean the test cases are too easy.

**The eval system is also what tells you when a tool is not worth adopting.** I tested whether DSPy could replace the hand-written prompts by optimizing against the dataset. On the `extract` node it could not, because the fields that matter are open-ended and have no code grader. On `classify` it could be graded, but the optimizer never beat the lean prompt. The real payoff was reading the traces, which surfaced 13 mislabeled records in the dataset. "Should I use DSPy?" is the wrong question. The right one is "Do I have a metric and labels?", and answering that is the same trace-review work the eval system already does. The full writeup is in [`experiments/README.md`](experiments/README.md).

## Choosing a model: the cost and latency bake-off

Picking a model is not a vibe and it is not a leaderboard ranking. Quality, cost, and latency pull against each other, and the only way to know which one wins for a given workload is to run the whole agent on your own data and measure all three. So I put the agent behind a single LiteLLM gateway, pointed every model at the same OpenAI-compatible endpoint, and ran the full pipeline over the dataset once per model, swapping the model with one environment variable. The gateway also keeps the provider choice reversible, which is the reason teams put a gateway in front of a model in the first place.

The headline number is **$ per pass**, the expected cost to get one correct triage. For an async email workflow latency is a guardrail, not a ranking axis. Nobody is watching a spinner, so a slow but cheap model can still win. p95 and p99 latency earn their place here by catching a model that loops or runs away on tool calls, not by shaving milliseconds off a reply a human reads an hour later.

| Model | Pass rate | p50 latency | p95 latency | p99 latency | Mean cost/trace | p95 cost/trace | $ per pass | Total run cost |
|---|---|---|---|---|---|---|---|---|
| `gpt-4o-mini` | 94% (97/103) | 14.8s | 18.5s | 24.5s | $0.00071 | $0.00090 | $0.00075 | ~$0.078 |
| `gemini-3.5-flash` | 95% (98/103) | 19.9s | 29.2s | 29.9s | $0.00974 | $0.01345 | $0.01024 | $0.224 |

Pass rate is the share of records the agent triaged correctly, and $ per pass is just mean cost divided by that rate, the money you expect to spend to get one correct triage. That last column is the whole point of the table. gpt-4o-mini is both cheaper and faster, and even giving gemini-3.5-flash a generous pass rate it still lands at roughly 15x the cost per correct answer, so it would need a real quality lead to earn its place.

The cost and latency numbers all come straight from Langfuse, read per trace off the runs the agent actually recorded. They are means per trace, not per record: a record that pauses to ask a tenant something and then resumes emits more than one trace, so the gpt-4o-mini run averages over 110 traces rather than 103.

Two things this bake-off caught that a public leaderboard never would:

- **A runaway loop that looked like a model problem and was not one.** Gemini was spinning the vendor-selection step over and over and burning real money on tool-call tokens. The cause was an empty vendor table in the dev database, not the model. With no vendors to return, the agent kept searching, never had anyone to dispatch, and looped until it hit the recursion limit. gpt-4o-mini hid the same bug by giving up quietly instead of looping, so its run looked clean. Seeding the table fixed both. The lesson is the one the rest of this repo keeps making: read what actually happened, do not trust the ok-versus-error count.
- **A reasoning-mode default that quietly cost about 100x.** Gemini 3.5 Flash ships with thinking turned on. Those hidden reasoning tokens are billed like output, and on a tool-calling agent they ran the cost up roughly a hundredfold before I turned thinking off to match gpt-4o-mini, which does not reason at all. An honest, apples-to-apples bake-off means matching that setting across the models, not accepting whatever each vendor ships as the default.

The takeaway for this workload is that gpt-4o-mini is both cheaper and faster, and Gemini 3.5 Flash would need a clear quality edge to justify roughly 15x the cost per trace, which is exactly the call the quality graders exist to settle. If I wanted a cheap Google challenger on the shortlist, the one to test is Gemini 2.5 Flash-Lite, which is priced to actually compete.

## Stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph 1.x | One node per pipeline step, explicit shared state, `interrupt()` for tenant clarifications, Postgres checkpointing for long-running jobs. Component evals depend on nodes being pure functions of `EmailState`, which LangGraph enforces naturally. |
| Tools | MCP server (FastMCP) | The destructive tools the LLM may call (`create_work_order`, `dispatch_vendor`, etc.) live behind MCP and are loaded once at graph import. Tool layer is swappable without touching the graph. |
| Database | Postgres on Neon | Multi-tenant config, vendor tables, work order state, and LangGraph checkpoints. SQLModel + asyncpg. |
| Ingest | FastAPI webhook (Gmail Pub/Sub) | Single seam from inbound mail to `NormalizedEmail` to `persist_email`. Eval and prod share the same code path from that seam onwards. |
| Tracing | Langfuse | Every node and every model call appears in a trace. The eval workflow leans on traces, not print debugging. |
| Models | OpenAI `gpt-4o-mini`, `temperature=0`, structured output | Cheap, deterministic. Pinned to `gpt-4o-2024-08-06` for the urgency judge so verdicts stay stable across runs. |
| Eval harness | Custom runner + code graders + validated judges + GitHub Actions gate | Dataset schema, validation splits, baseline-from-`main`, and report-only judge deltas are described in `evals/README.md`. |

## Run it locally

```bash
# Prerequisites: Python 3.14+, Postgres, a Langfuse instance
uv sync
cp .env.example .env  # fill in OPENAI_API_KEY, LANGFUSE_*, DATABASE_URL

# Run the FastAPI webhook
uv run fastapi dev agent/main.py

# Run the agent over the first 10 records of the dev set
# (start the MCP server first: docker compose up --build)
uv run python -m evals.runner --dataset datasets/e2e/dev.jsonl --limit 10

# Score a component in isolation
uv run python -m evals.components.classify_eval --id e2e-E12
```

Traces land in Langfuse. Eval artifacts live under `evals/error_analysis/`, grouped by review round: per-trace pass/fail labels, the named failure taxonomy, and the fix-versus-eval decisions. There is also a local trace review UI under `evals/review/` for hand-labeling runs the way the read-the-traces step needs.

## What is real and what is not

The agent runs on synthetic and publicly-sourced tenant emails, generated with diversity in mind (typos, multiple languages, multi-issue, vague, urgent, polite, hostile) and grounded in public renter-complaint patterns. Phone numbers, addresses, and units are fake. It does not run on real tenant data, by design.

Some pieces are wired but not production-hardened: the Gmail OAuth and Pub/Sub path works but has not been load-tested, and the long-running job-tracking triggers are sketched in the graph but the production scheduler is not fully wired. The eval methodology, the graders, the judge validation, and the CI gate are the parts that are fully built out, because they are the point.

## Repo map

- `agent/` is the LangGraph application, one node per step, prompts versioned as markdown.
- `datasets/` is the eval data, split by scope and lifecycle. See [`datasets/README.md`](datasets/README.md) for the record schema and the category counts.
- `evals/` is the runner, the regression gate, the graders, the component evals, and the error-analysis artifacts. Start with [`evals/README.md`](evals/README.md).
- `experiments/` is where I try things that might not work, kept off the main pipeline. The DSPy evaluation lives here. See [`experiments/README.md`](experiments/README.md).
- `scripts/` holds the operational scripts (seed vendors, replay the dataset, export the graph).
- `docs/` holds the architecture and methodology writeups.

## What's next

In rough order of value if I kept building this out:

1. **Carve a held-out test split for the urgency judge.** The 95 / 93 numbers are dev-split. A clean held-out measurement is the next honest move on this repo. (The customer project has that split. This one does not, yet.)
2. **Wire Steps 7 to 9 end to end.** The graph has the shape for clarify and long-running tracking, but the production scheduler and the multi-turn user simulator are not built. Until they are, those flows can be evaluated component-by-component but not end to end.
3. **Round 3 of error analysis.** Two rounds of trace review are checked in. The third runs against the agent after the most recent prompt fixes to confirm the failure modes actually died.
4. **Promote a real held-out golden set.** The current golden set is hand-curated. The next step is growing it from production failures, the way the methodology calls for, once there is a production stream to draw from.

---

## References

The four-step workflow (open coding, axial coding, gulf attribution, fix vs evals) and the methodology behind it come from Hamel Husain's writing on AI Evals. The related Three Gulfs framing (Shreya Shankar, David Okpare) builds on the same foundation.

- Hamel Husain, [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/)
- Hamel Husain, [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- David Okpare, [A Primer to Evals](https://www.davidokpare.com/blog/a-primer-to-evals)
- Shreya Shankar and Hamel Husain, [AI Evals for Engineers and PMs](https://maven.com/parlance-labs/evals) (Maven cohort)
- Hamel Husain, [Evals for AI Engineers](https://www.oreilly.com/library/view/evals-for-ai/9798341660717/) (O'Reilly)

---

Built by Mohsin Sheikhani. If anything here is interesting and you'd like to talk, [linkedin.com/in/mohsin-sheikhani](https://www.linkedin.com/in/mohsin-sheikhani/).
