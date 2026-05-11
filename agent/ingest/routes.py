import base64
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from agent.db.engine import async_session_factory, get_session
from agent.db.models import Client
from agent.ingest.gmail_client import get_message, list_new_message_ids
from agent.ingest.normalize import normalize_gmail_message
from agent.ingest.persist import persist_email
from agent.ingest.schemas import GmailNotification, GmailPushPayload
from agent.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["ingest"])


async def fetch_and_persist(client_id, history_id: int) -> None:
    """Pull new messages from Gmail since the client's last seen history id, persist them.

    Runs as a FastAPI BackgroundTask — after the webhook's 200 has been flushed.
    Opens its own session because the request-scoped session is gone by the time
    this runs.
    """
    async with async_session_factory() as session:
        client = await session.get(Client, client_id)
        if client is None:
            logger.error("background fetch: client %s vanished between webhook and task", client_id)
            return

        start = client.gmail_history_id or history_id
        try:
            message_ids = await list_new_message_ids(client, start)
        except Exception:
            logger.exception("Gmail history.list failed for client %s", client.id)
            return

        for message_id in message_ids:
            try:
                message = await get_message(client, message_id)
                normalized = normalize_gmail_message(message)
                await persist_email(client, normalized, session)
            except Exception:
                logger.exception(
                    "Failed to fetch/persist message %s for client %s", message_id, client.id
                )

        client.gmail_history_id = history_id
        session.add(client)
        await session.commit()


@router.post("/gmail", status_code=status.HTTP_200_OK)
async def gmail_webhook(
    payload: GmailPushPayload,
    background_tasks: BackgroundTasks,
    token: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    expected = settings.gmail_pubsub_verification_token
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid pubsub verification token")

    try:
        decoded = base64.urlsafe_b64decode(payload.message.data).decode("utf-8")
        notification = GmailNotification.model_validate(json.loads(decoded))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not decode pubsub message: {exc}")

    result = await session.execute(
        select(Client).where(Client.gmail_address == notification.email_address)
    )
    client = result.scalar_one_or_none()
    if client is None:
        # Unknown mailbox — ack the push so Pub/Sub stops retrying. Surfacing this
        # as a 404 would just generate retry storms.
        logger.warning("gmail push for unknown mailbox: %s", notification.email_address)
        return {"status": "ignored", "reason": "unknown_mailbox"}

    background_tasks.add_task(fetch_and_persist, client.id, notification.history_id)
    return {"status": "accepted"}
