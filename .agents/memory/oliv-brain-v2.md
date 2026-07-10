---
name: Oliv Brain V2 Architecture
description: Modular refactor of the Telegram finance bot — key decisions and constraints for future work.
---

## Architecture decisions

**All sheets I/O must use `await self._io(fn, *args)` in Brain.**
gspread is synchronous HTTP; calling it directly in async methods blocks the event loop.
`Brain._io()` wraps any sync callable in `loop.run_in_executor(None, ...)`.
**Why:** Single async process — blocking the loop stops ALL message handling.
**How to apply:** Any new Brain method that calls sheets functions must use `await self._io(...)`.

**AI Engine never sleeps on 429 — skip to next model immediately.**
`_generate_text` and `_generate_vision` in `ai_engine.py` have a fallback model chain.
On quota error (429), skip directly to next model without `time.sleep`.
**Why:** These methods run inside `run_in_executor` thread pool; sleeping exhausts threads under concurrent load.

**Router is AI-free; QualityScore threshold = 0.65.**
`brain/router.py` classifies messages using keyword matching only (no Gemini).
`brain/decision.py` uses `MIN_CONFIDENCE_TO_SAVE = 0.65`; below this Brain asks clarification instead of saving.

**Memory stored in `bot/memory_store.json` (not a new Sheets tab).**
`engine/memory.py` reads/writes a local JSON file.
**Why:** No API dependency, survives Sheets downtime, can migrate to DB later.

**Lazy init everywhere — nothing connects at import time.**
- `storage/auth.py`: `get_gspread_client()` connects on first call
- `sheets.py`: `_sheet_transaksi = None`, init on first `_get_sheet_transaksi()` call
- `engine/ai_engine.py`: `_client = None`, init on first `_get_client()` call
**Why:** CQ-02 fix — module-level network calls crashed startup if Sheets/Gemini was unavailable.

**AI contract: AI receives pre-computed summaries, never raw transactions for calculation.**
`brain.py` calls `FinancialEngine.*` (pure Python, static methods) first, then passes formatted
text summaries to `AIEngine.generate_insight_async()` or `answer_question_async()`.
AI writes narrative only; never recalculates numbers.

**File layout:**
- Entry point: `bot/bot.py` (thin — wiring only)
- Orchestrator: `bot/brain/brain.py` (Brain singleton)
- Classification: `bot/brain/router.py` (AI-free)
- Quality check: `bot/brain/decision.py`
- Context: `bot/brain/context_builder.py`
- Math: `bot/engine/financial.py` (all static, pure Python)
- AI: `bot/engine/ai_engine.py` (wraps Gemini, async via executor)
- Memory: `bot/engine/memory.py`
- Auth: `bot/storage/auth.py` (shared singleton)
- Handlers: `bot/handlers/commands.py`, `bot/handlers/messages.py` (thin)
