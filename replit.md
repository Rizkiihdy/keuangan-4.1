# Oliv — Personal Finance Bot

# 🧭 Status Saat Ini

Proyek Oliv berada di **akhir Phase 2 — sekitar 90–95% selesai**.

| Phase | Status | Detail |
|---|---|---|
| **Phase 1** | ✅ Stabil & berjalan | Telegram bot, Google Sheets, AI parsing (text + struk), laporan, budget, transaksi manual/transfer/invest/utang/goal. Dashboard tidak ada di repo ini (`.replit` masih nunjuk folder `dashboard/` yang tidak ditemukan). |
| **Phase 2** | 🚧 ~90–95% | Arsitektur Brain V2 sudah jadi: `Brain` singleton, `Router`, `DecisionEngine`, `ContextBuilder`, `AIEngine` v2, `FinancialEngine`, `MemoryEngine` v3 + `MemoryRetriever`. Sisanya: `ReflectionEngine` sudah diimplementasikan tapi belum di-*wire* di `bot.py` (di-pass `None`), jadi ekstraksi memory latar belakang dan analisis perilaku dari transaksi belum aktif. |
| **Phase 3** | 🔜 Belum dimulai | `Knowledge Engine` dan lapisan `Financial Intelligence` belum ada. Predictive analysis sudah dimulai ringan lewat `FinancialEngine.forecast_month_end()` & command `/forecast`. |

Langkah terdekat untuk mencapai 100% Phase 2: inject `ReflectionEngine` (butuh `MemoryExtractor` + `AIEngine`) ke `Brain.initialize()` dan tambahkan handler `/ingatan` di Telegram (kode Brain-nya sudah siap).

Oliv is a Telegram bot that helps track personal finances by logging transactions (income, expenses, transfers) to Google Sheets using natural language and receipt photo scanning powered by Gemini AI.

## Run & Operate

- `python main.py` — run the Telegram finance bot (main workflow)
- `cd bot && python bot.py` — run the bot directly

## Required Secrets

All secrets are stored in Replit's secret store (never hardcoded):
- `TELEGRAM_TOKEN` — Telegram bot token
- `GEMINI_API_KEY` — Google Gemini API key for AI parsing
- `GOOGLE_SERVICE_ACCOUNT_JSON` — Full JSON content of the Google service account key
- `GOOGLE_SHEET_ID` — (env var) Google Sheet ID for the spreadsheet

## Stack

- **Bot**: Python 3.11, python-telegram-bot, google-genai, gspread
- **AI**: Google Gemini 2.0/2.5 Flash (text + vision for receipt scanning)
- **Storage**: Google Sheets ("keuangan v4" → "Transaksi" worksheet)

## Where things live

- `bot/bot.py` — Telegram command handlers and message routing
- `bot/gemini_ai.py` — AI transaction parsing and receipt OCR
- `bot/sheets.py` — Google Sheets read/write (keuangan v4)
- `bot/sheets_manager.py` — Multi-spreadsheet manager (investasi, utang, aset, dll)
- `bot/config.py` — Categories, accounts, keywords configuration
- `main.py` — Entry point (adds bot/ to sys.path, runs bot)

## Architecture decisions

- No login flow — bot is Telegram-native, user identity comes from Telegram
- All credentials in Replit secrets, never in code
- GOOGLE_SERVICE_ACCOUNT_JSON may have trailing commas (pasted from GCloud Console) — sheets.py cleans this automatically
- Bot runs via `python main.py` from workspace root

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- The GOOGLE_SERVICE_ACCOUNT_JSON secret may be pasted with trailing commas — the loader in `bot/sheets.py` handles this automatically
- If the bot shows "409 Conflict", there are two instances running simultaneously — stop one and wait ~30s before restarting
- Job queue (weekly report scheduler) requires `pip install "python-telegram-bot[job-queue]"` — currently disabled gracefully
- `fly.toml` has an old `TELEGRAM_TOKEN`/`GEMINI_API_KEY` hardcoded in plaintext (leftover from a Fly.io deployment attempt). It's a different token than the one now in Replit Secrets, so it isn't the current bot, but it's still a leaked credential sitting in the repo — worth rotating/removing if that Fly deployment isn't in active use.

## Setup status (2026-07-11)

- Re-imported from GitHub; Python deps (`python-telegram-bot`, `google-genai`, `gspread`, `google-auth`, `flask`, `flask-cors`, `gunicorn`) installed via the package manager.
- Secrets configured: `TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON` (user-provided), `GOOGLE_SHEET_ID` (was already set).
- `Telegram Finance Bot` workflow (`cd bot && python bot.py`) runs and polls Telegram successfully.
- The `.replit` deployment block still points at a `dashboard/` folder and `dashboard_api:app` that don't exist in this repo — leftover from a prior project state. Not touched since deployment wasn't requested; flag before publishing.
