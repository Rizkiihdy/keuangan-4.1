"""
Oliv Bot — entry point.

This file is intentionally thin. Its only jobs:
1. Initialize Brain with all dependencies injected
2. Wire Telegram handlers
3. Start the polling loop

No business logic lives here. All decisions are Brain's responsibility.
"""

import os
import json
import logging
from datetime import time as dt_time

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

# Brain and modules
from brain.brain import Brain
from engine.memory import MemoryEngine
from utils.security import require_auth

# Handlers (thin wrappers)
from handlers.commands import (
    start, help_cmd, ringkasan, saldo_cmd, hariini_cmd, mingguini_cmd,
    terbesar_cmd, terakhir, analisa_cmd, budget_cmd, tanya, networth_cmd,
    forecast_cmd, pengeluaran, pemasukan,
    invest_cmd, dividen_cmd, jual_cmd, utang_cmd, piutang_cmd,
    goal_cmd, tabung_cmd, aset_cmd, list_sheets_cmd,
    post_init,
)
from handlers.messages import handle_free_text, handle_photo

# Sheets functions (injected into Brain)
from sheets import (
    get_semua_transaksi, tulis_transaksi, tulis_transfer,
    now_wib,
)
from sheets_manager import get_manager, list_spreadsheets, list_sheets

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is not set.")

REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "user_registry.json")


# ------------------------------------------------------------------ #
# USER REGISTRY (thin, kept for weekly report)                        #
# ------------------------------------------------------------------ #

def _load_reg() -> dict:
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_reg(reg: dict) -> None:
    try:
        with open(REGISTRY_FILE, "w") as f:
            json.dump(reg, f)
    except Exception as e:
        logger.error(f"Registry save failed: {e}")


# ------------------------------------------------------------------ #
# BRAIN WIRING                                                         #
# ------------------------------------------------------------------ #

def _get_budget_data() -> dict:
    """
    Fetch budget for all expense categories from Google Sheets.
    Returns {category: budget_amount} dict.
    """
    from sheets import get_anggaran_for_category
    from config import EXPENSE_CATEGORIES
    return {cat: get_anggaran_for_category(cat) for cat in EXPENSE_CATEGORIES}


def _get_goals_data():
    """Fetch goals and progress from Google Sheets."""
    try:
        goals_mgr = get_manager("keuangan", "Goals")
        progress_mgr = get_manager("keuangan", "Progress")
        return goals_mgr.get_all_rows(), progress_mgr.get_all_rows()
    except Exception as e:
        logger.warning(f"Goals fetch error: {e}")
        return [], []


def _initialize_brain() -> Brain:
    """Initialize Brain with all dependencies injected."""
    memory = MemoryEngine()  # uses default path (bot/memory_store.json)

    brain = Brain.initialize(
        sheets_read_fn=get_semua_transaksi,
        sheets_write_fn=tulis_transaksi,
        sheets_transfer_fn=tulis_transfer,
        sheets_budget_fn=_get_budget_data,
        sheets_goals_fn=_get_goals_data,
        sheets_manager_fn=get_manager,
        memory_engine=memory,
    )
    return brain


# ------------------------------------------------------------------ #
# WEEKLY REPORT JOB                                                    #
# ------------------------------------------------------------------ #

async def _send_weekly_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled weekly report — calls Brain for content generation."""
    reg = _load_reg()
    if not reg:
        logger.info("Weekly report: no registered users.")
        return

    brain = Brain.get_instance()
    logger.info(f"Sending weekly reports to {len(reg)} users...")

    for chat_id_str, info in reg.items():
        try:
            name = info.get("first_name", "Kak")
            report = await brain.generate_weekly_report_for_user(int(chat_id_str), name)
            await context.bot.send_message(
                chat_id=int(chat_id_str),
                text=f"📊 *LAPORAN MINGGUAN dari Oliv* 📊\n\n{report}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Weekly report failed for {chat_id_str}: {e}")


# ------------------------------------------------------------------ #
# MAIN                                                                 #
# ------------------------------------------------------------------ #

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN not set.")

    # Initialize Brain (lazy — Sheets and Gemini connect on first use)
    brain = _initialize_brain()
    logger.info("Brain initialized successfully.")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Pass registry helpers via bot_data for handlers that need it
    registry = _load_reg()
    app.bot_data["registry"] = registry
    app.bot_data["save_reg"] = _save_reg

    # Commands
    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("help",         help_cmd))
    app.add_handler(CommandHandler("pengeluaran",  pengeluaran))
    app.add_handler(CommandHandler("pemasukan",    pemasukan))
    app.add_handler(CommandHandler("ringkasan",    ringkasan))
    app.add_handler(CommandHandler("saldo",        saldo_cmd))
    app.add_handler(CommandHandler("hariini",      hariini_cmd))
    app.add_handler(CommandHandler("mingguini",    mingguini_cmd))
    app.add_handler(CommandHandler("terbesar",     terbesar_cmd))
    app.add_handler(CommandHandler("analisa",      analisa_cmd))
    app.add_handler(CommandHandler("budget",       budget_cmd))
    app.add_handler(CommandHandler("terakhir",     terakhir))
    app.add_handler(CommandHandler("tanya",        tanya))
    app.add_handler(CommandHandler("networth",     networth_cmd))
    app.add_handler(CommandHandler("forecast",     forecast_cmd))
    app.add_handler(CommandHandler("invest",       invest_cmd))
    app.add_handler(CommandHandler("dividen",      dividen_cmd))
    app.add_handler(CommandHandler("jual",         jual_cmd))
    app.add_handler(CommandHandler("utang",        utang_cmd))
    app.add_handler(CommandHandler("piutang",      piutang_cmd))
    app.add_handler(CommandHandler("goal",         goal_cmd))
    app.add_handler(CommandHandler("tabung",       tabung_cmd))
    app.add_handler(CommandHandler("aset",         aset_cmd))
    app.add_handler(CommandHandler("sheets",       list_sheets_cmd))

    # Message handlers (Brain routes internally)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    # Weekly report scheduler
    if app.job_queue:
        app.job_queue.run_daily(
            _send_weekly_report,
            time=dt_time(12, 0, 0),  # 12:00 UTC = 19:00 WIB
            days=(6,),               # Sunday
            name="weekly_report",
        )
        logger.info("Weekly report scheduled: Sunday 19:00 WIB.")
    else:
        logger.warning("Job queue unavailable — install python-telegram-bot[job-queue].")

    logger.info("Oliv Brain V2 started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
