# Oliv — Product Roadmap
**Version:** 1.0  
**Author:** CTO, Oliv Project  
**Date:** July 2026  
**Framework:** Impact-first. Bukan kesulitan coding.

---

## Prinsip Prioritisasi

Setiap fitur dinilai dari satu pertanyaan:

> **"Apakah ini membuat Oliv lebih berguna atau lebih pintar untuk pemiliknya hari ini?"**

Urutan dalam setiap versi menggambarkan prioritas, bukan timeline linear.

---

## Version 2 — "Oliv yang Bisa Dipercaya"
**Tema:** Sebelum menambah fitur baru, pastikan yang sudah ada berjalan sempurna dan aman.

### V2.1 — Access Control (Prioritas #1)
**Impact: 🔴 Critical**

Tanpa ini, Oliv adalah security liability. Ini harus selesai sebelum semua yang lain.

- Tambahkan `ALLOWED_TELEGRAM_IDS` di environment secrets
- Decorator `@require_auth` yang diceking di setiap handler
- Pesan yang tepat untuk unauthorized user (tidak bocor info)
- Support multi-user yang authorized (misalnya: kamu + pasangan)

**Done looks like:** Orang acak yang menemukan bot mendapat pesan "Maaf, bot ini private" — bukan data keuangan.

---

### V2.2 — Confirmation Flow Sebelum Simpan
**Impact: 🔴 High**

Saat ini Oliv langsung simpan tanpa konfirmasi. Jika AI salah parse, user harus buka Sheets manual.

- Setelah parsing, tampilkan: "Ini bener ga? *Bakso — Makan & Minum — Rp 5.000* [✅ Ya] [✏️ Edit]"
- Inline keyboard buttons: Konfirmasi, Edit Kategori, Edit Jumlah, Batal
- Timeout 60 detik — jika tidak direspons, simpan otomatis (backward compatible)

**Done looks like:** User bisa koreksi kategori yang salah tanpa membuka spreadsheet.

---

### V2.3 — Weekly Report Aktif
**Impact: 🟡 High**

Fitur ini sudah 95% selesai. Tinggal install satu package.

- Install `python-telegram-bot[job-queue]`
- Aktifkan scheduler Sunday 19:00 WIB
- Improve prompt weekly report: tambahkan perbandingan minggu lalu, highlight anomali

**Done looks like:** Setiap Minggu sore, Oliv kirim laporan tanpa diminta.

---

### V2.4 — Transaction ID & Edit/Delete
**Impact: 🟡 High**

- Tambahkan kolom `ID` ke setiap transaksi (format: `TXN-YYYYMMDD-XXXX`)
- Command `/edit <id> kategori=Transportasi` untuk koreksi
- Command `/hapus <id>` dengan konfirmasi
- Simpan ID ke confirmation message sehingga mudah di-referensikan

**Done looks like:** User bisa mengetik `/hapus TXN-20260709-0042` untuk menghapus transaksi yang salah.

---

### V2.5 — Fix Technical Debt Kritis
**Impact: 🟡 Medium**

- Extract auth code ke `utils/auth.py` (eliminasi duplikasi)
- Lazy-init Sheets dan Gemini (bot tetap start meskipun Sheets down)
- Fix kategori tidak konsisten di vision prompt
- Ganti `time.sleep()` dengan `asyncio.sleep()`
- Remove unused dependencies

---

## Version 3 — "Oliv yang Proaktif"
**Tema:** Dari reaktif menjadi proaktif. Oliv memberitahu kamu sebelum kamu bertanya.

### V3.1 — Smart Insight Bulanan
**Impact: 🔴 High**

Setiap awal bulan, Oliv kirim insight otomatis:
- "Zee, bulan lalu kamu habis Rp 2.3 juta buat makan — naik 35% dari bulan sebelumnya 🍽️"
- "Pengeluaran transportasimu turun 20% — mungkin karena lebih sering WFH?"
- "Kamu paling boros di hari Jumat. Rata-rata pengeluaran Jumat 2.4x hari biasa"

Ini tidak perlu fitur baru — data sudah ada. Yang perlu dibangun: prompt engineering yang lebih dalam dan scheduler trigger.

---

### V3.2 — Prediksi Akhir Bulan
**Impact: 🔴 High**

Pertanyaan yang selalu ingin dijawab user: "Cukup gak uangku sampai akhir bulan?"

