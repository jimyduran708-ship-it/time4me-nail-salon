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
