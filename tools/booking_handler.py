"""
DEPRECATED: replaced by tools/claude_agent.py + _execute_action() in app.py
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
                  slots_json=None, offered_at=None, proposed_slot=None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO booking_sessions
                (phone, client_id, step, service, slots_json, offered_at, proposed_slot)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                client_id     = excluded.client_id,
                step          = excluded.step,
                service       = excluded.service,
                slots_json    = excluded.slots_json,
                offered_at    = excluded.offered_at,
                proposed_slot = excluded.proposed_slot
            """,
            (phone, client_id, step, service, slots_json, offered_at, proposed_slot),
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

_NAME_PREFIXES = [
    "me llamo ", "soy ", "mi nombre es ", "me dicen ", "me llaman ",
    "mi nombre: ", "nombre: ", "llamame ", "llamame ", "me puedes llamar ",
    "pueden llamarme ", "soy la ", "soy el ",
]
_HONORIFICS = ["senora ", "senor ", "senorita ", "sra ", "sr ", "srta "]

_STRONG_CANCEL = {"cancelar", "ya no", "no quiero", "no gracias", "olvida", "olvidalo", "olvidalo"}
_AFFIRMATIVE = {
    "si", "sí", "claro", "perfecto", "ok", "okay", "dale", "va", "listo",
    "ese", "me funciona", "bien", "de acuerdo", "por supuesto", "me queda",
    "ese me queda", "ese horario", "ahi", "ahí", "perfecto", "andale", "ándale",
}


def _extract_name(text: str) -> str:
    """Elimina frases de presentación y regresa el nombre en Title Case."""
    cleaned = text.strip().lower()
    for prefix in _NAME_PREFIXES:
        if cleaned.startswith(prefix):
            text = text.strip()[len(prefix):]
            cleaned = text.lower()
            break
    for hon in _HONORIFICS:
        if cleaned.startswith(hon):
            text = text.strip()[len(hon):]
            break
    return text.strip().title()


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else full_name


def _load_slots(session: dict) -> list:
    """Reconstruye la lista de datetimes desde el JSON guardado en sesión."""
    slots = []
    for iso in json.loads(session.get("slots_json") or "[]"):
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = TZ.localize(dt)
        slots.append(dt.astimezone(TZ))
    return slots


