"""
Access control — @require_auth decorator and allowlist management.

Implements V2.1 Access Control from the roadmap.

Configuration:
    Set ALLOWED_TELEGRAM_IDS environment variable to a comma-separated
    list of authorized Telegram user IDs.

    Example: ALLOWED_TELEGRAM_IDS=123456789,987654321

    If the variable is empty or not set, the bot operates in OPEN mode
    (backward compatible with V1 behavior). A warning is logged.

Security contract:
    Every handler MUST be decorated with @require_auth.
    Unauthorized users receive a generic "bot is private" message
    that reveals no information about the system.
"""

import os
import logging
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Cached allowlist (loaded once, then cached)
_ALLOWED_IDS: set[int] | None = None


def _load_allowed_ids() -> set[int]:
    """Parse ALLOWED_TELEGRAM_IDS from environment."""
    raw = os.environ.get("ALLOWED_TELEGRAM_IDS", "").strip()
    if not raw:
        logger.warning(
            "ALLOWED_TELEGRAM_IDS is not set. Bot is running in OPEN mode — "
            "anyone can access financial data. Set this variable to secure the bot."
        )
        return set()

    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
        elif part:
            logger.warning(f"Ignoring non-numeric ALLOWED_TELEGRAM_IDS entry: {part!r}")

    logger.info(f"Access control: {len(ids)} authorized user(s) configured.")
    return ids


def get_allowed_ids() -> set[int]:
    """Return the cached allowlist (loaded lazily on first call)."""
    global _ALLOWED_IDS
    if _ALLOWED_IDS is None:
        _ALLOWED_IDS = _load_allowed_ids()
    return _ALLOWED_IDS


def is_authorized(chat_id: int) -> bool:
    """
    Check if a Telegram chat_id is authorized.

    Returns True if:
    - ALLOWED_TELEGRAM_IDS is not configured (open mode)
    - The chat_id is in the allowlist
    """
    allowed = get_allowed_ids()
    if not allowed:
        return True  # open mode
    return chat_id in allowed


def require_auth(func: Callable) -> Callable:
    """
    Decorator that enforces access control on Telegram handlers.

    Usage:
        @require_auth
        async def my_handler(update, context):
            ...

    Unauthorized users get a generic rejection message. No information
    about the system or its data is revealed.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id if update.effective_chat else None
        user_id = update.effective_user.id if update.effective_user else None

        check_id = user_id or chat_id
        if check_id is None or not is_authorized(check_id):
            logger.warning(
                f"Unauthorized access attempt — user_id={user_id}, chat_id={chat_id}"
            )
            if update.message:
                await update.message.reply_text(
                    "Maaf, bot ini private. 🔒\n\n"
                    "Kalau kamu merasa ini kesalahan, hubungi pemilik bot ya!"
                )
            return
        return await func(update, context)

    return wrapper


def reload_allowlist() -> int:
    """Force reload of the allowlist from environment. Returns count of authorized IDs."""
    global _ALLOWED_IDS
    _ALLOWED_IDS = None
    ids = get_allowed_ids()
    return len(ids)
