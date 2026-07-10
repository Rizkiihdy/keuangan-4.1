"""
Sheets data access layer — keuangan v4 spreadsheet.

Changes from V1:
- Lazy initialization: Sheets connection is made on first use,
  not at import time (CQ-02 fix).
- Shared auth: delegates to storage.auth.get_gspread_client()
  instead of duplicating auth code (CQ-01 fix).
- All public functions remain identical so Brain can call them
  without changes.
"""

import os
import re
import logging
from datetime import datetime, timedelta

from storage.auth import get_gspread_client
from config import (
    DAFTAR_AKUN, EXPENSE_CATEGORIES, INCOME_CATEGORIES,
    NON_BUDGET_CATEGORIES, TRANSAKSI_HEADERS
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# LAZY INITIALIZATION                                                  #
# ------------------------------------------------------------------ #
# These are None at import time. First function call triggers connect.

_sheet_utama = None
_sheet_transaksi = None


def _get_sheet_transaksi():
    """Return the Transaksi worksheet, connecting lazily on first call."""
    global _sheet_utama, _sheet_transaksi
    if _sheet_transaksi is None:
        gc = get_gspread_client()
        sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        if sheet_id:
            _sheet_utama = gc.open_by_key(sheet_id)
        else:
            _sheet_utama = gc.open("keuangan v4")
        _sheet_transaksi = _sheet_utama.worksheet("Transaksi")
        logger.info("Google Sheets (Transaksi) connected.")
    return _sheet_transaksi


def _get_sheet_utama():
    """Return the main spreadsheet, connecting lazily on first call."""
    _get_sheet_transaksi()  # ensures _sheet_utama is set
    return _sheet_utama


# ------------------------------------------------------------------ #
# TIMEZONE & EXCEL DATE HELPERS                                        #
# ------------------------------------------------------------------ #

WIB_OFFSET = timedelta(hours=7)


def now_wib() -> datetime:
    """Return current datetime in WIB (UTC+7)."""
    return datetime.utcnow() + WIB_OFFSET


def jam_sekarang_excel() -> float:
    """Return fraction of day for current WIB time (Num column)."""
    now = now_wib()
    return (now.hour / 24) + (now.minute / 1440) + (now.second / 86400)


def tanggal_sekarang_excel() -> float:
    """Return Excel serial date for today in WIB."""
    dt = now_wib()
    base = datetime(1899, 12, 30)
    delta = dt - base
    return delta.days + (delta.seconds / 86400)


def parse_rp(val_str) -> int:
    """Parse rupiah value: 'Rp3.700.000' → 3700000."""
    if not val_str:
        return 0
    s = str(val_str).strip()
    if not s:
        return 0
    s = re.sub(r"[Rp\s]", "", s)
    s = s.replace(".", "").replace(",", ".")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def excel_serial_to_iso(serial_str: str) -> str:
    """
    Convert Excel serial date number or date string to YYYY-MM-DD.

    Handles multiple formats for backward compatibility with
    manually-entered data in the sheet.
    """
    s = str(serial_str).strip()
    if not s:
        return ""
    try:
        serial = float(s)
        base = datetime(1899, 12, 30)
        dt = base + timedelta(days=serial)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def iso_to_excel_serial(iso_date_str: str) -> int:
    """Convert YYYY-MM-DD to Excel serial date number."""
    dt = datetime.strptime(iso_date_str, "%Y-%m-%d")
    base = datetime(1899, 12, 30)
    return (dt - base).days


# ------------------------------------------------------------------ #
# HELPERS                                                              #
# ------------------------------------------------------------------ #

def cari_baris_kosong(sheet) -> int:
    return len(sheet.col_values(1)) + 1


# ------------------------------------------------------------------ #
# WRITE                                                                #
# ------------------------------------------------------------------ #

def tulis_transaksi(
    akun: str,
    payee: str,
    memo: str,
    kategori: str,
    payment,
    deposit,
) -> None:
    """Write a single transaction row to the Transaksi sheet."""
    sheet = _get_sheet_transaksi()
    baris = cari_baris_kosong(sheet)
    data = [
        akun,
        tanggal_sekarang_excel(),
        jam_sekarang_excel(),
        payee,
        memo,
        "",             # Tag (reserved)
        kategori,
        "c",            # Clr
        int(payment) if payment else "",
        int(deposit) if deposit else "",
    ]
    sheet.update(
        range_name=f"A{baris}:J{baris}",
        values=[data],
        value_input_option="USER_ENTERED",
    )


def tulis_transfer(
    dari_akun: str,
    ke_akun: str,
    nominal: int,
    memo: str = "Pindah Saldo",
) -> None:
    """Write a transfer as two mirror rows (debit + credit)."""
    sheet = _get_sheet_transaksi()
    tgl = tanggal_sekarang_excel()
    jam = jam_sekarang_excel()
    b1 = cari_baris_kosong(sheet)

    sheet.update(
        range_name=f"A{b1}:J{b1}",
        values=[[dari_akun, tgl, jam, "-", memo, "", "[Transfer]", "c", int(nominal), ""]],
        value_input_option="USER_ENTERED",
    )
    b2 = b1 + 1
    sheet.update(
        range_name=f"A{b2}:J{b2}",
        values=[[ke_akun, tgl, jam, "-", memo, "", "[Transfer]", "c", "", int(nominal)]],
        value_input_option="USER_ENTERED",
    )


# ------------------------------------------------------------------ #
# READ                                                                 #
# ------------------------------------------------------------------ #

def get_semua_transaksi() -> list[dict]:
    """
    Read all transactions from the Transaksi sheet.

    Sheet keuangan V4 has 4 header rows; data starts at row index 4.
    Returns list of normalized transaction dicts.
    """
    sheet = _get_sheet_transaksi()
    semua = sheet.get_all_values()
    hasil = []

    for b in semua[4:]:
        if not b or not b[0].strip() or not (len(b) > 1 and b[1].strip()):
            continue
        akun = b[0].strip()
        if akun.startswith("[") or len(b) < 9:
            continue

        tgl_iso = excel_serial_to_iso(b[1])
        if not tgl_iso:
            continue

        payment = parse_rp(b[8]) if len(b) > 8 else 0
        deposit = parse_rp(b[9]) if len(b) > 9 else 0

        hasil.append({
            "akun":     akun,
            "tgl":      tgl_iso,
            "jam":      b[2].strip() if len(b) > 2 else "",
            "payee":    b[3].strip() if len(b) > 3 else "",
            "memo":     b[4].strip() if len(b) > 4 else "",
            "tag":      b[5].strip() if len(b) > 5 else "",
            "kategori": b[6].strip() if len(b) > 6 else "",
            "clr":      b[7].strip() if len(b) > 7 else "",
            "payment":  payment,
            "deposit":  deposit,
        })
    return hasil


def filter_operasional(transaksi: list[dict]) -> list[dict]:
    """Filter out non-operational categories (transfers, refunds, etc.)."""
    exclude = set(NON_BUDGET_CATEGORIES + ["[Beginning Balance]", "[Carryover Balance]", "NON-BUDGET CATEGORIES"])
    return [t for t in transaksi if t["kategori"] not in exclude]


def saldo_per_akun(transaksi: list[dict]) -> dict[str, float]:
    """Calculate balance per account from transaction list."""
    saldo: dict[str, float] = {}
    for t in transaksi:
        akun = t["akun"]
        saldo[akun] = saldo.get(akun, 0) + t["deposit"] - t["payment"]
    return saldo


def get_month_expense_for_category(kategori: str) -> float:
    """Total expense for a category in the current month."""
    bulan_ini = now_wib().strftime("%Y-%m")
    total = 0.0
    for t in get_semua_transaksi():
        if t["tgl"].startswith(bulan_ini) and t["kategori"] == kategori:
            total += t["payment"]
    return total


def get_anggaran_for_category(kategori: str) -> float:
    """
    Read budget for a category from the Budget sheet for the current month.

    Budget sheet structure (keuangan V4):
    - Data rows have category in col 0
    - Months in cols: Jan=col2, Feb=col3, ..., Dec=col13
    - So month N → col index = N + 1
    """
    try:
        sheet_budget = _get_sheet_utama().worksheet("Budget")
        data = sheet_budget.get_all_values()

        bulan_ini = now_wib().month
        col_index = bulan_ini + 1  # Jan(1)→col2, Feb(2)→col3, ...

        for row in data:
            if len(row) > col_index and row[0].strip() == kategori:
                val = row[col_index].strip()
                if val:
                    val_clean = re.sub(r"[Rp\s\.]", "", val).replace(",", ".")
                    try:
                        return float(val_clean)
                    except ValueError:
                        return 0.0
        return 0.0
    except Exception as e:
        logger.warning(f"Budget read error for {kategori}: {e}")
        return 0.0


def get_recent(n: int = 10) -> list[dict]:
    """Return the last N transactions in reverse chronological order."""
    txns = get_semua_transaksi()
    return txns[-n:][::-1]


def get_summary() -> dict:
    """
    Monthly summary for the current month.

    Returns: {total_income, total_expense, saldo, by_category, transactions}
    """
    bulan_ini = now_wib().strftime("%Y-%m")
    total_income = 0.0
    total_expense = 0.0
    by_category: dict[str, float] = {}
    transactions = 0

    for t in get_semua_transaksi():
        if not t["tgl"].startswith(bulan_ini):
            continue
        if t["kategori"] in NON_BUDGET_CATEGORIES:
            continue
        if t["payment"] > 0:
            total_expense += t["payment"]
            by_category[t["kategori"]] = by_category.get(t["kategori"], 0) + t["payment"]
            transactions += 1
        if t["deposit"] > 0:
            total_income += t["deposit"]
            transactions += 1

    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "saldo": total_income - total_expense,
        "by_category": by_category,
        "transactions": transactions,
    }


def get_week_transactions() -> list[dict]:
    """Return all transactions from the last 7 days."""
    hari_ini = now_wib().date()
    tujuh_lalu = hari_ini - timedelta(days=6)
    hasil = []
    for t in get_semua_transaksi():
        try:
            tgl_t = datetime.strptime(t["tgl"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if tujuh_lalu <= tgl_t <= hari_ini:
            hasil.append(t)
    return hasil
