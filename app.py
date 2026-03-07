"""
app.py — Flask application entry point.

Responsibilities:
  1. Serve the Meta webhook (GET for verification, POST for inbound messages)
  2. Start APScheduler background jobs on startup
  3. Initialize the SQLite database on first run

Inbound message routing is handled by tools/claude_agent.py.
Claude decides what action to take; this file executes it.
"""

import os
import logging
import threading
from collections import deque
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATUS_TOKEN = os.getenv("STATUS_TOKEN", "")

# ── In-memory error log (últimos 20 errores, persiste mientras el proceso corra) ──
_recent_errors: deque = deque(maxlen=20)


class _ErrorCollector(logging.Handler):
    """Logging handler que acumula registros ERROR+ en _recent_errors."""
    def emit(self, record: logging.LogRecord) -> None:
        _recent_errors.append({
            "time": self.formatter.formatTime(record) if self.formatter else record.asctime,
            "logger": record.name,
            "message": record.getMessage(),
        })


_err_handler = _ErrorCollector()
_err_handler.setLevel(logging.ERROR)
_err_handler.setFormatter(logging.Formatter("%(asctime)s"))
logging.getLogger().addHandler(_err_handler)

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
        try:
            from tools.alert_handler import send_critical_alert
            send_critical_alert("webhook_error", str(exc))
        except Exception:
            pass


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
    """Ask Claude what to do, then execute its decision."""
    from tools.phone_normalizer import normalize_to_e164, to_whatsapp_format
    from tools.db_clients import get_client_by_phone
    from tools.db_appointments import get_latest_appointment_for_client
    from tools.whatsapp_sender import mark_message_read
    import tools.claude_agent as claude_agent

    # Normalize incoming phone (WhatsApp sends without '+')
    phone_e164 = normalize_to_e164("+" + sender_raw)
    if not phone_e164:
        logger.warning(f"[route] Could not normalize phone: {sender_raw}")
        return

    wa_phone = to_whatsapp_format(phone_e164)
    mark_message_read(message_id)

    # Look up client and latest appointment
    client = get_client_by_phone(phone_e164)
    appt = get_latest_appointment_for_client(client["id"]) if client else None

    # Log inbound message (requires client to exist)
    if client:
        _log_inbound(message, message_id, appt, client)

    # Get conversation history
    history = _get_conversation_history(phone_e164, n=10)

    # Extract message text for the agent
    message_text = _extract_message_text(message)

    logger.info(f"[route] {phone_e164} → \"{message_text[:60]}\"")

    # Ask Claude what to do
    result = claude_agent.run(
        message_text=message_text,
        client=client,
        appointment=appt,
        history=history,
        wa_phone=wa_phone,
        phone_e164=phone_e164,
    )

    logger.info(f"[route] Claude decision: tool={result.get('tool')}")

    # Execute Claude's decision
    _execute_action(result, client, appt, wa_phone, phone_e164)

    # Sync to Sheets after any action (background, no-op if GOOGLE_SHEETS_ID not set)
    threading.Thread(target=_sheets_sync_safe, daemon=True).start()


def _extract_message_text(message: dict) -> str:
    """Extract displayable text from any message type."""
    msg_type = message.get("type", "")
    if msg_type == "text":
        return message.get("text", {}).get("body", "")
    elif msg_type == "interactive":
        reply = (
            message.get("interactive", {}).get("button_reply")
            or message.get("interactive", {}).get("list_reply", {})
        )
        return reply.get("title", reply.get("id", "")) if reply else ""
    else:
        return f"[{msg_type}]"


