# Error Analysis

Systematic error analysis transforms agent improvement from intuition-driven to data-driven. Rather than immediately fixing perceived problems, effective builders first analyze failure patterns to identify which components actually require attention.

---

## The Build-Analyze Loop

The development cycle prioritizes investigation before intervention:

1. Build agent version
2. Run evaluations
3. **Analyze errors** (most developers skip this critical step)
4. Identify which component failed most frequently
5. Fix that specific component
6. Re-run evaluations
7. Repeat

"Less experienced teams spend a lot of time building and probably much less time analyzing" (Andrew Ng). Analysis time prevents wasted effort on wrong components. Thirty minutes counting errors outperforms thirty hours fixing the wrong system.

---

## Traces and Spans Vocabulary

| Term | Definition |
|------|------------|
| **Trace** | Complete record capturing all intermediate outputs from a single agent execution - every LLM call, search operation, decision point, and final response |
| **Span** | Individual step's input, processing, and output within a trace. Each component produces one span |

This vocabulary enables precise error attribution. Rather than saying "the agent failed," you identify: "the source selection span picked low-quality sources despite high-quality options in search results."

Always trace errors to root cause by examining complete traces. A component might fail frequently because it receives degraded input upstream, not because it's broken. Attribution without investigation produces false improvements.

---

## The Spreadsheet Method

Simple tabulation reveals error patterns:

| Case | Component A | Component B | Component C | Error Location |
|------|-------------|-------------|-------------|----------------|
| Q1   | OK          | ERROR       | ERROR       | Component B    |
| Q2   | OK          | OK          | OK          | None           |
| Q3   | ERROR       | -           | -           | Component A    |
| Q4   | OK          | OK          | ERROR       | Component C    |

Count occurrences by location. Percentages emerge from data rather than memory bias.

---

## Why Counting Beats Intuition

Several cognitive biases distort error perception:

| Bias | Distortion | Fix |
|------|------------|-----|
| **Availability** | Recent or dramatic failures feel more common | Count all failures equally |
| **Confirmation** | You notice errors matching your existing theory | Categorize before theorizing |
| **Expertise** | You focus on components you understand best | Systematic span examination |
| **Anchoring** | First errors dominate thinking | Randomize analysis order |

---

## Prioritization Formula

**Priority = Frequency x Feasibility**

- **Frequency**: What percentage of failures originate here?
- **Feasibility**: How easily can you fix it? (Scale: 0=impossible to 1=trivial)

| Feasibility | Description | Examples |
|-------------|-------------|----------|
| 0.9-1.0 | Trivial | Configuration or regex changes |
| 0.7-0.8 | Easy | Prompt adjustments or filters |
| 0.5-0.6 | Moderate | Retraining or new components |
| 0.3-0.4 | Hard | New architecture or external dependencies |
| 0.0-0.2 | Unknown | Requires investigation first |

**Example**: A component failing 45% of the time but requiring infrastructure changes (feasibility 0.3) scores 13.5. Another failing 15% but fixable in minutes (feasibility 0.9) scores 13.5. Prioritize equally, but the second requires less effort.

---

## Error Analysis Implementation

```python
from dataclasses import dataclass
from collections import Counter

@dataclass
class AnalyzedCase:
    case_id: str
    error_location: str  # Which span failed
    trace: dict          # Full execution trace

def analyze_failures(cases: list[AnalyzedCase]) -> dict:
    """Generate error report from analyzed cases."""

    failed_cases = [c for c in cases if c.error_location != "none"]
    error_counts = Counter(case.error_location for case in failed_cases)
    total_failures = len(failed_cases)

    if total_failures == 0:
        return {"total_cases": len(cases), "failures": 0, "breakdown": {}}

    error_percentages = {
        location: {
            "count": count,
            "percentage": (count / total_failures) * 100
        }
        for location, count in error_counts.most_common()
    }

    return {
        "total_cases": len(cases),
        "failures": total_failures,
        "failure_rate": total_failures / len(cases),
        "breakdown": error_percentages,
        "top_priority": error_counts.most_common(1)[0][0]
    }

def prioritize_fixes(error_report: dict, feasibility: dict[str, float]) -> list:
    """Rank components by priority = frequency x feasibility."""

    priorities = []
    for location, data in error_report["breakdown"].items():
        freq = data["percentage"] / 100
        feas = feasibility.get(location, 0.5)
        priorities.append({
            "component": location,
            "frequency": freq,
            "feasibility": feas,
            "priority_score": freq * feas
        })

    return sorted(priorities, key=lambda x: x["priority_score"], reverse=True)
```

---

## Failure Mode Categorization

| Failure Mode | Definition | Severity | Example |
|--------------|------------|----------|---------|
| **Graceful** | Agent recognizes limitation and declines appropriately | Low | "I cannot schedule meetings in the past" |
| **Confident-Wrong** | Agent proceeds confidently with incorrect information | High | Creates meeting at wrong time without warning |
| **Partial** | Agent completes task but misses requirements | Medium | Schedules meeting but ignores timezone |
| **Tool-Selection** | Agent chooses wrong tool or API | Medium | Uses search instead of calendar API |

Confident-wrong failures outweigh all other considerations. A system that fails gracefully 50% of the time is safer than one that succeeds 90% but hallucinates confidently 10%.

```python
@dataclass
class ErrorAnalysis:
    case_id: str
    failure_mode: str  # graceful | confident-wrong | partial | tool-selection
    component_failed: str  # routing | tool-use | response-generation | validation
    root_cause: str
    trace: dict

def analyze_failure_distribution(errors: list[ErrorAnalysis]) -> dict:
    """Categorize failures by mode and component."""

    by_mode = Counter(e.failure_mode for e in errors)
    by_component = Counter(e.component_failed for e in errors)

    critical_failures = [e for e in errors if e.failure_mode == "confident-wrong"]

    return {
        "by_mode": dict(by_mode),
        "by_component": dict(by_component),
        "critical_count": len(critical_failures),
        "critical_cases": [e.case_id for e in critical_failures],
        "fix_priority": prioritize_components(by_component, critical_failures)
    }
```

---

## Development Mindset: Analysis Over Coding

**Time Allocation Comparison:**

| Team Experience | Building Time | Analysis Time | Result |
|-----------------|---------------|---------------|--------|
| Novice | 80% | 20% | Ship slowly, unclear why failures occur |
| Intermediate | 60% | 40% | Ship faster, understand some patterns |
| Expert | 40% | 60% | Ship fastest, systematic improvement |

**Mindset Shift Exercises:**

| Old Habit | New Habit |
|-----------|-----------|
| "Let me try changing the prompt" | "Let me analyze which 10 cases failed and why" |
| "This component feels wrong" | "This component failed in 8/20 cases (40% failure rate)" |
| "I'll add more validation" | "Validation won't fix the root cause (tool selection)" |
| "Run evals at the end" | "Run evals after every change to isolate impact" |
| "We need more test cases" | "We need to understand why existing cases fail" |

Thirty minutes counting errors outperforms thirty hours fixing the wrong component. Analysis provides certainty about what to fix; intuition provides guesses.
