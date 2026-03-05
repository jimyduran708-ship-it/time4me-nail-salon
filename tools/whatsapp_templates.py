"""
whatsapp_templates.py — Message template factory for Time 4 me Nail Salón.

No API calls here. Each function returns a dict ready to pass to
whatsapp_sender.send_template_message() or send_interactive_message().

All templates must be pre-approved by Meta before use.
Template names must match exactly what was approved in Meta Business Manager.
"""

from datetime import datetime
import pytz

SALON_TIMEZONE = pytz.timezone("America/Mexico_City")

DAYS_ES = {
    0: "lunes", 1: "martes", 2: "miércoles",
    3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo",
}
MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _format_datetime(iso_str: str) -> tuple[str, str]:
    """
    Convert ISO UTC string to local date and time strings in Spanish.
    Returns: ("sábado 14 de junio", "11:00 AM")
    """
    dt_utc = datetime.fromisoformat(iso_str).replace(tzinfo=pytz.utc)
    dt_local = dt_utc.astimezone(SALON_TIMEZONE)
    day_name = DAYS_ES[dt_local.weekday()]
    month_name = MONTHS_ES[dt_local.month]
    date_str = f"{day_name} {dt_local.day} de {month_name}"
    hour = dt_local.strftime("%I").lstrip("0") or "12"
    time_str = f"{hour}:{dt_local.strftime('%M')} {dt_local.strftime('%p').replace('AM', 'a.m.').replace('PM', 'p.m.')}"
    return date_str, time_str


# ── Template builders ──────────────────────────────────────────────────────────

def booking_confirmation(
    client_name: str,
    service: str,
    start_time_iso: str,
    stylist: str,
) -> dict:
    """
    Template: time4me_confirmacion_cita
    Sent immediately when appointment is created in Google Calendar.
    """
    date_str, time_str = _format_datetime(start_time_iso)
    return {
        "template_name": "time4me_confirmacion_cita",
        "params": [client_name, service, date_str, time_str, stylist],
    }


def appointment_reminder(
    client_name: str,
    service: str,
    start_time_iso: str,
    stylist: str,
) -> dict:
    """
    Template: time4me_recordatorio_cita
    Sent the morning before the appointment with interactive buttons.
    Includes quick-reply buttons for confirm / cancel / human.
    """
    date_str, time_str = _format_datetime(start_time_iso)
    return {
        "template_name": "time4me_recordatorio_cita",
        "params": [client_name, service, date_str, time_str, stylist],
        "buttons": [
            {"type": "reply", "reply": {"id": "CONFIRM", "title": "Confirmar ✅"}},
            {"type": "reply", "reply": {"id": "CANCEL", "title": "Cancelar ❌"}},
            {"type": "reply", "reply": {"id": "HUMAN", "title": "Hablar con alguien 💬"}},
        ],
    }


def cancellation_confirmed(
    client_name: str,
    start_time_iso: str,
    service: str,
) -> dict:
    """
    Template: time4me_cancelacion_confirmada
    Sent after processing a client cancellation. Offers to reschedule.
    """
    date_str, _ = _format_datetime(start_time_iso)
    return {
        "template_name": "time4me_cancelacion_confirmada",
        "params": [client_name, date_str, service],
    }


def upsell_prompt(client_name: str) -> dict:
    """
    Template: time4me_upsell_servicios
    Sent ~30 min after the reminder to prompt additional service interest.
    """
    return {
        "template_name": "time4me_upsell_servicios",
        "params": [client_name],
    }


def no_show_followup(client_name: str) -> dict:
    """
    Template: time4me_noshow_reagendar
    Sent after marking an appointment as no_show.
    """
    return {
        "template_name": "time4me_noshow_reagendar",
        "params": [client_name],
    }


def human_escalation(client_name: str, owner_whatsapp: str) -> dict:
    """
    Template: time4me_escalacion_humano
    Sent to the client when they request to speak to a person.
    Includes the owner's WhatsApp number.
    """
    return {
        "template_name": "time4me_escalacion_humano",
        "params": [client_name, f"wa.me/{owner_whatsapp}"],
    }


def appointment_confirmed_reply(client_name: str) -> str:
    """
    Freeform reply after client confirms (valid within 24h customer service window).
    Returns plain text — use send_text_message(), not send_template_message().
    """
    return f"¡Perfecto, {client_name}! Tu cita quedó confirmada. ¡Te esperamos! 💅"
