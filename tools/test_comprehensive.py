"""
test_comprehensive.py — Test exhaustivo de 66 escenarios reales.

Documenta el comportamiento actual del bot en 10 categorías de interacción:
  ✅ PASS    : El bot maneja el escenario correctamente (no escala)
  ⚠  EXP_ESC : El bot escala a humano (comportamiento esperado para ese escenario)
  ❌ FAIL    : Comportamiento inesperado

No hace llamadas a APIs externas. No implementa features nuevos.
Documenta gaps donde el bot escala en lugar de responder directamente.

Uso:
  set PYTHONUTF8=1 && python -m tools.test_comprehensive
  set PYTHONUTF8=1 && python -m tools.test_comprehensive --verbose
  set PYTHONUTF8=1 && python -m tools.test_comprehensive --cat 2
"""

import os
import sys
import tempfile
import itertools
import argparse
import logging
import unittest.mock as mock
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Callable

# ── CRÍTICO: DATABASE_PATH antes de cualquier import de tools ──────────────────
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.gettempdir(), "salon_test_comprehensive.db"
)
os.environ.setdefault("SALON_TIMEZONE", "America/Mexico_City")
os.environ.setdefault("SALON_OPEN_HOUR", "10")
os.environ.setdefault("SALON_CLOSE_HOUR", "19")
os.environ.setdefault("SALON_OPEN_DAYS", "0,1,2,3,4,5")
os.environ.setdefault("SALON_SLOT_DURATION", "90")
# OWNER_WHATSAPP vacío: evita que notify_owner_* intente enviar mensajes reales
os.environ.setdefault("OWNER_WHATSAPP", "")

# Silenciar logs ruidosos
logging.basicConfig(level=logging.WARNING)
for _log in ("app", "tools.booking_handler", "tools.reschedule_handler",
             "tools.escalation_handler", "tools.reminder_scheduler",
             "tools.db_init", "werkzeug", "apscheduler"):
    logging.getLogger(_log).setLevel(logging.ERROR)

# ── Mockear scheduler ANTES de importar app (_startup() corre al importar) ─────
with mock.patch("tools.reminder_scheduler.create_scheduler") as _ms, \
     mock.patch("tools.reminder_scheduler.sync_calendar_to_db"):
    _ms.return_value.start.return_value = None
    _ms.return_value.get_jobs.return_value = []
    import app as _app  # noqa — dispara init_db() y scheduler mockeado
    from app import _process_webhook

# ── Perfiles de cliente ────────────────────────────────────────────────────────
PHONE_UNKNOWN_WA   = "529988776655"   # nunca en DB
PHONE_UNKNOWN_E164 = "+529988776655"
PHONE_KNOWN_WA     = "529911112222"   # en DB + cita activa
PHONE_KNOWN_E164   = "+529911112222"
PHONE_NEW_WA       = "529944443333"   # cliente nuevo para booking multi-turn
PHONE_NEW_E164     = "+529944443333"

FAKE_EVENT_ID = "EVT_TEST_COMP_001"
FAKE_START    = "2099-12-31T18:00:00"
FAKE_END      = "2099-12-31T19:30:00"

_wamid = itertools.count(1)

# ── ANSI ───────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── SECTION 1: Fixtures & Helpers ─────────────────────────────────────────────

def _fake_slots():
    import pytz
    tz = pytz.timezone("America/Mexico_City")
    base = (
        datetime.now(tz).replace(hour=10, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )
    # Max 5 slots — matches the numbers[] list in reschedule_handler / whatsapp_templates
    return [base + timedelta(hours=i * 1.5) for i in range(5)]


def _msg(text: str, phone: str = PHONE_KNOWN_WA) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [{
        "from": phone,
        "id": f"wamid.t{next(_wamid)}",
        "timestamp": "1700000000",
        "type": "text",
        "text": {"body": text},
    }]}}]}]}


def _btn(button_id: str, phone: str = PHONE_KNOWN_WA) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [{
        "from": phone,
        "id": f"wamid.t{next(_wamid)}",
        "timestamp": "1700000000",
        "type": "interactive",
        "interactive": {"button_reply": {"id": button_id, "title": "btn"}},
    }]}}]}]}


