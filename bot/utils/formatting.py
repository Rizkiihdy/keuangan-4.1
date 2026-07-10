"""
Formatting utilities — rp(), fname(), emoji_kategori(), komentar_personal().

Extracted from bot.py (CQ-04 fix) to make them independently testable
and reusable across handlers and Brain.
"""

import random
from config import KATEGORI_EMOJI, KOMENTAR_OLIV


def rp(amount: float | int) -> str:
    """Format number as Indonesian Rupiah string.

    Example: 15000 → 'Rp 15.000'
    """
    return "Rp " + f"{float(amount):,.0f}".replace(",", ".")


def fname(user) -> str:
    """Return user's first name, defaulting to 'Kak'."""
    return (user.first_name or "Kak") if user else "Kak"


def emoji_kategori(kategori: str) -> str:
    """Return emoji for a transaction category."""
    return KATEGORI_EMOJI.get(kategori, "📌")


def komentar_personal(memo: str) -> str | None:
    """
    Return a random personal comment for recognized memo keywords.

    Returns None if no keyword matches (avoids repeated identical comments).
    """
    if not memo:
        return None
    memo_lower = memo.lower()
    for keyword, comments in KOMENTAR_OLIV.items():
        if keyword in memo_lower:
            return random.choice(comments)
    return None


def format_currency_short(amount: float | int) -> str:
    """Format large numbers in short form: 1500000 → '1,5 jt'"""
    amount = float(amount)
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f} jt".replace(".", ",")
    if amount >= 1_000:
        return f"{amount / 1_000:.0f} rb"
    return rp(amount)


def format_percentage(ratio: float) -> str:
    """Format ratio as percentage string: 0.85 → '85%'"""
    return f"{ratio * 100:.0f}%"


def format_transaction_line(txn: dict, show_account: bool = True) -> str:
    """Format a single transaction dict into a readable line."""
    em = emoji_kategori(txn.get("kategori", ""))
    memo = (txn.get("memo") or txn.get("kategori") or "-").title()
    amount = txn.get("payment", 0) or txn.get("deposit", 0)
    direction = "📉" if txn.get("payment", 0) > 0 else "📈"
    date = txn.get("tgl", "-")
    line = f"{direction} `{date}` {em} *{memo}* — {rp(amount)}"
    if show_account and txn.get("akun"):
        line += f" ({txn['akun']})"
    return line
