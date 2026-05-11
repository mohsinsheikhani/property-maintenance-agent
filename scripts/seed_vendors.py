"""Seed a small set of dummy vendors so Step 6 (vendor selection) has options.

Idempotent: skips trades that already have rows for the seed client.

Run:
    uv run python -m scripts.seed_vendors
"""

import asyncio

from sqlalchemy import select

from agent.db.engine import async_session_factory
from agent.db.models import Client, Vendor

_SEED_CLIENT_NAME = "Seed Property Manager (fixture)"

# (name, trade, zone, completion_rate, preferred)
_FIXTURES: list[tuple[str, str, str, float, bool]] = [
    # plumbing
    ("Metro Plumbing", "plumbing", "sydney_cbd", 0.96, True),
    ("ClearFlow", "plumbing", "sydney_cbd", 0.89, False),
    ("QuickFix Plumbers", "plumbing", "sydney_cbd", 0.75, False),
    # electrical
    ("Bright Spark Electrical", "electrical", "sydney_cbd", 0.94, True),
    ("Wattline", "electrical", "sydney_cbd", 0.82, False),
    # hvac
    ("CoolAir HVAC", "hvac", "sydney_cbd", 0.92, True),
    ("ThermoPro", "hvac", "sydney_cbd", 0.80, False),
    # locksmith
    ("KeyMasters", "locksmith", "sydney_cbd", 0.95, True),
    # general
    ("Handy Hands", "general", "sydney_cbd", 0.88, True),
    # pest
    ("PestPatrol", "pest", "sydney_cbd", 0.90, True),
    # appliance
    ("Appliance Pros", "appliance", "sydney_cbd", 0.91, True),
    ("FixIt Appliances", "appliance", "sydney_cbd", 0.77, False),
]


async def main() -> None:
    async with async_session_factory() as session:
        client = (
            await session.execute(select(Client).where(Client.name == _SEED_CLIENT_NAME))
        ).scalar_one_or_none()
        if client is None:
            raise SystemExit(f"seed client {_SEED_CLIENT_NAME!r} missing; load fixtures first")

        existing = {
            row[0]
            for row in (
                await session.execute(
                    select(Vendor.name).where(Vendor.client_id == client.id)
                )
            ).all()
        }

        added = 0
        for name, trade, zone, completion, preferred in _FIXTURES:
            if name in existing:
                continue
            session.add(
                Vendor(
                    client_id=client.id,
                    name=name,
                    trade=trade,
                    zone=zone,
                    completion_rate=completion,
                    preferred=preferred,
                    available=True,
                )
            )
            added += 1
        await session.commit()
        print(f"seeded {added} new vendor row(s); {len(existing)} already present")


if __name__ == "__main__":
    asyncio.run(main())
