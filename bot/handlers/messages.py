"""
Message handlers — thin handlers for non-command Telegram messages.

Delegates ALL logic to Brain. Zero business logic here.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from brain.brain import Brain
from utils.security import require_auth
from utils.formatting import fname

logger = logging.getLogger(__name__)


@require_auth
async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle free-text messages — the primary input method.

    Brain classifies and processes everything.
    Small talk → no loading message.
    Anything else → show "processing" first.
    """
    user = update.effective_user
    name = fname(user)
    text = update.message.text.strip()

    # Pre-classify with router to decide if we need a loading message
    from brain.router import Router, MessageType
    route = Router().classify(text)

    if route.message_type != MessageType.SMALL_TALK:
        await update.message.reply_text(f"Bentar ya {name}, aku proses dulu... ⏳")

    brain = Brain.get_instance()
    response = await brain.process_free_text(text, update.effective_chat.id, name)

    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle photo messages — receipt scanning via AI Vision.

    Always requires AI (Vision). Brain handles the full workflow.
    """
    user = update.effective_user
    name = fname(user)

    await update.message.reply_text(f"Ada struk nih {name}! Bentar, aku scan... 📸🔍")

    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        img_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.error(f"Photo download error: {e}")
        await update.message.reply_text(
            f"Aduh {name}, gagal download foto nih 😓 Coba lagi ya!"
        )
        return

    brain = Brain.get_instance()
    response = await brain.process_photo(img_bytes, "image/jpeg", update.effective_chat.id, name)
    await update.message.reply_text(response.text, parse_mode=response.parse_mode)
