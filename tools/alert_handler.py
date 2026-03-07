"""
alert_handler.py — Alertas críticas al dueño del salón vía WhatsApp.

Envía un mensaje a OWNER_WHATSAPP cuando ocurre un error grave:
  - Token de WhatsApp expirado (401)
  - Fallo al sincronizar Google Calendar
  - Excepción no manejada en el webhook

Cooldown: no repite la misma categoría de error más de 1 vez por hora,
para evitar spam si el problema persiste.

Limitación conocida: si el token de WhatsApp está expirado, las alertas
de ese error específico también fallarán. En ese caso el error queda en logs.
"""

import os
import time
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP", "")
# Números del desarrollador — reciben todas las alertas críticas (sin '+', formato WA)
# Separados por coma en la env var, o hardcodeados como fallback
_DEV_ENV = os.getenv("DEVELOPER_WHATSAPP", "523330600171,523337054880")
DEV_WHATSAPP: list[str] = [n.strip().lstrip("+") for n in _DEV_ENV.split(",") if n.strip()]

COOLDOWN_SECONDS = 3600  # 1 hora entre alertas del mismo tipo

# Cooldown en memoria (se resetea al reiniciar el proceso)
_last_alerts: dict[str, float] = {}


def _all_recipients() -> list[str]:
    """Retorna lista de números a notificar (dueña + desarrolladores), sin duplicados."""
    recipients = list(DEV_WHATSAPP)
    if OWNER_WHATSAPP and OWNER_WHATSAPP not in recipients:
        recipients.append(OWNER_WHATSAPP)
    return recipients


def send_critical_alert(error_type: str, details: str) -> None:
    """
    Envía alerta WhatsApp a la dueña y al desarrollador para un error crítico.

    Args:
        error_type: Identificador corto del tipo de error, ej: "token_expired",
                    "calendar_sync_failed", "webhook_error", "backup_failed"
        details:    Descripción del error (se trunca a 300 chars para WA).
    """
    recipients = _all_recipients()
    if not recipients:
        logger.warning(f"[alert] Sin destinatarios configurados — alerta ignorada: {error_type}")
        return

    now = time.time()
    last_sent = _last_alerts.get(error_type, 0)
    if now - last_sent < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last_sent))
        logger.info(f"[alert] Cooldown activo para '{error_type}' — próxima alerta en {remaining}s")
        return

    _last_alerts[error_type] = now

    label = {
        "token_expired": "🔑 TOKEN WHATSAPP EXPIRADO",
        "calendar_sync_failed": "📅 FALLO SINCRONIZACIÓN CALENDAR",
        "webhook_error": "⚡ ERROR EN WEBHOOK",
        "backup_failed": "💾 FALLO DE RESPALDO DB",
        "token_check_failed": "🔑 VERIFICACIÓN DE TOKEN FALLÓ",
    }.get(error_type, f"🚨 ERROR: {error_type.upper()}")

    details_short = str(details)[:300]
    message = (
        f"🚨 *Alerta Bot — Time 4 me*\n\n"
        f"{label}\n\n"
        f"{details_short}\n\n"
        f"_Revisa los logs de Railway para más detalles._"
    )

    from tools.whatsapp_sender import send_text_message
    for number in recipients:
        try:
            send_text_message(to=number, text=message)
            logger.info(f"[alert] Alerta enviada a {number}: {error_type}")
        except Exception as exc:
            logger.error(f"[alert] No se pudo enviar alerta a {number} ({error_type}): {exc}")
