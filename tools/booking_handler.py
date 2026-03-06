"""
booking_handler.py — Multi-turn booking flow via WhatsApp.

Allows clients (known or new) to book an appointment directly through WhatsApp.

State machine (stored in booking_sessions table, keyed by phone):
  ask_name    → collect client full name (new clients only)
  ask_service → collect desired service
  ask_slot    → show available slots, collect selection

Calendar event is created following the salon convention:
  Title:       "{service} - Por asignar"
  Description: "Cliente: {name}\\nTeléfono: {phone}"

Usage (from app.py):
  session = get_booking_session(wa_phone)
  if session:
      handle_booking_step(session, message, wa_phone, phone_e164)
      return
"""

import json
import logging
import os
from datetime import datetime, timedelta

import pytz

from tools.db_init import get_connection

logger = logging.getLogger(__name__)
TZ = pytz.timezone("America/Mexico_City")
SLOT_DURATION = int(os.getenv("SALON_SLOT_DURATION", "90"))


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_booking_session(phone: str) -> dict | None:
    """Return active booking session for this phone, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM booking_sessions WHERE phone = ?", (phone,)
        ).fetchone()
        if not row:
            return None
        session = dict(row)
        # Expire sessions older than 2 hours
        created = datetime.fromisoformat(session["created_at"])
        if created.tzinfo is None:
            created = TZ.localize(created)
        if datetime.now(TZ) - created > timedelta(hours=2):
            _clear_session(phone)
            return None
        return session
    finally:
        conn.close()


def _save_session(phone: str, step: str, client_id=None, service=None,
                  slots_json=None, offered_at=None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO booking_sessions (phone, client_id, step, service, slots_json, offered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                client_id  = excluded.client_id,
                step       = excluded.step,
                service    = excluded.service,
                slots_json = excluded.slots_json,
                offered_at = excluded.offered_at
            """,
            (phone, client_id, step, service, slots_json, offered_at),
        )
        conn.commit()
    finally:
        conn.close()


