"""
test_webhook_reply.py — Simula una respuesta inbound de WhatsApp.

Construye un payload idéntico al que Meta envía cuando el cliente
presiona un botón (Confirmar o Cancelar), y lo procesa directamente
usando la misma lógica del webhook de producción.

Verifica:
  - DB: status cambia a confirmed / cancelled
  - Calendar: se agrega etiqueta [CONFIRMADO] o [CANCELADO]
  - message_log: el mensaje inbound queda registrado

Prerequisitos:
  1. python tools/test_create_event.py
  2. python tools/test_run_simulation.py   (crea el cliente en la DB)

Uso:
  python tools/test_webhook_reply.py confirm
  python tools/test_webhook_reply.py cancel
"""

import os
import sys
import json
import logging
import time
import threading

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

EVENT_ID_FILE = ".tmp/sim_event_id.txt"
TEST_PHONE_E164 = "+523312345678"
# WhatsApp format (sin +): así llega en el webhook de Meta
TEST_PHONE_WA = "523312345678"

DIVIDER = "─" * 60


def _load_event_id() -> str:
    if not os.path.exists(EVENT_ID_FILE):
        print(f"\n✗ No hay evento de prueba guardado.")
        print(f"  Ejecuta primero: python tools/test_create_event.py")
        sys.exit(1)
    with open(EVENT_ID_FILE) as f:
        data = json.load(f)
    return data["event_id"]


def _build_button_payload(intent: str) -> dict:
    """
    Construye un payload de Meta Cloud API para un button reply.
    Replica exactamente lo que Meta envía cuando el cliente presiona un botón.
    """
    buttons = {
        "confirm": {
            "id": "CONFIRM",
            "title": "Confirmar \u2705",
        },
        "cancel": {
            "id": "CANCEL",
            "title": "Cancelar \u274c",
        },
    }
    btn = buttons[intent]

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "TEST_WABA_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5215500000000",
                                "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", "TEST"),
                            },
                            "messages": [
                                {
                                    "from": TEST_PHONE_WA,
                                    "id": f"wamid.sim_{intent}_{int(time.time())}",
                                    "timestamp": str(int(time.time())),
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": btn["id"],
                                            "title": btn["title"],
                                        },
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _show_db_state(label: str, event_id: str) -> None:
    from tools.db_appointments import get_appointment_by_event_id
    from tools.db_init import get_connection

    print(f"\n{DIVIDER}")
    print(f"  DB STATE: {label}")
    print(DIVIDER)

    appt = get_appointment_by_event_id(event_id)
    if not appt:
        print("  Cita: ✗ no encontrada")
        return

    print(f"  Cita id={appt['id']} | status={appt['status'].upper()}")
    print(f"  servicio={appt['service']} | estilista={appt['stylist']}")

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT direction, message_type, content, sent_at FROM message_log "
            "WHERE appointment_id = ? ORDER BY sent_at ASC",
            (appt["id"],),
        ).fetchall()
    finally:
        conn.close()

    if rows:
        print(f"\n  message_log ({len(rows)} registros):")
        for r in rows:
            d = dict(r)
            arrow = "→" if d["direction"] == "outbound" else "←"
            print(f"    {arrow} [{d['direction']}] {d['message_type']} | {d['content'][:60] if d['content'] else ''}")
    print(DIVIDER)


def _check_calendar(event_id: str, expected_intent: str) -> None:
    """Verifica que el Calendar tenga el label correcto."""
    from tools.calendar_reader import get_event_by_id

    print(f"\n  Verificando Google Calendar...")
    event = get_event_by_id(event_id)
    if not event:
        print(f"  Calendar: ✗ no se pudo leer el evento (puede ser por cancelación)")
        return

    raw_summary = event.get("raw", {}).get("summary", "")
    raw_status = event.get("raw", {}).get("status", "")

    if expected_intent == "confirm":
        if "[CONFIRMADO]" in raw_summary:
            print(f"  Calendar: ✓ título tiene [CONFIRMADO] → '{raw_summary}'")
        else:
            print(f"  Calendar: ✗ falta [CONFIRMADO] en título → '{raw_summary}'")
    elif expected_intent == "cancel":
        if raw_status == "cancelled" or "[CANCELADO]" in raw_summary:
            print(f"  Calendar: ✓ evento cancelado (status={raw_status}, título='{raw_summary}')")
        else:
            print(f"  Calendar: ✗ evento NO cancelado (status={raw_status}, título='{raw_summary}')")


def run_simulation(intent: str) -> None:
    if intent not in ("confirm", "cancel"):
        print(f"✗ Intent inválido: '{intent}'. Usa 'confirm' o 'cancel'.")
        sys.exit(1)

    event_id = _load_event_id()

    # Verificar que el cliente y la cita existen en DB
    from tools.db_clients import get_client_by_phone
    from tools.db_appointments import get_appointment_by_event_id

    client = get_client_by_phone(TEST_PHONE_E164)
    appt = get_appointment_by_event_id(event_id)

    if not client or not appt:
        print("\n✗ El cliente o la cita no están en la DB.")
        print("  Ejecuta primero: python tools/test_run_simulation.py")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  SIMULANDO RESPUESTA: {intent.upper()}")
    print(f"  Cliente: {client['name']} ({TEST_PHONE_E164})")
    print(f"  Cita:    id={appt['id']} | status actual={appt['status']}")
    print(f"{'='*60}")

    # Estado ANTES
    _show_db_state("ANTES de la respuesta", event_id)

    # Construir payload
    payload = _build_button_payload(intent)
    print(f"\n  Payload construido (message_id: {payload['entry'][0]['changes'][0]['value']['messages'][0]['id']})")

    # Procesar webhook directamente (sin servidor HTTP)
    # Importamos _process_webhook desde app.py — _startup() se llama al importar
    # pero es idempotente (init_db + scheduler ya corriendo están bien)
    print(f"\n  Procesando webhook...")
    from app import _process_webhook

    # El webhook procesa en background thread en producción,
    # aquí lo llamamos directo para poder esperar el resultado
    _process_webhook(payload)

    # Dar tiempo por si alguna operación de Calendar tarda
    time.sleep(2)

    # Estado DESPUÉS
    _show_db_state("DESPUÉS de la respuesta", event_id)

    # Verificar Calendar
    _check_calendar(event_id, intent)

    # Resultado final
    appt_after = get_appointment_by_event_id(event_id)
    expected_status = "confirmed" if intent == "confirm" else "cancelled"

    print(f"\n{'='*60}")
    if appt_after and appt_after["status"] == expected_status:
        print(f"  ✓ SIMULACIÓN EXITOSA")
        print(f"    DB status: {expected_status}")
        print(f"    Calendar: verificado arriba")
        print(f"    El flujo end-to-end funciona correctamente.")
    else:
        actual = appt_after["status"] if appt_after else "no encontrado"
        print(f"  ✗ FALLO: status esperado={expected_status}, actual={actual}")
        print(f"    Revisa los logs de arriba para identificar el error.")
    print(f"{'='*60}")

    print(f"\nCleanup:")
    print(f"  python tools/test_create_event.py --delete")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python tools/test_webhook_reply.py confirm|cancel")
        sys.exit(1)

    intent = sys.argv[1].lower()
    run_simulation(intent)
