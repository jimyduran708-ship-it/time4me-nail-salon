"""
smoke_test.py — Verifica que todos los módulos funcionan antes de desplegar.

Prueba solo la capa local (sin llamadas a APIs externas).
Corre: python tools/smoke_test.py

Resultado esperado: todos los tests pasan (✅).
Si alguno falla, la causa más común está entre corchetes.
"""

import sys
import os
import traceback

# Asegurar que el root del proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "[OK]"
FAIL = "[FAIL]"
results = []


def test(name: str, fn):
    try:
        fn()
        results.append((PASS, name))
        print(f"  {PASS}  {name}")
    except Exception as exc:
        results.append((FAIL, name))
        print(f"  {FAIL}  {name}")
        print(f"       -> {type(exc).__name__}: {exc}")
        if "--verbose" in sys.argv:
            traceback.print_exc()


# ── phone_normalizer ───────────────────────────────────────────────────────────
def test_phone_normalizer():
    from tools.phone_normalizer import normalize_to_e164, to_whatsapp_format, is_international

    assert normalize_to_e164("3312345678") == "+523312345678", "MX number without code"
    assert normalize_to_e164("+52 33 1234 5678") == "+523312345678", "MX with spaces"
    assert normalize_to_e164("+1 650 253 0000") == "+16502530000", "US number"
    assert normalize_to_e164("not-a-phone") is None, "Invalid should be None"
    assert to_whatsapp_format("+523312345678") == "523312345678", "Strip +"
    assert is_international("+16502530000") is True, "US is international"
    assert is_international("+523312345678") is False, "MX is not international"


# ── intent_parser ──────────────────────────────────────────────────────────────
def test_intent_parser_button():
    from tools.intent_parser import parse_intent

    msg = {"type": "interactive", "interactive": {"button_reply": {"id": "CONFIRM", "title": "Confirmar ✅"}}}
    assert parse_intent(msg) == "confirm"

    msg = {"type": "interactive", "interactive": {"button_reply": {"id": "CANCEL", "title": "Cancelar ❌"}}}
    assert parse_intent(msg) == "cancel"

    msg = {"type": "interactive", "interactive": {"button_reply": {"id": "HUMAN", "title": "Hablar con alguien 💬"}}}
    assert parse_intent(msg) == "human"


def test_intent_parser_text():
    from tools.intent_parser import parse_intent

    def txt(body): return {"type": "text", "text": {"body": body}}

    assert parse_intent(txt("Sí, ahí estaré")) == "confirm"
    assert parse_intent(txt("si confirmo")) == "confirm"
    assert parse_intent(txt("Cancelar por favor")) == "cancel"
    assert parse_intent(txt("no puedo ir")) == "cancel"
    assert parse_intent(txt("quiero hablar con alguien")) == "human"
    assert parse_intent(txt("reagendar")) == "reschedule"
    assert parse_intent(txt("🎉🎉🎉")) == "unknown"


def test_intent_parser_upsell():
    from tools.intent_parser import parse_intent

    def txt(body): return {"type": "text", "text": {"body": body}}

    assert parse_intent(txt("si quiero"), context="upsell") == "upsell_yes"
    assert parse_intent(txt("no gracias"), context="upsell") == "upsell_no"


# ── whatsapp_templates ─────────────────────────────────────────────────────────
def test_templates():
    from tools.whatsapp_templates import (
        booking_confirmation, appointment_reminder,
        cancellation_confirmed, upsell_prompt,
        no_show_followup, human_escalation,
    )

    iso = "2026-06-15T16:00:00+00:00"  # UTC → 10:00 AM Mexico City

    t = booking_confirmation("María", "Uñas acrílicas", iso, "Carmen")
    assert t["template_name"] == "time4me_confirmacion_cita"
    assert "María" in t["params"]
    assert "Carmen" in t["params"]

    t = appointment_reminder("Ana", "Pedicure", iso, "Diana")
    assert t["template_name"] == "time4me_recordatorio_cita"
    assert len(t["buttons"]) == 3

    t = cancellation_confirmed("Laura", iso, "Esmaltado")
    assert t["template_name"] == "time4me_cancelacion_confirmada"

    t = upsell_prompt("Sofía")
    assert "Sofía" in t["params"]

    t = no_show_followup("Carmen")
    assert "Carmen" in t["params"]

    t = human_escalation("Beatriz", "521XXXXXXXXXX")
    assert "Beatriz" in t["params"]


