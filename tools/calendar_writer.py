"""
calendar_writer.py — Write operations on Google Calendar.

Cancels events and updates title labels. Does NOT delete events —
cancelled events are kept for historical record.
"""

import os
from googleapiclient.discovery import build
from dotenv import load_dotenv
from tools.google_auth import get_credentials

load_dotenv()

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

LABEL_CANCELLED = "[CANCELADO]"
LABEL_CONFIRMED = "[CONFIRMADO]"
LABEL_NO_SHOW = "[NO SHOW]"


def _get_service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def _get_event(service, calendar_id: str, event_id: str) -> dict:
    return service.events().get(calendarId=calendar_id, eventId=event_id).execute()


# ── Public API ─────────────────────────────────────────────────────────────────

def cancel_event(event_id: str, calendar_id: str = None) -> None:
    """
    Mark a Google Calendar event as cancelled.
    Sets event.status = 'cancelled'. Keeps the event for historical record.
    Idempotent — safe to call on an already-cancelled event.
    """
    cal_id = calendar_id or CALENDAR_ID
    service = _get_service()
    event = _get_event(service, cal_id, event_id)

    if event.get("status") == "cancelled":
        return  # already cancelled, nothing to do

    event["status"] = "cancelled"
    service.events().update(
        calendarId=cal_id, eventId=event_id, body=event
    ).execute()


def add_label_to_event(event_id: str, label: str, calendar_id: str = None) -> None:
    """
    Prepend a label to the event title if not already present.
    e.g. "Uñas acrílicas - Carmen" → "[CONFIRMADO] Uñas acrílicas - Carmen"
    """
    cal_id = calendar_id or CALENDAR_ID
    service = _get_service()
    event = _get_event(service, cal_id, event_id)

    current_title = event.get("summary", "")
    if current_title.startswith(label):
        return  # label already applied

    # Remove any previous status label before adding the new one
    for existing_label in (LABEL_CANCELLED, LABEL_CONFIRMED, LABEL_NO_SHOW):
        if current_title.startswith(existing_label):
            current_title = current_title[len(existing_label):].strip()
            break

    event["summary"] = f"{label} {current_title}"
    service.events().update(
        calendarId=cal_id, eventId=event_id, body=event
    ).execute()


def mark_confirmed(event_id: str, calendar_id: str = None) -> None:
    add_label_to_event(event_id, LABEL_CONFIRMED, calendar_id)


def mark_cancelled(event_id: str, calendar_id: str = None) -> None:
    cancel_event(event_id, calendar_id)
    add_label_to_event(event_id, LABEL_CANCELLED, calendar_id)


def mark_no_show(event_id: str, calendar_id: str = None) -> None:
    add_label_to_event(event_id, LABEL_NO_SHOW, calendar_id)


def create_event(
    service: str,
    client_name: str,
    phone_e164: str,
    start_iso: str,
    end_iso: str,
    stylist: str = "Por asignar",
    notes: str = "",
    calendar_id: str = None,
) -> str:
    """
    Create a new appointment event following the salon convention:
      Title:       "{service} - {stylist}"
      Description: "Cliente: {name}\\nTeléfono: {phone}[\\nNotas: ...]"

    Returns the created Google Calendar event_id.
    """
    cal_id = calendar_id or CALENDAR_ID
    svc = _get_service()

    description = f"Cliente: {client_name}\nTeléfono: {phone_e164}"
    if notes:
        description += f"\nNotas: {notes}"

    event_body = {
        "summary": f"{service} - {stylist}",
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": "America/Mexico_City"},
        "end": {"dateTime": end_iso, "timeZone": "America/Mexico_City"},
    }
    created = svc.events().insert(calendarId=cal_id, body=event_body).execute()
    return created["id"]


def reschedule_event(event_id: str, new_start_iso: str, new_end_iso: str, calendar_id: str = None) -> None:
    """
    Mueve un evento a un nuevo horario sin cancelarlo.
    new_start_iso / new_end_iso: ISO 8601 con offset (ej. "2026-03-09T10:00:00-06:00")
    """
    cal_id = calendar_id or CALENDAR_ID
    service = _get_service()
    event = _get_event(service, cal_id, event_id)

    # Conservar timezone del evento original o usar el del string recibido
    tz = event.get("start", {}).get("timeZone", "America/Mexico_City")
    event["start"] = {"dateTime": new_start_iso, "timeZone": tz}
    event["end"] = {"dateTime": new_end_iso, "timeZone": tz}

    service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