- Hitung rata-rata pengeluaran harian dari data historis
- Proyeksikan sisa bulan
- Bandingkan dengan saldo saat ini dan income yang diharapkan
- "Dengan pola pengeluaran ini, kamu butuh Rp 1.2 juta lagi sampai akhir Juli. Saldo kamu Rp 850 ribu. 🟡"

---

### V3.3 — Goal Tracking Otomatis
**Impact: 🟡 High**

Goal sudah bisa dibuat via `/goal`, tapi:
- Tidak ada tracking otomatis progress
- Tidak ada notifikasi mendekati deadline
- Tidak ada saran berapa yang harus ditabung per bulan

Implementasi:
- Oliv menghitung progress setiap minggu dan mengirim update
- "Motor Baru" — progress 67% — "Kalau tabung 500rb/bulan, kamu bisa capai target bulan Oktober 🎯"
- Alert jika deadline < 30 hari dan progress < 50%

---

### V3.4 — Natural Language Memory
**Impact: 🟡 High**

Oliv bisa "mengingat" context dari percakapan sebelumnya dalam satu sesi:
- "Yang tadi salah kategori, ganti jadi transportasi" → Oliv tau "yang tadi" adalah transaksi terakhir
- "Hapus yang terakhir" → hapus transaksi terbaru

Implementasi: Simpan transaksi terakhir di context/session state Telegram.

---

### V3.5 — Budget Recommendation
**Impact: 🟡 Medium**

Berdasarkan pola historis, Oliv merekomendasikan budget bulanan:
- "Berdasarkan 3 bulan terakhir, pengeluaran makan kamu rata-rata Rp 1.8 juta. Mau aku set budget ini?"
- Validasi apakah budget yang diset masuk akal vs pola aktual

---

### V3.6 — Recurring Transaction Detection
**Impact: 🟡 Medium**

Deteksi transaksi yang berulang: Netflix, Spotify, listrik, cicilan.
- Otomatis kategorikan recurring transactions
- Alert jika ada recurring yang tidak muncul di bulan ini ("Hmm, belum ada transaksi listrik bulan ini. Udah dibayar?")

---

## Version 4 — "Oliv Financial Operating System"
**Tema:** Semua dimensi keuangan dalam satu brain. Net worth, not just cashflow.

### V4.1 — Net Worth Dashboard
**Impact: 🔴 High**

Command `/networth` yang menggabungkan:
- Saldo semua akun (dari Transaksi)
- Nilai aset saat ini (dari Aset sheet)
- Nilai investasi (dari Investasi sheets)
- Utang yang belum lunas (dari Utang sheet)
- = **Total Kekayaan Bersih**

Ini adalah angka paling penting dalam keuangan personal — dan Oliv sudah punya semua datanya.

---

### V4.2 — Web Dashboard
**Impact: 🔴 High**

Bot Telegram powerful, tapi ada visualisasi yang tidak bisa dilakukan di teks:
- Pie chart pengeluaran per kategori
- Bar chart tren bulanan
- Line chart net worth seiring waktu
- Goal progress bars

Fondasi sudah ada: `artifacts/api-server` dan `artifacts/mockup-sandbox` sudah terkonfigurasi di Replit.

---

### V4.3 — Merchant Intelligence
**Impact: 🟡 High**

Oliv belajar dari pola transaksi user:
- "Kopi Kenangan" → selalu "Makan & Minum", selalu "GoPay" → tidak perlu AI lagi
- "SPBU" → selalu "Transportasi"
- Toko baru yang belum dikenal → coba match dengan merchant database

Implementasi: Tabel merchant_memory di sheet atau local storage.

---

### V4.4 — Multi-Currency Support
**Impact: 🟡 Medium**

Untuk user yang punya investasi USD (saham US, crypto):
- Catat transaksi dalam USD: "beli AAPL 0.5 lembar $195"
- Auto-convert dengan kurs hari ini
- Tampilkan dalam IDR di ringkasan

---

### V4.5 — Statement Import
**Impact: 🟡 Medium**

Import transaksi dari:
- CSV export BCA/Mandiri/BRI
- PDF rekening
- Screenshot rekening (OCR)

Ini mengurangi gap jika user lupa mencatat beberapa hari.

---

### V4.6 — Tax Helper
**Impact: 🟡 Medium**

Khusus untuk user dengan penghasilan dari berbagai sumber (freelance, dividen, dll):
- Rekap penghasilan tahunan per kategori
- Estimasi pajak (PPh 21, PPh final)
- Export format yang bisa digunakan untuk SPT

