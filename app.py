"""
app.py — Flask application entry point.

Responsibilities:
  1. Serve the Meta webhook (GET for verification, POST for inbound messages)
  2. Start APScheduler background jobs on startup
  3. Initialize the SQLite database on first run

Inbound message routing:
  confirm    → mark appointment confirmed, update Calendar label
  cancel     → cancel appointment in DB + Calendar, notify owner, offer reschedule
  reschedule → escalate to human (owner handles manually)
  human      → send owner's WhatsApp link to client
  upsell_yes / upsell_no → log response
  unknown    → escalate to human
"""

import json
import os
import logging
import threading
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")


# ── Startup ────────────────────────────────────────────────────────────────────

def _startup() -> None:
    """Initialize DB and start scheduler. Called once after app is ready."""
    from tools.db_init import init_db
    from tools.reminder_scheduler import create_scheduler, sync_calendar_to_db

    init_db()

    scheduler = create_scheduler()
    scheduler.start()
    logger.info("[app] APScheduler started with %d jobs", len(scheduler.get_jobs()))

    # Run an immediate sync so new deploys don't have to wait 30 minutes
    threading.Thread(target=sync_calendar_to_db, daemon=True).start()


# ── Webhook ────────────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def webhook_verify():
    """Meta webhook verification handshake."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("[webhook] Verification successful")
        return challenge, 200
    logger.warning("[webhook] Verification failed — token mismatch")
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook_receive():
    """
    Receive inbound WhatsApp events from Meta.
    Always returns 200 immediately; processing happens in a background thread.
    """
    data = request.get_json(silent=True) or {}
    threading.Thread(target=_process_webhook, args=(data,), daemon=True).start()
    return jsonify({"status": "ok"}), 200


def _process_webhook(data: dict) -> None:
    """Process a webhook payload in a background thread."""
    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        # Handle message status updates (delivered, read) — just log, no action needed
        if "statuses" in value:
            return

        messages = value.get("messages", [])
        if not messages:
            return

        message = messages[0]
        sender_raw = message.get("from", "")
        message_id = message.get("id", "")

        # Dedup: skip if we already processed this message_id
        if _already_processed(message_id):
            return

        _route_message(sender_raw, message, message_id)

    except Exception as exc:
        logger.error(f"[webhook] Unhandled error in _process_webhook: {exc}", exc_info=True)


def _already_processed(whatsapp_message_id: str) -> bool:
    """Check message_log for duplicate delivery."""
    if not whatsapp_message_id:
        return False
    from tools.db_init import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM message_log WHERE whatsapp_message_id = ? AND direction = 'inbound'",
            (whatsapp_message_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _route_message(sender_raw: str, message: dict, message_id: str) -> None:
    """Look up client and appointment, then dispatch by intent."""
    from tools.phone_normalizer import normalize_to_e164, to_whatsapp_format
    from tools.db_clients import get_client_by_phone
    from tools.db_appointments import (
        get_latest_appointment_for_client,
        update_appointment_status,
        set_client_response,
    )
    from tools.intent_parser import parse_intent
    from tools.whatsapp_sender import send_template_message, send_text_message, mark_message_read
    from tools.whatsapp_templates import (
        cancellation_confirmed, appointment_confirmed_reply,
    )
    from tools.calendar_writer import mark_confirmed, mark_cancelled
    from tools.escalation_handler import escalate_to_human, notify_owner_cancellation
    from tools.db_init import get_connection

    # Normalize incoming phone (WhatsApp sends without '+')
    phone_e164 = normalize_to_e164("+" + sender_raw)
    if not phone_e164:
        logger.warning(f"[route] Could not normalize phone: {sender_raw}")
        return

    wa_phone = to_whatsapp_format(phone_e164)
    mark_message_read(message_id)

    # ── Active booking session? Route to booking handler first ─────────────────
    from tools.booking_handler import get_booking_session, handle_booking_step
    booking_session = get_booking_session(wa_phone)
    if booking_session:
        handle_booking_step(booking_session, message, wa_phone, phone_e164)
        return

    # Look up client
    client = get_client_by_phone(phone_e164)
    if not client:
        # Unknown client — start booking flow if they want to book, else escalate
        if parse_intent(message) == "book":
            from tools.booking_handler import start_booking
            logger.info(f"[route] New client {phone_e164} wants to book")
            start_booking(wa_phone, phone_e164, client=None)
        else:
            logger.info(f"[route] Unknown sender {phone_e164} — escalating to human")
            escalate_to_human(wa_phone, "cliente")
        return

    # Log inbound message
    appt = get_latest_appointment_for_client(client["id"])
    _log_inbound(message, message_id, appt, client)

    # If client is mid-reschedule, try to handle slot selection first
    reschedule_state = json.loads(appt.get("reschedule_state") or "null") if appt else None
    if reschedule_state:
        from tools.reschedule_handler import handle_slot_selection
        if handle_slot_selection(appt, client, message, reschedule_state, wa_phone):
            return

    # Determine context for upsell intent disambiguation
    context = "upsell" if (appt and appt.get("upsell_sent_at") and not appt.get("client_response")) else "reminder"
    intent = parse_intent(message, context=context)
    logger.info(f"[route] Intent={intent} for client {client['name']} ({phone_e164})")

    if intent == "confirm":
        if appt:
            update_appointment_status(appt["id"], "confirmed")
            try:
                mark_confirmed(appt["google_event_id"])
            except Exception as exc:
                logger.warning(f"[route] Could not label Calendar event as confirmed: {exc}")
            # Freeform reply is valid because client just messaged us (within 24h window)
            send_text_message(
                to=wa_phone,
                text=appointment_confirmed_reply(client["name"]),
                appointment_id=appt["id"],
                client_id=client["id"],
            )

    elif intent == "cancel":
        if appt:
            update_appointment_status(appt["id"], "cancelled")
            try:
                mark_cancelled(appt["google_event_id"])
            except Exception as exc:
                logger.warning(f"[route] Could not cancel Calendar event: {exc}")
            notify_owner_cancellation(appt, client)
            template = cancellation_confirmed(
                client_name=client["name"],
                start_time_iso=appt["start_time"],
                service=appt.get("service") or "tu servicio",
            )
            send_template_message(
                to=wa_phone,
                template=template,
                appointment_id=appt["id"],
                client_id=client["id"],
            )

    elif intent == "book":
        from tools.booking_handler import start_booking
        start_booking(wa_phone, phone_e164, client=client)

    elif intent == "reschedule":
        if appt:
            from tools.reschedule_handler import initiate_reschedule
            initiate_reschedule(appt, client, wa_phone)
        else:
            escalate_to_human(
                to_phone=wa_phone,
                client_name=client["name"],
                appointment_id=None,
                client_id=client["id"],
            )

    elif intent in ("human", "unknown"):
        escalate_to_human(
            to_phone=wa_phone,
            client_name=client["name"],
            appointment_id=appt["id"] if appt else None,
            client_id=client["id"],
        )

    elif intent in ("upsell_yes", "upsell_no"):
        if appt:
            set_client_response(appt["id"], intent)
        logger.info(f"[route] Upsell response logged: {intent}")

    else:
        logger.warning(f"[route] Unhandled intent: {intent}")


def _log_inbound(message: dict, message_id: str, appt, client: dict) -> None:
    """Persist inbound message to message_log."""
    from tools.db_init import get_connection
    msg_type = message.get("type", "")
    if msg_type == "text":
        content = message.get("text", {}).get("body", "")
    elif msg_type == "interactive":
        reply = message.get("interactive", {}).get("button_reply", {})
        content = reply.get("title", reply.get("id", ""))
    else:
        content = f"[{msg_type}]"

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO message_log
                (appointment_id, client_id, direction, message_type, content, whatsapp_message_id)
            VALUES (?, ?, 'inbound', 'freeform', ?, ?)
            """,
            (appt["id"] if appt else None, client["id"], content, message_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── Health check ───────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _startup()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
else:
    # Running under gunicorn — startup must still be called
    _startup()
