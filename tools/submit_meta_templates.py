"""
submit_meta_templates.py — Submit the 6 WhatsApp message templates to Meta for approval.

Run once. Templates take 24-48h to be approved by Meta.
If a template already exists, it is reported as such (not re-submitted).

Usage:
    PYTHONUTF8=1 python -m tools.submit_meta_templates
"""

import os
import json
import requests
from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WABA_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
API_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{WABA_ID}/message_templates"

# Meta error subcodes that mean the template already exists
ALREADY_EXISTS_SUBCODES = {136003, 2388024}


# ---------------------------------------------------------------------------
# Template definitions — texts adjusted to match params sent by whatsapp_templates.py
# ---------------------------------------------------------------------------

TEMPLATES = [
    # 1. Booking confirmation (5 params: name, service, date, time, stylist)
    {
        "name": "time4me_confirmacion_cita",
        "language": "es_MX",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, tu cita en *Time 4 me Nail Salon* esta confirmada!\n\n"
                    "Servicio: {{2}}\n"
                    "Fecha: {{3}}\n"
                    "Hora: {{4}}\n"
                    "Estilista: {{5}}\n"
                    "Av. Ruben Dario 1206, Providencia 2a. Secc, Guadalajara\n\n"
                    "Te esperamos!"
                ),
                "example": {
                    "body_text": [[
                        "Maria", "Unas acrilicas",
                        "lunes 10 de marzo", "11:00 a.m.", "Carmen"
                    ]]
                },
            }
        ],
    },

    # 2. Appointment reminder (5 params: name, service, date, time, stylist) + 3 quick-reply buttons
    {
        "name": "time4me_recordatorio_cita",
        "language": "es_MX",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, manana tienes cita con nosotros:\n\n"
                    "Servicio: {{2}}\n"
                    "Fecha: {{3}}\n"
                    "Hora: {{4}}\n"
                    "Estilista: {{5}}\n\n"
                    "Confirmas tu cita?"
                ),
                "example": {
                    "body_text": [[
                        "Maria", "Unas acrilicas",
                        "martes 11 de marzo", "11:00 a.m.", "Carmen"
                    ]]
                },
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Confirmar"},
                    {"type": "QUICK_REPLY", "text": "Cancelar"},
                    {"type": "QUICK_REPLY", "text": "Hablar con alguien"},
                ],
            },
        ],
    },

    # 3. Cancellation confirmed (3 params: name, date, service)
    {
        "name": "time4me_cancelacion_confirmada",
        "language": "es_MX",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, tu cita del {{2}} para {{3}} fue cancelada sin problema.\n\n"
                    "Quieres reagendar? Escribenos y con gusto te buscamos un nuevo horario."
                ),
                "example": {
                    "body_text": [["Maria", "lunes 10 de marzo", "Unas acrilicas"]]
                },
            }
        ],
    },

    # 4. Upsell prompt (1 param: name) — MARKETING category
    {
        "name": "time4me_upsell_servicios",
        "language": "es_MX",
        "category": "MARKETING",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, ya casi es tu cita!\n\n"
                    "Te gustaria agregar algun servicio extra?\n"
                    "Diseno especial / Spa de manos / Exfoliacion de pies\n\n"
                    "Responde SI si quieres que te cotizamos, o NO si por ahora esta bien.\n\n"
                    "Nos vemos manana!"
                ),
                "example": {
                    "body_text": [["Maria"]]
                },
            }
        ],
    },

    # 5. No-show follow-up (1 param: name)
    {
        "name": "time4me_noshow_reagendar",
        "language": "es_MX",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}, hoy te esperabamos y notamos que no pudiste venir. No hay problema!\n\n"
                    "Escribenos cuando quieras para reagendar tu cita.\n"
                    "L-V 9am-7pm / Sab 9am-2:30pm"
                ),
                "example": {
                    "body_text": [["Maria"]]
                },
            }
        ],
    },

    # 6. Human escalation (2 params: name, owner wa.me link)
    {
        "name": "time4me_escalacion_humano",
        "language": "es_MX",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": (
                    "Hola {{1}}! Claro, con gusto te conecto con nuestra encargada.\n\n"
                    "Puedes escribirle directamente aqui: {{2}}\n\n"
                    "Gracias!"
                ),
                "example": {
                    "body_text": [["Maria", "wa.me/523312345678"]]
                },
            }
        ],
    },
]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_template(template: dict) -> dict:
    """POST a single template to Meta. Returns a result dict."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(BASE_URL, json=template, headers=headers, timeout=30)
    except (ReadTimeout, ReqConnectionError) as exc:
        return {"name": template["name"], "result": "error", "status_code": None, "error": str(exc)}
    body = resp.json()

    if resp.status_code == 200:
        return {"name": template["name"], "result": "submitted", "id": body.get("id")}

    # Check for "already exists" error
    error_subcode = body.get("error", {}).get("error_subcode")
    if error_subcode in ALREADY_EXISTS_SUBCODES:
        return {"name": template["name"], "result": "already_exists"}

    return {
        "name": template["name"],
        "result": "error",
        "status_code": resp.status_code,
        "error": body.get("error", body),
    }


def main():
    if not ACCESS_TOKEN:
        print("ERROR: WHATSAPP_ACCESS_TOKEN no encontrado en .env")
        return
    if not WABA_ID:
        print("ERROR: WHATSAPP_BUSINESS_ACCOUNT_ID no encontrado en .env")
        return

    print(f"Sometiendo {len(TEMPLATES)} templates a Meta (WABA: {WABA_ID})...\n")

    results = []
    for tmpl in TEMPLATES:
        result = submit_template(tmpl)
        results.append(result)

        icon = {"submitted": "OK", "already_exists": "YA_EXISTE", "error": "ERROR"}.get(
            result["result"], "?"
        )
        if result["result"] == "submitted":
            print(f"  [{icon}] {result['name']} — id: {result.get('id')}")
        elif result["result"] == "already_exists":
            print(f"  [{icon}] {result['name']}")
        else:
            print(f"  [{icon}] {result['name']} — {result.get('status_code')} {result.get('error')}")

    submitted = sum(1 for r in results if r["result"] == "submitted")
    existing = sum(1 for r in results if r["result"] == "already_exists")
    errors = sum(1 for r in results if r["result"] == "error")

    print(f"\nResumen: {submitted} sometidos, {existing} ya existian, {errors} errores")
    if submitted > 0:
        print("Los templates sometidos estarán en revisión 24-48h.")
        print("Verifica en Meta Business Manager → WhatsApp → Message Templates.")


if __name__ == "__main__":
    main()
