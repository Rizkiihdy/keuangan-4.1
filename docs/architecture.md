# Oliv Architecture — Brain V2

## Prinsip Desain

| Prinsip | Detail |
|---|---|
| Single Responsibility | Setiap modul punya 1 tanggung jawab |
| AI sebagai alat, bukan inti | 90-95% request selesai tanpa memanggil Gemini |
| Lazy init | Koneksi Google Sheets & Gemini dibuat saat pertama kali dipakai |
| Type hints & docstrings | Semua public function terdokumentasi |
| Singleton Brain | Satu instance Brain dibagi ke semua handler |

---

## Arsitektur V2 (Brain V2)

```
Telegram Update
      │
      ▼
┌─────────────┐
│  bot.py     │  ← thin entry point, hanya wiring handler & polling
│ (entry)     │
└──────┬──────┘
       │  delegate
       ▼
┌──────────────────────────────────────────────────────────┐
│                      BRAIN (Singleton)                    │
│                   brain/brain.py                          │
│                                                          │
│  1. Context Builder  →  UserContext                       │
│  2. Router           →  MessageType + confidence          │
│  3. Dispatch:                                             │
│     ├─ Pure Python path (no AI) ──────────────────────── │
│     │   └─ Financial Engine                              │
│     └─ AI path (NLU / Vision / Reasoning) ───────────── │
│         ├─ AI Engine: parse/OCR/answer                   │
│         └─ Decision Engine: quality check                │
│  4. Return BrainResponse                                  │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────┐
│  Handlers (thin wrappers)      │
│  handlers/commands.py          │
│  handlers/messages.py          │
│  ─ Extract Update              │
│  ─ Call Brain method           │
│  ─ Send BrainResponse to TG    │
└────────────────────────────────┘
```

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  TELEGRAM LAYER                                             │
│  bot.py — hanya Application, CommandHandlers, wiring       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  HANDLER LAYER (thin)                                       │
│  handlers/commands.py — semua 22 command handler            │
│  handlers/messages.py — free text + photo handler           │
│  Decorator: @require_auth (setiap handler)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ delegate all logic
┌──────────────────────────▼──────────────────────────────────┐
│  BRAIN (Singleton Orchestrator)  brain/brain.py             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  process_free_text()                                   │ │
│  │  process_photo()                                       │ │
│  │  process_command_*() (one method per command)          │ │
│  └────────────────────────────────────────────────────────┘ │
└───────┬─────────────────────┬───────────────────────────────┘
        │                     │
┌───────▼──────────┐  ┌───────▼──────────────────────────────┐
│  brain/router.py │  │  brain/decision.py                   │
│  ─ Keyword-based │  │  ─ QualityScore (5 dimensions)       │
│  ─ AI-free       │  │  ─ Confidence threshold check        │
│  ─ 10 types      │  │  ─ Returns: proceed or clarify       │
│  ─ RouterResult  │  └──────────────────────────────────────┘
└──────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│  brain/context_builder.py                                │
│  ─ UserContext dataclass                                 │
│  ─ build_minimal() / build_with_memory() / build_full()  │
│  ─ Bounded context: last 3 months only                   │
└──────────────────────────────────────────────────────────┘

┌─────────────────────────────────┐   ┌──────────────────────────────┐
│  ENGINE LAYER                   │   │  STORAGE LAYER               │
│  engine/financial.py            │   │  storage/auth.py             │
│  ─ Pure Python, all static      │   │  ─ Shared Google auth        │
│  ─ No Gemini calls ever         │   │  ─ Singleton gspread.Client  │
│  ─ No direct Sheets access      │   │  ─ Lazy init                 │
│  ─ All math done here           │   └──────────────────────────────┘
│                                 │
│  engine/ai_engine.py            │   ┌──────────────────────────────┐
│  ─ Wraps Gemini API             │   │  DATA LAYER                  │
│  ─ Async wrappers (executor)    │   │  sheets.py                   │
│  ─ Vision prompt: fixed cats    │   │  ─ Lazy Sheets init          │
│  ─ confidence in every parse    │   │  ─ Uses storage.auth         │
│  ─ AI never calculates numbers  │   │  sheets_manager.py           │
│                                 │   │  ─ Multi-spreadsheet manager │
│  engine/memory.py               │   │  ─ Uses storage.auth         │
│  ─ Long-term user facts         │   └──────────────────────────────┘
│  ─ Stored: memory_store.json    │
│  ─ 8 categories                 │   ┌──────────────────────────────┐
│  ─ Blocks sensitive terms       │   │  UTILS                       │
└─────────────────────────────────┘   │  utils/formatting.py         │
                                      │  utils/security.py           │
                                      │  ─ @require_auth decorator   │
                                      └──────────────────────────────┘
