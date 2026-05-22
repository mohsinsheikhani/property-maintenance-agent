"""DSPy port of the `classify` node (agent/graph/nodes.py).

The live node uses a long hand-written prompt (agent/graph/prompts/classify.md).
Here we write a lean signature and let the optimizer try to rediscover the rules
from the labeled dataset. The desc strings are kept thin on purpose so we can
see how much the optimizer recovers.

Classify is a fair DSPy test where extract was not: every field below is a closed
set of values, so the metric is plain code, no judge. urgency is the one field
with a real judgment call, so the metric reports it separately and we read those
misses by hand before trusting the number.
"""

from typing import Literal, Optional

import dspy

Category = Literal["plumbing", "electrical", "hvac", "locksmith", "general", "pest", "appliance"]
Urgency = Literal["high", "medium", "low"]
RiskFlag = Literal["water_damage_potential", "fire_hazard", "security_risk", "habitability_violation"]


class ClassifyMaintenanceEmail(dspy.Signature):
    """Classify a tenant maintenance email into a category, urgency tier, and risk flags.

    A maintenance email is something the landlord/PM is responsible for fixing in
    the building. Lease questions, invoices, inter-tenant disputes, parking, and
    billing are not maintenance. Read the whole thread before deciding.
    """

    thread: str = dspy.InputField(
        desc="Full thread, oldest first, each turn labeled TENANT or AGENT."
    )

    category: Optional[Category] = dspy.OutputField(
        desc="The maintenance category. Null when not_a_maintenance_request is true."
    )
    urgency: Optional[Urgency] = dspy.OutputField(
        desc="From physical facts only, never tone. high = immediate threat to "
        "habitability/safety/property (active leak, no heat in cold, gas smell, "
        "locked out). medium = a real fault in daily use but not immediate "
        "(partly-broken appliance, slow drain). low = cosmetic/minor, or no "
        "concrete physical fact. Null when not_a_maintenance_request is true."
    )
    risk_flags: list[RiskFlag] = dspy.OutputField(
        desc="Only flags with an explicit physical signal in the body; opt-in, not "
        "implied by the category. Empty list when none apply."
    )
    not_a_maintenance_request: bool = dspy.OutputField(
        desc="True when the email is about something other than a fix the landlord "
        "owns (lease, invoice, dispute, parking, billing, owner message), or carries "
        "no maintenance signal at all."
    )
    pm_queue: Optional[Literal["tenancy", "dispute", "accounting", "owner", "review"]] = dspy.OutputField(
        desc="Human queue to route a non-maintenance email to; null otherwise."
    )

    # pm_queue is part of the prod contract but only 2 records label it, so the
    # metric does not score it. It stays here for I/O fidelity, not as a target.


# Predict is the zero-reasoning baseline, closest to the current node. On the
# 46-example val set, MIPROv2 light gave +0.8 (noise) and ChainOfThought gave
# -3.3 (reasoning talks the model out of the right tier on a closed-set task).
# Neither beat the lean prompt, so Predict stays.
classify = dspy.Predict(ClassifyMaintenanceEmail)
