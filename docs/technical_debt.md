# Oliv — Technical Debt & Security Audit
**Version:** 1.0  
**Author:** CTO, Oliv Project  
**Date:** July 2026

---

## Security Audit

### SEC-01 — Exposed Secrets in fly.toml
**Risk: 🔴 HIGH**  
**File:** `fly.toml`

```toml
[env]
  TELEGRAM_TOKEN = "8858919060:AAG36quotEXjaiI4VSpZE_iO0Bi4k7e-JPE"
  GEMINI_API_KEY = "AQ.Ab8RN6IhdC8_PGlpPrUFTJFmr87b_zD1BK0m8LUjF_ag59qYxg"
```

**Detail:** Dua secrets hardcoded langsung di file konfigurasi yang committed ke git repository. Meskipun token ini kemungkinan sudah expired, best practice adalah menganggap semua token yang pernah ada di git history sebagai compromised.

**Rekomendasi:** Revoke token tersebut (sudah dilakukan untuk Gemini key, cek Telegram). Remove dari file. Migrate ke Fly.io secrets (`flyctl secrets set`).

---

### SEC-02 — Zero Access Control
**Risk: 🔴 CRITICAL**  
**File:** `bot/bot.py` — semua handler

Tidak ada satu pun handler yang memverifikasi identitas pengirim:

```python
async def ringkasan(update, context):
    name = fname(update.effective_user)
    _register(update.effective_user, update.effective_chat.id)
    # ← tidak ada check: apakah user ini authorized?
    data = get_summary()  # ← langsung akses data keuangan
```

Ini berlaku untuk **semua 22 command** dan kedua message handlers.

**Rekomendasi:** Implementasikan allowlist berbasis `ALLOWED_TELEGRAM_IDS` environment variable. Decorator `@require_auth` di setiap handler.

---

### SEC-03 — Service Account Scope Terlalu Luas
**Risk: 🟡 MEDIUM**  
**File:** `bot/sheets.py` baris 37-42, `bot/sheets_manager.py` baris 28-33

```python
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",  # ← terlalu luas
]
```

Scope `drive` memberikan akses ke **seluruh Google Drive**, bukan hanya spreadsheet yang spesifik. Jika service account credentials bocor, attacker bisa membaca semua file di Drive.

**Rekomendasi:** Gunakan hanya `spreadsheets` scope. Share spreadsheet spesifik ke service account email, bukan berikan akses Drive penuh.

---

### SEC-04 — Spreadsheet IDs Hardcoded
**Risk: 🟢 LOW**  
**File:** `bot/sheets_manager.py` baris 86-143

6 dari 7 spreadsheet ID di-hardcode langsung di source code:

```python
"investasi": {
    "id": "1XjhlnGvlgsaxl3ZB9iaxUCfVvKdhATXw3yWk-fJeq2U",
```

Spreadsheet ID bukan secret (tidak memberikan akses tanpa credentials), tapi secara prinsip konfigurasi tidak boleh di dalam kode.

**Rekomendasi:** Pindahkan ke environment variables atau file konfigurasi terpisah yang di-gitignore.

---

### SEC-05 — User Registry Tidak Terenkripsi
**Risk: 🟢 LOW**  
**File:** `bot/user_registry.json`

File ini menyimpan mapping chat_id → nama user di disk tanpa enkripsi. Di Replit, file ini accessible ke siapa pun yang memiliki akses ke repl.

**Rekomendasi:** Data ini minimal, tapi untuk privacy compliance sebaiknya disimpan sebagai environment variable atau di-encrypt at rest.

---

## Code Quality Issues

### CQ-01 — Duplicated Authentication Code
**Severity: 🟡 MEDIUM**  
**Files:** `bot/sheets.py` (baris 15-45) dan `bot/sheets_manager.py` (baris 10-36)

Kode identik yang parse `GOOGLE_SERVICE_ACCOUNT_JSON`, membersihkan JSON malformed, dan membuat credentials. Jika ada format baru yang perlu di-handle, harus diperbaiki di **dua tempat**.