def start_booking(wa_phone: str, phone_e164: str, client: dict | None) -> None:
    """
    Entry point: client expressed intent to book.
    If known client → ask for service directly.
    If new client  → ask for name first.
    """
    from tools.whatsapp_sender import send_text_message

    if client:
        first = _first_name(client["name"])
        _save_session(wa_phone, step="ask_service", client_id=client["id"])
        send_text_message(
            to=wa_phone,
            text=f"¡Hola, {first}! Con gusto te agendo una cita. ¿Qué servicio te gustaría?",
        )
    else:
        _save_session(wa_phone, step="ask_name")
        send_text_message(
            to=wa_phone,
            text=(
                "¡Hola! Bienvenida a Time 4 me Nail Salón. "
                "Con gusto te ayudo a agendar tu cita. "
                "¿Me podrías dar tu nombre completo?"
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
    elif step == "ask_confirm_slot":
        _handle_ask_confirm_slot(session, message, wa_phone, phone_e164)
    else:
        logger.warning(f"[booking] Unknown step '{step}' for {wa_phone}")
        _clear_session(wa_phone)


# ── Step handlers ──────────────────────────────────────────────────────────────

def _handle_ask_name(session: dict, message: dict, wa_phone: str, phone_e164: str) -> None:
    from tools.whatsapp_sender import send_text_message
    from tools.db_clients import get_or_create_client

    if message.get("type") != "text":
        send_text_message(to=wa_phone, text="¿Me podrías escribir tu nombre completo?")
        return

    raw = message["text"]["body"].strip()
    name = _extract_name(raw)
    if len(name) < 2:
        send_text_message(to=wa_phone, text="¿Me podrías escribir tu nombre completo?")
        return

    client, _ = get_or_create_client(name=name, phone=phone_e164)
    _save_session(wa_phone, step="ask_service", client_id=client["id"])

    send_text_message(
        to=wa_phone,
        text=f"¡Mucho gusto, {_first_name(client['name'])}! ¿Qué servicio te gustaría para tu cita?",
    )
    logger.info(f"[booking] Got name '{name}' for {wa_phone}")


def _handle_ask_service(session: dict, message: dict, wa_phone: str) -> None:
    from tools.whatsapp_sender import send_text_message
    from tools.calendar_availability import get_available_slots

    if message.get("type") != "text":
        send_text_message(to=wa_phone, text="¿Qué servicio te gustaría?")
        return

    service = message["text"]["body"].strip()
    if len(service) < 2:
        send_text_message(to=wa_phone, text="¿Qué servicio te gustaría?")
        return

    slots = get_available_slots(days_ahead=7, max_slots=6)
    if not slots:
        send_text_message(
            to=wa_phone,
            text=(
                "Por el momento no tenemos horarios disponibles en los próximos días. "
                "Te contactamos en cuanto tengamos un espacio libre. ¡Disculpa!"
            ),
        )
        _clear_session(wa_phone)
        logger.info(f"[booking] No slots available for {wa_phone}")
        return

    client_id = session.get("client_id")
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
        text=(
            f"¡Perfecto! ¿Tienes alguna preferencia de día u horario? "
            "Trabajamos de lunes a sábado de 10:00 a.m. a 7:00 p.m. 😊"
        ),
    )
    logger.info(f"[booking] Asking slot preference for service '{service}' to {wa_phone}")


def _handle_ask_slot(
    session: dict, message: dict, wa_phone: str, phone_e164: str
) -> None:
    """Parsea preferencia de horario → propone el mejor slot → avanza a ask_confirm_slot."""
    from tools.whatsapp_sender import send_text_message
    from tools.intent_parser import parse_preferred_slot, _normalize, _matches, CANCEL_KEYWORDS
    from tools.db_clients import get_client_by_id
    from tools.whatsapp_templates import _format_datetime

    slots = _load_slots(session)

    if message.get("type") == "text":
        normalized = _normalize(message["text"]["body"])
        if _matches(normalized, CANCEL_KEYWORDS) and any(kw in normalized for kw in _STRONG_CANCEL):
            _clear_session(wa_phone)
            send_text_message(to=wa_phone, text="Sin problema, cuando quieras escríbenos. ¡Que tengas bonito día! 😊")
            return

    best_idx = parse_preferred_slot(message, slots)
    if best_idx is None:
        best_idx = 0  # default al primer slot disponible

    proposed = slots[best_idx]
    client_id = session.get("client_id")

    _save_session(
        wa_phone,
        step="ask_confirm_slot",
        client_id=client_id,
        service=session.get("service"),
        slots_json=session.get("slots_json"),
        proposed_slot=proposed.isoformat(),
    )

    date_str, time_str = _format_datetime(proposed.isoformat())
    send_text_message(
        to=wa_phone,
        text=f"Tengo disponible el {date_str} a las {time_str} — ¿te funciona ese horario? 😊",
    )
    logger.info(f"[booking] Proposed slot {proposed.isoformat()} to {wa_phone}")


def _handle_ask_confirm_slot(
    session: dict, message: dict, wa_phone: str, phone_e164: str
) -> None:
    """Cliente confirma o rechaza el slot propuesto."""
    from tools.whatsapp_sender import send_text_message
    from tools.intent_parser import parse_intent, _normalize, _matches, CANCEL_KEYWORDS
    from tools.calendar_writer import create_event
    from tools.db_appointments import upsert_appointment
    from tools.db_clients import get_client_by_id, get_or_create_client
    from tools.whatsapp_templates import _format_datetime

    normalized = _normalize(message.get("text", {}).get("body", "")) if message.get("type") == "text" else ""

    # Cancelación explícita → terminar sesión
    if any(kw in normalized for kw in _STRONG_CANCEL):
        _clear_session(wa_phone)
        send_text_message(to=wa_phone, text="Sin problema, cuando quieras escríbenos. ¡Que tengas bonito día! 😊")
        return

    intent = parse_intent(message, context="reminder")
    is_yes = intent == "confirm" or _matches(normalized, _AFFIRMATIVE)
    is_no = intent == "cancel" or "no" in normalized.split()

    if is_yes:
        # Crear evento con el slot propuesto
        proposed_iso = session.get("proposed_slot")
        if not proposed_iso:
            _clear_session(wa_phone)
            return

        proposed = datetime.fromisoformat(proposed_iso)
        if proposed.tzinfo is None:
            proposed = TZ.localize(proposed)
        end_dt = proposed + timedelta(minutes=SLOT_DURATION)
        service = session.get("service", "Servicio")

        client_id = session.get("client_id")
        client = get_client_by_id(client_id) if client_id else None
        if not client:
            client, _ = get_or_create_client(name="Cliente", phone=phone_e164)

        try:
            event_id = create_event(
                service=service,
                client_name=client["name"],
                phone_e164=phone_e164,
                start_iso=proposed.isoformat(),
                end_iso=end_dt.isoformat(),
            )
        except Exception as exc:
            logger.error(f"[booking] Failed to create Calendar event: {exc}")
            send_text_message(to=wa_phone, text="Tuve un problema al agendar. En un momento te contactamos. ¡Disculpa!")
            return

        upsert_appointment(
            event_id,
            client_id=client["id"],
            service=service,
            stylist="Por asignar",
            start_time=proposed.isoformat(),
            end_time=end_dt.isoformat(),
            status="pending",
        )

        _clear_session(wa_phone)

        date_str, time_str = _format_datetime(proposed.isoformat())
        first = _first_name(client["name"])
        send_text_message(
            to=wa_phone,
            text=(
                f"¡Listo, {first}! Quedaste agendada para el {date_str} "
                f"a las {time_str} — {service}. "
                "En breve recibirás tu confirmación. ¡Te esperamos! 💅"
            ),
        )
        logger.info(f"[booking] Booked {client['name']} — event {event_id} at {proposed.isoformat()}")

    elif is_no:
        # Proponer el siguiente slot disponible
        slots = _load_slots(session)
        proposed_iso = session.get("proposed_slot", "")
        next_slot = next((s for s in slots if s.isoformat() != proposed_iso), None)

        if not next_slot:
            _clear_session(wa_phone)
            send_text_message(
                to=wa_phone,
                text="Por el momento no tengo más horarios disponibles. Te contactamos en cuanto tengamos un espacio. ¡Disculpa! 🙏",
            )
            return

        _save_session(
            wa_phone,
            step="ask_confirm_slot",
            client_id=session.get("client_id"),
            service=session.get("service"),
            slots_json=session.get("slots_json"),
            proposed_slot=next_slot.isoformat(),
        )

        date_str, time_str = _format_datetime(next_slot.isoformat())
        send_text_message(
            to=wa_phone,
            text=f"Sin problema. También tengo el {date_str} a las {time_str} — ¿te queda bien ese? 😊",
        )

    else:
        # Respuesta ambigua → pedir confirmación de nuevo
        proposed_iso = session.get("proposed_slot", "")
        if proposed_iso:
            proposed = datetime.fromisoformat(proposed_iso)
            if proposed.tzinfo is None:
                proposed = TZ.localize(proposed)
            date_str, time_str = _format_datetime(proposed.isoformat())
            send_text_message(
                to=wa_phone,
                text=f"Disculpa, no te entendí bien. ¿El {date_str} a las {time_str} te funciona? 😊",
            )
