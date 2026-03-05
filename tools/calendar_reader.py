"""
calendar_reader.py — Read appointments from Google Calendar.

Uses a Service Account (server-to-server auth, no OAuth refresh needed).
The service account JSON path is set via GOOGLE_SERVICE_ACCOUNT_JSON in .env.

Google Calendar event convention for this salon:
  Title:       "<Service> - <Stylist>"   e.g. "Uñas acrílicas - Carmen"
  Description: Multi-line block:
                 Cliente: María López
                 Teléfono: +523312345678
                 Notas: alergia a acrílicos
"""

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from googleapiclient.discovery import build
from dotenv import load_dotenv
from tools.google_auth import get_credentials

load_dotenv()

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")


def _get_service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def _parse_description(description: str) -> dict:
    """
    Extract structured fields from the event description block.
    Returns dict with keys: client_name, phone, notes (all optional).
    """
    result = {"client_name": None, "phone": None, "notes": None}
    if not description:
        return result

    for line in description.splitlines():
        line = line.strip()
        if re.match(r"(?i)cliente\s*:", line):
            result["client_name"] = re.sub(r"(?i)cliente\s*:", "", line).strip()
        elif re.match(r"(?i)tel[eé]fono\s*:", line):
            result["phone"] = re.sub(r"(?i)tel[eé]fono\s*:", "", line).strip()
        elif re.match(r"(?i)notas?\s*:", line):
            result["notes"] = re.sub(r"(?i)notas?\s*:", "", line).strip()
    return result


def _parse_title(title: str) -> dict:
    """
    Extract service and stylist from event title.
    Expected format: "Service - Stylist"
    If no " - " separator, the whole title is treated as the service.
    """
    if " - " in title:
        parts = title.split(" - ", 1)
        return {"service": parts[0].strip(), "stylist": parts[1].strip()}
    return {"service": title.strip(), "stylist": None}


def _event_to_dict(event: dict) -> dict:
    """Convert a Google Calendar event resource to a flat dict."""
    title_parts = _parse_title(event.get("summary", ""))
    desc_parts = _parse_description(event.get("description", ""))

    start = event.get("start", {})
    end = event.get("end", {})
    start_dt = start.get("dateTime") or start.get("date")
    end_dt = end.get("dateTime") or end.get("date")

    return {
        "google_event_id": event["id"],
        "service": title_parts["service"],
        "stylist": title_parts["stylist"],
        "client_name": desc_parts["client_name"],
        "phone": desc_parts["phone"],
        "notes": desc_parts["notes"],
        "start_time": start_dt,
        "end_time": end_dt,
        "status": event.get("status", "confirmed"),  # Google: confirmed|tentative|cancelled
        "raw": event,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def get_upcoming_events(hours_ahead: int = 72, calendar_id: str = None) -> list[dict]:
    """
    Return events starting within the next `hours_ahead` hours.
    Includes cancelled events so the sync job can update their status.
    """
    cal_id = calendar_id or CALENDAR_ID
    if not cal_id:
        raise ValueError("GOOGLE_CALENDAR_ID not set in environment")

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=hours_ahead)).isoformat()

    service = _get_service()
    result = service.events().list(
        calendarId=cal_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        showDeleted=True,   # include cancelled events for sync purposes
        maxResults=250,
    ).execute()

    events = result.get("items", [])
    return [_event_to_dict(e) for e in events]


def get_event_by_id(event_id: str, calendar_id: str = None) -> Optional[dict]:
    """Fetch a single event by ID."""
    cal_id = calendar_id or CALENDAR_ID
    if not cal_id:
        raise ValueError("GOOGLE_CALENDAR_ID not set in environment")
    service = _get_service()
    try:
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        return _event_to_dict(event)
    except Exception:
        return None
