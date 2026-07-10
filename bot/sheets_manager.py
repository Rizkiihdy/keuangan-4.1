"""
Multi-spreadsheet manager — manages connections to all 7 spreadsheets.

Changes from V1:
- Uses shared auth from storage.auth (CQ-01 fix, eliminates duplication)
- Auth code is no longer duplicated here
- All other behavior is identical
"""

import os
import logging
import gspread

from storage.auth import get_gspread_client

logger = logging.getLogger(__name__)


class SheetManager:
    """Manages a single worksheet inside a Google Spreadsheet."""

    def __init__(self, spreadsheet_id: str, worksheet_name: str, headers: list | None = None):
        self.spreadsheet_id = spreadsheet_id
        gc = get_gspread_client()
        self.spreadsheet = gc.open_by_key(spreadsheet_id)
        self.headers = headers
        try:
            self.worksheet = self.spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            if headers:
                self.worksheet = self.spreadsheet.add_worksheet(
                    title=worksheet_name,
                    rows="1000",
                    cols=str(len(headers)),
                )
                self.worksheet.append_row(headers)
            else:
                raise
        if headers:
            self._col_map = {h: i for i, h in enumerate(headers)}

    def find_empty_row(self) -> int:
        return len(self.worksheet.col_values(1)) + 1

    def append_row(self, values_dict: dict) -> None:
        if self.headers:
            row = [values_dict.get(h, "") for h in self.headers]
        else:
            row = list(values_dict.values())
        self.worksheet.append_row(row, value_input_option="USER_ENTERED")

    def get_all_rows(self) -> list[dict]:
        raw = self.worksheet.get_all_values()
        if not raw:
            return []
        headers = raw[0]
        rows = []
        for r in raw[1:]:
            if not any(r):
                continue
            rows.append({h: v for h, v in zip(headers, r)})
        return rows

    def get_row_count(self) -> int:
        return len(self.worksheet.get_all_values())


# ------------------------------------------------------------------ #
# SPREADSHEET REGISTRY                                                 #
# ------------------------------------------------------------------ #

SPREADSHEETS = {
    "keuangan": {
        "id": os.environ.get("GOOGLE_SHEET_ID", "1nbDsBmrQ74g-yC1k8_XVbh8kIP6wfC9ewjAxG6FaCtw"),
        "name": "keuangan v4",
        "sheets": {
            "Transaksi": ["Akun", "Tanggal", "Num", "Payee", "Memo", "Tag", "Category", "Clr", "PAYMENT", "DEPOSIT"],
            "Budget":    ["Kategori", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
            "Goals":     ["Nama Goal", "Target Jumlah", "Terkumpul", "Deadline", "Status", "Keterangan"],
            "Progress":  ["Tanggal", "Nama Goal", "Jumlah Masuk", "Saldo Goal"],
            "Aset":      ["Nama Aset", "Jenis", "Nilai Beli", "Nilai Sekarang", "Tanggal Beli", "Keterangan"],
        },
    },
    "home_affordability": {
        "id": "1-9aEDT1oGcucnQPTdI_QaikKD3F73pD5xcPY5WAchaQ",
        "name": "Home Affordability",
        "sheets": {"Sheet1": None},
    },
    "pensiun": {
        "id": "1WB9EUyYChvxb2cV6vNe9_7qDjYpz6vvjQgvF-iRd4Gg",
        "name": "Kalkulator Pensiun",
        "sheets": {"Sheet1": None},
    },
    "simulasi_kredit": {
        "id": "1kvXfV57eAxDx7Tlm-H0HwpVHHd1lXTEAXDJ8qvm0bEw",
        "name": "Simulasi Kredit Motor/Mobil",
        "sheets": {"Sheet1": None},
    },
    "tabungan_pensiun": {
        "id": "1YrvpTJsLE1MORB5i79EJYCuJIjti7f2wdP0M5v8lLjg",
        "name": "Kalkulator Tabungan Dana Pensiun",
        "sheets": {"Sheet1": None},
    },
    "investasi": {
        "id": "1XjhlnGvlgsaxl3ZB9iaxUCfVvKdhATXw3yWk-fJeq2U",
        "name": "Pelacak Investasi",
        "sheets": {
            "Account1": ["Tanggal", "Jenis", "Nama", "Jumlah Lot", "Harga Beli", "Total", "Broker", "Keterangan"],
            "Account2": ["Tanggal", "Jenis", "Nama", "Jumlah Lot", "Harga Beli", "Total", "Broker", "Keterangan"],
            "Account3": ["Tanggal", "Jenis", "Nama", "Jumlah Lot", "Harga Beli", "Total", "Broker", "Keterangan"],
            "Summary":  ["Nama", "Total Lot", "Avg Harga", "Total Value", "Profit/Loss"],
        },
    },
    "utang": {
        "id": "1pjxANUen_K-4Onvf2XENb1XnvdkI5_FOV2LjIA_wrq0",
        "name": "Kalkulator Utang",
        "sheets": {"Sheet1": None},
    },
}

# Singleton manager cache
_managers: dict[str, SheetManager] = {}


def get_manager(spreadsheet_key: str, sheet_key: str, headers: list | None = None) -> SheetManager:
    """Get or create a cached SheetManager for a spreadsheet/sheet pair."""
    cache_key = f"{spreadsheet_key}:{sheet_key}"
    if cache_key not in _managers:
        spec = SPREADSHEETS[spreadsheet_key]
        h = headers if headers else spec["sheets"].get(sheet_key)
        _managers[cache_key] = SheetManager(spec["id"], sheet_key, h)
    return _managers[cache_key]


def get_spreadsheet_id(key: str) -> str:
    return SPREADSHEETS[key]["id"]


def list_spreadsheets() -> list[tuple[str, dict]]:
    """Return list of all configured spreadsheet keys and specs."""
    return list(SPREADSHEETS.items())


def list_sheets(spreadsheet_key: str) -> list[str]:
    """Return sheet names inside a spreadsheet."""
    return list(SPREADSHEETS[spreadsheet_key]["sheets"].keys())


def read_sheet_raw(spreadsheet_key: str, sheet_key: str) -> list[list]:
    """Read all raw values from a sheet."""
    spec = SPREADSHEETS[spreadsheet_key]
    gc = get_gspread_client()
    spreadsheet = gc.open_by_key(spec["id"])
    ws = spreadsheet.worksheet(sheet_key)
    return ws.get_all_values()
