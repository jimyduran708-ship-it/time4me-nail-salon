"""
test_create_event.py — Crea un evento de prueba en Google Calendar.

El evento usa el formato exacto que el bot espera:
  Título:       "Uñas acrílicas - Carmen"
  Descripción:  "Cliente: Test Simulación\nTeléfono: +523312345678\nNotas: prueba"

El evento empieza 25 horas desde ahora para pasar los filtros de sync (72h)
y de recordatorio (24h).

Guarda el event_id en .tmp/sim_event_id.txt para que los otros scripts lo lean.

Uso:
    python tools/test_create_event.py
    python tools/test_create_event.py --delete   # borra el evento guardado
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from googleapiclient.discovery import build
from tools.google_auth import get_credentials

load_dotenv()

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
EVENT_ID_FILE = ".tmp/sim_event_id.txt"

# Datos del evento de prueba
TEST_PHONE = "+523330600171"
TEST_CLIENT = "Test Simulación"
TEST_SERVICE = "Uñas acrílicas"
TEST_STYLIST = "Carmen"
HOURS_AHEAD = 25  # suficiente para sync 72h, reminder 24h, y confirmación inmediata


def _get_service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def create_test_event() -> str:
    """
    Crea el evento en Google Calendar y devuelve el event_id.
    """
    if not CALENDAR_ID:
        raise ValueError("GOOGLE_CALENDAR_ID no está configurado en .env")

    # Zona horaria de México
    tz_offset = timedelta(hours=-6)  # America/Mexico_City (UTC-6 en invierno)
    now_utc = datetime.now(timezone.utc)
    start_utc = now_utc + timedelta(hours=HOURS_AHEAD)
    end_utc = start_utc + timedelta(hours=1, minutes=30)

    # Google Calendar acepta RFC3339 con offset
    def to_rfc3339(dt: datetime) -> str:
        local = dt + tz_offset
        return local.strftime("%Y-%m-%dT%H:%M:%S") + "-06:00"

    event_body = {
        "summary": f"{TEST_SERVICE} - {TEST_STYLIST}",
        "description": (
            f"Cliente: {TEST_CLIENT}\n"
            f"Teléfono: {TEST_PHONE}\n"
            f"Notas: evento de prueba — borrar después"
        ),
        "start": {
            "dateTime": to_rfc3339(start_utc),
            "timeZone": "America/Mexico_City",
        },
        "end": {
            "dateTime": to_rfc3339(end_utc),
            "timeZone": "America/Mexico_City",
        },
    }

    service = _get_service()
    created = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
    event_id = created["id"]

    # Guardar event_id para los otros scripts
    os.makedirs(".tmp", exist_ok=True)
    with open(EVENT_ID_FILE, "w") as f:
        json.dump({"event_id": event_id, "created_at": now_utc.isoformat()}, f, indent=2)

    print(f"\n✓ Evento creado exitosamente")
    print(f"  Event ID:  {event_id}")
    print(f"  Título:    {event_body['summary']}")
    print(f"  Inicio:    {event_body['start']['dateTime']} (Mexico City)")
    print(f"  Cliente:   {TEST_CLIENT} — {TEST_PHONE}")
    print(f"\n  Guardado en: {EVENT_ID_FILE}")
    print(f"\nSiguiente paso:")
    print(f"  python tools/test_run_simulation.py")
    return event_id


def delete_test_event() -> None:
    """
    Borra el evento de prueba guardado en .tmp/sim_event_id.txt.
    """
    if not os.path.exists(EVENT_ID_FILE):
        print(f"No hay evento guardado en {EVENT_ID_FILE}")
        return

    with open(EVENT_ID_FILE) as f:
        data = json.load(f)
    event_id = data["event_id"]

    service = _get_service()
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        os.remove(EVENT_ID_FILE)
        print(f"✓ Evento {event_id} eliminado de Google Calendar")
    except Exception as exc:
        print(f"✗ Error al eliminar evento: {exc}")
        print(f"  Bórralo manualmente desde Calendar: https://calendar.google.com")


if __name__ == "__main__":
    if "--delete" in sys.argv:
        delete_test_event()
    else:
        create_test_event()
