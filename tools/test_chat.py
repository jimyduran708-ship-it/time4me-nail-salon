"""
test_chat.py — Simulacion interactiva del bot como cliente nuevo.

Intercepta send_text_message y send_template_message para mostrar
las respuestas del bot en consola en lugar de enviarlas por WhatsApp.

Uso:
  PYTHONUTF8=1 python -m tools.test_chat
  PYTHONUTF8=1 python -m tools.test_chat --phone 523399887766

El numero de telefono es falso (nunca llega a WhatsApp).
"""

import os
import sys
import time
import json
import logging
import unittest.mock as mock
from dotenv import load_dotenv

load_dotenv()

# Suprimir logs del scheduler y Flask durante la simulacion
logging.basicConfig(level=logging.WARNING)
logging.getLogger("app").setLevel(logging.WARNING)
logging.getLogger("tools.booking_handler").setLevel(logging.WARNING)
logging.getLogger("tools.intent_parser").setLevel(logging.WARNING)

# Numero de telefono falso para la simulacion
TEST_PHONE_WA = "529900000001"   # formato Meta (sin +)
TEST_PHONE_E164 = "+529900000001"

if len(sys.argv) >= 3 and sys.argv[1] == "--phone":
    raw = sys.argv[2].lstrip("+")
    TEST_PHONE_WA = raw
    TEST_PHONE_E164 = "+" + raw

_msg_counter = [0]

BOT_COLOR  = "\033[96m"   # cyan
USER_COLOR = "\033[93m"   # amarillo
RESET      = "\033[0m"


def _print_bot(text: str) -> None:
    print(f"\n{BOT_COLOR}[BOT] {text}{RESET}\n")


def _mock_send_text(to, text, appointment_id=None, client_id=None, **kwargs):
    _print_bot(text)


def _mock_send_template(to, template, appointment_id=None, client_id=None, **kwargs):
    # Extraer texto del template dict para mostrarlo legible
    name = template.get("name", "template")
    components = template.get("components", [])
    body_text = ""
    for comp in components:
        if comp.get("type") == "body":
            body_text = comp.get("parameters", [{}])[0].get("text", "")
            break
    if body_text:
        _print_bot(f"[template:{name}]\n{body_text}")
    else:
        _print_bot(f"[template:{name}] {json.dumps(template, ensure_ascii=False)[:200]}")


def _mock_mark_read(message_id):
    pass


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


def main():
    print("\n" + "=" * 60)
    print("  SIMULACION DE CLIENTE NUEVO — Time 4 me Nail Salon")
    print(f"  Telefono simulado: {TEST_PHONE_E164}")
    print("  Escribe mensajes como si fueras el cliente.")
    print("  Escribe 'salir' para terminar.")
    print("=" * 60 + "\n")

    # Parchamos los senders ANTES de importar app
    # (app importa los modulos al primer uso, asi que el mock debe estar activo)
    with mock.patch("tools.whatsapp_sender.send_text_message", side_effect=_mock_send_text), \
         mock.patch("tools.whatsapp_sender.send_template_message", side_effect=_mock_send_template), \
         mock.patch("tools.whatsapp_sender.mark_message_read", side_effect=_mock_mark_read):

        # Importar y preparar app (init_db, etc.)
        import app as _app   # noqa: F401 — dispara _startup() que corre init_db

        from app import _process_webhook

        while True:
            try:
                user_input = input(f"{USER_COLOR}[TU]  {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSaliendo.")
                break

            if user_input.lower() in ("salir", "exit", "quit"):
                print("Sesion terminada.")
                break

            if not user_input:
                continue

            payload = _build_text_payload(user_input)
            _process_webhook(payload)
            time.sleep(0.3)   # pequena pausa para que los prints salgan ordenados


if __name__ == "__main__":
    main()
