from typing import Annotated, Optional, List
from typing_extensions import TypedDict, NotRequired

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class EmailState(TypedDict):
    email_id: str
    # Tool-calling conversation used by the route node + ToolNode.
    messages: NotRequired[Annotated[list[AnyMessage], add_messages]]
    from_address: NotRequired[str]
    subject: NotRequired[str]
    body: NotRequired[str]
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
    category: NotRequired[Optional[str]]
    urgency: NotRequired[Optional[str]]
    risk_flags: NotRequired[Optional[List[str]]]
    not_a_maintenance_request: NotRequired[Optional[bool]]
    insufficient_info: NotRequired[Optional[bool]]
    # Step 5 result: id of the work order create_work_order returned (if any).
    work_order_id: NotRequired[Optional[str]]
