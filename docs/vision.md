# Oliv — Vision Document
**Version:** 1.0  
**Author:** CTO, Oliv Project  
**Date:** July 2026  
**Status:** Foundational — tidak berubah tanpa persetujuan eksplisit

---

## Satu Kalimat

> Oliv adalah **Personal Financial Operating System** — bukan chatbot, bukan pencatat transaksi — melainkan sistem yang membantu pemiliknya mengambil keputusan keuangan yang lebih baik setiap hari.

---

## Masalah yang Diselesaikan

Mayoritas orang Indonesia yang melek finansial memiliki spreadsheet keuangan yang tidak dipakai setelah bulan pertama. Alasannya satu: **friction terlalu tinggi**. Membuka aplikasi, login, memilih kategori, mengisi form — semua itu cukup untuk membuat seseorang menyerah.

Oliv menghilangkan friction itu sepenuhnya.

Kamu tidak perlu membuka aplikasi. Kamu tidak perlu mengingat kategori. Kamu cukup bercerita seperti berbicara kepada teman:

> *"beli bakso 5rb"*

Dan Oliv mencatat, mengkategorikan, menyimpan, menganalisis — dalam waktu 2 detik.

---

## Target Jangka Panjang

Oliv adalah **CFO pribadi** yang:

1. **Mengenal pemiliknya** — tahu bahwa "grab" selalu transportasi, tahu bahwa pengeluaran makan kamu naik di akhir bulan, tahu bahwa kamu lebih boros di hari Jumat.

2. **Proaktif, bukan reaktif** — tidak menunggu ditanya. Oliv memberi tahu kamu sebelum kamu tersadar ada masalah.

3. **Kontekstual** — paham kondisi spesifik kamu: gaji kamu, goals kamu, kebiasaan kamu, aset kamu. Bukan generic financial advice.

4. **Terintegrasi** — semua dimensi keuangan ada di satu tempat: harian, bulanan, tahunan, investasi, utang, tujuan, aset bersih.

---

## Filosofi Produk

### 1. Friction adalah musuh
Setiap langkah tambahan yang dibutuhkan user untuk mencatat adalah peluang mereka berhenti mencatat. Desain setiap fitur dengan menghitung jumlah tap/kata yang dibutuhkan.

### 2. Tambah fitur bukan tujuan
Setiap fitur harus menjawab satu pertanyaan: *"Apakah ini membuat Oliv lebih pintar atau lebih berguna untuk pemiliknya?"*  
Jika tidak — fitur itu tidak layak dibangun.

### 3. Data adalah aset, bukan log
Setiap transaksi yang dicatat bukan sekadar baris di spreadsheet. Setiap baris adalah data training untuk model pemahaman Oliv tentang perilaku finansial pemiliknya.

### 4. Karakter bukan fitur
Oliv bukan asisten generik. Oliv punya nama, punya gaya bicara, punya rasa sayang kepada pemiliknya. Ini bukan kosmetik — ini adalah elemen kunci yang membuat user mau kembali setiap hari.

### 5. Infrastruktur mengikuti kebutuhan
Saat ini Oliv berjalan di Google Sheets dan Telegram. Infrastruktur ini bisa berubah. Filosofi tidak boleh berubah.

---

## Apa yang BUKAN Oliv

- ❌ Bukan aplikasi budgeting generik seperti Money Manager atau Mint
- ❌ Bukan chatbot AI yang bisa ditanya apa saja
- ❌ Bukan platform multi-user yang mengutamakan pertumbuhan pengguna
- ❌ Bukan alat reporting yang hanya reaktif terhadap pertanyaan
- ❌ Bukan pengganti konsultan keuangan

---

## Ukuran Keberhasilan

Oliv berhasil jika:

1. Pemiliknya mencatat **lebih dari 80% transaksi** tanpa effort sadar
2. Pemiliknya **tidak perlu membuka spreadsheet** untuk tahu kondisi keuangannya
3. Oliv **memberikan insight yang pemiliknya tidak minta** tapi sangat relevan
4. Pemiliknya merasa Oliv **mengenal dirinya** lebih baik dari bulan ke bulan

---

## Evolusi Oliv

| Fase | Deskripsi | Kondisi Sekarang |
|------|-----------|-----------------|
| **V1 — Pencatat** | Catat transaksi via chat, simpan ke Sheets | ✅ Selesai |
| **V2 — Analis** | Insight proaktif, budgeting cerdas, peringatan real-time | 🔧 Next |
| **V3 — Advisor** | Prediksi, rekomendasi, goal tracking otomatis | 📋 Planned |
| **V4 — Operating System** | Multi-source data, open banking, net worth tracking | 🔮 Future |
| **V5 — CFO Pribadi** | Fully personalized, learning dari perilaku, proactive decisions | 🌟 Vision |
