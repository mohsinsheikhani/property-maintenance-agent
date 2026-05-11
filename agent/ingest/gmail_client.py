"""Thin wrapper over the Gmail API for ingest.

Only the calls ingest needs: `history.list` (find new message ids since a checkpoint)
and `messages.get` (fetch one message in full). Both wrap synchronous googleapiclient
calls in `asyncio.to_thread` so the webhook handler can await them without blocking
the event loop.

Per-client OAuth credentials live in `clients.oauth_tokens` and get rebuilt into a
`Credentials` object on each call. That is wasteful, but keeps the surface small and
avoids holding refresh tokens in memory across requests. Optimize if it ever shows up
in latency traces.
"""

from __future__ import annotations

import asyncio
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from agent.db.models import Client
from agent.settings import settings

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)


def _credentials_for(client: Client) -> Credentials:
    if not client.oauth_tokens:
        raise RuntimeError(
            f"Client {client.id} has no oauth_tokens — Gmail API calls are unavailable."
        )
    return Credentials(
        token=client.oauth_tokens.get("access_token"),
        refresh_token=client.oauth_tokens.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.gmail_oauth_client_id,
        client_secret=settings.gmail_oauth_client_secret,
        scopes=list(SCOPES),
    )


def _service_for(client: Client):
    return build("gmail", "v1", credentials=_credentials_for(client), cache_discovery=False)


async def list_new_message_ids(client: Client, start_history_id: int) -> list[str]:
    def _call() -> list[str]:
        service = _service_for(client)
        message_ids: list[str] = []
        request = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=start_history_id, historyTypes=["messageAdded"])
        )
        while request is not None:
            response = request.execute()
            for history in response.get("history", []) or []:
                for added in history.get("messagesAdded", []) or []:
                    msg = added.get("message", {})
                    if msg.get("id"):
                        message_ids.append(msg["id"])
            request = (
                service.users().history().list_next(previous_request=request, previous_response=response)
            )
        return message_ids

    return await asyncio.to_thread(_call)


async def get_message(client: Client, message_id: str) -> dict[str, Any]:
    def _call() -> dict[str, Any]:
        service = _service_for(client)
        return service.users().messages().get(userId="me", id=message_id, format="full").execute()

    return await asyncio.to_thread(_call)
