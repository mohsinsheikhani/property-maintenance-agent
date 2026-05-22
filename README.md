# Property Maintenance Triage Agent

Built an AI maintenance operations layer for property portfolios: a triage and classification agent, vendor routing, and job tracking that takes a tenant email from inbox to dispatched work order. It reduces request-to-dispatch time to under 30 minutes and handles 60 to 85% of incoming requests without a human touching them.

The harder and more valuable part is not the agent. It is the eval system that proves the agent works, catches it when it breaks, and blocks bad changes before they ship. That is what this repo is really about.

> **A note on what this is.** This is a public, high level view of a project I built for a customer. The agent, the methodology, and the eval harness are real and runnable. The full customer dataset, the production traces, and the calibrated final judge numbers are not exposed here. Where this version uses a smaller synthetic dataset or a dev-split number instead of the full customer result, I say so plainly rather than dressing it up.

## The problem, in business terms

A property manager running a 500-unit portfolio gets 30 to 50 maintenance emails a day, mixed in with rent questions, lease disputes, scam mail, and noise complaints. Every one of them needs a category, a priority, a vendor, and a reply. Done by hand, the work grows with the portfolio, so a team handling 400 units cannot take on 800 without hiring.

Done badly by AI, it is worse than doing nothing. A missed water-damage flag floods the unit below. A misrouted noise complaint sends a plumber out for nothing. A hallucinated unit number puts a vendor at the wrong door. So the real question is not "can a model triage emails." It is "how do you know it is triaging them correctly, and how do you keep knowing that as the system changes." Most teams answer that with a few demos and a good feeling. This project answers it with numbers.

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
- `datasets/` is the eval data, split by scope and lifecycle.
- `evals/` is the runner, the regression gate, the graders, the component evals, and the error-analysis artifacts. Start with `evals/README.md`.
- `experiments/` is where I try things that might not work, kept off the main pipeline. The DSPy evaluation lives here.
- `scripts/` holds the operational scripts (seed vendors, replay the dataset, export the graph).
- `docs/` holds the architecture and methodology writeups.
