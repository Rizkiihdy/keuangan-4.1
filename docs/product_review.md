# Oliv — Product Review
**Version:** 1.0  
**Perspektif:** Product Manager  
**Author:** CTO, Oliv Project  
**Date:** July 2026

---

## Apa Tujuan Oliv Sekarang?

Saat ini Oliv berfungsi sebagai **intelligent transaction recorder** — sebuah bot yang mendengarkan cerita keuangan user dan mencatatnya ke Google Sheets dengan kategorisasi otomatis.

Yang sudah berjalan dengan sangat baik:
- Input zero-friction via natural language
- Scan foto struk
- Budget tracking dasar
- AI Q&A tentang transaksi historis
- Coverage dimensi keuangan yang luas (22 commands)

Yang belum tercapai dari visi awal:
- Tidak ada proaktivitas — Oliv hanya merespons, tidak pernah berinisiatif
- Tidak ada personalisasi — Oliv tidak "mengenal" pemiliknya lebih baik dari waktu ke waktu
- Tidak ada keamanan — siapa pun bisa mengakses
- Tidak ada feedback loop — tidak ada cara user mengkoreksi AI tanpa buka Sheets

---

## Apa Kekurangan Terbesar?

**Kekurangan #1: Tidak ada konfirmasi parsing.**

Ini adalah friction point terbesar yang merusak kepercayaan. Jika Oliv salah parse "makan siang dengan client" sebagai "Makan & Minum" padahal seharusnya "Bisnis", user tidak tahu sampai mereka buka Sheets. Dan kebanyakan user tidak akan buka Sheets — itulah mengapa mereka pakai Oliv.

Setiap kali Oliv salah dan user tidak koreksi, data menjadi tidak akurat. Data yang tidak akurat membuat semua insight dan ringkasan tidak bisa dipercaya.

**Kekurangan #2: Oliv tidak pernah berinisiatif.**

Di V1 ini, Oliv adalah alat yang menunggu. Padahal potensi terbesarnya adalah menjadi advisor yang proaktif. User sudah memberikan data yang sangat kaya — tapi Oliv hanya menyimpannya tanpa menggunakannya untuk memberikan nilai tambah.

---

## Apa yang Membuat Oliv Unik?

**1. Kombinasi: Natural Language + Foto + Google Sheets**

Tidak ada aplikasi keuangan personal Indonesia yang kombinasikan ketiganya sekarang. Sebagian besar aplikasi memaksa user memilih dari form. Oliv memungkinkan input yang benar-benar natural.

**2. Sheets sebagai sumber kebenaran yang transparan**

User bisa melihat, mengedit, dan menganalisis data mereka sendiri tanpa bergantung pada interface Oliv. Ini membangun kepercayaan: "aku tahu dataku ada di mana dan aku bisa akses kapan saja."

**3. Karakter dan persona yang konsisten**

Oliv bukan asisten generik. Dia punya nama, punya gaya bicara, punya komentar personal tentang kebiasaan user. Ini menciptakan hubungan emosional yang membuat orang kembali setiap hari — sesuatu yang tidak bisa dicopy hanya dengan menambahkan nama ke generic chatbot.

**4. Coverage keuangan yang komprehensif tanpa kompleksitas**

22 command yang mencakup transaksi, investasi, utang, goals, dan aset — tapi semua diakses dengan cara yang sama: chat. User tidak perlu belajar interface baru untuk setiap modul.

---

## Apa yang Tidak Perlu Ditambahkan?

**1. Integrasi bank real-time**

Meskipun tampak menarik, ini akan mengubah Oliv menjadi fintech yang butuh lisensi, butuh security audit mendalam, dan menarik risk yang tidak sebanding dengan nilai tambahnya. Oliv kuat justru karena simplicity-nya.

**2. Social features**

"Bandingkan pengeluaranmu dengan teman" adalah feature yang menarik di atas kertas tapi merusak nilai inti Oliv: personalisasi dan kepercayaan. Keuangan adalah hal yang sangat pribadi.

**3. Gamification berlebihan**

Badges, streak, leaderboard — ini adalah mekanisme engagement yang berhasil di aplikasi fitness atau bahasa, tapi terasa trivial untuk konteks keuangan. Orang dewasa tidak butuh stiker untuk mencatat pengeluaran; mereka butuh manfaat nyata.

**4. AI chatting general**

Oliv bukan ChatGPT yang kebetulan bisa catat transaksi. Setiap kali user mencoba menggunakan Oliv untuk pertanyaan di luar keuangan, itu adalah signal untuk memperjelas scope, bukan untuk memperluas kemampuan AI-nya.

---

## Fitur yang Justru Mengurangi Kualitas (Anti-features)

### 1. `/analisa` tanpa batasan data

Saat ini `/analisa` mengirim **semua** transaksi historis ke Gemini. Jika ada 1000+ transaksi, ini:
- Sangat lambat (3-10 detik)
- Mahal (banyak token terpakai)
- Berisiko terpotong di context window (output tidak akurat)

Lebih baik batasi ke 3 bulan terakhir, atau user bisa spesifikasi bulan.

### 2. `/tanya` dengan data tak terbatas

Sama dengan analisa — memberikan semua data ke AI tanpa filtering adalah anti-pattern yang terlihat powerful tapi menghasilkan jawaban yang tidak reliable untuk dataset besar.

### 3. Komentar personal tanpa konteks

Komentar seperti "rokok lagi nih Zee 👀" muncul setiap kali ada kata "rokok" di memo. Ini charming pertama kali, tapi setelah 10 kali beli rokok, komentar yang sama menjadi annoying dan mengurangi keunikannya. Butuh variasi lebih banyak atau mekanisme untuk mengurangi frekuensi.

### 4. 22 command yang tidak semua terdokumentasi dengan baik

Command `/invest`, `/dividen`, `/jual`, `/utang`, `/piutang`, `/goal`, `/tabung`, `/aset` tidak muncul di /start message. User yang tidak tahu syntaxnya akan mencoba dan gagal. Feature yang tidak diketahui adalah feature yang tidak ada.

---

## Rekomendasi Prioritas Produk

Sebagai Product Manager, urutan prioritas saya adalah:

1. **Keamanan (V2.1)** — Tanpa ini, semua yang lain tidak ada artinya. Satu orang yang menemukan bot ini bisa merusak kepercayaan total.

2. **Confirmation flow (V2.2)** — Ini adalah perbedaan antara tool yang "lumayan" dan tool yang "bisa dipercaya". Data yang tidak akurat = insights yang tidak berguna = user yang churn.

3. **Proactive weekly insight (V3.1)** — Ini yang mengubah Oliv dari "tool yang harus diingatkan" menjadi "advisor yang proaktif". Satu pesan mingguan yang insightful bisa menggantikan 5 command manual.

4. **Net worth dashboard (V4.1)** — Semua data sudah ada. Ini adalah fitur yang paling high-value dengan effort paling rendah: tinggal menggabungkan data yang sudah tersimpan di berbagai sheet.

5. **Confirmation dari kategori salah (V2.2 lanjutan)** — Setiap koreksi yang user buat adalah training data untuk memperbaiki Gemini prompt. Ini adalah fondasi untuk Oliv yang "belajar".

---

## Satu Hal yang Paling Penting

Jika hanya ada satu hal yang harus diubah minggu depan, jawabannya adalah:

**Tambahkan konfirmasi sebelum simpan.**

Bukan karena fiturnya paling complex. Tapi karena ini yang paling langsung mempengaruhi kepercayaan user terhadap data mereka. Dan kepercayaan adalah segalanya untuk sebuah aplikasi keuangan.
