from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, DateTime, UniqueConstraint
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

    status: str = Field(default="pending", index=True)  # 'pending'|'processing'|'done'|'failed'
