"""
backup_handler.py — Respaldo periódico de la base de datos SQLite a Google Drive.

Usa el service account existente (GOOGLE_SERVICE_ACCOUNT_JSON) para subir la DB.
Mantiene los últimos 7 backups; elimina los más antiguos automáticamente.

Corre como job APScheduler diario a las 2:00 AM (ver reminder_scheduler.py).
También puede ejecutarse manualmente:
    python -m tools.backup_handler

─────────────────────────────────────────────────────────────────────────────
PREREQUISITOS (una sola vez, configuración manual):

1. Google Cloud Console → "APIs y servicios" → Biblioteca
   → Buscar "Google Drive API" → Habilitar

2. Google Drive → Crear carpeta "Time4me Backups"
   → Compartir con el email del service account (formato: xxx@yyy.iam.gserviceaccount.com)
   → Rol: Editor

3. Copiar el ID de la carpeta (aparece en la URL: drive.google.com/drive/folders/ESTE_ID)

4. Railway → Variables → agregar:
   GOOGLE_DRIVE_BACKUP_FOLDER_ID = <el ID copiado>

El email del service account está en GOOGLE_SERVICE_ACCOUNT_JSON bajo "client_email".
─────────────────────────────────────────────────────────────────────────────
"""

import os
import io
import logging
import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_PATH = os.getenv("DATABASE_PATH", ".tmp/salon.db")
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", "")
MAX_BACKUPS = 7


def backup_db_to_drive() -> str:
    """
    Sube la DB a Google Drive como salon_backup_YYYY-MM-DD_HH-MM.db.
    Elimina backups antiguos si hay más de MAX_BACKUPS.
    Retorna el file_id del backup creado.
    Lanza Exception si falla (el scheduler lo logueará).
    """
    if not DRIVE_FOLDER_ID:
        raise RuntimeError(
            "GOOGLE_DRIVE_BACKUP_FOLDER_ID no configurado. "
            "Ver instrucciones en tools/backup_handler.py"
        )

    if not os.path.exists(DATABASE_PATH):
        raise FileNotFoundError(f"Base de datos no encontrada en: {DATABASE_PATH}")

    from tools.google_auth import get_credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    creds = get_credentials(scopes=[
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/drive.file",
    ])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"salon_backup_{timestamp}.db"

    # Leer DB en memoria (SQLite puede estar en uso; copiamos el contenido tal cual)
    with open(DATABASE_PATH, "rb") as f:
        db_bytes = f.read()

    media = MediaIoBaseUpload(
        io.BytesIO(db_bytes),
        mimetype="application/octet-stream",
        resumable=False,
    )
    file_meta = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
    }
    result = drive.files().create(body=file_meta, media_body=media, fields="id").execute()
    file_id = result["id"]
    logger.info(f"[backup] Backup subido: {filename} (id={file_id}, {len(db_bytes)//1024} KB)")

    # Limpiar backups antiguos (mantener solo los últimos MAX_BACKUPS)
    _cleanup_old_backups(drive)

    return file_id


def _cleanup_old_backups(drive) -> None:
    """Elimina backups antiguos, dejando solo los últimos MAX_BACKUPS."""
    query = (
        f"'{DRIVE_FOLDER_ID}' in parents "
        f"and name contains 'salon_backup_' "
        f"and trashed = false"
    )
    results = drive.files().list(
        q=query,
        orderBy="createdTime desc",
        fields="files(id, name, createdTime)",
    ).execute()
    files = results.get("files", [])

    if len(files) <= MAX_BACKUPS:
        return

    to_delete = files[MAX_BACKUPS:]
    for f in to_delete:
        try:
            drive.files().delete(fileId=f["id"]).execute()
            logger.info(f"[backup] Backup antiguo eliminado: {f['name']}")
        except Exception as exc:
            logger.warning(f"[backup] No se pudo eliminar {f['name']}: {exc}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        fid = backup_db_to_drive()
        print(f"Backup exitoso. file_id={fid}")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
