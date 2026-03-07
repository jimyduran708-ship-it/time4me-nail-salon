"""
setup_ops.py — Configura las variables de Railway para la infraestructura de operaciones.

Qué hace:
  1. Genera STATUS_TOKEN aleatorio
  2. Crea carpeta "Time4me Backups" en Google Drive (requiere Drive API habilitada)
  3. Sube STATUS_TOKEN y GOOGLE_DRIVE_BACKUP_FOLDER_ID a Railway

Prerequisito para Drive:
  Google Cloud Console → APIs → Google Drive API → Habilitar
  (mismo proyecto que el Calendar existente)

Correr:
    set PYTHONUTF8=1
    python -m tools.setup_ops
"""

import os
import sys
import json
import secrets
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Railway IDs (desde memory/architecture.md)
RAILWAY_PROJECT_ID = "0dc7ee8f-37ce-492e-b383-a5ad0dfdfd8a"
RAILWAY_ENV_ID = "08d2a10f-e1d8-40f7-9998-40e47e218fd9"
RAILWAY_SERVICE_ID = "b8f62b9d-2889-4c77-b33c-83a62f817365"
RAILWAY_CONFIG = os.path.expanduser("~/.railway/config.json")


def _railway_token() -> str:
    with open(RAILWAY_CONFIG) as f:
        return json.load(f)["user"]["token"]


def _set_railway_vars(variables: dict) -> None:
    token = _railway_token()
    vars_gql = ", ".join(f'{k}: "{v}"' for k, v in variables.items())
    query = (
        'mutation { variableCollectionUpsert(input: {'
        f'projectId: "{RAILWAY_PROJECT_ID}", '
        f'environmentId: "{RAILWAY_ENV_ID}", '
        f'serviceId: "{RAILWAY_SERVICE_ID}", '
        f'variables: {{{vars_gql}}}'
        '}) }'
    )
    resp = requests.post(
        "https://backboard.railway.app/graphql/v2",
        json={"query": query},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Railway GraphQL error: {data['errors']}")
    logger.info(f"[railway] Variables subidas: {list(variables.keys())}")


def _create_drive_folder() -> str:
    """Crea 'Time4me Backups' en Drive y retorna el folder_id."""
    from tools.google_auth import get_credentials
    from googleapiclient.discovery import build

    creds = get_credentials(scopes=[
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/drive.file",
    ])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    # Verificar si ya existe
    results = drive.files().list(
        q="name = 'Time4me Backups' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id, name)",
    ).execute()
    existing = results.get("files", [])
    if existing:
        folder_id = existing[0]["id"]
        logger.info(f"[drive] Carpeta ya existe: id={folder_id}")
        return folder_id

    # Crear carpeta nueva
    meta = {
        "name": "Time4me Backups",
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = drive.files().create(body=meta, fields="id").execute()
    folder_id = folder["id"]
    logger.info(f"[drive] Carpeta creada: id={folder_id}")
    return folder_id


def main() -> None:
    print("\n=== Setup Infraestructura de Operaciones ===\n")

    # 1. STATUS_TOKEN
    existing_status_token = os.getenv("STATUS_TOKEN", "")
    if existing_status_token:
        status_token = existing_status_token
        print(f"STATUS_TOKEN ya existe en .env: {status_token[:8]}...")
    else:
        status_token = secrets.token_hex(16)
        print(f"STATUS_TOKEN generado: {status_token}")

    # 2. Drive folder
    print("\nCreando carpeta de backups en Google Drive...")
    print("(Si falla con 403: habilita Google Drive API en Cloud Console primero)")
    try:
        folder_id = _create_drive_folder()
        print(f"Carpeta Drive OK: id={folder_id}")
        drive_ok = True
    except Exception as exc:
        print(f"\nERROR Drive: {exc}")
        print("\nPaso manual necesario:")
        print("  1. Abre: https://console.cloud.google.com/apis/library/drive.googleapis.com")
        print("  2. Habilita Google Drive API en el mismo proyecto que Calendar")
        print("  3. Vuelve a correr este script")
        folder_id = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", "")
        drive_ok = False

    # 3. Railway
    print("\nSubiendo variables a Railway...")
    vars_to_set = {"STATUS_TOKEN": status_token}
    if drive_ok and folder_id:
        vars_to_set["GOOGLE_DRIVE_BACKUP_FOLDER_ID"] = folder_id
    elif folder_id:
        vars_to_set["GOOGLE_DRIVE_BACKUP_FOLDER_ID"] = folder_id

    try:
        _set_railway_vars(vars_to_set)
        print("Variables subidas a Railway OK.")
    except Exception as exc:
        print(f"ERROR Railway: {exc}")
        print("Sube las variables manualmente:")
        for k, v in vars_to_set.items():
            print(f"  {k} = {v}")

    print("\n=== Resumen ===")
    print(f"STATUS_TOKEN        = {status_token}")
    print(f"Drive folder_id     = {folder_id or '(pendiente)'}")
    print(f"\nURL panel status:")
    print(f"  https://time4me-nail-salon-production.up.railway.app/status?token={status_token}")
    if not drive_ok:
        print("\nFalta: habilitar Drive API y volver a correr este script.")


if __name__ == "__main__":
    main()
