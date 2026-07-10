# Oliv — Weaknesses Analysis
**Version:** 1.0  
**Author:** CTO, Oliv Project  
**Date:** July 2026

---

## W1 — Zero Access Control (CRITICAL)

**Severity: 🔴 CRITICAL**

**Masalah:** Tidak ada autentikasi atau otorisasi apapun. Siapa pun yang mengetahui username bot di Telegram dapat:

1. Membaca **seluruh riwayat keuangan** via `/ringkasan`, `/saldo`, `/tanya`, `/terakhir`
2. **Menulis transaksi palsu** ke Google Sheet
3. **Mengeksekusi semua 22 command** tanpa batasan
4. **Mendaftar ke weekly report** dan menerima laporan keuangan private

Tidak ada filter `user_id`, tidak ada allowlist, tidak ada rate limiting.

**Risiko aktual:** Jika seseorang menemukan bot ini, mereka bisa melihat total aset, saldo per akun, utang, piutang, goals, pola pengeluaran harian — semua data yang sangat sensitif.

**Mengapa belum diperbaiki:** Tidak ada mekanismenya di codebase saat ini.

---

## W2 — Startup Tightly Coupled ke External Services

**Severity: 🔴 HIGH**

**Masalah:** `sheets.py` dan `sheets_manager.py` melakukan koneksi ke Google Sheets **pada saat import**, bukan saat pertama kali digunakan. `GeminiAI()` juga diinisialisasi di module level `bot.py`.

```python
# sheets.py — ini dieksekusi saat 'import sheets'
sheet_utama = gc.open_by_key(_sheet_id)  # ← bisa crash di sini
sheet_transaksi = sheet_utama.worksheet("Transaksi")  # ← atau di sini
```

**Dampak:** Jika Google Sheets timeout, credentials expired, atau worksheet tidak ditemukan — bot crash sepenuhnya sebelum event loop Telegram bahkan dimulai. Tidak ada graceful degradation.

---

## W3 — Weekly Report Non-Functional

**Severity: 🟡 MEDIUM**

**Masalah:** Fitur laporan mingguan sudah dibangun lengkap (`_send_weekly_report`, `generate_weekly_report`) tapi **tidak bisa berjalan** karena `python-telegram-bot[job-queue]` (yang membutuhkan APScheduler) belum terinstall.

```
PTBUserWarning: No `JobQueue` set up. To use `JobQueue`, you must install PTB via 
`pip install "python-telegram-bot[job-queue]"`.
```

Log ini muncul setiap kali bot start. Fitur ini sudah 100% siap secara kode — hanya butuh satu package.

---

## W4 — Google Sheets Performance Bottleneck

**Severity: 🟡 MEDIUM**

**Masalah:** Setiap operasi baca data **mengambil seluruh sheet sekaligus**:

```python
def get_semua_transaksi():
    semua = sheet_transaksi.get_all_values()  # Ambil SEMUA baris
    ...
```

Operasi seperti `/budget` melakukan **dua** full-sheet reads:
1. `get_month_expense_for_category()` → `get_semua_transaksi()` (full read)
2. `get_anggaran_for_category()` → membaca Budget sheet

Dan `/budget` memanggil ini **12 kali** (sekali per kategori).

**Dampak saat ini:** Lambat (2-5 detik) bahkan dengan data sedikit. Akan semakin buruk seiring bertambahnya transaksi.

---

## W5 — Tidak Ada Transaction ID / Audit Trail

**Severity: 🟡 MEDIUM**

**Masalah:** Setiap transaksi yang dicatat tidak memiliki unique identifier. Kolom `Tag` di sheet selalu kosong.

**Dampak:**
- Tidak bisa melakukan edit/delete transaksi spesifik via bot
- Tidak bisa melacak apakah transaksi berhasil dicatat (duplicate possible jika user kirim dua kali)
- Tidak ada audit log — siapa yang mencatat apa dan kapan
- Tidak bisa menghubungkan konfirmasi bot dengan baris di sheet
- Kolom `Num` menyimpan waktu sebagai Excel fraction, bukan ID yang dapat di-query

---

## W6 — No Confirmation/Edit Flow

**Severity: 🟡 MEDIUM**

