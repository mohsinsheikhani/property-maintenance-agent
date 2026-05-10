# Regression Protection

Regression protection isn't about preventing all changes - it's about knowing what your changes do. Evaluation suites transform from one-time validation into continuous quality assurance through systematic baseline comparison and per-criterion tracking.

Aggregate performance improvements can mask critical regressions in specific criteria. A system that improves from 80% to 85% overall while dropping from 95% to 75% on factual accuracy has regressed where it matters most.

---

## The Baseline-First Development Pattern

Every agent modification requires baseline establishment before changes begin. This discipline prevents post-hoc rationalization of unexpected performance shifts.

```python
# 1. BEFORE any code changes
baseline_results = run_full_eval_suite(agent, dataset)
save_baseline(
    results=baseline_results,
    version="v1.2.3",
    timestamp=datetime.now(),
    metadata={"model": "claude-sonnet-4-5", "config": current_config}
)

# 2. Make your changes
modify_agent_code()

# 3. AFTER changes, run identical eval suite
current_results = run_full_eval_suite(agent, dataset)

# 4. Compare per-criterion, not just aggregate
regression_report = detect_regressions(
    baseline=baseline_results,
    current=current_results,
    threshold_config=DOMAIN_THRESHOLDS
)

# 5. Review before proceeding
if regression_report["has_regressions"]:
    print(regression_report["detailed_analysis"])
    # Decide: accept tradeoff, revert change, or iterate further
```

Never compare current performance to memory or intuition. Always compare to captured baseline data.

---

## Per-Criterion Regression Detection

Aggregate metrics hide critical signal. Track every criterion independently.

**Why Aggregates Fail:**

| Scenario | Overall Score | Hidden Reality |
|----------|--------------|----------------|
| Baseline | 82% | All criteria balanced |
| After change | 87% (+5%) | "factual_consistency" dropped 92% to 72% (-20%) |
| Interpretation | Looks like improvement | Critical regression masked by other gains |

```python
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class CriterionResult:
    name: str
    baseline_score: float
    current_score: float

    @property
    def delta(self) -> float:
        return self.current_score - self.baseline_score

    @property
    def pct_change(self) -> float:
        if self.baseline_score == 0:
            return 0
        return (self.delta / self.baseline_score) * 100

def detect_regressions(
    baseline: Dict[str, float],
    current: Dict[str, float],
    threshold_config: dict
) -> dict:
    """Detect regressions by comparing each criterion independently."""

    criterion_results = []
    regressions = []

    for criterion_name in baseline.keys():
        result = CriterionResult(
            name=criterion_name,
            baseline_score=baseline[criterion_name],
            current_score=current.get(criterion_name, 0)
        )
        criterion_results.append(result)

        threshold = threshold_config.get("drop_threshold", 0.05)
        any_drop_fails = threshold_config.get("any_drop", False)

        if any_drop_fails and result.delta < 0:
            regressions.append(result)
        elif abs(result.delta) >= threshold and result.delta < 0:
            regressions.append(result)

    baseline_avg = sum(baseline.values()) / len(baseline)
    current_avg = sum(current.values()) / len(current)

    return {
        "has_regressions": len(regressions) > 0,
        "regression_count": len(regressions),
        "regressed_criteria": [r.name for r in regressions],
        "criterion_details": [
            {
                "name": r.name,
                "baseline": r.baseline_score,
                "current": r.current_score,
                "delta": r.delta,
                "pct_change": r.pct_change
            }
            for r in criterion_results
        ],
        "aggregate_baseline": baseline_avg,
        "aggregate_current": current_avg,
        "aggregate_delta": current_avg - baseline_avg,
        "detailed_analysis": format_regression_report(criterion_results, regressions)
    }

def format_regression_report(all_results: List[CriterionResult],
                             regressions: List[CriterionResult]) -> str:
    """Generate human-readable regression report."""

    lines = ["=" * 60, "REGRESSION DETECTION REPORT", "=" * 60, ""]

    if not regressions:
        lines.append("No regressions detected")
    else:
        lines.append(f"{len(regressions)} regression(s) detected:")
        lines.append("")
        for reg in regressions:
            lines.append(f"  - {reg.name}")
            lines.append(f"    Baseline: {reg.baseline_score:.1%}")
            lines.append(f"    Current:  {reg.current_score:.1%}")
            lines.append(f"    Delta:    {reg.delta:+.1%} ({reg.pct_change:+.1f}%)")
            lines.append("")

    lines.append("All Criteria Changes:")
    lines.append("")
    for result in sorted(all_results, key=lambda r: r.delta):
        direction = "DOWN" if result.delta < 0 else "UP" if result.delta > 0 else "SAME"
        lines.append(
            f"  [{direction}] {result.name}: "
            f"{result.baseline_score:.1%} -> {result.current_score:.1%} "
            f"({result.delta:+.1%})"
        )

    return "\n".join(lines)
```

