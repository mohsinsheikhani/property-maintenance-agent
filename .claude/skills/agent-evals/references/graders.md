# Graders

Graders are functions that score agent outputs. Choose grader type based on quadrant classification.

Binary criteria produce more reliable scores than numeric scales because they leverage LLM classification strengths while avoiding calibration weaknesses.

---

## CRITICAL: Test Graders with Real Agent Responses

Never create graders by testing them with mock/dummy data. Always test graders against real agent outputs.

| Approach | Problem | Result |
|----------|---------|--------|
| Mock Data Testing | Tests grader logic in isolation, not real agent behavior | Grader passes on fake data, fails to catch real agent bugs |
| Real Agent Testing | Tests grader against actual agent outputs | Discovers real routing failures, missing handoffs, incorrect tool calls |

```python
# WRONG: Testing grader with mocked agent response
def test_routing_grader_unit_test():
    mock_result = {"agent": "FAQAgent", "response": "..."}  # Fake data
    expected = {"agent": "FAQAgent"}
    result = grade_routing(mock_result, expected)
    assert result["passed"]  # Test passes, but proves nothing about real agent

# CORRECT: Testing grader with real agent execution
async def test_routing_grader_integration():
    # Actually call the agent
    agent_result = await handle_message("What's your refund policy?")

    expected = {"agent": "FAQAgent"}
    grade_result = grade_routing(agent_result, expected)

    # This reveals REAL issues:
    # - Triage agent not routing to FAQAgent
    # - Agent asking for email before answering simple questions
    # - Handoffs not configured correctly
    assert grade_result["passed"]  # May fail - that's the point!
```

Real agent testing discovered in actual implementation:
- TriageAgent wasn't routing to specialists (stayed at triage level)
- Agent required customer email even for simple FAQ questions
- Only 2/7 routing tests passed (29% success rate)
- These bugs would have been hidden by mock data testing

**Required Practice**:
1. Build the grader with correct logic
2. Test against real agent by calling `handle_message()` or equivalent
3. Document failures - low scores reveal agent bugs, not grader bugs
4. Iterate on agent until graders pass with real responses

Graders that pass with mock data but fail with real agents are exposing the exact problems evals are designed to catch. Failing tests on real data is success - you found bugs to fix.

---

## Code-Based Grader (Q1, Q3)

Use when criterion is objective/code-checkable. Structure checks as a dictionary with sum-based scoring and standardized result format:

```python
def grade_response(output: str, expected: dict) -> dict:
    """Code-based grader with structured checks and standardized output."""
    checks = {
        "has_required_fields": all(
            field in output for field in expected.get("required_fields", [])
        ),
        "valid_json": is_valid_json(output),
        "within_length": len(output) <= expected.get("max_length", 1000),
        "no_pii_detected": not contains_pii(output),
        "matches_expected": output.strip() == expected.get("exact_match", "").strip()
    }

    score = sum(checks.values()) / len(checks)

    return {
        "passed": score >= expected.get("threshold", 0.8),
        "score": score,
        "checks": checks,
        "failed_checks": [k for k, v in checks.items() if not v]
    }
```

---

## LLM Grader (Q2, Q4)

Use when criterion requires semantic judgment. Decompose quality assessments into 5-7 specific yes/no questions rather than numeric scales. Each question should be clear enough that multiple humans would arrive at the same conclusion independently. The final score comes from counting affirmative answers.

```python
LLM_GRADER_PROMPT = """
Evaluate the following agent response against the criteria below.

## Input
{input}

## Agent Response
{response}

## Reference (if available)
{reference}

## Evaluation Criteria
Answer each question with YES or NO only:

1. Does the response directly address the user's request?
2. Is the information factually consistent with the reference?
3. Is the response free of hallucinated details not in the source?
4. Does the tone match the expected context (professional/casual)?
5. Is the response complete without unnecessary verbosity?

## Your Evaluation
Provide exactly 5 lines, one answer per criterion:
"""

def parse_llm_grader_response(llm_response: str) -> dict:
    """Parse binary YES/NO responses into structured result."""
    lines = [line.strip().upper() for line in llm_response.strip().split('\n') if line.strip()]
    criteria = [
        "addresses_request", "factually_consistent",
        "no_hallucinations", "appropriate_tone", "complete_response"
    ]

    checks = {
        criteria[i]: lines[i] == "YES"
        for i in range(min(len(lines), len(criteria)))
    }

    return {
        "passed": sum(checks.values()) >= 4,
        "score": sum(checks.values()) / len(criteria),
        "checks": checks
    }
```

---

## Combined Grader Pattern

Execute code checks first, then run LLM evaluation only for responses passing structural checks. This optimizes cost by avoiding expensive LLM calls on obviously flawed outputs:

