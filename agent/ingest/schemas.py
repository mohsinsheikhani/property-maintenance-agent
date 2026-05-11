from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PubSubMessage(BaseModel):
    """The inner `message` block of a Google Pub/Sub push envelope."""

    data: str
    message_id: str = Field(alias="messageId")
    publish_time: Optional[str] = Field(default=None, alias="publishTime")
    attributes: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class GmailPushPayload(BaseModel):
    """The outer envelope Google Pub/Sub posts to the webhook."""

    message: PubSubMessage
    subscription: str


class GmailNotification(BaseModel):
    """Decoded inner contents of `message.data` — Gmail's notification shape.

    Gmail Pub/Sub publishes `{"emailAddress": "...", "historyId": 12345}` as the
    base64-encoded `data` field.
    """

    email_address: str = Field(alias="emailAddress")
    history_id: int = Field(alias="historyId")

    model_config = ConfigDict(populate_by_name=True)


class NormalizedEmail(BaseModel):
    """The canonical 'an email' shape. The seam between every email source and persistence.

    Producers: Gmail webhook normalizer, fixture loader, hypothetical Outlook later.
    Consumer: `persist_email`.
    """

    source: Literal["gmail", "fixture"]
    source_message_id: str

    from_address: str
    subject: str
    body: str

    received_at: datetime
    raw_payload: Optional[dict[str, Any]] = None