def _clear_session(phone: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM booking_sessions WHERE phone = ?", (phone,))
        conn.commit()
    finally:
        conn.close()


# ── Public API ─────────────────────────────────────────────────────────────────

def start_booking(wa_phone: str, phone_e164: str, client: dict | None) -> None:
    """
    Entry point: client expressed intent to book.
    If known client → ask for service directly.
    If new client  → ask for name first.
    """
    from tools.whatsapp_sender import send_text_message

    if client:
        _save_session(wa_phone, step="ask_service", client_id=client["id"])
        send_text_message(
            to=wa_phone,
            text=(
                f"Hola {client['name']}! Para agendar tu cita, "
                "dime que servicio te gustaria:\n\n"
                "Manicure / Pedicure / Unas acrilicas / Unas en gel / "
                "Spa de manos / Exfoliacion de pies / Otro"
            ),
        )
    else:
        _save_session(wa_phone, step="ask_name")
        send_text_message(
            to=wa_phone,
            text=(
                "Hola! Bienvenida a Time 4 me Nail Salon. "
                "Para agendar tu cita, primero dime tu nombre completo."
            ),
        )
    logger.info(f"[booking] Started booking flow for {wa_phone}")


def handle_booking_step(
    session: dict, message: dict, wa_phone: str, phone_e164: str
) -> None:
    """Dispatch to the correct handler based on the current step."""
    step = session["step"]

    if step == "ask_name":
        _handle_ask_name(session, message, wa_phone, phone_e164)
    elif step == "ask_service":
        _handle_ask_service(session, message, wa_phone)
    elif step == "ask_slot":
        _handle_ask_slot(session, message, wa_phone, phone_e164)
    else:
        logger.warning(f"[booking] Unknown step '{step}' for {wa_phone}")
        _clear_session(wa_phone)


# ── Step handlers ──────────────────────────────────────────────────────────────

def _handle_ask_name(session: dict, message: dict, wa_phone: str, phone_e164: str) -> None:
    from tools.whatsapp_sender import send_text_message
    from tools.db_clients import get_or_create_client

    if message.get("type") != "text":
        send_text_message(to=wa_phone, text="Por favor escribe tu nombre completo.")
        return

    name = message["text"]["body"].strip()
    if len(name) < 2:
        send_text_message(to=wa_phone, text="Por favor escribe tu nombre completo.")
        return

    client = get_or_create_client(name=name, phone=phone_e164)
    _save_session(wa_phone, step="ask_service", client_id=client["id"])

    send_text_message(
        to=wa_phone,
        text=(
            f"Mucho gusto, {client['name']}! "
            "Dime que servicio te gustaria:\n\n"
            "Manicure / Pedicure / Unas acrilicas / Unas en gel / "
            "Spa de manos / Exfoliacion de pies / Otro"
        ),
    )
    logger.info(f"[booking] Got name '{name}' for {wa_phone}")


def _handle_ask_service(session: dict, message: dict, wa_phone: str) -> None:
    from tools.whatsapp_sender import send_text_message
    from tools.calendar_availability import get_available_slots
    from tools.whatsapp_templates import format_slots_message
    from tools.db_clients import get_client_by_id

    if message.get("type") != "text":
        send_text_message(to=wa_phone, text="Por favor escribe el servicio que deseas.")
        return

    service = message["text"]["body"].strip()
    if len(service) < 2:
        send_text_message(to=wa_phone, text="Por favor escribe el servicio que deseas.")
        return

    slots = get_available_slots(days_ahead=7, max_slots=5)
    if not slots:
        send_text_message(
            to=wa_phone,
            text=(
                "Por el momento no tenemos horarios disponibles en los proximos dias. "
                "Te contactamos en cuanto haya un espacio libre!"
            ),
        )
        _clear_session(wa_phone)
        logger.info(f"[booking] No slots available for {wa_phone}")
        return

    client_id = session.get("client_id")
    client = get_client_by_id(client_id) if client_id else None
    client_name = client["name"] if client else "!"

    slots_json = json.dumps([s.isoformat() for s in slots])
    _save_session(
        wa_phone,
        step="ask_slot",
        client_id=client_id,
        service=service,
        slots_json=slots_json,
        offered_at=datetime.now(TZ).isoformat(),
    )

    send_text_message(
        to=wa_phone,
        text=format_slots_message(client_name, slots),
    )
    logger.info(f"[booking] Offered slots for service '{service}' to {wa_phone}")


def _handle_ask_slot(
    session: dict, message: dict, wa_phone: str, phone_e164: str
) -> None:
    from tools.whatsapp_sender import send_text_message
    from tools.intent_parser import parse_slot_index, _normalize, _matches, CANCEL_KEYWORDS
    from tools.calendar_writer import create_event
    from tools.db_appointments import upsert_appointment
    from tools.db_clients import get_client_by_id, get_or_create_client
    from tools.whatsapp_templates import _format_datetime

    # Rebuild slot list
    slots: list[datetime] = []
    for iso in json.loads(session.get("slots_json") or "[]"):
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = TZ.localize(dt)
        slots.append(dt.astimezone(TZ))

    # If client says "cancel" → abort flow
    if message.get("type") == "text":
        normalized = _normalize(message["text"]["body"])
        if _matches(normalized, CANCEL_KEYWORDS):
            _clear_session(wa_phone)
            send_text_message(
                to=wa_phone,
                text="Sin problema, cuando quieras agendar tu cita escríbenos.",
            )
            return

    chosen_idx = parse_slot_index(message, slots)
    if chosen_idx is None:
        from tools.reschedule_handler import _format_slot_list
        send_text_message(
            to=wa_phone,
            text=(
                "Disculpa, no entendi bien. Cual de estos horarios te queda mejor?\n\n"
                + _format_slot_list(slots)
                + "\n\nResponde con el numero."
            ),
        )
        return

    chosen = slots[chosen_idx]
    end_dt = chosen + timedelta(minutes=SLOT_DURATION)
    start_iso = chosen.isoformat()
    end_iso = end_dt.isoformat()
    service = session.get("service", "Servicio")

    # Get or create client
    client_id = session.get("client_id")
    client = get_client_by_id(client_id) if client_id else None
    if not client:
        client = get_or_create_client(name="Cliente", phone=phone_e164)

    # Create Google Calendar event
    try:
        event_id = create_event(
            service=service,
            client_name=client["name"],
            phone_e164=phone_e164,
            start_iso=start_iso,
            end_iso=end_iso,
        )
    except Exception as exc:
        logger.error(f"[booking] Failed to create Calendar event: {exc}")
        send_text_message(
            to=wa_phone,
            text="Tuve un problema al agendar. En un momento te contactamos para confirmar.",
        )
        return

    # Persist in DB
    upsert_appointment(
        event_id,
        client_id=client["id"],
        service=service,
        stylist="Por asignar",
        start_time=start_iso,
        end_time=end_iso,
        status="pending",
    )

    _clear_session(wa_phone)

    # Confirm to client
    date_str, time_str = _format_datetime(start_iso)
    send_text_message(
        to=wa_phone,
        text=(
            f"Listo, {client['name']}! Tu cita quedo agendada:\n\n"
            f"Servicio: {service}\n"
            f"Fecha: {date_str}\n"
            f"Hora: {time_str}\n\n"
            "Te llegara una confirmacion en breve. Te esperamos!"
        ),
    )
    logger.info(
        f"[booking] Appointment created for {client['name']} — event {event_id} at {start_iso}"
    )