```python
def combined_grader(output: str, expected: dict, llm_client) -> dict:
    """Two-stage grader: code checks first, LLM evaluation second."""

    # Stage 1: Fast code-based structural checks
    structural_checks = {
        "valid_format": is_valid_json(output),
        "within_limits": len(output) <= expected.get("max_length", 2000),
        "has_required_sections": all(
            section in output for section in expected.get("sections", [])
        )
    }

    structural_passed = all(structural_checks.values())

    if not structural_passed:
        return {
            "passed": False,
            "stage_failed": "structural",
            "structural_checks": structural_checks,
            "semantic_checks": None,
            "reason": f"Failed structural checks: {[k for k, v in structural_checks.items() if not v]}"
        }

    # Stage 2: Expensive LLM-based semantic evaluation
    llm_response = llm_client.evaluate(
        prompt=LLM_GRADER_PROMPT.format(
            input=expected.get("input", ""),
            response=output,
            reference=expected.get("reference", "N/A")
        )
    )

    semantic_result = parse_llm_grader_response(llm_response)

    return {
        "passed": semantic_result["passed"],
        "stage_failed": None if semantic_result["passed"] else "semantic",
        "structural_checks": structural_checks,
        "semantic_checks": semantic_result["checks"],
        "score": semantic_result["score"]
    }
```

---

## Grader Design Principles

| Principle | Guidance |
|-----------|----------|
| **Test with real agents** | NEVER test graders with mock data - always use real agent outputs |
| **Prioritize code checks** | Use code-based graders for all deterministic criteria |
| **Reserve LLM for semantics** | Only invoke LLM judges when semantic understanding is required |
| **Avoid numeric scales** | Prefer binary YES/NO over 1-5 ratings due to calibration inconsistencies |
| **Use 5-7 binary criteria** | Decompose quality into specific yes/no questions clear enough for human consensus |
| **Evaluate independently** | Score each response separately against identical criteria; avoid pairwise comparisons |
| **Sequence for cost** | Run cheap checks before expensive ones to fail fast |
| **Standardize output** | Always return structured results with pass/fail, score, and failed checks |

---

## Independent Evaluation Over Pairwise Comparison

When comparing agent outputs (e.g., A/B testing prompts or model changes), avoid asking an LLM to directly compare two responses.

**Why Pairwise Fails:**
- **Positional bias**: LLMs tend to favor the first or last option presented
- **Inconsistent criteria**: The judge may weight different factors across comparisons
- **Non-transitive rankings**: A > B and B > C doesn't guarantee A > C

```python
def compare_responses_independently(response_a: str, response_b: str,
                                     input_context: str, criteria: list) -> dict:
    """Evaluate each response separately, then compare scores mathematically."""

    # Evaluate A independently
    score_a = evaluate_against_criteria(response_a, input_context, criteria)

    # Evaluate B independently with IDENTICAL criteria
    score_b = evaluate_against_criteria(response_b, input_context, criteria)

    # Mathematical comparison, not LLM opinion
    return {
        "response_a_score": score_a,
        "response_b_score": score_b,
        "winner": "A" if score_a > score_b else "B" if score_b > score_a else "tie",
        "margin": abs(score_a - score_b)
    }
```

Calculate final scores mathematically from independent evaluations. Never ask "which response is better?" - this framing introduces bias.

---

## Grader Validation

LLM judges are powerful but imperfect. Validate against human judgment before production deployment.

### Human Calibration Process

1. Gather human ratings: Have humans rate at least 20 sample responses using your criteria
2. Run LLM grader: Evaluate the same 20 samples with your automated grader
3. Measure agreement: Calculate alignment between human and LLM judgments
4. Iterate if needed: Poor alignment signals criteria need clarification

### Agreement Thresholds

| Metric | Target | Action if Below |
|--------|--------|-----------------|
| Exact match | >=70% | Revise criteria for clarity |
| Within-one | >=90% | Review edge cases, add examples |

```python
def validate_grader_against_humans(
    samples: list[dict],
    human_ratings: list[dict],
    llm_grader: callable
) -> dict:
    """Validate LLM grader alignment with human judgment."""

    llm_ratings = [llm_grader(sample) for sample in samples]

    exact_matches = sum(
        1 for h, l in zip(human_ratings, llm_ratings)
        if h["passed"] == l["passed"]
    )

    within_one = sum(
        1 for h, l in zip(human_ratings, llm_ratings)
        if abs(h["score"] - l["score"]) <= 0.2
    )

    n = len(samples)

    return {
        "exact_match_rate": exact_matches / n,
        "within_one_rate": within_one / n,
        "ready_for_production": (exact_matches / n >= 0.7) and (within_one / n >= 0.9),
        "disagreements": [
            {"sample": s, "human": h, "llm": l}
            for s, h, l in zip(samples, human_ratings, llm_ratings)
            if h["passed"] != l["passed"]
        ]
    }
```

### When Alignment Fails

| Issue | Likely Cause | Fix |
|-------|--------------|-----|
| Low exact match | Ambiguous criteria | Rewrite questions to be more specific |
| Inconsistent within-one | Edge case handling | Add examples of borderline cases to prompt |
| Systematic bias | Criteria mismatch | Humans and LLM interpret criteria differently - align definitions |

A grader that disagrees with humans 30%+ of the time will produce unreliable signals and erode trust in your evaluation system. Invest in calibration upfront.
