# Oliv — Current System Inventory
**Version:** 1.0  
**Author:** CTO, Oliv Project  
**Date:** July 2026

> Dokumen ini adalah **snapshot** dari apa yang ada sekarang. Bukan tentang apa yang harusnya ada.

---

## File Inventory

| File | Lines | Peran |
|------|-------|-------|
| `main.py` | 10 | Entry point. Menambahkan `bot/` ke sys.path, memanggil `bot.main()` |
| `bot/bot.py` | 1203 | Core orchestrator. Semua handler Telegram, routing, business logic |
| `bot/gemini_ai.py` | 288 | AI engine. Parse teks, scan struk, generate report, Q&A |
| `bot/sheets.py` | 312 | Data access layer untuk spreadsheet utama (keuangan v4) |
| `bot/sheets_manager.py` | 179 | Multi-spreadsheet manager untuk 7 spreadsheet eksternal |
| `bot/config.py` | 136 | Global constants: kategori, akun, emoji, komentar personal |
| `bot/setup_sheets.py` | 833 | Script sekali-jalan untuk membangun struktur spreadsheet |
| `requirements.txt` | 8 | Python dependencies |
| `fly.toml` | 25 | Legacy Fly.io deployment config (deprecated) |
| `bot/user_registry.json` | - | File JSON menyimpan chat_id → {first_name, full_name} |

---

## Command Inventory (22 Commands)

### Transaksi Dasar
| Command | Handler | Deskripsi |
|---------|---------|-----------|
| `/start` | `start()` | Registrasi user, tampilkan welcome message + semua perintah |
| `/help` | `help_cmd()` | Alias untuk /start |
| `/pengeluaran` | `pengeluaran()` | Catat pengeluaran manual: `/pengeluaran 45000 "Makan & Minum" Kopi` |
| `/pemasukan` | `pemasukan()` | Catat pemasukan manual: `/pemasukan 5000000 Gaji` |

### Pelaporan
| Command | Handler | Deskripsi |
|---------|---------|-----------|
| `/ringkasan` | `ringkasan()` | Ringkasan bulan ini: pemasukan, pengeluaran, saldo, per kategori |
| `/saldo` | `saldo_cmd()` | Saldo per akun (dihitung dari seluruh transaksi) |
| `/hariini` | `hariini_cmd()` | Semua pengeluaran hari ini |
| `/mingguini` | `mingguini_cmd()` | Pengeluaran 7 hari terakhir, per kategori + persentase |
| `/terbesar` | `terbesar_cmd()` | Top 10 pengeluaran terbesar bulan ini |
| `/terakhir` | `terakhir()` | 10 transaksi terakhir |
| `/budget` | `budget_cmd()` | Status budget bulan ini: Aman/Rawan/Over per kategori |
| `/analisa` | `analisa_cmd()` | AI-powered analisis pola pengeluaran bulan ini |
| `/tanya` | `tanya()` | Natural language Q&A: `/tanya berapa total makan bulan ini?` |

### Investasi
| Command | Handler | Deskripsi |
|---------|---------|-----------|
| `/invest` | `invest_cmd()` | Catat beli saham/reksadana ke Account1/2/3 |
| `/dividen` | `dividen_cmd()` | Catat dividen diterima |
| `/jual` | `jual_cmd()` | Catat realisasi jual + profit/loss |

### Utang & Piutang
| Command | Handler | Deskripsi |
|---------|---------|-----------|
| `/utang` | `utang_cmd()` | Catat utang (kamu yang berhutang) |
| `/piutang` | `piutang_cmd()` | Catat piutang (kamu yang memberi hutang) |

### Goals & Aset
| Command | Handler | Deskripsi |
|---------|---------|-----------|
| `/goal` | `goal_cmd()` | Buat target tabungan baru |
| `/tabung` | `tabung_cmd()` | Tambahkan uang ke goal tertentu |
| `/aset` | `aset_cmd()` | Catat pembelian aset (HP, motor, dll) |

### Admin
| Command | Handler | Deskripsi |
|---------|---------|-----------|
| `/sheets` | `list_sheets_cmd()` | Tampilkan semua spreadsheet yang terhubung |

---

## Message Handlers (Non-Command)

| Handler | Trigger | Aksi |
|---------|---------|------|
| `handle_free_text()` | Semua teks yang bukan command | Kirim ke Gemini untuk di-parse sebagai transaksi |
| `handle_photo()` | Foto yang dikirim | Download foto, kirim ke Gemini Vision untuk scan struk |

### Filter Bukan Transaksi (`BUKAN_TRANSAKSI` list)
Pesan seperti "oke", "haha", "makasih", "sip" — diabaikan tanpa proses AI.

---

## AI Functions (4 Functions)

