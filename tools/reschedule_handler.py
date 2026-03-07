"""
DEPRECATED: replaced by tools/claude_agent.py + _execute_action() in app.py
reschedule_handler.py — Flujo multi-turno de reagendamiento.

Turno 1: initiate_reschedule — busca slots, envía opciones, guarda estado en DB.
Turno 2: handle_slot_selection — parsea elección del cliente, actualiza Calendar + DB,
         notifica dueña, confirma al cliente.
"""

import json
import logging
import os
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger(__name__)
TZ = pytz.timezone("America/Mexico_City")
SLOT_DURATION = int(os.getenv("SALON_SLOT_DURATION", "90"))


# ── Turno 1: ofrecer slots ─────────────────────────────────────────────────────

def initiate_reschedule(appointment: dict, client: dict, wa_phone: str) -> None:
    """
    Busca slots disponibles y los envía al cliente.
    Guarda el estado en appointments.reschedule_state para el siguiente turno.
    """
    from tools.calendar_availability import get_available_slots
    from tools.whatsapp_sender import send_text_message
    from tools.db_appointments import set_reschedule_state

    slots = get_available_slots(days_ahead=7, max_slots=5)

    if not slots:
        send_text_message(
            to=wa_phone,
            text=(
                f"Hola {client['name']}, ahorita no veo espacios libres "
                "en los próximos días. En cuanto haya disponibilidad te aviso, ¿te parece?"
            ),
        )
        logger.info(f"[reschedule] No slots available for {client['name']}")
        return

    state = {
        "slots": [s.isoformat() for s in slots],
        "offered_at": datetime.now(TZ).isoformat(),
        "old_start": appointment.get("start_time", ""),
    }
    set_reschedule_state(appointment["id"], state)

    from tools.whatsapp_templates import format_slots_message
    send_text_message(to=wa_phone, text=format_slots_message(client["name"], slots))
    logger.info(f"[reschedule] Offered {len(slots)} slots to {client['name']}")


# ── Turno 2: procesar elección ─────────────────────────────────────────────────

def handle_slot_selection(
    appointment: dict,
    client: dict,
    message: dict,
    state: dict,
    wa_phone: str,
) -> bool:
    """
    Intenta hacer match entre el mensaje del cliente y uno de los slots ofrecidos.

    Devuelve True si manejó el mensaje (éxito o re-prompt).
    Devuelve False para dejar caer al flujo normal de intents (ej. si dice "cancelar").
    """
    from tools.intent_parser import parse_slot_index, _normalize, _matches, CANCEL_KEYWORDS, CONFIRM_KEYWORDS
    from tools.whatsapp_sender import send_text_message
    from tools.whatsapp_templates import reschedule_confirmed_message
    from tools.calendar_writer import reschedule_event
    from tools.db_appointments import update_appointment_reschedule, clear_reschedule_state
    from tools.escalation_handler import notify_owner_reschedule

    # Expirar estado si tiene más de 24h
    offered_at_str = state.get("offered_at")
    if offered_at_str:
        offered_at = datetime.fromisoformat(offered_at_str)
        if offered_at.tzinfo is None:
            offered_at = TZ.localize(offered_at)
        if datetime.now(TZ) - offered_at > timedelta(hours=24):
            clear_reschedule_state(appointment["id"])
            return False

    # Reconstruir lista de slots como datetimes
    slots: list[datetime] = []
    for iso in state.get("slots", []):
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = TZ.localize(dt)
        slots.append(dt.astimezone(TZ))

    # Si el cliente dice "cancelar" o "confirmar" → dejar al flujo normal
    raw_text = message.get("text", {}).get("body", "") if message.get("type") == "text" else ""
    normalized = _normalize(raw_text)
    if _matches(normalized, CANCEL_KEYWORDS) or _matches(normalized, CONFIRM_KEYWORDS):
        clear_reschedule_state(appointment["id"])
        return False

    # Intentar parsear la elección
    chosen_idx = parse_slot_index(message, slots)

    if chosen_idx is None:
        # Re-prompt con la misma lista
        send_text_message(
            to=wa_phone,
            text=(
                "Disculpa, no entendí bien. ¿Cuál de estos horarios te queda mejor?\n\n"
                + _format_slot_list(slots)
                + "\n\nResponde con el número 😊"
            ),
        )
        return True

    chosen = slots[chosen_idx]
    new_start_iso = chosen.isoformat()
    new_end_iso = (chosen + timedelta(minutes=SLOT_DURATION)).isoformat()
    old_start = state.get("old_start", appointment.get("start_time", ""))

    # Actualizar Google Calendar
    try:
        reschedule_event(appointment["google_event_id"], new_start_iso, new_end_iso)
    except Exception as exc:
        logger.error(f"[reschedule] Failed to update Calendar: {exc}")
        send_text_message(
            to=wa_phone,
            text="Tuve un problema al mover la cita. En un momento te contactamos.",
        )
        return True

    # Actualizar DB
    update_appointment_reschedule(appointment["id"], new_start_iso, new_end_iso)
    clear_reschedule_state(appointment["id"])

    # Notificar a la dueña
    notify_owner_reschedule(appointment, client, chosen, old_start)

    # Confirmar al cliente
    send_text_message(to=wa_phone, text=reschedule_confirmed_message(client["name"], chosen))
    logger.info(f"[reschedule] Appointment {appointment['id']} rescheduled to {new_start_iso}")
    return True


def _format_slot_list(slots: list[datetime]) -> str:
    from tools.whatsapp_templates import _format_datetime
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = []
    for i, slot in enumerate(slots):
        date_str, time_str = _format_datetime(slot.isoformat())
        lines.append(f"{numbers[i]} {date_str} a las {time_str}")
    return "\n".join(lines)
