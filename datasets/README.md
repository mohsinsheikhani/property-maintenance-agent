# Datasets

Eval data for the property maintenance triage agent, organized per the structure in [`plan/appendix.md`](../plan/appendix.md). Two scopes — E2E (full pipeline) and components (single step in isolation). Local JSONL is the source of truth; git diffs are the version history.

## Layout

```
datasets/
├── e2e/
│   ├── dev.jsonl              # 103 cases — used during judge iteration
│   ├── validation.jsonl       # Held out, only touched at validation time (not yet built)
│   ├── golden_v1.jsonl        # Frozen CI regression suite (not yet built)
│   └── production_samples/    # Sampled "production" traces (not yet built)
├── components/
│   ├── pre_filter.jsonl       # (email, expected_action) for spam/phishing detection (not yet built)
│   ├── extraction.jsonl       # (email, expected_fields) for the extraction step (not yet built)
│   ├── classification.jsonl   # (extracted_fields, expected_buckets) — note: takes ground-truth upstream input
│   ├── routing.jsonl          # (email, classification, expected_tool_call) (not yet built)
│   └── vendor_selection.jsonl # (classification, vendor_table, expected_vendor_id) (not yet built)
└── README.md                  # This file
```

The component datasets feed ground-truth upstream state per the "conditional eval scoring" rule in the appendix — the classification dataset uses *correct* extracted fields, not whatever extraction produced live.

## Record schema

Every JSONL line in every dataset follows the same four-field contract:

```jsonc
{
  "id": "...",                // stable, unique per record
  "query": { ... },           // the input — shape varies by dataset
  "expected": { ... },        // the expected behavior — shape varies by step
  "metadata": { ... }         // category, failure_mode tags, rationale, source notes
}
```

`id`, `query`, `expected`, `metadata`. Graders read `expected`. Runners log `id` to Langfuse. Error analysis filters by `metadata.failure_mode` or `metadata.category`.

## E2E `dev.jsonl` schema

The seed E2E dataset. Each record is one tenant email and the expected agent behavior at every graded pipeline step.

**`query`** — the inbound email:

```jsonc
{
  "from": "sarah@example.com",
  "subject": "URGENT - water everywhere unit 4B",
  "body": "Hi - the pipe under my kitchen sink just burst..."
}
```

**`expected`** — keyed by pipeline step from `plan/project_recommendation_plan.md`:

```jsonc
{
  "pre_filter": { "action": "pass" },                    // or { "action": "archive", "reason": "phishing_suspected" }
  "extract":    { "unit": "4B", "location": "kitchen sink", "duration": "~15 min" },
  "classify":   { "category": "plumbing", "urgency": "high", "risk_flags": ["water_damage_potential"] },
  "route":      { "tool": "create_work_order" },         // single tool, or array for multi-intent
  "clarify":    { "triggered": false }                   // or { "triggered": true, "missing_fields": ["unit_number"] }
}
```

When a step is unreachable (e.g. pre-filter archives the email, so extract/classify/route are not run), the unreachable steps are omitted from `expected`.

**`metadata`**:

```jsonc
{
  "category": "typical" | "edge" | "error",
  "failure_mode": null,                                  // e.g. "tone_vs_facts" for E03
  "rationale": "Why this case is in the dataset",
  "source": "synthetic" | "scraped" | "real"
}
```

## Category counts and pass-rate targets

Per the methodology in [Designing Eval Datasets](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/evals-agent-performance/designing-eval-datasets):

| Category | Count | Definition | Target pass rate |
|---|---|---|---|
| typical | 47 | Clear intent, identifiable trade, enough info — the 80% of real inbox traffic | 90%+ |
| edge | 43 | Ambiguity, multi-intent, missing fields, tone-vs-facts mismatches — judgment calls | 70–80% |
| error | 13 | Outside the agent's pipeline — spam, phishing, lease, noise, rent | N/A (correct destination, not "success") |

## Sourcing and grounding

All seed emails are **synthetic** (`metadata.source = "synthetic"`), grounded in real renter complaint patterns from public templates and rental-advice forums. Tone, length, formality, and typos vary on purpose; phone numbers, addresses, and unit numbers are fake.

As production traces accumulate (once the agent is deployed against a real inbox), the dataset grows **event-driven**, per the methodology: a production failure mode that isn't represented here becomes a new case. Promoted records carry `metadata.source = "real"` and a pointer to the source trace.

## Coverage gaps deliberately left for later

- **Multi-turn clarification flows (Step 8)** — need conversation transcripts, will land in `datasets/components/clarification_sessions.jsonl`
- **Long-running tracking events (Step 9)** — vendor SMS replies, tenant follow-ups, time-based wakeups — need session-level fixtures
- **Photo attachments** — out of scope until multimodal extraction is wired up
- **Non-English emails** — explicitly deferred; will be added when the agent supports them

## How records are written

Hand-crafted in a markdown scratchpad first (subject + body + reasoning), then converted to JSONL once the case is stable. The conversion is mechanical; what matters is the rationale field — every record must answer "why is this case in the dataset, and what would breaking it mean?" Records without a real rationale get dropped, not kept.
