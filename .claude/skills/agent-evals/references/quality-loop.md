# The Complete Quality Loop

Agent development = Building + Analysis. High-performing teams allocate disproportionate time to understanding failures rather than coding fixes, achieving faster deployment through systematic learning rather than intuitive problem-solving.

The quality loop isn't linear - it's a continuous cycle where production failures feed back into dataset improvement, creating a compounding advantage over time.

---

## The Ten-Step Workflow

```
1. Build Initial Agent -> 2. Create Eval Dataset -> 3. Execute Evals
         ^                                              |
    10. Monitor                                  4. Analyze Errors
    Production                                          |
         ^                                     5. Fix Lowest Component
    9. Deploy with                                      |
    Safeguards                                   6. Re-run Evals
         ^                                              |
    8. Ship Decision <- 7. Verify No Regression <-------+
```

---

### Step 1: Build Initial Agent (Quick Prototype)

Goal: Create minimally viable agent to generate baseline data, not production-ready system.

Anti-Pattern: Spending weeks on initial architecture before measuring quality.

```python
# Week 1: Quick prototype
def initial_agent(user_input: str) -> str:
    """Bare minimum agent to test core hypothesis."""
    prompt = f"You are a helpful assistant. User: {user_input}"
    return llm.generate(prompt)
```

Time Investment: 1-3 days maximum. The goal is generating outputs to evaluate, not perfection.

### Step 2: Create Evaluation Dataset (10-20 Cases)

Design dataset using the three-category framework (Typical/Edge/Error). See `references/dataset-design.md` for full details.

### Step 3: Execute Evals (Establish Baseline)

Run full evaluation suite to establish baseline before any optimization. Record both aggregate and per-criterion scores.

```python
baseline_results = {
    "version": "v0.1",
    "aggregate_score": 0.73,
    "by_criterion": {
        "correct_tool_selection": 0.85,
        "factual_accuracy": 0.68,
        "appropriate_tone": 0.90,
        "complete_response": 0.72,
        "handles_errors_gracefully": 0.60
    },
    "by_category": {
        "typical": 0.82,
        "edge": 0.65,
        "error": 0.58
    }
}
```

Save complete traces for error analysis, not just scores.

### Step 4: Analyze Errors Systematically

Apply error analysis methodology. See `references/error-analysis.md` for full details.

### Steps 5-7: Fix, Re-test, Verify (Iteration Cycle)

**Step 5**: Target the single lowest-performing component. Resist fixing multiple things simultaneously.

```python
# GOOD: Single targeted fix
def improved_agent(user_input: str) -> str:
    context = retrieve_relevant_context(user_input)
    prompt = f"""You are a helpful assistant.
IMPORTANT: Only state facts explicitly present in the context below.
If the context doesn't contain information needed to answer, say so.
Context: {context}
User: {user_input}"""
    return llm.generate(prompt)

# BAD: Multiple simultaneous changes
# Changed prompt + temperature + added validation + new retrieval
# Which change helped? Which hurt? Unknown.
```

**Step 6**: Execute identical evaluation suite on modified agent.

**Step 7**: Apply regression detection. See `references/regression-protection.md`.

```python
regression_report = detect_regressions(
    baseline=baseline_results["by_criterion"],
    current=iteration_1_results["by_criterion"],
    threshold_config={"drop_threshold": 0.05}
)
```

Decision Point: Accept tradeoff, iterate further, or revert.

---

## Eval-Driven Development Loop

```
1. Establish Baseline
   |
2. Identify Lowest-Performing Criterion
   |
3. Hypothesize Root Cause
   |
4. Make Targeted Change
   |
5. Run Full Eval Suite
   |
6. Compare to Baseline
   |-> Regression detected? -> Investigate/revert -> Back to step 3
   +-> Improvement confirmed? -> Update baseline -> Back to step 2
```

| Discipline | Why It Matters |
|------------|----------------|
| Baseline before changes | Prevents confirmation bias |
| Change one thing at a time | Enables attribution |
| Full eval suite every time | Catches hidden regressions |
| Decide explicitly | Accept, reject, or iterate - never leave changes in limbo |
| Update baseline on accept | New baseline becomes comparison target |

**Anti-Pattern:**
```python
# BAD: Making multiple changes without intermediate evals
improve_prompt()
change_temperature()
add_validation_step()
run_evals()  # Which change caused which effect?

# GOOD: Eval-driven iteration
baseline = run_evals()
improve_prompt()
results_1 = run_evals()
compare(baseline, results_1)  # Prompt change isolated
```

