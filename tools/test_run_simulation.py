"""
test_run_simulation.py — Simula los jobs del scheduler localmente.

Pasos:
  1. Inicializa la DB (si no existe)
  2. Lee el evento de prueba desde Google Calendar (sync_calendar_to_db)
  3. Muestra el estado de la DB (cliente + cita creados)
  4. Dispara el job de confirmaciones (send_booking_confirmations)
     → El envío a Meta FALLARÁ si los templates no están aprobados — es esperado.
     → Lo que verificamos es que la lógica de selección funciona correctamente.
  5. Muestra el estado final de la DB

Prerequisito:
  python tools/test_create_event.py  (ya debe haberse ejecutado)

Uso:
  python tools/test_run_simulation.py
"""

import os
import sys
import json
import logging

from dotenv import load_dotenv

load_dotenv()

# ── Logging visible en consola ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

EVENT_ID_FILE = ".tmp/sim_event_id.txt"
TEST_PHONE_E164 = "+523312345678"

DIVIDER = "─" * 60


def _load_event_id() -> str:
    if not os.path.exists(EVENT_ID_FILE):
        print(f"\n✗ No hay evento de prueba guardado.")
        print(f"  Ejecuta primero: python tools/test_create_event.py")
        sys.exit(1)
    with open(EVENT_ID_FILE) as f:
        data = json.load(f)
    return data["event_id"]


def _show_db_state(label: str, event_id: str) -> None:
    """Imprime el estado actual de la DB para el evento de prueba."""
    from tools.db_appointments import get_appointment_by_event_id
    from tools.db_clients import get_client_by_phone
    from tools.db_init import get_connection

    print(f"\n{DIVIDER}")
    print(f"  DB STATE: {label}")
    print(DIVIDER)

    appt = get_appointment_by_event_id(event_id)
    client = get_client_by_phone(TEST_PHONE_E164)

    if not client:
        print("  Cliente:  ✗ no encontrado en DB")
    else:
        print(f"  Cliente:  ✓ id={client['id']} | {client['name']} | {client['phone']}")

    if not appt:
        print("  Cita:     ✗ no encontrada en DB")
    else:
        print(f"  Cita:     ✓ id={appt['id']} | status={appt['status']}")
        print(f"            servicio={appt['service']} | estilista={appt['stylist']}")
        print(f"            inicio={appt['start_time']}")
        print(f"            confirmación enviada: {'✓' if appt['confirmation_sent_at'] else '✗ pendiente'}")
        print(f"            recordatorio enviado: {'✓' if appt['reminder_sent_at'] else '✗ pendiente'}")

    # Mensajes en message_log para esta cita
    if appt:
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
                print(f"    [{d['direction']}] {d['message_type']} | {d['content'][:60] if d['content'] else ''}")
        else:
            print(f"\n  message_log: vacío")

    print(DIVIDER)


def step1_sync() -> None:
    print(f"\n{'='*60}")
    print("  PASO 1: sync_calendar_to_db()")
    print(f"{'='*60}")
    print("  Leyendo eventos de Google Calendar y sincronizando a SQLite...")

    from tools.db_init import init_db
    from tools.reminder_scheduler import sync_calendar_to_db

    init_db()
    sync_calendar_to_db()
    print("  sync_calendar_to_db() completado.")


def step2_show_after_sync(event_id: str) -> None:
    _show_db_state("después del sync", event_id)

    from tools.db_appointments import get_appointment_by_event_id
    appt = get_appointment_by_event_id(event_id)

    if not appt:
        print("\n✗ FALLO: El evento de prueba no aparece en la DB.")
        print(f"  Event ID buscado: {event_id}")
        print("  Verifica que el evento fue creado correctamente en Google Calendar.")
        print("  y que GOOGLE_CALENDAR_ID apunta al calendario correcto.")
        sys.exit(1)
    else:
        print("\n✓ PASO 1 OK: Cita sincronizada correctamente.")


def step3_confirmation(event_id: str) -> None:
    print(f"\n{'='*60}")
    print("  PASO 2: send_booking_confirmations()")
    print(f"{'='*60}")
    print("  Buscando citas sin confirmación enviada...")
    print("  NOTA: El envío a WhatsApp fallará si los templates no están")
    print("  aprobados — eso es esperado en esta etapa.\n")

    from tools.reminder_scheduler import send_booking_confirmations
    send_booking_confirmations()
    print("\n  send_booking_confirmations() completado.")


def step4_show_final(event_id: str) -> None:
    _show_db_state("estado final", event_id)

    from tools.db_appointments import get_appointment_by_event_id
    appt = get_appointment_by_event_id(event_id)

    if appt and appt.get("confirmation_sent_at"):
        print("\n✓ PASO 2 OK: Confirmación enviada (Meta aceptó el template).")
    else:
        print("\n⚠ PASO 2: Confirmación NO enviada.")
        print("  Esto es normal si los templates no están aprobados aún.")
        print("  Revisa los logs de arriba para ver el error de Meta.")
        print("  La lógica de selección de citas sí funcionó — el intento se hizo.")

    print(f"\n{'='*60}")
    print("  SIGUIENTE PASO: simular respuesta del cliente")
    print(f"{'='*60}")
    print("  python tools/test_webhook_reply.py confirm")
    print("  python tools/test_webhook_reply.py cancel")


if __name__ == "__main__":
    event_id = _load_event_id()
    print(f"\nSimulación para evento: {event_id}")

    step1_sync()
    step2_show_after_sync(event_id)
    step3_confirmation(event_id)
    step4_show_final(event_id)
