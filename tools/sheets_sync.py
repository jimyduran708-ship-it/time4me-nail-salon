"""
sheets_sync.py — Sincroniza clientes y citas a Google Sheets para visibilidad de la dueña.

Mantiene dos pestañas actualizadas en tiempo real:
  - "Clientes"  → todos los clientes registrados
  - "Citas"     → todas las citas (pasadas y futuras)

La lógica es un overwrite completo en cada sync: borra todo y reescribe.
Funciona bien para el volumen de un salón pequeño.

Env var requerida:
  GOOGLE_SHEETS_ID — ID del spreadsheet (se configura con tools/setup_sheets.py)

La API de Sheets debe estar habilitada en Google Cloud Console
(mismo proyecto que Calendar).

Corre periódicamente como job del scheduler y también después de
cada acción del bot (send_message, create_booking, etc.).
"""

import os
import logging
import pytz
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
TZ = pytz.timezone("America/Mexico_City")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]

STATUS_LABELS = {
    "pending":   "⏳ Pendiente",
    "confirmed": "✅ Confirmada",
    "cancelled": "❌ Cancelada",
    "completed": "✔ Completada",
    "no_show":   "👻 No se presentó",
}


def _sheets_service():
    from tools.google_auth import get_credentials
    from googleapiclient.discovery import build
    creds = get_credentials(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _fmt_dt(iso: str) -> tuple[str, str]:
    """Convierte ISO datetime a (fecha 'Lun 10 Mar', hora '10:30 AM')."""
    if not iso:
        return "", ""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        dt_local = dt.astimezone(TZ)
        dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        meses = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                 "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        fecha = f"{dias[dt_local.weekday()]} {dt_local.day} {meses[dt_local.month]}"
        hora = dt_local.strftime("%-I:%M %p") if os.name != "nt" else dt_local.strftime("%I:%M %p").lstrip("0")
        return fecha, hora
    except Exception:
        return iso[:10], ""


def sync_all_to_sheets() -> None:
    """
    Overwrite completo de ambas pestañas desde SQLite.
    Llama esto después de cualquier evento importante o como job periódico.
    """
    if not SHEETS_ID:
        logger.debug("[sheets] GOOGLE_SHEETS_ID no configurado — sync omitido")
        return

    try:
        _sync_clientes()
        _sync_citas()
        logger.info("[sheets] Sync completo a Google Sheets OK")
    except Exception as exc:
        logger.error(f"[sheets] Sync falló: {exc}", exc_info=True)


def _sync_clientes() -> None:
    from tools.db_init import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, phone, notes, created_at, last_visit FROM clients ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    header = [["ID", "Nombre", "Teléfono", "Notas", "Registrado", "Última visita"]]
    data = []
    for r in rows:
        created = r["created_at"][:10] if r["created_at"] else ""
        last = r["last_visit"][:10] if r["last_visit"] else ""
        data.append([
            r["id"],
            r["name"] or "",
            r["phone"] or "",
            r["notes"] or "",
            created,
            last,
        ])

    _overwrite_sheet("Clientes", header + data)


def _sync_citas() -> None:
    from tools.db_init import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT a.id, c.name AS client_name, c.phone AS client_phone,
                   a.service, a.stylist, a.start_time, a.status, a.updated_at
            FROM appointments a
            LEFT JOIN clients c ON a.client_id = c.id
            ORDER BY a.start_time DESC
            """
        ).fetchall()
    finally:
        conn.close()

    header = [["ID", "Cliente", "Teléfono", "Servicio", "Estilista",
               "Fecha", "Hora", "Estado", "Actualizado"]]
    data = []
    for r in rows:
        fecha, hora = _fmt_dt(r["start_time"])
        updated = r["updated_at"][:10] if r["updated_at"] else ""
        data.append([
            r["id"],
            r["client_name"] or "—",
            r["client_phone"] or "—",
            r["service"] or "—",
            r["stylist"] or "—",
            fecha,
            hora,
            STATUS_LABELS.get(r["status"], r["status"] or ""),
            updated,
        ])

    _overwrite_sheet("Citas", header + data)


def _overwrite_sheet(tab_name: str, values: list[list]) -> None:
    """Borra el contenido de la pestaña y escribe los nuevos valores."""
    svc = _sheets_service()
    sheets = svc.spreadsheets()

    # Limpiar primero
    sheets.values().clear(
        spreadsheetId=SHEETS_ID,
        range=f"{tab_name}!A:Z",
    ).execute()

    if not values:
        return

    sheets.values().update(
        spreadsheetId=SHEETS_ID,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