def _img(phone: str = PHONE_UNKNOWN_WA) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [{
        "from": phone,
        "id": f"wamid.t{next(_wamid)}",
        "timestamp": "1700000000",
        "type": "image",
        "image": {"id": "fake_img_id"},
    }]}}]}]}


def _seed_db():
    """Borra y recrea el DB de test para garantizar estado limpio entre runs."""
    # Eliminar el archivo de DB para evitar colisiones de wamid y estado residual
    db_path = os.environ["DATABASE_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)

    from tools.db_init import init_db, get_connection
    from tools.db_clients import get_or_create_client
    from tools.db_appointments import upsert_appointment

    init_db()

    client, _ = get_or_create_client("María de Prueba", PHONE_KNOWN_E164)
    upsert_appointment(
        google_event_id=FAKE_EVENT_ID,
        client_id=client["id"],
        service="Manicure",
        stylist="Carmen",
        start_time=FAKE_START,
        end_time=FAKE_END,
    )
    conn = get_connection()
    conn.execute(
        "UPDATE appointments SET status='pending', upsell_sent_at=NULL,"
        " client_response=NULL WHERE google_event_id=?",
        (FAKE_EVENT_ID,)
    )
    conn.commit()
    conn.close()


def _restore(upsell: bool = False):
    """Resetea la cita de prueba a estado pending y elimina citas extra creadas por el booking flow."""
    from tools.db_init import get_connection
    conn = get_connection()
    # Eliminar cualquier appointment extra creado durante los tests de booking
    row = conn.execute(
        "SELECT id FROM clients WHERE phone=?", (PHONE_KNOWN_E164,)
    ).fetchone()
    if row:
        conn.execute(
            "DELETE FROM appointments WHERE client_id=? AND google_event_id!=?",
            (row["id"], FAKE_EVENT_ID)
        )
    # Resetear la cita de prueba principal
    conn.execute(
        "UPDATE appointments SET status='pending', reschedule_state=NULL,"
        " client_response=NULL, upsell_sent_at=?"
        " WHERE google_event_id=?",
        (datetime.now().isoformat() if upsell else None, FAKE_EVENT_ID)
    )
    conn.commit()
    conn.close()


def _clean_session(phone: str = PHONE_KNOWN_WA):
    from tools.db_init import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM booking_sessions WHERE phone=?", (phone,))
    conn.commit()
    conn.close()


def _delete_client(phone_e164: str, phone_wa: str):
    """Borra un cliente y sus sesiones para simular cliente nuevo."""
    from tools.db_init import get_connection
    conn = get_connection()
    # Deshabilitar FK temporalmente para simplificar el borrado
    conn.execute("PRAGMA foreign_keys = OFF")
    row = conn.execute(
        "SELECT id FROM clients WHERE phone=?", (phone_e164,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM message_log WHERE client_id=?", (row["id"],))
        conn.execute("DELETE FROM appointments WHERE client_id=?", (row["id"],))
        conn.execute("DELETE FROM booking_sessions WHERE client_id=?", (row["id"],))
        conn.execute("DELETE FROM clients WHERE id=?", (row["id"],))
    conn.execute("DELETE FROM booking_sessions WHERE phone=?", (phone_wa,))
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()


# ── SECTION 2: Test Runner ────────────────────────────────────────────────────

class Status(Enum):
    PASS    = "PASS"
    EXP_ESC = "EXP_ESC"
    FAIL    = "FAIL"


@dataclass
class TR:
    category: str
    name: str
    input_text: str
    expected: str
    actual: str
    status: Status
    reply: str
    notes: str = ""


_cap: List[dict] = []


@contextmanager
def _patched():
    _cap.clear()

    def _txt(to, text, **kw):
        _cap.append({"t": "text", "body": text})

    def _tpl(to, template, **kw):
        _cap.append({"t": "tpl", "name": template.get("template_name", "")})

    with mock.patch("tools.whatsapp_sender.send_text_message",     side_effect=_txt), \
         mock.patch("tools.whatsapp_sender.send_template_message",  side_effect=_tpl), \
         mock.patch("tools.whatsapp_sender.mark_message_read",      return_value=None), \
         mock.patch("tools.calendar_writer.create_event",           return_value="fake_evt"), \
         mock.patch("tools.calendar_writer.mark_confirmed",         return_value=None), \
         mock.patch("tools.calendar_writer.mark_cancelled",         return_value=None), \
         mock.patch("tools.calendar_writer.reschedule_event",       return_value=None), \
         mock.patch("tools.calendar_availability.get_available_slots",
                    return_value=_fake_slots()):
        yield


def _escalated(msgs: List[dict]) -> bool:
    return any(
        m["t"] == "tpl" and "escalacion_humano" in m["name"]
        for m in msgs
    )


def _summary(msgs: List[dict]) -> str:
    parts = []
    for m in msgs:
        if m["t"] == "text":
            # Strip non-ASCII to avoid cp1252 encoding errors on Windows
            safe = m["body"].encode("ascii", "replace").decode("ascii")
            parts.append(safe[:70])
        else:
            parts.append(f"[{m['name']}]")
    return " | ".join(parts) if parts else "[sin respuesta]"


def _extract_input(payload: dict) -> str:
    try:
        msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        if msg["type"] == "text":
            return msg["text"]["body"]
        elif msg["type"] == "interactive":
            return f"[btn:{msg['interactive']['button_reply']['id']}]"
        return f"[{msg['type']}]"
    except Exception:
        return "[?]"


def run1(
    cat: str,
    name: str,
    payload: dict,
    expected: str,
    setup: Optional[Callable] = None,
    notes: str = "",
) -> TR:
    if setup:
        setup()
    with _patched():
        _process_webhook(payload)
    msgs = list(_cap)
    actual = "escalates" if _escalated(msgs) else "handles"
    if expected == "escalates":
        status = Status.EXP_ESC if actual == "escalates" else Status.FAIL
    else:
        status = Status.PASS if actual == "handles" else Status.FAIL
    return TR(cat, name, _extract_input(payload), expected, actual, status,
              _summary(msgs)[:120], notes)


def runN(
    cat: str,
    name: str,
    payloads: List[dict],
    expected: str,
    setup: Optional[Callable] = None,
    notes: str = "",
) -> TR:
    if setup:
        setup()
    all_msgs: List[dict] = []
    with _patched():
        for p in payloads:
            _cap.clear()
            _process_webhook(p)
            all_msgs.extend(list(_cap))
    input_text = " → ".join(_extract_input(p) for p in payloads)[:100]
    actual = "escalates" if _escalated(all_msgs) else "handles"
    if expected == "escalates":
        status = Status.EXP_ESC if actual == "escalates" else Status.FAIL
    else:
        status = Status.PASS if actual == "handles" else Status.FAIL
    return TR(cat, name, input_text, expected, actual, status,
              _summary(all_msgs)[:120], notes)


# ── SECTION 3: Test Cases ─────────────────────────────────────────────────────

def cat_01() -> List[TR]:
    """Primer contacto — cliente desconocido, todos deben escalar."""
    C = "1. Primer contacto"
    cases = [
        ("1.01 precio directo",       _msg("cuanto cuesta la manicure",      PHONE_UNKNOWN_WA)),
        ("1.02 precio con typo",       _msg("kanto cuesta el esmaltado",      PHONE_UNKNOWN_WA)),
        ("1.03 precio formal",         _msg("¿Me podría decir el precio?",    PHONE_UNKNOWN_WA)),
        ("1.04 servicios disponibles", _msg("qué servicios tienen",           PHONE_UNKNOWN_WA)),
        ("1.05 servicios informal",    _msg("que hacen ahi",                  PHONE_UNKNOWN_WA)),
        ("1.06 ubicacion sin acento",  _msg("donde estan ubicados",           PHONE_UNKNOWN_WA)),
        ("1.07 ubicacion con acento",  _msg("dónde están ubicados",           PHONE_UNKNOWN_WA)),
        ("1.08 horarios apertura",     _msg("a qué hora abren",               PHONE_UNKNOWN_WA)),
        ("1.09 disponibilidad hoy",    _msg("tienen disponibilidad hoy",      PHONE_UNKNOWN_WA)),
        ("1.10 duracion servicio",     _msg("cuanto dura la manicure",        PHONE_UNKNOWN_WA)),
        ("1.11 mensaje imagen",        _img(PHONE_UNKNOWN_WA)),
    ]
    return [run1(C, name, payload, "escalates") for name, payload in cases]


def cat_02() -> List[TR]:
    """Reservar cita — bot debe iniciar flujo de agendamiento."""
    C = "2. Reservar cita"
    results = []

    # 2.01-2.06: un solo turno, intent=book, cliente desconocido
    # Limpiar sesión antes de cada test (la anterior crea booking_session)
    single_cases = [
        ("2.01 agendar directo",   _msg("quiero agendar",                    PHONE_UNKNOWN_WA)),
        ("2.02 agendar con typo",  _msg("kiero una cita",                    PHONE_UNKNOWN_WA)),
        ("2.03 agendar + cita",    _msg("quiero agendar cita",               PHONE_UNKNOWN_WA)),
        ("2.04 agendar formal",    _msg("Quisiera reservar una cita",        PHONE_UNKNOWN_WA)),
        ("2.05 agendar pregunta",  _msg("me pueden agendar",                 PHONE_UNKNOWN_WA)),
        ("2.06 necesitar cita",    _msg("necesito cita",                     PHONE_UNKNOWN_WA)),
    ]
    for name, payload in single_cases:
        results.append(run1(C, name, payload, "handles",
                            setup=lambda: _clean_session(PHONE_UNKNOWN_WA)))

    # 2.07: Multi-turn 5 pasos — cliente NUEVO
    def setup_207():
        _delete_client(PHONE_NEW_E164, PHONE_NEW_WA)

    results.append(runN(
        C, "2.07 booking completo nuevo",
        [
            _msg("quiero agendar",             PHONE_NEW_WA),
            _msg("me llamo Sandra Torres",     PHONE_NEW_WA),
            _msg("manicure con gel",           PHONE_NEW_WA),
            _msg("el viernes por la mañana",   PHONE_NEW_WA),
            _msg("si perfecto",                PHONE_NEW_WA),
        ],
        "handles", setup=setup_207,
    ))

    # 2.08: Multi-turn 4 pasos — cliente CONOCIDO (salta ask_name)
    def setup_208():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    results.append(runN(
        C, "2.08 booking cliente conocido",
        [
            _msg("quiero agendar",  PHONE_KNOWN_WA),
            _msg("pedicure spa",    PHONE_KNOWN_WA),
            _msg("cualquier dia",   PHONE_KNOWN_WA),
            _msg("dale",            PHONE_KNOWN_WA),
        ],
        "handles", setup=setup_208,
    ))

    # 2.09: Multi-turn — cancelar al inicio del flujo
    def setup_209():
        _delete_client(PHONE_NEW_E164, PHONE_NEW_WA)

    results.append(runN(
        C, "2.09 booking luego intenta cancelar",
        [
            _msg("quiero agendar",         PHONE_NEW_WA),
            _msg("me llamo Ana García",    PHONE_NEW_WA),
            _msg("cancelar",               PHONE_NEW_WA),
        ],
        "handles",
        setup=setup_209,
        notes="GAP: 'cancelar' en paso ask_service se trata como nombre del servicio",
    ))

    return results


def cat_03() -> List[TR]:
    """Cambiar cita — cliente conocido con cita activa."""
    C = "3. Cambiar cita"

    def setup():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    results = []
    single_cases = [
        ("3.01 reagendar directo",  _msg("quiero reagendar")),
        ("3.02 cambiar hora",       _msg("cambiar mi hora")),
        ("3.03 cambiar dia",        _msg("cambiar a otro dia")),
        ("3.04 reprogramar",        _msg("reprogramar mi cita")),
    ]
    for name, payload in single_cases:
        results.append(run1(C, name, payload, "handles", setup=setup))

    results.append(run1(
        C, "3.05 typo reagendar", _msg("reajendarme"), "escalates",
        setup=setup,
        notes="GAP: typo no reconocido como reschedule intent — escala",
    ))

    # 3.06: Multi-turn reagendar completo
    results.append(runN(
        C, "3.06 reschedule completo",
        [_msg("quiero reagendar"), _msg("el primero")],
        "handles", setup=setup,
    ))

    return results


def cat_04() -> List[TR]:
    """Cancelar cita — cliente conocido con cita activa."""
    C = "4. Cancelar cita"

    def setup():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    cases = [
        ("4.01 cancelar directo",    _msg("cancelar mi cita")),
        ("4.02 cancelar emergencia", _msg("no puedo ir, surgio algo")),
        ("4.03 cancelar no asistir", _msg("no voy a poder asistir")),
        ("4.04 boton CANCEL",        _btn("CANCEL")),
    ]
    return [run1(C, name, payload, "handles", setup=setup) for name, payload in cases]


def cat_05() -> List[TR]:
    """Antes de la cita — confirmaciones y avisos."""
    C = "5. Antes de la cita"

    def setup_conf():
        _clean_session(PHONE_KNOWN_WA)
        _restore(upsell=False)  # upsell=False para que "sí" → confirm, no upsell_yes

    def setup_cancel():
        _clean_session(PHONE_KNOWN_WA)
        _restore(upsell=False)

    results = [
        run1(C, "5.01 confirmar texto",    _msg("si ahi estare"),              "handles", setup=setup_conf),
        run1(C, "5.02 confirmar explicito", _msg("si confirmo"),               "handles", setup=setup_conf),
        run1(C, "5.03 boton CONFIRM",      _btn("CONFIRM"),                    "handles", setup=setup_conf),
        run1(C, "5.04 no puede ir",        _msg("no puedo ir"),                "handles", setup=setup_cancel),
        run1(C, "5.05 llegara tarde",      _msg("voy a llegar un poco tarde"), "escalates",
             setup=setup_conf,
             notes="BUG: 'voy' esta en CONFIRM_KEYWORDS — bot confirma la cita en vez de escalar"),
        run1(C, "5.06 cambiar hora",       _msg("puedo cambiar la hora"),      "handles", setup=setup_conf),
    ]
    return results


def cat_06() -> List[TR]:
    """Durante la cita — todos escalan (no hay handler para estos casos)."""
    C = "6. Durante la cita"

    def setup():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    cases = [
        ("6.01 ya llegue",        _msg("ya llegue")),
        ("6.02 estacionamiento",  _msg("donde me estaciono")),
        ("6.03 estoy afuera",     _msg("estoy afuera esperando")),
        ("6.04 ya estoy aqui",    _msg("ya estoy aqui")),
    ]
    return [run1(C, name, payload, "escalates", setup=setup) for name, payload in cases]


def cat_07() -> List[TR]:
    """Después de la cita — reclamos, opiniones, upsell."""
    C = "7. Despues de la cita"

    def setup_esc():
        _clean_session(PHONE_KNOWN_WA)
        _restore(upsell=False)

    def setup_upsell():
        _clean_session(PHONE_KNOWN_WA)
        _restore(upsell=True)

    results = [
        run1(C, "7.01 satisfaccion positiva", _msg("me encanto el resultado"),    "escalates", setup=setup_esc),
        run1(C, "7.02 pedir opinion",          _msg("quiero dejar una opinion"),  "escalates", setup=setup_esc),
        run1(C, "7.03 retoque problema",       _msg("se me despego el acrilico"), "escalates", setup=setup_esc),
        run1(C, "7.04 reclamo calidad",        _msg("me salio mal la manicure"),  "escalates", setup=setup_esc),
        run1(C, "7.05 pregunta garantia",      _msg("tienen garantia"),           "escalates", setup=setup_esc),
        run1(C, "7.06 upsell acepta",          _msg("si quiero"),                 "handles",   setup=setup_upsell),
        run1(C, "7.07 upsell rechaza",         _msg("no gracias"),                "handles",   setup=setup_upsell),
        run1(C, "7.08 upsell me interesa",     _msg("me interesa"),               "handles",   setup=setup_upsell),
    ]
    return results


def cat_08() -> List[TR]:
    """Clientes frecuentes."""
    C = "8. Clientes frecuentes"

    def setup():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    results = [
        run1(C, "8.01 cuando tengo cita",   _msg("cuando tengo cita"),
             "handles",  # "cita" en BOOK_KEYWORDS → inicia flujo de agendamiento
             setup=setup,
             notes="INFO: 'cita' dispara book intent — bot pregunta servicio en vez de responder 'tienes cita el...'"),
        run1(C, "8.02 la misma de siempre", _msg("la misma de siempre"),
             "escalates", setup=setup,
             notes="GAP: sin keyword 'book' — no inicia agendamiento"),
        run1(C, "8.03 misma estilista",     _msg("con la misma chica que me atendio"),
             "escalates", setup=setup,
             notes="GAP: referencia a estilista específica no reconocida"),
        run1(C, "8.04 otra cita",           _msg("quiero otra cita"),          "handles", setup=setup),
        run1(C, "8.05 agendar igual",       _msg("quiero agendar igual que la vez pasada"), "handles", setup=setup),
    ]
    return results


def cat_09() -> List[TR]:
    """Pagos — todos escalan (bot no tiene integración de pagos)."""
    C = "9. Pagos"

    def setup():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    cases = [
        ("9.01 formas de pago",  _msg("que formas de pago aceptan")),
        ("9.02 anticipo",        _msg("hay que dar anticipo")),
        ("9.03 confirmar pago",  _msg("ya hice el deposito")),
        ("9.04 precio final",    _msg("cuanto me salio en total")),
        ("9.05 tarjeta",         _msg("aceptan tarjeta")),
    ]
    return [run1(C, name, payload, "escalates", setup=setup) for name, payload in cases]


def cat_10() -> List[TR]:
    """Marketing y promociones — todos escalan."""
    C = "10. Marketing"

    def setup():
        _clean_session(PHONE_KNOWN_WA)
        _restore()

    cases = [
        ("10.01 pregunta promo",     _msg("tienen promociones")),
        ("10.02 vi promo manicure",  _msg("vi que tienen promo de manicure")),
        ("10.03 promo aplica hoy",   _msg("la promo aplica hoy")),
        ("10.04 apartar promo",      _msg("quiero apartar la promo")),
        ("10.05 2x1",                _msg("vi que tienen 2x1")),
    ]
    return [run1(C, name, payload, "escalates", setup=setup) for name, payload in cases]


# ── SECTION 4: Report ─────────────────────────────────────────────────────────

def print_report(results: List[TR], verbose: bool = False) -> int:
    total   = len(results)
    passed  = sum(1 for r in results if r.status == Status.PASS)
    exp_esc = sum(1 for r in results if r.status == Status.EXP_ESC)
    failed  = sum(1 for r in results if r.status == Status.FAIL)

    SEP1 = "=" * 70
    SEP2 = "-" * 70
    print(f"\n{BOLD}{SEP1}{RESET}")
    print(f"{BOLD}  REPORTE: Test Comprehensivo - Time 4 me Nail Salon Bot{RESET}")
    print(SEP1)
    print(
        f"  Total: {total}  |  "
        f"{GREEN}PASS: {passed}{RESET}  |  "
        f"{YELLOW}EXP_ESC: {exp_esc}{RESET}  |  "
        f"{RED}FAIL: {failed}{RESET}"
    )
    print(SEP1)

    # Por categoria
    cats: dict = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)

    print(f"  {'Categoria':<36} {'PASS':>5} {'EXP_ESC':>8} {'FAIL':>5} {'Total':>6}")
    print(f"  {'-' * 62}")
    for cat, cat_results in cats.items():
        p = sum(1 for r in cat_results if r.status == Status.PASS)
        e = sum(1 for r in cat_results if r.status == Status.EXP_ESC)
        f = sum(1 for r in cat_results if r.status == Status.FAIL)
        mark = f"{RED}x{RESET}" if f else f"{GREEN}+{RESET}"
        print(f"  {mark} {cat:<34} {p:>5} {e:>8} {f:>5} {len(cat_results):>6}")

    # Gaps detectados (EXP_ESC con notas)
    gaps = [r for r in results if r.status == Status.EXP_ESC and r.notes]
    if gaps:
        print(f"\n{SEP2}")
        print(f"  {YELLOW}GAPS DETECTADOS (el bot escala cuando podria responder directamente):{RESET}")
        for r in gaps:
            print(f"  [!] {r.name:<45} {GRAY}{r.notes[:60]}{RESET}")

    # Fallos inesperados
    fails = [r for r in results if r.status == Status.FAIL]
    if fails:
        print(f"\n{SEP2}")
        print(f"  {RED}FALLOS (comportamiento inesperado - requiere investigacion):{RESET}")
        for r in fails:
            print(f"\n  [X] {BOLD}{r.name}{RESET}")
            print(f"     Input:    {r.input_text[:70]}")
            print(f"     Esperado: {r.expected}  |  Actual: {r.actual}")
            print(f"     Reply:    {GRAY}{r.reply[:80]}{RESET}")
            if r.notes:
                print(f"     Nota:     {r.notes}")

    # Verbose: detalle completo
    if verbose:
        print(f"\n{SEP2}")
        print(f"  DETALLE COMPLETO")
        current_cat = None
        for r in results:
            if r.category != current_cat:
                current_cat = r.category
                print(f"\n  [{current_cat}]")
            icon = (
                f"{GREEN}[P]{RESET}" if r.status == Status.PASS
                else f"{YELLOW}[W]{RESET}" if r.status == Status.EXP_ESC
                else f"{RED}[F]{RESET}"
            )
            print(f"    {icon} {r.name:<45} {GRAY}{r.reply[:55]}{RESET}")

    print(f"\n{SEP1}\n")

    if failed == 0:
        print(f"  {GREEN}{BOLD}Todo en orden.{RESET} "
              f"{exp_esc} escenarios escalan a humano (comportamiento esperado).\n")
    else:
        print(f"  {RED}{BOLD}{failed} fallos inesperados.{RESET} "
              f"Ejecuta con --verbose para ver el detalle completo.\n")

    return failed


# ── SECTION 5: Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test exhaustivo del bot — 66 escenarios en 10 categorías"
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Mostrar detalle de todos los tests")
    parser.add_argument("--cat", type=int, metavar="N",
                        help="Correr solo categoría N (1-10)")
    args = parser.parse_args()

    print(f"\n{BOLD}Iniciando test comprehensivo...{RESET}")
    _seed_db()

    all_cats = [cat_01, cat_02, cat_03, cat_04, cat_05,
                cat_06, cat_07, cat_08, cat_09, cat_10]

    if args.cat:
        if 1 <= args.cat <= 10:
            categories = [all_cats[args.cat - 1]]
        else:
            print(f"Categoría inválida: {args.cat}. Usa 1-10.")
            sys.exit(1)
    else:
        categories = all_cats

    results: List[TR] = []
    for cat_fn in categories:
        cat_results = cat_fn()
        results.extend(cat_results)
        p = sum(1 for r in cat_results if r.status == Status.PASS)
        e = sum(1 for r in cat_results if r.status == Status.EXP_ESC)
        f = sum(1 for r in cat_results if r.status == Status.FAIL)
        label = cat_results[0].category if cat_results else "?"
        f_str = f"{RED}{f}F{RESET}" if f else f"{GRAY}0{RESET}"
        print(f"  {label:<35} {GREEN}{p}P{RESET}  {YELLOW}{e}W{RESET}  {f_str}")

    failed_count = print_report(results, verbose=args.verbose)
    sys.exit(1 if failed_count > 0 else 0)


if __name__ == "__main__":
    main()