**Masalah:** Setelah transaksi dicatat, tidak ada cara untuk:
- Mengkonfirmasi apakah parsing AI benar sebelum disimpan
- Mengedit transaksi yang salah kategori
- Menghapus transaksi yang tidak sengaja dicatat dua kali

Jika Gemini salah parse "beli BBM 50rb" sebagai "Makan & Minum" bukan "Transportasi", user harus buka spreadsheet manual untuk koreksi.

---

## W7 — Duplicate Auth Code

**Severity: 🟠 MEDIUM-LOW**

**Masalah:** Kode autentikasi Google Sheets (parse service account JSON, fix trailing commas, create credentials, authorize gspread) **diduplikasi identik** di dua file:

- `bot/sheets.py` baris 15-45
- `bot/sheets_manager.py` baris 10-36

Jika ada bug di satu tempat (misalnya: format JSON baru yang perlu di-handle), harus diperbaiki di dua tempat. Ini sudah terjadi: `sheets.py` menggunakan `re.DOTALL` untuk multiline private key, tapi `sheets_manager.py` tidak menggunakan flag yang sama.

---

## W8 — Kategori Tidak Konsisten antara Text dan Vision Prompts

**Severity: 🟠 MEDIUM-LOW**

**Masalah:** Prompt untuk `parse_receipt_photo` mengandung kategori yang **tidak ada** di `ALL_CATEGORIES`:

```python
# Dalam prompt parse_receipt_photo:
"- Salon/spa/barbershop → Perawatan Diri"   # ← tidak ada di system
"- Toko HP/elektronik → Gadget & Elektronik" # ← tidak ada di system
```

Kategori valid adalah "Hiburan & Lifestyle" dan "Belanja Pakaian & Barang". Jika Gemini mengembalikan "Perawatan Diri", data tersimpan ke sheet dengan kategori yang tidak dikenali sistem budget.

---

## W9 — Global Mutable State

**Severity: 🟠 MEDIUM-LOW**

**Masalah:** `_registry` di `bot.py` adalah global dictionary yang dimutasi langsung:

```python
_registry = _load_reg()  # loaded at import time

def _register(user, chat_id):
    _registry[key] = {...}  # mutate global dict
    _save_reg(_registry)    # write to disk
```

Dalam konteks async Telegram bot, jika dua pesan datang bersamaan, ada race condition di mana satu write bisa menimpa yang lain. Juga: `_managers` di `sheets_manager.py` adalah global dict yang menyimpan koneksi aktif.

---

## W10 — Dependencies Tidak Digunakan

**Severity: 🟢 LOW**

`requirements.txt` menginstall packages yang tidak digunakan oleh bot:

- `flask` — tidak ada Flask server di bot
- `flask-cors` — tidak ada CORS config
- `gunicorn` — tidak ada WSGI server
- `tlgbotfwk` — tidak jelas digunakan di mana

Ini menambah waktu install, ukuran container, dan attack surface tanpa manfaat.

---

## W11 — `bot.py` Terlalu Besar

**Severity: 🟢 LOW**

1203 baris dalam satu file mencampur:
- Command handlers
- Business logic (budget alert, transfer parsing, account detection)
- Utility functions (rp, fname, emoji_kategori)
- Persona logic (komentar_personal)
- Scheduling

Ini membuat file sulit di-navigate dan di-test secara unit.

---

## W12 — Tidak Ada Logging ke Persistent Store

**Severity: 🟢 LOW**

Semua logging ke stdout saja (`logging.basicConfig`). Ketika bot restart, semua log hilang. Tidak ada cara untuk:
- Audit berapa banyak transaksi yang berhasil/gagal
- Melihat error yang terjadi ketika tidak ada yang monitoring
- Melacak usage patterns

---

## W13 — fly.toml Mengandung Secrets

**Severity: 🔴 HIGH** (historical, sudah tidak aktif tapi file masih ada)

File `fly.toml` yang committed ke repository mengandung:
```
TELEGRAM_TOKEN = "8858919060:AAG36quotEXjaiI4VSpZE_iO0Bi4k7e-JPE"
GEMINI_API_KEY = "AQ.Ab8RN6IhdC8_PGlpPrUFTJFmr87b_zD1BK0m8LUjF_ag59qYxg"
```

Meskipun ini token lama/invalid, token yang terekspos di git history adalah security risk. Token Telegram yang bocor memungkinkan seseorang mengambil alih bot.
