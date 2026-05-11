import base64
from datetime import datetime, timezone
from typing import Any

from agent.ingest.schemas import NormalizedEmail


def _decode_b64url(data: str) -> str:
    """Gmail encodes message body parts as base64url with optional padding stripped."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")


def _find_plain_text_body(payload: dict[str, Any]) -> str:
    """Walk a Gmail payload tree and return the first text/plain body found.

    Falls back to the top-level body, then to an empty string. HTML is intentionally
    not unwrapped here — the pre-filter and extraction prompts work on plain text.
    """
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})

    if mime_type == "text/plain" and body.get("data"):
        return _decode_b64url(body["data"])

    for part in payload.get("parts", []) or []:
        found = _find_plain_text_body(part)
        if found:
            return found

    if body.get("data"):
        return _decode_b64url(body["data"])

    return ""


def _header(headers: list[dict[str, str]], name: str) -> str:
    target = name.lower()
    for h in headers:
        if h.get("name", "").lower() == target:
            return h.get("value", "")
    return ""


def normalize_gmail_message(message: dict[str, Any]) -> NormalizedEmail:
    """Convert a Gmail `users.messages.get(format=full)` response into a NormalizedEmail."""
    payload = message.get("payload", {})
    headers = payload.get("headers", [])

    body = _find_plain_text_body(payload)
    subject = _header(headers, "Subject")
    from_address = _header(headers, "From")

    internal_ms = message.get("internalDate")
    if internal_ms is not None:
        received_at = datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc)
    else:
        received_at = datetime.now(timezone.utc)

    return NormalizedEmail(
        source="gmail",
        source_message_id=message["id"],
        from_address=from_address,
        subject=subject,
        body=body,
        received_at=received_at,
        raw_payload=message,
    )