| Fungsi | Input | Output | Model |
|--------|-------|--------|-------|
| `parse_transaction(text)` | String teks bebas | Dict: tipe, jumlah, kategori, memo, payee, akun | Text models |
| `parse_receipt_photo(bytes, mime)` | Image bytes + mime type | Dict + items field | Vision models |
| `generate_weekly_report(txns, name)` | List transaksi + nama | Markdown report string | Text models |
| `ask(question, txns)` | Pertanyaan + data transaksi | Natural language answer | Text models |

---

## Spreadsheets Connected

| Key | Spreadsheet Name | Sheets | Terhubung via |
|-----|-----------------|--------|---------------|
| `keuangan` | keuangan v4 | Transaksi, Budget, Goals, Progress, Aset | `GOOGLE_SHEET_ID` env var |
| `investasi` | Pelacak Investasi | Account1, Account2, Account3, Summary | Hardcoded ID |
| `utang` | Kalkulator Utang | Sheet1 | Hardcoded ID |
| `home_affordability` | Home Affordability | Sheet1 | Hardcoded ID |
| `pensiun` | Kalkulator Pensiun | Sheet1 | Hardcoded ID |
| `simulasi_kredit` | Simulasi Kredit Motor/Mobil | Sheet1 | Hardcoded ID |
| `tabungan_pensiun` | Kalkulator Tabungan Dana Pensiun | Sheet1 | Hardcoded ID |

---

## Akun yang Didukung (10 Akun)

| Akun | Keywords (auto-detect) |
|------|----------------------|
| Cash | (default/fallback) |
| BCA | bca |
| GoPay | gopay, go-pay, qr, qris |
| ShopeePay | shopeepay, shopee pay, shopee |
| DANA | dana |
| RDN | rdn |
| Jago | jago |
| Tabungan 27Th | tabungan, tabung, 27th |
| Dana Darurat | dana darurat, darurat |
| Investasi | investasi, invest |

---

## Kategori Pengeluaran (12)

1. Makan & Minum
2. Transportasi
3. Pulsa / Internet
4. Cicilan & Tagihan
5. Hiburan & Lifestyle
6. Tempat Tinggal (Housing)
7. Kesehatan
8. Belanja Pakaian & Barang
9. Pendidikan
10. Hadiah & Sosial
11. Bisnis
12. Lain-lain

## Kategori Pemasukan (5)

1. Gaji
2. Bonus
3. Dividen
4. Usaha
5. Lain-lain

## Non-Budget Categories (5)

`[Transfer]`, `[Refund]`, `[piutang]`, `[Biaya Tak Terduga]`, `[Dll]`

---

## Scheduled Jobs

| Job | Schedule | Status |
|-----|----------|--------|
| Weekly Report | Setiap Minggu 12:00 UTC (19:00 WIB) | ⚠️ **DISABLED** — `python-telegram-bot[job-queue]` belum diinstall |

---

## User Registry

File `bot/user_registry.json` menyimpan:
```json
{
  "chat_id_string": {
    "first_name": "Zee",
    "full_name": "Zee Full Name"
  }
}
```
- Digunakan untuk mengirim weekly report ke semua user terdaftar
- Tidak ada mekanisme unreg/delete
- Tidak ada pembatasan akses — siapa pun yang menyapa bot akan terdaftar

---

## Budget Alert Logic

| Kondisi | Pesan | Emoji |
|---------|-------|-------|
| `spent/budget >= 1.0` | Budget OVER | 🔴 |
| `spent/budget >= 0.85` | Budget Rawan | 🟡 |
| `spent/budget < 0.85` | Tidak ada alert | - |
| `budget == 0` | Tidak ada alert (budget belum diset) | - |

---

## Komentar Personal (Persona Triggers)

Oliv memiliki komentar khusus untuk kata-kata tertentu di memo transaksi:

| Keyword | Contoh Komentar |
|---------|-----------------|
| rokok | "rokok lagi nih Zee 👀" |
| kopi | "caffeine mode on 😂" |
| grab/gojek | "ojol maning 🛵" |
| gaji | "yeay gajian! 🎉" |
| investasi | "investor mode on! 📈💪" |
| ...15 lainnya | - |

---

## Dependency Stack

```
python-telegram-bot==22.8   # Telegram Bot framework
google-genai==2.10.0        # Gemini AI client
gspread==6.2.1              # Google Sheets client
google-auth==2.55.2         # Google OAuth
flask==3.1.3                # (installed, tidak digunakan di bot)
flask-cors==6.0.5           # (installed, tidak digunakan di bot)
gunicorn==26.0.0            # (installed, tidak digunakan di bot)
tlgbotfwk==0.4.61           # (installed, tidak jelas digunakan di mana)
```
