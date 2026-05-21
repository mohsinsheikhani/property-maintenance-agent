from typing import Annotated, Optional, List, Literal
from typing_extensions import TypedDict, NotRequired

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class Turn(TypedDict):
    role: Literal["tenant", "agent"]
    subject: NotRequired[Optional[str]]
    body: str


class EmailState(TypedDict):
    email_id: str
    # Tool-calling conversation used by the route node + ToolNode.
    messages: NotRequired[Annotated[list[AnyMessage], add_messages]]
    from_address: NotRequired[str]
    subject: NotRequired[str]
    body: NotRequired[str]
    # Full multi-turn thread. Seeded by the producer (persist_email caller) with
    # the original tenant email; clarify appends agent ask + tenant reply on each
    # cycle. Extract reads this rather than subject/body so it sees the full context
    # after a clarification round-trip.
    thread: NotRequired[List[Turn]]
    pre_filter_decision: NotRequired[Optional[str]]   # "pass" | "archive"
    pre_filter_reason: NotRequired[Optional[str]]
    unit_number: NotRequired[Optional[str]]
    location_in_unit: NotRequired[Optional[str]]
    duration_mentioned: NotRequired[Optional[str]]
    description: NotRequired[Optional[str]]
    related_unit: NotRequired[Optional[str]]
    diy_attempted: NotRequired[Optional[str]]
    callback_phone: NotRequired[Optional[str]]
    tenant_framing: NotRequired[Optional[str]]
    tenant_sentiment: NotRequired[Optional[str]]
    lease_question_present: NotRequired[Optional[bool]]
    insufficient_info: NotRequired[Optional[bool]]
    missing_fields: NotRequired[List[str]]
    category: NotRequired[Optional[str]]
    urgency: NotRequired[Optional[str]]
    risk_flags: NotRequired[Optional[List[str]]]
    not_a_maintenance_request: NotRequired[Optional[bool]]
    pm_queue: NotRequired[Optional[str]]  # set only when not_a_maintenance_request=true
    # Clarify bookkeeping.
    clarify_attempts: NotRequired[int]
    clarify_outcome: NotRequired[Optional[Literal["sent", "resumed", "escalated", "archived"]]]
    # Draft body produced by clarify_draft and consumed by clarify_pause. Held in
    # state across the interrupt so the pause node has nothing to recompute on resume.
    pending_clarify_body: NotRequired[Optional[str]]
    # Step 5 result: id of the work order create_work_order returned (if any).
    work_order_id: NotRequired[Optional[str]]
