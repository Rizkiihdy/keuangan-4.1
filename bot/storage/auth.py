"""
Shared Google Sheets authentication.

Extracted from sheets.py and sheets_manager.py to eliminate
duplicated auth code (CQ-01 / SEC-03).

Usage:
    from storage.auth import get_gspread_client
    gc = get_gspread_client()
"""

import os
import re
import json
import logging

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# Minimal required scope — removed broad 'drive' scope (SEC-03 fix)
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Singleton client
_gc: gspread.Client | None = None


def _parse_service_account_json() -> dict:
    """
    Parse GOOGLE_SERVICE_ACCOUNT_JSON environment variable into a dict.

    Handles common issues:
    - Surrounding quotes from certain secret stores
    - Trailing commas (invalid JSON from some copy-paste sources)
    - Literal newlines inside private_key string
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON environment variable is not set."
        )

    # Strip surrounding single or double quotes
    if len(raw) >= 2 and raw[0] in ("'", '"') and raw[-1] == raw[0]:
        raw = raw[1:-1]

    # Fix trailing commas before } or ]
    raw = re.sub(r",\s*}", "}", raw)
    raw = re.sub(r",\s*]", "]", raw)

    # Fix literal \n inside private_key value (re.DOTALL ensures multiline match)
    raw = re.sub(
        r'("private_key"\s*:\s*")(.*?)(")',
        lambda m: m.group(1) + m.group(2).replace("\n", "\\n") + m.group(3),
        raw,
        flags=re.DOTALL,
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"
        ) from exc


def get_gspread_client() -> gspread.Client:
    """
    Return a singleton authorized gspread client.

    Lazy-initialized on first call so that importing this module
    does NOT perform network I/O (CQ-02 fix).
    """
    global _gc
    if _gc is None:
        key_info = _parse_service_account_json()
        creds = Credentials.from_service_account_info(key_info, scopes=SCOPE)
        _gc = gspread.authorize(creds)
        logger.info("Google Sheets client initialized.")
    return _gc


def reset_client() -> None:
    """Force re-initialization on next call (useful for credential rotation)."""
    global _gc
    _gc = None