Always review the full criterion-level report, even when aggregate scores improve. Regressions in high-importance criteria (factual accuracy, safety, tone) matter more than improvements in low-importance ones (formatting, verbosity).

---

## Context-Dependent Thresholds

| Domain | Threshold Config | Rationale |
|--------|-----------------|-----------|
| **High-Stakes** (medical, financial, safety-critical) | `any_drop=True` | Any performance decrease requires investigation |
| **Standard** (customer support, productivity tools) | `drop_threshold=0.05` | 5% drops trigger review |
| **Experimental** (prototypes, research) | `drop_threshold=0.10` | 10% threshold allows rapid experimentation |

```python
THRESHOLDS = {
    "production_medical": {
        "any_drop": True,
        "require_signoff": True,
        "criteria_weights": {
            "factual_accuracy": 2.0,
            "safety_compliance": 2.0,
            "formatting": 0.5
        }
    },

    "production_standard": {
        "drop_threshold": 0.05,
        "require_signoff": False,
        "critical_criteria": ["factual_accuracy", "appropriate_tone"]
    },

    "development": {
        "drop_threshold": 0.10,
        "require_signoff": False,
        "alert_only": True
    }
}

def apply_weighted_thresholds(regression_report: dict, config: dict) -> dict:
    """Apply domain-specific weights and thresholds."""

    weights = config.get("criteria_weights", {})
    critical = config.get("critical_criteria", [])

    weighted_regressions = []
    for detail in regression_report["criterion_details"]:
        weight = weights.get(detail["name"], 1.0)
        is_critical = detail["name"] in critical

        weighted_delta = detail["delta"] * weight

        threshold = config.get("drop_threshold", 0.05)
        if is_critical:
            threshold = threshold / 2

        if weighted_delta < -threshold:
            weighted_regressions.append({
                **detail,
                "weighted_delta": weighted_delta,
                "is_critical": is_critical,
                "severity": "HIGH" if is_critical else "MEDIUM"
            })

    return {
        **regression_report,
        "weighted_regressions": weighted_regressions,
        "requires_signoff": (
            config.get("require_signoff", False) and
            len(weighted_regressions) > 0
        )
    }
```

Choose threshold based on the question: "What's worse - blocking a beneficial change or shipping a harmful regression?"

---

## CI/CD Integration

Automated regression protection prevents accidental deployment of degraded agents.

```yaml
# .github/workflows/agent-eval.yml
name: Agent Evaluation

on:
  pull_request:
    paths:
      - 'agent/**'
      - 'prompts/**'
      - 'config/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup environment
        run: pip install -r requirements.txt

      - name: Load baseline
        run: python scripts/load_baseline.py --branch main --output baseline.json

      - name: Run evaluation suite
        run: python scripts/run_evals.py --dataset eval_datasets.json --output current.json

      - name: Detect regressions
        id: regression_check
        run: |
          python scripts/compare_results.py \
            --baseline baseline.json \
            --current current.json \
            --threshold-config production_standard \
            --output regression_report.json

      - name: Post results to PR
        uses: actions/github-script@v6
        with:
          script: |
            const report = require('./regression_report.json');
            const body = formatReportForGitHub(report);
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body
            });

      - name: Block merge on regression
        if: steps.regression_check.outputs.has_regressions == 'true'
        run: |
          echo "::error::Regressions detected. Review required before merge."
          exit 1
```

| Component | Purpose |
|-----------|---------|
| Baseline loading | Fetch comparison target from main branch or artifact storage |
| Identical eval suite | Run same dataset/graders on PR branch |
| Automated comparison | Detect regressions without human calculation |
| PR comment | Surface results where decisions happen |
| Merge blocking | Prevent accidental regression deployment |

---

## Baseline Storage

```python
def save_baseline(results: dict, version: str, metadata: dict):
    """Store baseline for future comparison."""
    baseline_entry = {
        "version": version,
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "metadata": metadata
    }

    # Option 1: Version control (simple, auditable)
    baseline_file = f"baselines/{version}.json"
    with open(baseline_file, "w") as f:
        json.dump(baseline_entry, f, indent=2)

    # Option 2: Database (queryable, scalable)
    db.baselines.insert_one(baseline_entry)

    # Option 3: Cloud storage (distributed teams)
    s3.upload_json(baseline_entry, f"baselines/{version}.json")

def load_baseline(version: str = "latest") -> dict:
    """Load baseline for comparison."""
    if version == "latest":
        version = get_latest_baseline_version()
    return json.load(open(f"baselines/{version}.json"))
```
