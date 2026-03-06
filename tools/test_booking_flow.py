"""
test_booking_flow.py — Simula conversacion completa de agendamiento (cliente nuevo).

Ejecuta una secuencia de mensajes pre-definida y muestra las respuestas del bot.
No hace llamadas reales a WhatsApp ni a Google Calendar.

Uso:
  PYTHONUTF8=1 python -m tools.test_booking_flow
"""

import os
import sys
import time
import json
import logging
import unittest.mock as mock
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.WARNING)

TEST_PHONE_WA  = "529900000099"
TEST_PHONE_E164 = "+529900000099"

_msg_counter = [0]
BOT   = "\033[96m"
USER  = "\033[93m"
INFO  = "\033[90m"
RESET = "\033[0m"

FAKE_EVENT_ID = "fake_calendar_event_001"

# ── Mocks ──────────────────────────────────────────────────────────────────────

def _mock_send_text(to, text, appointment_id=None, client_id=None, **kwargs):
    print(f"\n{BOT}[BOT]{RESET}  {text}\n")

def _mock_send_template(to, template, appointment_id=None, client_id=None, **kwargs):
    name = template.get("name", "template")
    components = template.get("components", [])
    parts = []
    for comp in components:
        if comp.get("type") == "body":
            for p in comp.get("parameters", []):
                if p.get("type") == "text":
                    parts.append(p["text"])
    body = " ".join(parts) if parts else json.dumps(template)[:120]
    print(f"\n{BOT}[BOT][template:{name}]{RESET}  {body}\n")

def _mock_mark_read(message_id):
    pass

def _mock_create_event(service, client_name, phone_e164, start_iso, end_iso):
    print(f"\n{INFO}[Calendar] Creando evento: {service} para {client_name} el {start_iso}{RESET}")
    return FAKE_EVENT_ID

def _mock_upsert_appointment(*args, **kwargs):
    print(f"{INFO}[DB] Cita guardada en DB{RESET}")

def _build_text_payload(text: str) -> dict:
    _msg_counter[0] += 1
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": TEST_PHONE_WA,
                        "id": f"wamid.sim_{_msg_counter[0]}_{int(time.time())}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": text},
                    }]
                }
            }]
        }]
    }

def _fake_slots():
    """Genera 5 slots falsos para no depender de Google Calendar."""
    import pytz
    tz = pytz.timezone("America/Mexico_City")
    base = datetime.now(tz).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return [base + timedelta(hours=i * 1.5) for i in range(5)]

def send(process_fn, text: str):
    print(f"{USER}[TU]{RESET}   {text}")
    payload = _build_text_payload(text)
    process_fn(payload)
    time.sleep(0.2)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  SIMULACION — Flujo completo de agendamiento (cliente nuevo)")
    print(f"  Telefono: {TEST_PHONE_E164}")
    print("=" * 60)

    with mock.patch("tools.whatsapp_sender.send_text_message",   side_effect=_mock_send_text), \
         mock.patch("tools.whatsapp_sender.send_template_message", side_effect=_mock_send_template), \
         mock.patch("tools.whatsapp_sender.mark_message_read",   side_effect=_mock_mark_read), \
         mock.patch("tools.calendar_writer.create_event",         side_effect=_mock_create_event), \
         mock.patch("tools.db_appointments.upsert_appointment",   side_effect=_mock_upsert_appointment), \
         mock.patch("tools.calendar_availability.get_available_slots", return_value=_fake_slots()):

        import app as _app  # noqa — dispara init_db
        from app import _process_webhook

        # Limpiar sesion anterior si existe (para que siempre sea cliente nuevo)
        from tools.db_init import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM booking_sessions WHERE phone = ?", (TEST_PHONE_WA,))
        conn.execute("DELETE FROM clients WHERE phone = ?", (TEST_PHONE_E164,))
        conn.commit()
        conn.close()

        print("\n--- PASO 1: Cliente envia mensaje de agendamiento ---")
        send(_process_webhook, "hola, quiero agendar una cita")

        print("--- PASO 2: Cliente da su nombre ---")
        send(_process_webhook, "Maria Lopez")

        print("--- PASO 3: Cliente elige servicio ---")
        send(_process_webhook, "Unas acrilicas")

        print("--- PASO 4: Cliente elige slot (opcion 2) ---")
        send(_process_webhook, "2")

        print("\n" + "=" * 60)
        print("  FIN DE SIMULACION")
        print("=" * 60)


if __name__ == "__main__":
    main()