```

---

## File Structure

```
bot/
├── bot.py                    ← thin entry point (V2 rewrite)
├── config.py                 ← all constants (categories, accounts)
├── sheets.py                 ← Transaksi sheet R/W (lazy init)
├── sheets_manager.py         ← multi-spreadsheet manager (lazy)
├── gemini_ai.py              ← legacy AI (kept for reference)
│
├── brain/
│   ├── __init__.py
│   ├── brain.py              ← Brain singleton, central orchestrator
│   ├── router.py             ← AI-free message classifier (10 types)
│   ├── decision.py           ← QualityScore + DecisionEngine
│   └── context_builder.py    ← UserContext assembler
│
├── engine/
│   ├── __init__.py
│   ├── financial.py          ← Pure Python math (no AI, no Sheets)
│   ├── ai_engine.py          ← AI wrapper (async, category-safe)
│   └── memory.py             ← Long-term user fact storage
│
├── handlers/
│   ├── __init__.py
│   ├── commands.py           ← All 22 command handlers (thin)
│   └── messages.py           ← Free text + photo handlers (thin)
│
├── storage/
│   ├── __init__.py
│   └── auth.py               ← Shared Google auth singleton
│
├── utils/
│   ├── __init__.py
│   ├── formatting.py         ← rp(), fname(), emoji_kategori(), etc.
│   └── security.py           ← @require_auth decorator
│
└── memory_store.json         ← Long-term memory (auto-created)
```

---

## Message Flow (Free Text)

```
User: "beli kopi 15rb di gopay"
         │
         ▼
  Brain.process_free_text()
         │
         ├─ Router.classify() → TRANSACTION (conf=0.85, signals=[amount_present, expense_keyword])
         │
         ├─ Memory.get_context_summary() → "" (new user)
         │
         ├─ AIEngine.parse_transaction_async()
         │    → ParsedTransaction(tipe="Pengeluaran", jumlah=15000,
         │                         kategori="Makan & Minum", memo="Kopi",
         │                         payee="di gopay", akun="GoPay",
         │                         confidence=0.92)
         │
         ├─ DecisionEngine.evaluate_transaction()
         │    → QualityScore(acc=1.0, comp=1.0, conf=0.92, safe=1.0, cons=1.0)
         │    → DecisionResult(should_proceed=True)
         │
         ├─ sheets.tulis_transaksi(akun="GoPay", payment=15000, ...)
         │
         └─ BrainResponse(text="✅ Tercatat, ...", used_ai=True)
                │
         handler.send_message()
```

---

## AI Contract

**AI BOLEH:**
- Parse natural language → structured data
- OCR receipt photos
- Reason about pre-calculated financial data
- Generate narrative (laporan, insight, saran)
- Suggest clarification questions

**AI TIDAK BOLEH:**
- Menghitung angka sendiri (harus dari FinancialEngine)
- Akses Google Sheets langsung
- Return angka tanpa data yang diberikan
- Run tanpa confidence scoring

---

## Quality Score (DecisionEngine)

Setiap response punya score internal sebelum dieksekusi:

| Dimensi | Bobot | Deskripsi |
|---|---|---|
| accuracy | 20% | Validasi data (amount > 0, kategori valid, akun valid) |
| completeness | 20% | Semua field required terisi |
| confidence | 30% | Nilai dari AI parse (0.0–1.0) |
| safety | 20% | Tidak ada type/kategori mismatch |
| consistency | 10% | Konsisten dengan known user context |

Threshold: overall < 0.65 → Brain bertanya klarifikasi, tidak menyimpan data.

---

## Known Issues Fixed in V2

| ID | Masalah | Fix |
|---|---|---|
| CQ-01 | Duplikasi Google auth | `storage/auth.py` — shared singleton |
| CQ-02 | Module-level network call | Lazy init di `sheets.py`, `sheets_manager.py`, `ai_engine.py` |
| CQ-03 | `time.sleep()` block async loop | `ai_engine.py` async wrappers via `run_in_executor` |
| CQ-04 | Zero access control | `@require_auth` decorator on every handler |
| CQ-05 | Vision prompt pakai kategori invalid | `ai_engine.py` — hanya pakai kategori dari `config.py` |
| CQ-06 | `/budget` 24× full table reads | `FinancialEngine.get_budget_status()` — 1 read, Python loop |
| CQ-07 | God Class `bot.py` | Dipecah ke 8 modul terpisah |

---

## Roadmap

| Version | Fitur |
|---|---|
| V2.1 (sekarang) | Brain V2 architecture |
| V2.2 | Confirmation flow sebelum save transaksi |
| V3.0 | User onboarding, multi-user hardening |
| V4.0 | Net Worth tracker, aset & investasi terintegrasi |
| V5.0 | Proactive alerts, predictive recommendations |