| Approach | Initial Speed | Debug Time | Total Time | Confidence |
|----------|--------------|------------|------------|------------|
| No evals | Fast | Very long | Longest | Low |
| Eval at end | Fast | Long | Long | Medium |
| Eval per change | Moderate | Minimal | Shortest | High |

---

## Diminishing Returns Detection

```python
@dataclass
class IterationMetrics:
    iteration: int
    improvement: float
    effort_hours: float
    regressions_introduced: int

def detect_diminishing_returns(iterations: list[IterationMetrics]) -> dict:
    """Flag when additional iteration yields minimal gains."""
    if len(iterations) < 3:
        return {"continue": True, "reason": "Insufficient data"}

    recent = iterations[-3:]
    avg_improvement = sum(i.improvement for i in recent) / len(recent)
    avg_effort = sum(i.effort_hours for i in recent) / len(recent)

    MIN_IMPROVEMENT = 0.02  # 2% per iteration
    MAX_EFFORT = 8  # 8 hours per iteration

    if avg_improvement < MIN_IMPROVEMENT and avg_effort > MAX_EFFORT:
        return {
            "continue": False,
            "reason": f"Diminishing returns: {avg_improvement:.1%} gain for {avg_effort:.1f}h effort",
            "recommendation": "Ship current version or redesign approach"
        }
    return {"continue": True}
```

After 3-5 iterations with <2% gains each, you've likely hit architectural limits.

---

## Ship Decision

| Score Range | Decision | High-Stakes | Standard | Experimental |
|-------------|----------|-------------|----------|--------------|
| >=95% | Ship confidently | Yes | Yes | Yes |
| 90-95% | Ship with monitoring | Review | Yes | Yes |
| 80-90% | Ship if low-stakes | No | Review | Yes |
| 70-80% | Prototype only | No | No | Limited |
| <70% | Continue iteration | No | No | No |

**Additional considerations beyond score:**
- Failure modes: Graceful degradation preferred over confident-wrong
- Improvement trajectory: Shipping 85% with upward trend beats 88% plateaued
- User expectations: Better than current alternative matters more than absolute score
- Monitoring capability: Ship earlier if you can detect and rollback failures quickly

---

## Deploy with Safeguards

```python
DEPLOYMENT_SAFEGUARDS = {
    "regression_protection": {
        "enabled": True,
        "baseline_version": "v0.5",
        "alert_threshold": 0.05,
        "auto_rollback_threshold": 0.10
    },
    "monitoring": {
        "sample_rate": 0.10,
        "alert_on_criteria": ["factual_accuracy", "safety_compliance"],
        "human_review_threshold": 0.70
    },
    "gradual_rollout": {
        "enabled": True,
        "stages": [
            {"percentage": 0.05, "duration_hours": 24},
            {"percentage": 0.25, "duration_hours": 48},
            {"percentage": 1.0, "duration_hours": None}
        ]
    },
    "rollback_plan": {
        "previous_version": "v0.4",
        "automated": True,
        "manual_override": True
    }
}
```

| Safeguard | Purpose | Configuration |
|-----------|---------|---------------|
| Regression detection | Catch performance drops early | 5% alert, 10% auto-rollback |
| Sample evaluation | Continuous quality monitoring | 10% of production traffic |
| Gradual rollout | Limit blast radius | 5% -> 25% -> 100% over days |
| Rollback plan | Quick recovery | Automated with manual override |

---

## Monitor Production and Grow Dataset

Production deployment isn't the end - it's the beginning of continuous improvement.

```python
class ProductionMonitor:
    """Continuous quality monitoring and dataset growth."""

    def monitor_production_traffic(self, sample_rate: float = 0.10):
        """Evaluate random sample of production interactions."""
        for interaction in sample_production_stream(rate=sample_rate):
            result = self.eval_suite.grade(
                input=interaction["input"],
                output=interaction["output"]
            )

            if result["score"] < self.alert_config["human_review_threshold"]:
                self.flag_for_review(interaction, result)

            if self.is_novel_failure(interaction, result):
                self.add_to_dataset_candidates(interaction, result)

    def is_novel_failure(self, interaction: dict, result: dict) -> bool:
        """Detect failure patterns not in current eval dataset."""
        similarity_scores = [
            compute_similarity(interaction["input"], case["input"])
            for case in self.dataset
        ]
        max_similarity = max(similarity_scores)
        return result["score"] < 0.70 and max_similarity < 0.75
```

**Feedback Loop:**
```
Production Failures -> Dataset Growth -> Next Iteration -> Ship Improved Version
         ^                                                          |
         +----------------------------------------------------------+
```
