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

    # Avoid classifying twice; Brain owns routing and parsing.
    brain = Brain.get_instance()
    response = await brain.process_free_text(text, update.effective_chat.id, name)

    await update.message.reply_text(response.text, parse_mode=response.parse_mode)


@require_auth
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a Telegram voice note, then pass its text through the normal transaction flow."""
    user = update.effective_user
    name = fname(user)
    await update.message.reply_text("🎙️ Aku dengarkan voice kamu dulu ya...")

    try:
        voice = update.message.voice
        tg_file = await context.bot.get_file(voice.file_id)
        audio_bytes = bytes(await tg_file.download_as_bytearray())
        mime_type = voice.mime_type or "audio/ogg"

        brain = Brain.get_instance()
        transcript = await brain._ai.transcribe_voice_async(audio_bytes, mime_type)
        if not transcript:
            await update.message.reply_text(
                "Maaf, suaranya belum terbaca jelas. Coba rekam ulang dengan suara lebih dekat ya."
            )
            return

        await update.message.reply_text(
            f"📝 Aku menangkap: _{transcript}_\n\nAku proses sebagai transaksi ya...",
            parse_mode="Markdown",
        )
        response = await brain.process_free_text(transcript, update.effective_chat.id, name)
        await update.message.reply_text(response.text, parse_mode=response.parse_mode)
    except Exception as e:
        logger.exception("Voice processing failed: %s", e)
        await update.message.reply_text(
            "Maaf, voice note belum berhasil diproses. Coba kirim ulang atau ketik transaksinya ya."
        )


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
