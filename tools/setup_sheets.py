"""
setup_sheets.py — Crea el Google Spreadsheet "Time 4 me — Panel" y lo configura.

Qué hace:
  1. Crea un Spreadsheet con dos pestañas: "Clientes" y "Citas"
  2. Formatea las cabeceras (fondo oscuro, texto blanco, negrita)
  3. Congela la fila de cabeceras
  4. Comparte el Spreadsheet con el email de la dueña (opcional)
  5. Sube GOOGLE_SHEETS_ID a Railway
  6. Hace el primer sync completo de datos

Prerequisito:
  Google Cloud Console → APIs → "Google Sheets API" → Habilitar
  (mismo proyecto que Calendar y Drive)

Correr:
  set PYTHONUTF8=1
  python -m tools.setup_sheets [email-de-la-dueña@gmail.com]
"""

import os
import sys
import json
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAILWAY_PROJECT_ID = "0dc7ee8f-37ce-492e-b383-a5ad0dfdfd8a"
RAILWAY_ENV_ID = "08d2a10f-e1d8-40f7-9998-40e47e218fd9"
RAILWAY_SERVICE_ID = "b8f62b9d-2889-4c77-b33c-83a62f817365"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Colores cabecera: morado oscuro para Clientes, azul oscuro para Citas
HEADER_COLOR_CLIENTES = {"red": 0.29, "green": 0.13, "blue": 0.42}
HEADER_COLOR_CITAS = {"red": 0.07, "green": 0.27, "blue": 0.49}


def _build_services():
    from tools.google_auth import get_credentials
    from googleapiclient.discovery import build
    creds = get_credentials(scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return sheets, drive


def _railway_token() -> str:
    config_path = os.path.expanduser("~/.railway/config.json")
    with open(config_path) as f:
        return json.load(f)["user"]["token"]


def _set_railway_var(key: str, value: str) -> None:
    token = _railway_token()
    query = (
        'mutation { variableCollectionUpsert(input: {'
        f'projectId: "{RAILWAY_PROJECT_ID}", '
        f'environmentId: "{RAILWAY_ENV_ID}", '
        f'serviceId: "{RAILWAY_SERVICE_ID}", '
        f'variables: {{{key}: "{value}"}}'
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
        raise RuntimeError(f"Railway error: {data['errors']}")


def _format_header_request(sheet_id: int, color: dict, num_cols: int) -> list:
    """Genera requests de formato para la fila de cabecera de una pestaña."""
    return [
        # Fondo de color
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": num_cols},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                       "bold": True, "fontSize": 10},
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
        # Congelar cabecera
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id,
                               "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]


def create_spreadsheet(owner_email: str = "") -> str:
    """Crea el spreadsheet, formatea y retorna su ID."""
    sheets_svc, drive_svc = _build_services()

    # 1. Crear el archivo vía Drive API (el service account tiene su propio Drive)
    #    mimeType de Google Sheets crea un Spreadsheet vacío con una pestaña "Sheet1"
    drive_result = drive_svc.files().create(
        body={
            "name": "Time 4 me - Panel de Operaciones",
            "mimeType": "application/vnd.google-apps.spreadsheet",
        },
        fields="id",
    ).execute()
    sheet_id = drive_result["id"]
    logger.info(f"[setup] Archivo creado via Drive API: id={sheet_id}")

    # 2. Renombrar la pestaña "Sheet1" a "Clientes" y agregar "Citas"
    # Primero obtenemos el sheetId real de la pestaña existente
    meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets").execute()
    first_tab_id = meta["sheets"][0]["properties"]["sheetId"]

    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": first_tab_id, "title": "Clientes"},
                "fields": "title",
            }},
            {"addSheet": {"properties": {"title": "Citas", "index": 1}}},
        ]},
    ).execute()

    # Obtener IDs actualizados
    meta2 = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets").execute()
    sheet_tabs = {s["properties"]["title"]: s["properties"]["sheetId"]
                  for s in meta2["sheets"]}

    logger.info(f"[setup] Pestanas configuradas: {list(sheet_tabs.keys())}")

    # 2. Formatear cabeceras y congelar filas
    format_requests = (
        _format_header_request(sheet_tabs["Clientes"], HEADER_COLOR_CLIENTES, 6) +
        _format_header_request(sheet_tabs["Citas"], HEADER_COLOR_CITAS, 9)
    )
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": format_requests},
    ).execute()
    logger.info("[setup] Formato de cabeceras aplicado")

    # 3. Ancho de columnas automático (autoResize)
    auto_resize = [
        {"autoResizeDimensions": {
            "dimensions": {"sheetId": tab_id, "dimension": "COLUMNS",
                           "startIndex": 0, "endIndex": 9}
        }}
        for tab_id in sheet_tabs.values()
    ]
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": auto_resize},
    ).execute()

    # 4. Compartir con la dueña si se proporcionó email
    if owner_email:
        try:
            drive_svc.permissions().create(
                fileId=sheet_id,
                body={"type": "user", "role": "reader", "emailAddress": owner_email},
                sendNotificationEmail=True,
            ).execute()
            logger.info(f"[setup] Compartido con {owner_email} (lector)")
        except Exception as exc:
            logger.warning(f"[setup] No se pudo compartir con {owner_email}: {exc}")

    return sheet_id