Contoh perbedaan yang sudah muncul:
- `sheets.py` menggunakan `flags=re.DOTALL` untuk private key regex
- `sheets_manager.py` **tidak** menggunakan flag ini, berpotensi gagal untuk multiline private keys

**Rekomendasi:** Extract ke `auth.py` atau `utils.py` dengan fungsi `get_gspread_client()` yang dipanggil oleh keduanya.

---

### CQ-02 — Module-Level Side Effects
**Severity: 🔴 HIGH**  
**Files:** `bot/sheets.py`, `bot/sheets_manager.py`, `bot/bot.py`

Code yang melakukan I/O dieksekusi saat `import`:

```python
# sheets.py — dieksekusi saat import sheets
creds = Credentials.from_service_account_info(KUNCI_GOOGLE, scopes=SCOPE)
gc = gspread.authorize(creds)
sheet_utama = gc.open_by_key(_sheet_id)  # ← network call!
sheet_transaksi = sheet_utama.worksheet("Transaksi")  # ← network call!

# bot.py — dieksekusi saat import bot
ai = GeminiAI()  # ← instantiates Gemini client
_registry = _load_reg()  # ← file I/O
```

**Dampak:** Tidak bisa import modul ini untuk testing tanpa environment lengkap. Crash saat startup jika service eksternal tidak tersedia.

---

### CQ-03 — Magic Numbers
**Severity: 🟢 LOW**  
**File:** Various

```python
# bot/bot.py
if ratio >= 1.0:   # ← angka magic, tidak ada nama
if ratio >= 0.85:  # ← apa artinya 0.85? "BUDGET_WARNING_THRESHOLD"
get_recent(10)     # ← kenapa 10? tidak ada konstanta

# bot/sheets.py
for b in semua[4:]:  # ← kenapa 4? "TRANSAKSI_HEADER_ROWS = 4"
col_index = bulan_ini + 1  # ← kenapa +1? perlu komentar
```

---

### CQ-04 — bot.py Terlalu Besar (1203 Lines)
**Severity: 🟡 MEDIUM**  
**File:** `bot/bot.py`

File ini mencampur terlalu banyak tanggung jawab:
- Command handlers (seharusnya di `handlers/`)
- Business logic (`_budget_alert`, transfer parsing, account detection)
- Utility functions (`rp()`, `fname()`, `emoji_kategori()`)
- Persona logic (`komentar_personal()`)
- Scheduling (`_send_weekly_report`)
- App lifecycle (`main()`)

**Dampak:** Sulit ditambah fitur baru tanpa risiko breaking yang lain. Tidak bisa unit test secara isolated.

---

### CQ-05 — Kategori Tidak Konsisten antara Prompts
**Severity: 🟡 MEDIUM**  
**File:** `bot/gemini_ai.py` baris 183-211

Prompt `parse_receipt_photo` menyebutkan kategori yang tidak ada di `config.py`:
- "Perawatan Diri" (tidak ada)
- "Gadget & Elektronik" (tidak ada)

Jika Gemini mengembalikan kategori-kategori ini, data tersimpan dengan kategori invalid — tidak ter-handle di budget, tidak muncul di /ringkasan dengan benar.

---

### CQ-06 — Unused Dependencies
**Severity: 🟢 LOW**  
**File:** `requirements.txt`

```
flask       # tidak ada Flask app di bot
flask-cors  # tidak ada Flask app di bot
gunicorn    # tidak ada WSGI server di bot
tlgbotfwk   # tidak jelas digunakan di mana
```

---

### CQ-07 — Async Antipattern: Synchronous sleep() di Async Context
**Severity: 🟡 MEDIUM**  
**File:** `bot/gemini_ai.py` baris 63, 98

```python
time.sleep(delay + 1)  # ← blocking sleep di coroutine context
```

`time.sleep()` adalah blocking call. Dalam async context (Telegram bot menggunakan asyncio), ini memblokir **seluruh event loop**, bukan hanya coroutine yang sedang berjalan. Selama sleep, tidak ada update Telegram yang diproses.

**Rekomendasi:** Ganti dengan `asyncio.sleep()` — tapi ini memerlukan perubahan signature method menjadi `async`.

---

