"""property_maintenance_mcp — MCP server for the triage agent's routing/dispatch tools.

Exposes the tool surface the LangGraph routing node (Step 5) and vendor-selection
node (Step 6) will call. Each tool is a thin wrapper over an async DB write or read
using the existing async_session_factory.

Tool surface (grounded in plan/project_recommendation_plan.md and datasets/e2e/dev.jsonl):
  - create_work_order      Step 5  destructive  records a maintenance work order
  - assign_to_pm_queue     Step 5  destructive  hands the email to a human PM queue
  - archive_email          Step 5  idempotent   marks an email archived (spam / non-actionable)
  - search_vendors         Step 6  read-only    list candidate vendors for a trade
  - dispatch_vendor        Step 6  destructive  link a vendor to an existing work order

Run as a stdio MCP server:
    uv run python -m mcp_server.server
"""

import json
import os
from typing import Literal, Optional
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from agent.db.engine import async_session_factory
from agent.db.models import Email, PmQueue, Vendor, WorkOrder

# Allow host headers from localhost and the docker-compose service name so the
# server works both bare-metal and inside the compose network.
_transport_security = TransportSecuritySettings(
    allowed_hosts=[
        "127.0.0.1:*",
        "localhost:*",
        "[::1]:*",
        "mcp-server:*",
        "0.0.0.0:*",
    ],
)

mcp = FastMCP(
    "property_maintenance_mcp",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8000")),
    transport_security=_transport_security,
)

Trade = Literal["plumbing", "electrical", "hvac", "locksmith", "general", "pest", "appliance"]
Urgency = Literal["high", "medium", "low"]
PmQueueName = Literal["owner", "tenancy", "dispute", "accounting", "review"]


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload}, default=str)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


# ---------- Step 5: routing tools ----------


class CreateWorkOrderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email_id: UUID = Field(..., description="UUID of the source email in the emails table")
    category: Trade = Field(..., description="Trade bucket from the fixed taxonomy")
    urgency: Urgency = Field(..., description="Urgency from the rubric: high|medium|low")
    risk_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Risk flags from the fixed list (water_damage_potential, fire_hazard, "
            "security_risk, habitability_violation). Empty list if none apply."
        ),
    )
    description: str = Field(..., description="Short problem description grounded in the email")
    location_in_unit: Optional[str] = Field(default=None, description="Where in the unit (e.g. 'kitchen sink')")
    unit_number: Optional[str] = Field(default=None, description="Tenant's unit number if present in the email")
    pm_note: Optional[str] = Field(
        default=None,
        description=(
            "Optional note for the PM (e.g. 'repeat complaint, hostile tone'). "
            "Use sparingly — only when human handling context is relevant."
        ),
    )