---

## Version 5 — "Oliv sebagai CFO Pribadi"
**Tema:** Dari alat menjadi advisor. Dari reactive menjadi prescriptive.

### V5.1 — Personalized Financial Model
**Impact: 🔴 Critical**

Oliv membangun model keuangan personal yang unik untuk setiap user:
- Memahami income pattern (gajian tanggal berapa, besarannya)
- Memahami fixed costs (sewa, cicilan, langganan)
- Memahami variable costs dan elasticitasnya
- Memahami savings rate historis

Output: Oliv bisa menjawab "apakah aku bisa beli laptop Rp 15 juta bulan ini?" dengan analisis yang benar-benar kontekstual.

---

### V5.2 — Proactive Decision Support
**Impact: 🔴 Critical**

Oliv tidak hanya menjawab pertanyaan — tapi proaktif memberikan rekomendasi:
- "Zee, bulan ini kamu bisa tabung Rp 500rb lebih dari biasanya. Mau dialokasikan ke Dana Darurat atau Motor Baru?"
- "Pengeluaran kamu bulan ini 15% di atas rata-rata. Paling banyak di Hiburan. Mau kurangi budget hiburan bulan depan?"

---

### V5.3 — Life Event Planning
**Impact: 🟡 High**

Membantu perencanaan untuk life events:
- "Aku mau nikah 2 tahun lagi dengan budget Rp 150 juta" → Oliv buat plan tabungan
- "Aku mau beli rumah 5 tahun lagi" → analisis kemampuan, DP yang dibutuhkan, cicilan yang sustainable
- "Aku mau pensiun usia 55" → proyeksi berdasarkan aset dan investasi saat ini

---

### V5.4 — Investment Intelligence
**Impact: 🟡 High**

Dari sekedar mencatat investasi, menjadi menganalisisnya:
- Portfolio allocation recommendation berdasarkan risk profile
- Alert jika satu saham terlalu dominan (concentration risk)
- Tracking dividen vs target
- Perbandingan actual return vs benchmark (IHSG, SBN)

---

### V5.5 — Family Finance Mode
**Impact: 🟡 Medium**

Multi-user dengan shared budget:
- Pasangan bisa mencatat ke sheet yang sama
- Shared goals dengan contribution tracking per person
- Split bill calculator yang terintegrasi dengan piutang
- Privacy setting: ada transaksi yang hanya visible ke satu person

---

## Feature Graveyard — Fitur yang TIDAK Akan Dibangun

Ini adalah fitur yang mungkin terlihat menarik tapi **tidak sesuai dengan filosofi Oliv**:

| Fitur | Alasan Ditolak |
|-------|---------------|
| Integrasi bank otomatis (open banking) | Regulasi OJK kompleks, security risk tinggi, maintenance hell |
| Crypto portfolio tracker lengkap | Sudah ada banyak tools khusus; bukan core job Oliv |
| Marketplace / e-commerce integration | Keluar dari scope keuangan personal |
| Social features (compare dengan teman) | Privacy concern; bukan nilai Oliv |
| Gamification (badges, streak) | Bisa mengganggu fokus; Oliv bukan app permainan |
| Built-in investment execution | Regulasi, lisensi, dan liability terlalu besar |

---

## Ringkasan Timeline

```
V2 — Oliv yang Bisa Dipercaya
├── V2.1 Access Control          ← PALING URGENT
├── V2.2 Confirmation Flow
├── V2.3 Weekly Report Aktif
├── V2.4 Transaction ID & Edit
└── V2.5 Technical Debt Fix

V3 — Oliv yang Proaktif
├── V3.1 Smart Monthly Insight   ← Highest impact per effort
├── V3.2 Prediksi Akhir Bulan
├── V3.3 Goal Tracking Otomatis
├── V3.4 Natural Language Memory
├── V3.5 Budget Recommendation
└── V3.6 Recurring Detection

V4 — Financial Operating System
├── V4.1 Net Worth Dashboard     ← Data sudah ada, tinggal build
├── V4.2 Web Dashboard
├── V4.3 Merchant Intelligence
├── V4.4 Multi-Currency
├── V4.5 Statement Import
└── V4.6 Tax Helper

V5 — CFO Pribadi
├── V5.1 Personalized Financial Model
├── V5.2 Proactive Decision Support
├── V5.3 Life Event Planning
├── V5.4 Investment Intelligence
└── V5.5 Family Finance Mode
```
