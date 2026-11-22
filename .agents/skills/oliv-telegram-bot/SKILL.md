---
name: oliv-telegram-bot
description: Project-specific operating guide for maintaining, deploying, and extending the Oliv Telegram finance recorder.
---

# Oliv Telegram Bot — Project Skill

## Product scope (must preserve)
Oliv is a transaction recorder only. Supported user flows:
- Record expenses.
- Record income.
- Record transfers between accounts.
- Scan receipt photos.
- Transcribe Telegram voice notes, then process the transcript as a transaction.

Do not reintroduce financial reports, balances, analytics, budget alerts, forecasts, investment/loan/goals workflows, or financial Q&A unless the owner explicitly changes the scope.

Gemini remains required for natural-language transaction parsing, receipt photo understanding, and voice transcription. Do not replace these with brittle keyword-only amount/category parsing. Low-confidence or ambiguous transactions must ask for clarification rather than silently writing uncertain values.

## Repository and deployment
- GitHub repository: `Rizkiihdy/keuangan-4.1`
- Production/deployment branch: `render-free-deploy`
- Render service: `keuangan-4.1` (confirm current service name in Render before acting; render.yaml currently names it `oliv-keuangan-v41`)
- Runtime: Python; entry point `python main.py`
- Render mode: webhook (`BOT_MODE=webhook`)
- Deployment is connected to the `render-free-deploy` branch.

Always inspect the latest code on the deployment branch before editing. Never assume a previous chat's code snapshot is current. Fetch the latest file and blob SHA before updating. Make narrow, reviewable changes and validate syntax/flow before deployment. Never force-push or overwrite unrelated user changes.

## Data and secrets
Google Sheets is the durable source of truth for transactions. Do not delete, recreate, rename, or migrate the existing financial spreadsheets unless explicitly requested.
Render Free filesystem is ephemeral; do not rely on local JSON/files as the only durable transaction store.
Never ask the owner to paste secrets into chat and never commit secrets.
Required Render environment variables:
- `BOT_MODE=webhook`
- `TELEGRAM_TOKEN`
- `GEMINI_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_SHEET_ID`
- `WEBHOOK_PATH`
- `WEBHOOK_SECRET_TOKEN`
Optional:
- `ALLOWED_TELEGRAM_IDS` (currently intentionally unset; bot is public by owner choice)
- Render supplies `RENDER_EXTERNAL_URL` and `PORT`.

The Google service account must retain Editor access to the existing financial spreadsheets used by the bot.

## Architecture
- `main.py`: adds `bot/` to import path and starts bot.
- `bot/bot.py`: Telegram app wiring and webhook/polling startup.
- `bot/brain/brain.py`: central transaction orchestration and Gemini/Sheets coordination.
- `bot/brain/router.py`: AI-free message classification.
- `bot/brain/decision.py`: confidence/quality gate; preserve clarification behavior.
- `bot/engine/ai_engine.py`: Gemini text parsing, receipt vision, voice transcription.
- `bot/sheets.py`: main transaction spreadsheet read/write layer.
- `bot/storage/auth.py`: Google service account authentication.
- `bot/handlers/messages.py`: text, photo, and voice Telegram handlers.
- `bot/handlers/commands.py`: /start, /help, manual expense and income commands, plus legacy unused handlers.
- `render.yaml`: Render deployment configuration.

### Non-negotiable engineering rules
1. All synchronous Google Sheets/file I/O called from async Brain methods must go through `await self._io(fn, *args)`.
2. Gemini calls must use the existing async wrappers/executor pattern; do not block the Telegram event loop.
3. On Gemini 429, skip to the next configured model immediately; never sleep inside worker threads.
4. Keep lazy initialization: no Google/Gemini network calls at module import time.
5. Validate AI output and confidence before saving. If amount/type/category/account is uncertain, ask the user to clarify.
6. After successful writes, invalidate any transaction cache.
7. Keep receipt scan and voice transcription as first-class supported input methods.
8. Keep logs useful but never log tokens, API keys, service-account JSON, or full webhook URLs containing secrets.

## Current implementation notes (verify before changing)
- Voice handler exists in `bot/handlers/messages.py` and forwards transcription to `Brain.process_free_text`.
- Photo handler exists and calls `Brain.process_photo`; user has not yet confirmed a successful real receipt scan.
- `Brain.process_photo` currently writes parsed receipt data to Sheets after Vision parsing and decision evaluation. Review confidence enforcement before changing; never silently save a low-confidence receipt.
- `bot/bot.py` registers only /start, /help, /pengeluaran, /pemasukan, plus photo, voice, and ordinary text handlers.
- At the latest inspection, `post_init()` in `bot/handlers/commands.py` still advertised many legacy commands (reports, analysis, investments, debts, goals, assets). This is inconsistent with the recorder-only scope and should be corrected to advertise only /start, /help, /pengeluaran, /pemasukan.
- Existing /start text describes expense, income, transfer, and receipt scan; add voice guidance when updating it.
- `render.yaml` has an optional ALLOWED_TELEGRAM_IDS variable even though current public mode leaves it unset.
- Current model IDs in `bot/engine/ai_engine.py` are `gemini-3.5-flash-lite` and `gemini-3.8-flash`. Do not assume these are valid indefinitely; verify against current official Gemini model documentation if model errors occur. Do not change model IDs without evidence.

## Deployment checklist (Render)
1. Confirm correct repository and branch: `Rizkiihdy/keuangan-4.1` / `render-free-deploy`.
2. Confirm Render service is connected to that branch.
3. Confirm all required environment variables exist in Render (do not expose values in chat).
4. Confirm Google service account access to the existing Sheets.
5. Deploy latest commit and inspect deploy/runtime logs for startup errors.
6. Confirm Telegram webhook is configured and bot responds.
7. Smoke-test a text expense, text income, transfer, and voice transaction.
8. Test receipt photo separately; inspect logs if it fails.
9. Verify each successful transaction is written correctly to the existing Google Sheet.
10. Do not claim deployment or a feature is successful until the user/runtime confirms it.

## Moving to another Render account
- Reuse the same GitHub repository and deployment branch.
- Create a new Render Web Service from the repo/branch and set the Python start command to `python main.py`.
- Re-enter required environment variables securely in the new Render dashboard. Do not copy secrets into GitHub or chat.
- Preserve the same Google Sheets and service-account permissions.
- Update webhook configuration through the app startup using the new Render external URL; ensure only the intended active service is receiving Telegram updates.
- Deploy and run the smoke tests above.
- Render Free has usage/sleep limitations and may change its terms. Check the current Render dashboard/docs rather than promising permanent free hosting.

## Safe change workflow
For every feature request:
1. Restate the desired behavior and identify impacted files.
2. Fetch current source from `render-free-deploy`.
3. Trace the full flow (handler → Brain → AI/Sheets) before editing.
4. Make the smallest coherent patch.
5. Check Python syntax and imports; inspect all changed lines.
6. Commit to `render-free-deploy` only after validation.
7. Explain exactly what changed and what still needs user testing.
8. Never deploy destructive spreadsheet changes or change product scope without explicit approval.
