"""DSPy port of the `extract` node (agent/graph/nodes.py:124).

The live node uses a 1.3k-token hand-written prompt (agent/graph/prompts/extract.md)
with structured output. This rewrites the same I/O contract as a lean signature
and lets the optimizer try to rediscover the rules from the labeled dataset. The
desc strings are kept thin so we can measure how much it recovers.

The node's insufficient_info / missing_fields outputs are gone here. They were the
model restating which facts are absent, bookkeeping it could get out of sync with
the data fields. We let the model do the one genuine judgment call
(location_not_applicable) and derive the gate in code via derive_gate below, so it
can no longer contradict itself.
"""

from typing import Literal, Optional

import dspy

Sentiment = Literal["neutral", "calm", "anxious", "hostile", "polite", "panicked"]


class ExtractMaintenanceFields(dspy.Signature):
    """Extract structured fields from a tenant maintenance email thread.

    The thread holds the original tenant email plus any agent clarification
    asks and tenant replies. Read all turns together. Return null for any
    field not clearly stated; do not infer or carry values across emails.
    """

    thread: str = dspy.InputField(
        desc="Full thread, oldest first, each turn labeled TENANT or AGENT."
    )

    unit_number: Optional[str] = dspy.OutputField(
        desc="Tenant's unit/apartment number, verbatim from the thread; else null."
    )
    location_in_unit: Optional[str] = dspy.OutputField(
        desc="Where the failing thing is (e.g. 'kitchen sink'), not where a symptom "
        "shows. A drip landing in the tub is location 'shower'. Null if not spot-tied."
    )
    duration_mentioned: Optional[str] = dspy.OutputField(
        desc="How long the problem has existed, per the tenant. Not appliance run "
        "times or one failed attempt. Null if only one attempt is described."
    )
    description: Optional[str] = dspy.OutputField(
        desc="Self-contained object + symptom (e.g. 'oven won't turn on'). Object or "
        "symptom alone is not enough; a room name alone is not enough. Null otherwise."
    )
    related_unit: Optional[str] = dspy.OutputField(
        desc="A second unit involved, e.g. a leak from upstairs."
    )
    diy_attempted: Optional[str] = dspy.OutputField(
        desc="Anything the tenant already tried before emailing."
    )
    callback_phone: Optional[str] = dspy.OutputField(
        desc="Phone number, only if the tenant gave one."
    )
    tenant_framing: Optional[str] = dspy.OutputField(
        desc="Tenant's own urgency wording ('no rush', 'ASAP'). Sign-offs/thanks "
        "are not framing. Null if no timing/urgency wording."
    )
    tenant_sentiment: Optional[Sentiment] = dspy.OutputField(
        desc="Judge the writing, not the situation. Null if too short to carry tone."
    )
    lease_question_present: bool = dspy.OutputField(
        desc="True if the email also asks a lease/tenancy question on the side."
    )
    location_not_applicable: bool = dspy.OutputField(
        desc="True when the situation fixes the location, so a null location is "
        "complete, not missing: lockout (the apartment door), a whole-unit issue "
        "(no power/water), or anything tied to the unit entry."
    )

    # insufficient_info and missing_fields are not outputs on purpose. The node
    # derives them from the data fields above plus this flag (see docstring), so
    # the model can't return unit_number and list it as missing at the same time.


# Predict is the zero-reasoning baseline, closest to the current node.
extract = dspy.Predict(ExtractMaintenanceFields)


def _blank(v: Optional[str]) -> bool:
    # None and whitespace-only "" both mean absent; the LM may emit either.
    return v is None or (isinstance(v, str) and not v.strip())


def derive_gate(pred) -> tuple[bool, list[str]]:
    """Compute (insufficient_info, missing_fields) from an extract prediction.

    Order is fixed so the grader's list comparison stays stable. location_in_unit
    counts as missing only when it is blank and the situation does not fix it.
    """
    missing: list[str] = []
    if _blank(pred.unit_number):
        missing.append("unit_number")
    if _blank(pred.location_in_unit) and not pred.location_not_applicable:
        missing.append("location_in_unit")
    if _blank(pred.description):
        missing.append("description")
    return bool(missing), missing