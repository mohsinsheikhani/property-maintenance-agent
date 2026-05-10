# Dataset Design

Quality over quantity. Start with 10-20 examples. The bottleneck in agent improvement is understanding *why* failures occur, not accumulating raw test volume.

---

## The Three-Category Framework

| Category | Count | Purpose | Pass Rate Target |
|----------|-------|---------|------------------|
| **Typical** | 10 | Common use cases representing 80% of real usage | 90%+ |
| **Edge** | 5 | Unusual but valid scenarios requiring judgment calls | 70-80% |
| **Error** | 5 | Requests outside agent scope or impossible requests | Should fail gracefully |

**Typical Cases (10)**: Bread-and-butter scenarios the agent was designed for - straightforward task creation, basic queries, standard workflows.

**Edge Cases (5)**: Uncommon but legitimate requests - emoji in titles, ambiguous time references, multiple simultaneous actions, special characters. Tests graceful degradation.

**Error Cases (5)**: Test recognition of limitations - out-of-domain queries, malformed inputs, impossible requests, inappropriate commands the agent should decline.

---

## Real Data Over Synthetic

| Data Type | Characteristics | Value |
|-----------|-----------------|-------|
| **Synthetic** | Clean, well-formed, imagined | Low - misses real usage patterns |
| **Production** | Messy, abbreviated, context-dependent | High - reveals genuine failure modes |

**Mining Real Data Process:**
1. Export 30 days of user queries
2. Filter for negative signals: poor ratings, retry patterns, support tickets, abandoned sessions
3. Sample 50-100 candidates
4. Classify into Typical/Edge/Error categories
5. Select 20 diverse, representative cases

---

## Eval Case Structure

Each case requires three components:

```json
{
  "input": "User message + relevant context (prior conversation, user state)",
  "expected": "Success criteria, output patterns, should_succeed boolean",
  "rationale": "Why this case exists and what it tests"
}
```

---

## Minimum Viable Dataset Example

```python
INITIAL_DATASET = [
    # Typical cases (10)
    {"input": "Schedule meeting tomorrow 2pm", "category": "typical"},
    {"input": "What's on my calendar Friday?", "category": "typical"},
    # ... 8 more typical cases

    # Edge cases (5)
    {"input": "Schedule meeting party time", "category": "edge"},
    {"input": "Meeting at 2 (which timezone?)", "category": "edge"},
    # ... 3 more edge cases

    # Error cases (5)
    {"input": "Schedule meeting yesterday", "category": "error"},
    {"input": "Delete all my data", "category": "error"},
    # ... 3 more error cases
]
```

Real production data outweighs synthetic data by 10x. Mine actual user queries when possible.

---

## Dataset Growth Strategy

Grow organically through production feedback, not arbitrary coverage targets:

**Add cases when:**
- Production failures reveal uncovered patterns
- New case initially fails (confirms bug exists)
- After fix, case passes (confirms fix works)

**Don't add cases because:**
- "We should have better coverage" (vague)
- "Competitors have larger datasets" (irrelevant)
- "Time has passed since last update" (age != gaps)

Twenty thoughtful cases revealing failure patterns outperform thousands producing only pass-rate percentages. Evaluation systems exist to drive improvement, not generate confidence scores.

---

## Dataset Growth from Production

| Signal | Action | Rationale |
|--------|--------|-----------|
| Novel failure pattern | Add to dataset immediately | Prevents regression in newly discovered edge case |
| Repeated failure (3+ times) | High priority addition | Frequency indicates gap in coverage |
| Critical failure (score <50%) | Add and investigate urgently | Severe quality issue |
| Graceful handling | Lower priority | System working as intended |

The best eval datasets are grown organically from production failures, not designed upfront. Initial 20 cases bootstrap the process; production monitoring compounds dataset quality over time.
