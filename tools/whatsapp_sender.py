"""
whatsapp_sender.py — Send WhatsApp messages via Meta Cloud API.

Handles template messages, interactive messages (quick-reply buttons),
and freeform text (only valid within a 24h customer service window).

All sends are logged to message_log via db_appointments helpers.
Retries up to 3 times with exponential backoff on transient errors.
"""

import os
import time
import logging
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
API_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]  # seconds between retries


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _post_with_retry(payload: dict) -> dict:
    """POST to Meta API with exponential backoff on 429/5xx."""
    last_error = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        resp = requests.post(BASE_URL, json=payload, headers=_headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504):
            logger.warning(
                f"[whatsapp] Attempt {attempt+1} failed ({resp.status_code}), "
                f"retrying in {delay}s…"
            )
            last_error = resp
            time.sleep(delay)
        else:
            # Client error (4xx) — no point retrying
            logger.error(f"[whatsapp] Send failed {resp.status_code}: {resp.text}")
            resp.raise_for_status()

    logger.error(f"[whatsapp] All retries exhausted. Last status: {last_error.status_code}")
    last_error.raise_for_status()


def _log_message(
    appointment_id: Optional[int],
    client_id: Optional[int],
    direction: str,
    message_type: str,
    content: str,
    whatsapp_message_id: Optional[str] = None,
) -> None:
    """Persist message to message_log table."""
    try:
        from tools.db_init import get_connection
        conn = get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO message_log
                (appointment_id, client_id, direction, message_type, content, whatsapp_message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (appointment_id, client_id, direction, message_type, content, whatsapp_message_id),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning(f"[whatsapp] Failed to log message: {exc}")


# ── Public API ─────────────────────────────────────────────────────────────────

def send_template_message(
    to: str,
    template: dict,
    appointment_id: int = None,
    client_id: int = None,
) -> dict:
    """
    Send a pre-approved Meta template message.

    Args:
        to: WhatsApp-format phone (no '+', e.g. "523312345678")
        template: dict from whatsapp_templates.py, with keys:
                  template_name (str), params (list[str]),
                  optionally buttons (list[dict])
        appointment_id / client_id: for logging

    Returns Meta API response dict.
    """
    template_name = template["template_name"]
    params = template.get("params", [])
    buttons = template.get("buttons")

    components = []

    # Body parameters
    if params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        })

    # Interactive quick-reply buttons
    if buttons:
        for idx, btn in enumerate(buttons):
            components.append({
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(idx),
                "parameters": [{"type": "payload", "payload": btn["reply"]["id"]}],
            })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "es_MX"},
            "components": components,
        },
    }

    response = _post_with_retry(payload)
    wa_id = response.get("messages", [{}])[0].get("id")
    _log_message(appointment_id, client_id, "outbound", template_name,
                 str(params), wa_id)
    return response


def send_text_message(
    to: str,
    text: str,
    appointment_id: int = None,
    client_id: int = None,
) -> dict:
    """
    Send a freeform text message.
    Only valid within a 24h customer service window (client messaged us first).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    response = _post_with_retry(payload)
    wa_id = response.get("messages", [{}])[0].get("id")
    _log_message(appointment_id, client_id, "outbound", "freeform", text, wa_id)
    return response


def mark_message_read(message_id: str) -> None:
    """Send a read receipt for an inbound message."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    try:
        requests.post(BASE_URL, json=payload, headers=_headers(), timeout=5)
    except Exception as exc:
        logger.warning(f"[whatsapp] Failed to send read receipt: {exc}")