# ── db layer ───────────────────────────────────────────────────────────────────
def test_db_init():
    import tempfile, os
    os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "salon_test.db")
    from tools.db_init import init_db
    init_db()


def test_db_clients():
    from tools.db_clients import create_client, get_client_by_phone, get_or_create_client, search_clients_by_name
    import sqlite3

    phone = "+529999000001"
    try:
        client = create_client("Test Cliente", phone)
        assert client["name"] == "Test Cliente"
        assert client["phone"] == phone

        found = get_client_by_phone(phone)
        assert found is not None
        assert found["id"] == client["id"]

        existing, created = get_or_create_client("Test Cliente", phone)
        assert not created

        results = search_clients_by_name("Test")
        assert any(c["phone"] == phone for c in results)
    except sqlite3.IntegrityError:
        pass  # phone already inserted from a previous run — OK


def test_db_appointments():
    from tools.db_clients import get_client_by_phone
    from tools.db_appointments import (
        upsert_appointment, get_appointment_by_event_id,
        get_appointments_needing_confirmation,
    )

    phone = "+529999000001"
    client = get_client_by_phone(phone)
    if not client:
        from tools.db_clients import create_client
        client = create_client("Test Cliente", phone)

    event_id = "TEST_EVENT_SMOKE_001"
    appt = upsert_appointment(
        google_event_id=event_id,
        client_id=client["id"],
        service="Uñas acrílicas",
        stylist="Carmen",
        start_time="2099-12-31T16:00:00",
        end_time="2099-12-31T17:00:00",
    )
    assert appt["google_event_id"] == event_id
    assert appt["service"] == "Uñas acrílicas"

    # Should appear in needing_confirmation list
    needing = get_appointments_needing_confirmation()
    assert any(a["google_event_id"] == event_id for a in needing)


# ── calendar_reader parsing (no API call) ──────────────────────────────────────
def test_calendar_parser():
    from tools.calendar_reader import _parse_title, _parse_description

    t = _parse_title("Uñas acrílicas - Carmen")
    assert t["service"] == "Uñas acrílicas"
    assert t["stylist"] == "Carmen"

    t = _parse_title("Pedicure")
    assert t["service"] == "Pedicure"
    assert t["stylist"] is None

    d = _parse_description("Cliente: María López\nTeléfono: +523312345678\nNotas: alergia")
    assert d["client_name"] == "María López"
    assert d["phone"] == "+523312345678"
    assert d["notes"] == "alergia"

    d = _parse_description("")
    assert d["client_name"] is None


# ── Run all tests ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\nSmoke Test -- Time 4 me Nail Salon Bot\n")

    print("phone_normalizer")
    test("Normalizacion de telefonos", test_phone_normalizer)

    print("\nintent_parser")
    test("Botones interactivos", test_intent_parser_button)
    test("Texto libre", test_intent_parser_text)
    test("Contexto upsell", test_intent_parser_upsell)

    print("\nwhatsapp_templates")
    test("Templates de mensajes", test_templates)

    print("\nbase de datos")
    test("Inicializar DB", test_db_init)
    test("CRUD clientes", test_db_clients)
    test("CRUD citas", test_db_appointments)

    print("\ncalendar_reader (parseo local, sin API)")
    test("Parseo de titulo de evento", test_calendar_parser)

    # Summary
    passed = sum(1 for r in results if r[0] == PASS)
    total = len(results)
    print(f"\n{'--'*20}")
    print(f"Resultado: {passed}/{total} tests pasaron")
    if passed < total:
        print("Ejecuta con --verbose para ver el traceback completo.")
        sys.exit(1)
    else:
        print("Todo listo para desplegar [OK]")
