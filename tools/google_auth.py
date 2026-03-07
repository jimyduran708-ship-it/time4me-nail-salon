"""
google_auth.py — Shared Google service account authentication.

Supports two modes (auto-detected from environment):
  1. File path:    GOOGLE_SERVICE_ACCOUNT_JSON=./service_account.json
  2. JSON string:  GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}

Mode 2 is used on Railway where you paste the JSON content directly
as an environment variable (no file upload needed).
"""

import os
import json
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_ENV_KEY = "GOOGLE_SERVICE_ACCOUNT_JSON"


def get_credentials(scopes: list[str] | None = None) -> service_account.Credentials:
    """
    Load service account credentials from env.
    Raises ValueError if the env var is missing or malformed.

    Args:
        scopes: OAuth2 scopes to request. Defaults to Calendar-only.
    """
    active_scopes = scopes if scopes is not None else DEFAULT_SCOPES

    raw = os.getenv(_ENV_KEY, "").strip()
    if not raw:
        raise ValueError(
            f"{_ENV_KEY} is not set. "
            "Set it to a file path (e.g. ./service_account.json) "
            "or paste the JSON content directly as the env var value."
        )

    # Detect JSON string vs file path
    if raw.startswith("{"):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=active_scopes)
    else:
        if not os.path.exists(raw):
            raise FileNotFoundError(f"Service account file not found: {raw}")
        return service_account.Credentials.from_service_account_file(raw, scopes=active_scopes)