def _get_conversation_history(phone_e164: str, n: int = 10) -> list:
    """Fetch last n messages for this phone from message_log."""
    from tools.db_init import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ml.direction, ml.content, ml.sent_at
            FROM message_log ml
            JOIN clients c ON ml.client_id = c.id
            WHERE c.phone = ?
            ORDER BY ml.sent_at DESC
            LIMIT ?
            """,
            (phone_e164, n),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def _execute_action(result: dict, client, appointment, wa_phone: str, phone_e164: str) -> None:
    """Execute the tool decision returned by claude_agent.run()."""
    from tools.whatsapp_sender import send_text_message
    from tools.db_appointments import update_appointment_status
    from tools.calendar_writer import mark_confirmed
    from tools.escalation_handler import (
        escalate_to_human,
        notify_owner_cancellation,
        notify_owner_reschedule_request,
    )

    tool = result.get("tool")
    inp = result.get("input", {})

    try:
        if tool == "send_message":
            send_text_message(
                to=wa_phone,
                text=inp["message"],
                client_id=client["id"] if client else None,
                appointment_id=appointment["id"] if appointment else None,
            )

        elif tool == "confirm_appointment":
            appt_id = inp["appointment_id"]
            update_appointment_status(appt_id, "confirmed")
            try:
                mark_confirmed(appointment["google_event_id"])
            except Exception as exc:
                logger.warning(f"[execute] Calendar confirm failed: {exc}")
            send_text_message(
                to=wa_phone,
                text=inp["response_message"],
                client_id=client["id"] if client else None,
                appointment_id=appt_id,
            )

        elif tool == "cancel_appointment":
            # Handoff to human — the owner resolves the cancellation directly in Calendar
            send_text_message(
                to=wa_phone,
                text=inp["response_message"],
                client_id=client["id"] if client else None,
                appointment_id=appointment["id"] if appointment else None,
            )
            notify_owner_cancellation(appointment, client)
            escalate_to_human(
                to_phone=wa_phone,
                client_name=client["name"] if client else "cliente",
                appointment_id=appointment["id"] if appointment else None,
                client_id=client["id"] if client else None,
            )

        elif tool == "reschedule_appointment":
            # Handoff to human — the owner coordinates the new slot with the client
            send_text_message(
                to=wa_phone,
                text=inp["response_message"],
                client_id=client["id"] if client else None,
                appointment_id=appointment["id"] if appointment else None,
            )
            notify_owner_reschedule_request(appointment, client)
            escalate_to_human(
                to_phone=wa_phone,
                client_name=client["name"] if client else "cliente",
                appointment_id=appointment["id"] if appointment else None,
                client_id=client["id"] if client else None,
            )

        elif tool == "escalate_to_human":
            escalate_to_human(
                to_phone=wa_phone,
                client_name=client["name"] if client else "cliente",
                appointment_id=appointment["id"] if appointment else None,
                client_id=client["id"] if client else None,
            )

        else:
            logger.warning(f"[execute] Unknown tool from Claude: {tool!r}")
            send_text_message(
                to=wa_phone,
                text="Disculpa, tuve un problema técnico. En unos minutos te contactamos.",
                client_id=client["id"] if client else None,
            )

    except Exception as exc:
        logger.error(f"[execute] Error executing tool '{tool}': {exc}", exc_info=True)
        try:
            send_text_message(
                to=wa_phone,
                text="Disculpa, ocurrió un error. En unos minutos te contactamos.",
            )
        except Exception:
            pass


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


def _sheets_sync_safe() -> None:
    """Sync silencioso a Google Sheets. No falla el flujo principal si hay error."""
    try:
        from tools.sheets_sync import sync_all_to_sheets
        sync_all_to_sheets()
    except Exception as exc:
        logger.warning(f"[sheets] Sync en background falló: {exc}")


# ── Health check ───────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ── Status panel ───────────────────────────────────────────────────────────────

@app.route("/status", methods=["GET"])
def status():
    """
    Panel mínimo de operaciones. Requiere ?token=STATUS_TOKEN.
    Retorna JSON con estado del bot, citas de hoy, últimos mensajes y errores recientes.
    """
    if not STATUS_TOKEN or request.args.get("token") != STATUS_TOKEN:
        return jsonify({"error": "Forbidden"}), 403

    from tools.db_init import get_connection
    import datetime
    import pytz

    TZ = pytz.timezone("America/Mexico_City")
    now_local = datetime.datetime.now(TZ)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_end = now_local.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    db_path = os.getenv("DATABASE_PATH", ".tmp/salon.db")
    db_size_kb = 0
    try:
        db_size_kb = round(os.path.getsize(db_path) / 1024, 1)
    except OSError:
        pass

    conn = get_connection()
    try:
        appointments_today = [
            dict(r)
            for r in conn.execute(
                """
                SELECT a.id, a.service, a.stylist, a.start_time, a.status,
                       c.name AS client_name, c.phone AS client_phone
                FROM appointments a
                LEFT JOIN clients c ON a.client_id = c.id
                WHERE a.start_time >= ? AND a.start_time <= ?
                ORDER BY a.start_time
                """,
                (today_start, today_end),
            ).fetchall()
        ]

        last_messages = [
            dict(r)
            for r in conn.execute(
                """
                SELECT ml.direction, ml.content, ml.sent_at,
                       c.name AS client_name
                FROM message_log ml
                LEFT JOIN clients c ON ml.client_id = c.id
                ORDER BY ml.sent_at DESC
                LIMIT 10
                """,
            ).fetchall()
        ]
    finally:
        conn.close()

    return jsonify({
        "bot": "ok",
        "timestamp": now_local.isoformat(),
        "db_path": db_path,
        "db_size_kb": db_size_kb,
        "appointments_today_count": len(appointments_today),
        "appointments_today": appointments_today,
        "last_10_messages": list(reversed(last_messages)),
        "recent_errors": list(_recent_errors),
    }), 200


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _startup()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
else:
    # Running under gunicorn — startup must still be called
    _startup()