### CQ-08 — File JSON Registry Tidak Thread-Safe
**Severity: 🟢 LOW**  
**File:** `bot/bot.py` baris 43-69

```python
def _save_reg(reg):
    with open(REGISTRY_FILE, "w") as f:
        json.dump(reg, f)
```

Jika dua pesan datang bersamaan dan keduanya trigger `_register()`, ada race condition. Pada praktiknya jarang terjadi untuk single user, tapi ini tetap code smell.

---

## AI Quality Issues

### AI-01 — Tidak Ada Confidence Score
**Severity: 🟡 MEDIUM**

Tidak ada mekanisme untuk mengetahui seberapa yakin AI tentang parsingnya. "beli sesuatu 50rb" mungkin di-parse sebagai "Lain-lain" — tapi user tidak tahu apakah Oliv yakin atau tidak.

**Rekomendasi:** Tambahkan field `confidence` ke JSON response. Jika confidence < 70%, tunjukkan pertanyaan klarifikasi.

---

### AI-02 — Prompt Tidak Menyertakan Konteks Historis
**Severity: 🟡 MEDIUM**

Setiap parsing transaksi adalah stateless. Oliv tidak tahu:
- "gopay" kemarin selalu "GoPay" untuk user ini
- User ini biasanya belanja di "Indomaret" kategori "Makan & Minum", bukan "Belanja"
- Merchant favorite user

**Dampak:** Akurasi tidak meningkat seiring waktu. Oliv tidak "belajar" dari user.

---

### AI-03 — Hallucination Risk pada /tanya
**Severity: 🟡 MEDIUM**

`ask()` memberikan seluruh data transaksi ke Gemini sebagai string plain text:

```python
rows = "\n".join(
    f"{t.get('tgl','')} | {t.get('kategori','')} | Rp{float(t.get('payment',0)):,.0f} | {t.get('memo','')}"
    for t in transactions
)
```

Jika transaksi sangat banyak (> context window), data akan terpotong dan Gemini bisa menghasilkan jawaban yang salah tanpa indikasi error. Tidak ada validasi apakah jawaban Gemini konsisten dengan data.

---

### AI-04 — Tidak Ada Raw Input Logging
**Severity: 🟡 MEDIUM**

Input user dan output Gemini tidak disimpan. Tidak ada cara untuk:
- Audit mengapa transaksi ter-parse dengan cara tertentu
- Improve prompts berdasarkan kasus yang salah
- Debug masalah di production

---

## Google Sheets Architecture Issues

### GS-01 — No Transaction ID
**Severity: 🔴 HIGH**

Tidak ada primary key di setiap baris transaksi. Tidak bisa:
- Edit/delete spesifik dari bot
- Detect duplicates
- Link transaksi ke confirmation message

---

### GS-02 — Full-Table Scan untuk Setiap Query
**Severity: 🟡 MEDIUM**

`get_semua_transaksi()` selalu membaca **seluruh sheet**. Tidak ada indexing, tidak ada pagination, tidak ada caching. Semakin lama dipakai, semakin lambat.

Estimasi performa:
- 100 transaksi: ~0.5s
- 1000 transaksi: ~2-3s  
- 5000 transaksi: ~10-15s (sudah tidak acceptable)

---

### GS-03 — Date Format Campur
**Severity: 🟡 MEDIUM**

Sheet menyimpan tanggal sebagai Excel serial number, tapi `excel_serial_to_iso()` harus handle multiple format karena ketidakkonsistenan historis:

```python
for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"):
```

Tidak ada schema enforcement — siapa pun yang edit sheet manual bisa input format yang tidak ter-handle.

---

### GS-04 — Budget Sheet Tidak Sinkron dengan Transaksi
**Severity: 🟡 MEDIUM**

Budget dibaca dari sheet "Budget" yang strukturnya berbeda dari "Anggaran" (yang dibuat oleh setup_sheets.py). Kolom index dihitung manual:

```python
col_index = bulan_ini + 1  # Jan(1) → col 2
```

Jika user memodifikasi struktur Budget sheet (menambah/menghapus kolom), logic ini rusak tanpa error yang jelas.
