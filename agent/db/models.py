from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _tz_col(*, nullable: bool = False, default=None):
    return Column(DateTime(timezone=True), nullable=nullable, default=default)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Client(SQLModel, table=True):
    __tablename__ = "clients"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    gmail_address: str = Field(index=True, unique=True)
    gmail_history_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger))
    oauth_tokens: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    vendor_table: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    urgency_policy: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    tone_guide: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow, sa_column=_tz_col(default=_utcnow))


class Email(SQLModel, table=True):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "source",
            "source_message_id",
            name="uq_email_client_source_message",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    client_id: UUID = Field(foreign_key="clients.id", index=True)

    source: str  # 'gmail' | 'fixture' — enforced by NormalizedEmail at the seam
    source_message_id: str

    from_address: str
    subject: str
    body: str
    raw_payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))

    received_at: datetime = Field(sa_column=_tz_col())
    ingested_at: datetime = Field(default_factory=_utcnow, sa_column=_tz_col(default=_utcnow))

    status: str = Field(default="pending", index=True)  # 'pending'|'processing'|'done'|'failed'|'archived'


class WorkOrder(SQLModel, table=True):
    """Maintenance work order created from a tenant email after routing.

    Fields ground in datasets/e2e/dev.jsonl `expected.classify` + `expected.extract`:
    category/urgency/risk_flags come from classify, unit/location from extract,
    pm_note from E04-style routes (hostile-tone repeat complaint).
    """

    __tablename__ = "work_orders"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email_id: UUID = Field(foreign_key="emails.id", index=True)
    client_id: UUID = Field(foreign_key="clients.id", index=True)

    category: str = Field(index=True)  # plumbing|electrical|hvac|locksmith|general|pest|appliance
    urgency: str = Field(index=True)   # high|medium|low
    risk_flags: Optional[list[str]] = Field(default=None, sa_column=Column(JSONB))

    description: str
    location_in_unit: Optional[str] = Field(default=None)
    unit_number: Optional[str] = Field(default=None)
    pm_note: Optional[str] = Field(default=None)

    vendor_id: Optional[UUID] = Field(default=None, foreign_key="vendors.id", index=True)
    status: str = Field(default="open", index=True)  # 'open'|'dispatched'|'completed'|'cancelled'

    created_at: datetime = Field(default_factory=_utcnow, sa_column=_tz_col(default=_utcnow))


class PmQueue(SQLModel, table=True):
    """Item handed off to a human PM queue (owner / tenancy / dispute / accounting / review).

    `queue` values seen in dataset: tenancy, dispute, accounting. Plan also defines owner, review.
    `priority` left as a free string — dataset uses "normal" while plan suggests high/medium/low.
    """

    __tablename__ = "pm_queue"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email_id: UUID = Field(foreign_key="emails.id", index=True)
    client_id: UUID = Field(foreign_key="clients.id", index=True)

    queue: str = Field(index=True)  # owner|tenancy|dispute|accounting|review
    priority: str = Field(default="normal")
    reason: str

    status: str = Field(default="pending", index=True)  # 'pending'|'handled'
    created_at: datetime = Field(default_factory=_utcnow, sa_column=_tz_col(default=_utcnow))


class Vendor(SQLModel, table=True):
    """Contractor available for dispatch. Used by Step 6 (vendor selection).

    Mirrors the plan's search_vendors signature: filter by trade + zone + available.
    `preferred` and `completion_rate` are the two ranking inputs the plan calls out.
    """

    __tablename__ = "vendors"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    client_id: UUID = Field(foreign_key="clients.id", index=True)

    name: str
    trade: str = Field(index=True)  # plumbing|electrical|hvac|locksmith|general|pest|appliance
    zone: Optional[str] = Field(default=None, index=True)
    completion_rate: float = Field(default=0.0, sa_column=Column(Float))
    preferred: bool = Field(default=False, sa_column=Column(Boolean))
    available: bool = Field(default=True, sa_column=Column(Boolean))

    created_at: datetime = Field(default_factory=_utcnow, sa_column=_tz_col(default=_utcnow))
