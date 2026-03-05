"""
escalation_handler.py — Handle human escalation requests and cancellation alerts.

When a client wants to speak to a person, the bot:
1. Sends the client the owner's WhatsApp contact link
2. Logs the escalation in message_log

When a cancellation happens, the bot notifies the owner via WhatsApp
so they can fill the freed slot or follow up if needed.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP", "")  # format: 521XXXXXXXXXX (no +)


def escalate_to_human(
    to_phone: str,
    client_name: str,
    appointment_id: Optional[int] = None,
    client_id: Optional[int] = None,
) -> None:
    """
    Send the owner's WhatsApp link to the client so they can reach a human directly.
    """
    from tools.whatsapp_sender import send_template_message
    from tools.whatsapp_templates import human_escalation

    template = human_escalation(client_name, OWNER_WHATSAPP)
    send_template_message(
        to=to_phone,
        template=template,
        appointment_id=appointment_id,
        client_id=client_id,
    )
    logger.info(f"[escalation] Human escalation sent to {to_phone} (client: {client_name})")


def notify_owner_cancellation(
    appointment: dict,
    client: dict,
) -> None:
    """
    Send a WhatsApp message to the owner notifying them of a cancellation.
    This lets them fill the freed slot or follow up with the client.

    Args:
        appointment: appointment dict with service, stylist, start_time
        client: client dict with name, phone
    """
    if not OWNER_WHATSAPP:
        logger.warning("[escalation] OWNER_WHATSAPP not set — skipping owner notification")
        return

    from tools.whatsapp_sender import send_text_message
    from tools.whatsapp_templates import _format_datetime

    date_str, time_str = _format_datetime(appointment.get("start_time", ""))
    service = appointment.get("service", "servicio")
    stylist = appointment.get("stylist", "sin asignar")
    client_name = client.get("name", "cliente")
    client_phone = client.get("phone", "")

    message = (
        f"⚠️ *Cancelación de cita*\n\n"
        f"👤 Cliente: {client_name}\n"
        f"📞 Tel: {client_phone}\n"
        f"💅 Servicio: {service}\n"
        f"📅 Fecha: {date_str} a las {time_str}\n"
        f"💇 Estilista: {stylist}\n\n"
        f"El slot quedó libre. ¿Quieres reagendar o dejarlo disponible?"
    )

    send_text_message(to=OWNER_WHATSAPP, text=message)
    logger.info(
        f"[escalation] Cancellation notification sent to owner for appointment {appointment.get('id')}"
    )


def notify_owner_no_phone(event_id: str, service: str, start_time: str) -> None:
    """
    Alert the owner when a Calendar event is missing a client phone number,
    so they can add it manually before the reminder job runs.
    """
    if not OWNER_WHATSAPP:
        return

    from tools.whatsapp_sender import send_text_message
    from tools.whatsapp_templates import _format_datetime

    date_str, time_str = _format_datetime(start_time)
    message = (
        f"⚠️ *Cita sin teléfono registrado*\n\n"
        f"💅 Servicio: {service}\n"
        f"📅 Fecha: {date_str} a las {time_str}\n"
        f"🗓️ ID de evento: {event_id}\n\n"
        f"Por favor agrega el teléfono del cliente en la descripción del evento "
        f"para que pueda enviarle el recordatorio."
    )

    send_text_message(to=OWNER_WHATSAPP, text=message)
    logger.warning(f"[escalation] Missing phone alert sent for event {event_id}")
