"""
token_checker.py — Verifica que el WHATSAPP_ACCESS_TOKEN siga vigente.

Hace un GET ligero al endpoint del número de teléfono en la Graph API.
  - 200 → token válido, loguea OK
  - 401 → token expirado, envía alerta al dueño

Corre como job APScheduler diario a las 8:00 AM (ver reminder_scheduler.py).
También puede ejecutarse manualmente:
    python -m tools.token_checker

─────────────────────────────────────────────────────────────────────────────
SISTEMA PERMANENTE (elimina la necesidad de renovar tokens):

Para obtener un token que no expira nunca:
  1. Meta Business Suite → Configuración → Cuentas del sistema
  2. Crear "System User" con rol Admin
  3. En el System User → "Agregar activos" → WhatsApp Business Account → Control total
  4. "Generar token nuevo" → sin fecha de expiración
  5. Copiar el token y actualizarlo en Railway:
     Railway → Variables → WHATSAPP_ACCESS_TOKEN → nuevo valor → Deploy
─────────────────────────────────────────────────────────────────────────────
"""

import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
API_VERSION = "v19.0"


def check_whatsapp_token() -> bool:
    """
    Verifica que el token de WhatsApp sea válido.
    Retorna True si el token es válido, False si está expirado o falla.
    Envía alerta al dueño si el token ya no funciona.
    """
    if not PHONE_NUMBER_ID or not ACCESS_TOKEN:
        logger.warning("[token_checker] WHATSAPP_PHONE_NUMBER_ID o ACCESS_TOKEN no configurados")
        return False

    url = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except Exception as exc:
        logger.error(f"[token_checker] Error de red al verificar token: {exc}")
        return False

    if resp.status_code == 200:
        data = resp.json()
        display_name = data.get("display_phone_number", "desconocido")
        logger.info(f"[token_checker] Token válido. Número: {display_name}")
        return True

    if resp.status_code == 401:
        logger.error("[token_checker] Token EXPIRADO (401). Se requiere renovar WHATSAPP_ACCESS_TOKEN.")
        try:
            from tools.alert_handler import send_critical_alert
            send_critical_alert(
                "token_expired",
                "El WHATSAPP_ACCESS_TOKEN expiró (verificación diaria 8 AM). "
                "Renueva el token en Meta Business Suite y actualiza la variable en Railway.",
            )
        except Exception as exc:
            logger.error(f"[token_checker] No se pudo enviar alerta: {exc}")
        return False

    logger.warning(f"[token_checker] Respuesta inesperada {resp.status_code}: {resp.text[:200]}")
    try:
        from tools.alert_handler import send_critical_alert
        send_critical_alert(
            "token_check_failed",
            f"Verificación de token retornó {resp.status_code}: {resp.text[:200]}",
        )
    except Exception:
        pass
    return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ok = check_whatsapp_token()
    sys.exit(0 if ok else 1)
