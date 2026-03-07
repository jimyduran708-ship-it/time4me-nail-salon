"""
test_claude_agent.py — Prueba aislada del agente Claude.

Verifica que el agente devuelva las herramientas correctas para mensajes
típicos, sin tocar app.py ni la base de datos real.

Uso:
    set PYTHONUTF8=1 && python -m tools.test_claude_agent
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Verificar que ANTHROPIC_API_KEY esté configurada
if not os.getenv("ANTHROPIC_API_KEY"):
    print("ERROR: ANTHROPIC_API_KEY no está configurada en .env")
    sys.exit(1)

from tools.claude_agent import run

# ── Fixtures ──────────────────────────────────────────────────────────────────

KNOWN_CLIENT = {"id": 1, "name": "María García", "phone": "+523312345678"}

PENDING_APPT = {
    "id": 10,
    "google_event_id": "abc123",
    "service": "manicure",
    "stylist": "Por asignar",
    "start_time": "2026-03-09T16:00:00-06:00",
    "end_time": "2026-03-09T17:30:00-06:00",
    "status": "pending",
    "upsell_sent_at": None,
    "client_response": None,
    "reschedule_state": None,
}

UPSELL_APPT = {**PENDING_APPT, "upsell_sent_at": "2026-03-08T09:30:00", "client_response": None}

NO_HISTORY = []

BOOKING_HISTORY = [
    {"direction": "inbound", "content": "quiero agendar una cita", "sent_at": "2026-03-06T10:00:00"},
    {"direction": "outbound", "content": "¡Hola! ¿Me dices tu nombre para registrarte?", "sent_at": "2026-03-06T10:00:01"},
]

# ── Test cases ────────────────────────────────────────────────────────────────

TESTS = [
    # (descripcion, message_text, client, appointment, history, expected_tool)
    ("confirmar cita", "sí, ahí estaré", KNOWN_CLIENT, PENDING_APPT, NO_HISTORY, "confirm_appointment"),
    ("cancelar cita", "mejor cancela mi cita", KNOWN_CLIENT, PENDING_APPT, NO_HISTORY, "cancel_appointment"),
    ("quiere agendar (nueva clienta)", "quiero agendar", None, None, NO_HISTORY, "send_message"),
    ("dar nombre en flujo booking", "me llamo Laura", None, None, BOOKING_HISTORY, "send_message"),
    ("pregunta de precio (escalar)", "¿cuánto cuesta el acrílico?", KNOWN_CLIENT, None, NO_HISTORY, "escalate_to_human"),
    ("queja (escalar)", "la última vez me quedaron horribles", KNOWN_CLIENT, PENDING_APPT, NO_HISTORY, "escalate_to_human"),
    ("upsell sí", "sí, agrega eso", KNOWN_CLIENT, UPSELL_APPT, NO_HISTORY, "record_upsell_response"),
    ("upsell no", "no gracias, solo lo básico", KNOWN_CLIENT, UPSELL_APPT, NO_HISTORY, "record_upsell_response"),
]


def run_tests():
    passed = 0
    failed = 0

    print("\n" + "=" * 65)
    print("  TEST AISLADO — Claude Agent")
    print("=" * 65)

    for desc, msg, client, appt, history, expected in TESTS:
        result = run(
            message_text=msg,
            client=client,
            appointment=appt,
            history=history,
            wa_phone="523312345678",
            phone_e164="+523312345678",
        )

        tool = result.get("tool", "")
        ok = tool == expected

        status = "PASS" if ok else "FAIL"
        color = "\033[92m" if ok else "\033[91m"
        reset = "\033[0m"

        print(f"  {color}{status}{reset}  {desc}")
        if not ok:
            print(f"        esperado: {expected}")
            print(f"        obtenido: {tool}")
            print(f"        input:    {result.get('input', {})}")
            failed += 1
        else:
            inp = result.get("input", {})
            # Show the message/response for visibility
            preview = inp.get("response_message") or inp.get("message") or ""
            if preview:
                safe = preview[:80].encode("ascii", errors="replace").decode("ascii")
            print(f"        -> {safe}")
            passed += 1

    print("=" * 65)
    print(f"  PASS: {passed}  |  FAIL: {failed}  |  Total: {passed + failed}")
    print("=" * 65 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