@mcp.tool(
    name="create_work_order",
    annotations={
        "title": "Create maintenance work order",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def create_work_order(params: CreateWorkOrderInput) -> str:
    """Create a maintenance work order linked to a tenant email.

    Use when the routed email is a legitimate maintenance request. The client_id is
    derived from the email record so the caller does not pass it. Returns the new
    work_order_id on success.
    """
    async with async_session_factory() as session:
        email = (
            await session.execute(select(Email).where(Email.id == params.email_id))
        ).scalar_one_or_none()
        if email is None:
            return _err(f"email {params.email_id} not found")

        wo = WorkOrder(
            email_id=email.id,
            client_id=email.client_id,
            category=params.category,
            urgency=params.urgency,
            risk_flags=params.risk_flags or None,
            description=params.description,
            location_in_unit=params.location_in_unit,
            unit_number=params.unit_number,
            pm_note=params.pm_note,
        )
        session.add(wo)
        await session.commit()
        return _ok({"work_order_id": str(wo.id), "status": wo.status})


class AssignToPmQueueInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email_id: UUID = Field(..., description="UUID of the source email")
    queue: PmQueueName = Field(
        ...,
        description="Which PM queue to route to: owner, tenancy, dispute, accounting, review",
    )
    priority: str = Field(
        default="normal",
        description="Priority hint for the PM (free-form; 'normal' by default)",
    )
    reason: str = Field(..., description="One-line reason for the human picking this up")


@mcp.tool(
    name="assign_to_pm_queue",
    annotations={
        "title": "Hand off to PM queue",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def assign_to_pm_queue(params: AssignToPmQueueInput) -> str:
    """Route the email to a human PM queue (lease, dispute, accounting, etc.).

    Use when the email is legitimate but is not a maintenance request, or when a
    maintenance email also contains a question that belongs to a human queue
    (multi-intent, e.g. dataset case E01: oven + lease renewal).
    """
    async with async_session_factory() as session:
        email = (
            await session.execute(select(Email).where(Email.id == params.email_id))
        ).scalar_one_or_none()
        if email is None:
            return _err(f"email {params.email_id} not found")

        item = PmQueue(
            email_id=email.id,
            client_id=email.client_id,
            queue=params.queue,
            priority=params.priority,
            reason=params.reason,
        )
        session.add(item)
        await session.commit()
        return _ok({"pm_queue_id": str(item.id), "queue": item.queue})


class ArchiveEmailInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email_id: UUID = Field(..., description="UUID of the email to archive")
    reason: str = Field(..., description="Why this email is being archived (audit trail)")


@mcp.tool(
    name="archive_email",
    annotations={
        "title": "Archive email",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def archive_email(params: ArchiveEmailInput) -> str:
    """Mark an email as archived. Idempotent: archiving an already-archived email is a no-op.

    Use for spam, phishing, completely off-topic, or any email the routing step decides
    should not proceed further. The reason is stored implicitly by the caller via traces
    today; the column is not yet on the emails table.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            update(Email).where(Email.id == params.email_id).values(status="archived")
        )
        await session.commit()
        if result.rowcount == 0:
            return _err(f"email {params.email_id} not found")
        return _ok({"email_id": str(params.email_id), "status": "archived"})


# ---------- Step 6: vendor selection tools ----------


class SearchVendorsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    trade: Trade = Field(..., description="Trade required for the job")
    zone: Optional[str] = Field(
        default=None,
        description="Building zone (e.g. 'sydney_cbd'). Omit to search all zones.",
    )
    available_only: bool = Field(
        default=True,
        description="If true (default), only return vendors currently marked available.",
    )
    limit: int = Field(default=10, ge=1, le=50, description="Max vendors to return")


@mcp.tool(
    name="search_vendors",
    annotations={
        "title": "Search vendors",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search_vendors(params: SearchVendorsInput) -> str:
    """Find candidate vendors for a trade, optionally filtered by zone and availability.

    Returns vendors ordered by (preferred desc, completion_rate desc) so the agent
    sees the strongest options first. Each entry includes id, name, trade, zone,
    completion_rate, preferred, available.
    """
    async with async_session_factory() as session:
        stmt = select(Vendor).where(Vendor.trade == params.trade)
        if params.zone is not None:
            stmt = stmt.where(Vendor.zone == params.zone)
        if params.available_only:
            stmt = stmt.where(Vendor.available.is_(True))
        stmt = stmt.order_by(Vendor.preferred.desc(), Vendor.completion_rate.desc()).limit(
            params.limit
        )
        rows = (await session.execute(stmt)).scalars().all()

    vendors = [
        {
            "id": str(v.id),
            "name": v.name,
            "trade": v.trade,
            "zone": v.zone,
            "completion_rate": v.completion_rate,
            "preferred": v.preferred,
            "available": v.available,
        }
        for v in rows
    ]
    return _ok({"count": len(vendors), "vendors": vendors})


class DispatchVendorInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    work_order_id: UUID = Field(..., description="UUID of the work order to dispatch")
    vendor_id: UUID = Field(..., description="UUID of the vendor selected from search_vendors")


@mcp.tool(
    name="dispatch_vendor",
    annotations={
        "title": "Dispatch vendor to work order",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def dispatch_vendor(params: DispatchVendorInput) -> str:
    """Assign a vendor to an existing work order and mark the work order 'dispatched'.

    Fails if the work order or vendor does not exist, or if the work order is not in
    the 'open' state.
    """
    async with async_session_factory() as session:
        wo = (
            await session.execute(select(WorkOrder).where(WorkOrder.id == params.work_order_id))
        ).scalar_one_or_none()
        if wo is None:
            return _err(f"work_order {params.work_order_id} not found")
        if wo.status != "open":
            return _err(f"work_order {params.work_order_id} is in status '{wo.status}', expected 'open'")

        vendor = (
            await session.execute(select(Vendor).where(Vendor.id == params.vendor_id))
        ).scalar_one_or_none()
        if vendor is None:
            return _err(f"vendor {params.vendor_id} not found")

        wo.vendor_id = vendor.id
        wo.status = "dispatched"
        session.add(wo)
        await session.commit()
        return _ok(
            {
                "work_order_id": str(wo.id),
                "vendor_id": str(vendor.id),
                "vendor_name": vendor.name,
                "status": wo.status,
            }
        )


if __name__ == "__main__":
    # MCP_TRANSPORT=streamable-http for docker / remote, stdio for local CLIs.
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
