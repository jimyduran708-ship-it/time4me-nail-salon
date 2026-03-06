"""
calendar_availability.py — Encuentra slots libres en Google Calendar.

Configurable via env vars (con defaults razonables para un salón):
  SALON_OPEN_HOUR      int  hora de apertura en 24h (default: 10)
  SALON_CLOSE_HOUR     int  hora de cierre en 24h   (default: 19)
  SALON_OPEN_DAYS      csv  días abiertos 0=lun…6=dom (default: 0,1,2,3,4,5)
  SALON_SLOT_DURATION  int  minutos por cita          (default: 90)
"""

import os
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

from tools.calendar_reader import get_upcoming_events

load_dotenv()

TZ = pytz.timezone("America/Mexico_City")
OPEN_HOUR = int(os.getenv("SALON_OPEN_HOUR", "10"))
CLOSE_HOUR = int(os.getenv("SALON_CLOSE_HOUR", "19"))
SLOT_DURATION = int(os.getenv("SALON_SLOT_DURATION", "90"))
OPEN_DAYS = set(int(d) for d in os.getenv("SALON_OPEN_DAYS", "0,1,2,3,4,5").split(","))


def get_available_slots(days_ahead: int = 7, max_slots: int = 5) -> list[datetime]:
    """
    Devuelve hasta max_slots datetimes libres (zona Mexico_City) en los
    próximos days_ahead días, excluyendo horarios con eventos existentes.
    """
    existing = get_upcoming_events(hours_ahead=days_ahead * 24)
    busy: list[tuple[datetime, datetime]] = []
    for evt in existing:
        if evt.get("status") == "cancelled":
            continue
        s = _parse_dt(evt.get("start_time"))
        e = _parse_dt(evt.get("end_time"))
        if s and e:
            busy.append((s, e))

    now = datetime.now(TZ)
    # Empezar como mínimo 1 hora desde ahora, redondeado a la hora
    start_from = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    slots: list[datetime] = []
    slot_delta = timedelta(minutes=SLOT_DURATION)
    current_day = start_from
    days_checked = 0

    while len(slots) < max_slots and days_checked <= days_ahead:
        if current_day.weekday() in OPEN_DAYS:
            day_open = current_day.replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0)
            day_close = current_day.replace(hour=CLOSE_HOUR, minute=0, second=0, microsecond=0)
            candidate = day_open if day_open >= current_day else current_day

            while candidate + slot_delta <= day_close:
                if not _overlaps(candidate, candidate + slot_delta, busy):
                    slots.append(candidate)
                    if len(slots) >= max_slots:
                        break
                candidate += slot_delta

        current_day = (current_day + timedelta(days=1)).replace(
            hour=OPEN_HOUR, minute=0, second=0, microsecond=0
        )
        days_checked += 1

    return slots


def _parse_dt(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = TZ.localize(dt)
        return dt.astimezone(TZ)
    except Exception:
        return None


def _overlaps(start: datetime, end: datetime, busy: list[tuple]) -> bool:
    for b_start, b_end in busy:
        if start < b_end and end > b_start:
            return True
    return False