def configure_existing_spreadsheet(sheet_id: str) -> None:
    """Configura pestanas y formato en un Spreadsheet ya existente."""
    sheets_svc, _ = _build_services()

    meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets").execute()
    existing_titles = {s["properties"]["title"]: s["properties"]["sheetId"]
                       for s in meta["sheets"]}

    requests = []
    # Renombrar primera pestaña a "Clientes" si no existe
    if "Clientes" not in existing_titles:
        first_id = list(existing_titles.values())[0]
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": first_id, "title": "Clientes"},
            "fields": "title",
        }})
        existing_titles["Clientes"] = first_id

    # Agregar "Citas" si no existe
    if "Citas" not in existing_titles:
        requests.append({"addSheet": {"properties": {"title": "Citas", "index": 1}}})

    if requests:
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": requests}
        ).execute()

    # Obtener IDs finales
    meta2 = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets").execute()
    sheet_tabs = {s["properties"]["title"]: s["properties"]["sheetId"]
                  for s in meta2["sheets"]}

    # Formatear cabeceras
    fmt_requests = (
        _format_header_request(sheet_tabs["Clientes"], HEADER_COLOR_CLIENTES, 6) +
        _format_header_request(sheet_tabs["Citas"], HEADER_COLOR_CITAS, 9)
    )
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id, body={"requests": fmt_requests}
    ).execute()
    logger.info(f"[setup] Spreadsheet {sheet_id} configurado correctamente")


def main() -> None:
    # Uso: python -m tools.setup_sheets [SPREADSHEET_ID] [owner@email.com]
    args = sys.argv[1:]
    sheet_id_arg = ""
    owner_email = ""
    for a in args:
        if "@" in a:
            owner_email = a
        elif len(a) > 20:  # IDs de Drive son largos
            sheet_id_arg = a

    print("\n=== Setup Google Sheets - Time 4 me ===\n")

    existing = os.getenv("GOOGLE_SHEETS_ID", "") or sheet_id_arg
    if existing:
        sheet_id = existing
        print(f"Usando Spreadsheet existente: {sheet_id}")
        print("Configurando pestanas y formato...")
        try:
            configure_existing_spreadsheet(sheet_id)
            print("Formato aplicado OK")
        except Exception as exc:
            print(f"Aviso formato: {exc} (continuando de todas formas)")
    else:
        print("No se proporcionó un Spreadsheet ID.")
        print("\nPasos para crear el panel:")
        print("  1. Ve a https://sheets.google.com y crea un nuevo Spreadsheet")
        print("  2. Comparte con Editor: salon-bot@time-4-me-nail-salon.iam.gserviceaccount.com")
        print("  3. Copia el ID de la URL (la parte larga entre /d/ y /edit)")
        print("  4. Corre: python -m tools.setup_sheets TU_SPREADSHEET_ID")
        sys.exit(0)

    print("\nSubiendo GOOGLE_SHEETS_ID a Railway...")
    try:
        _set_railway_var("GOOGLE_SHEETS_ID", sheet_id)
        print("OK")
    except Exception as exc:
        print(f"ERROR Railway: {exc}")
        print(f"Subelo manualmente: GOOGLE_SHEETS_ID = {sheet_id}")

    # Primer sync de datos
    print("\nSincronizando datos actuales...")
    os.environ["GOOGLE_SHEETS_ID"] = sheet_id
    try:
        from tools.sheets_sync import sync_all_to_sheets
        sync_all_to_sheets()
        print("Sync OK")
    except Exception as exc:
        print(f"Sync fallo: {exc}")

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    print(f"\n=== Listo ===")
    print(f"URL del panel: {url}")
    if owner_email:
        print(f"Comparte el link con: {owner_email}")
    else:
        print("Comparte el link con la duena para que pueda verlo.")


if __name__ == "__main__":
    main()
