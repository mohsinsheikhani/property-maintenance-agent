"""Code graders for agent outputs.

Each grader is a pure function: (expected: dict, final_state: dict) -> GraderResult.
- result.status is one of "pass" | "fail" | "skipped".
- "skipped" means the grader doesn't apply (e.g. expected field is absent).
  Skipped records should not be counted in pass-rate denominators.

Graders are intentionally narrow. One grader checks one field. Bundle them at
the call site (see evals/grade.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class GraderResult:
    name: str
    status: str  # "pass" | "fail" | "skipped"
    expected: Any = None
    actual: Any = None
    reason: str = ""


Grader = Callable[[dict, dict], GraderResult]
