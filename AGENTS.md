# PANDUAN PENGEMBANGAN & ATURAN AGEN (ALFA OS)

Dokumen ini memuat aturan mutlak dari **Fahmi** untuk semua agen AI saat mengelola, mengembangkan, dan memodifikasi repositori ALFA.

---

## 1. Zero Regression (Pertahankan Fitur yang Sudah Benar)
- **DILARANG KERAS** menghilangkan, merombak tanpa izin, atau merusak fitur-fitur yang sudah bekerja dengan benar saat melakukan perbaikan bug atau penambahan fitur baru.
- Perbaikan bug harus fokus dan tepat sasaran (surgical fix), tidak mengubah kontrak API, signature fungsi yang sudah ada, atau format output yang sudah diandalkan oleh sistem lain.

## 2. Tanya & Jelaskan Risiko Terlebih Dahulu
- Sebelum melakukan perubahan besar, refactoring arsitektur, mengubah skema database, atau mengganti pustaka inti:
  1. Jelaskan rencana tindakan secara singkat dan jelas.
  2. Paparkan potensi risiko, efek samping (side-effects), dan dampaknya terhadap fitur lain.
  3. Minta persetujuan Fahmi sebelum mengeksekusi perubahan berisiko tinggi.

## 3. Verifikasi & Pengujian Wajib
- Setiap perubahan kode harus diverifikasi:
  - Jalankan pengujian otomatis terkait (`venv/bin/pytest tests/...`).
  - Pastikan layanan yang terpengaruh (`systemctl --user status ...`) tetap berjalan sehat.
  - Verifikasi fungsionalitas nyata melalui pemanggilan fungsi atau uji endpoint (`curl`).

## 4. Perlindungan Mutlak Sesi WhatsApp (Anti-Logout & Anti-Reset)
- **DILARANG KERAS** melakukan logout, menghentikan paksa (kill), merestart, mereset sesi, atau menghapus user data Chromium/WhatsApp (`wa-sheets-bot.service` dan folder terkait) saat memperbarui sistem atau melakukan perbaikan kode.
- Login WhatsApp sangat sulit dan sering mengalami kendala pada QR code, sehingga sesi login aktif yang sudah tersambung **WAJIB dijaga 100% tetap hidup dan tidak boleh diinterupsi**.
- Saat me-restart service ALFA setelah pembaruan, **HANYA** restart `telegram-ai-bot.service` dan `alfa-dashboard.service`. **JANGAN PERNAH** menyentuh atau merestart `wa-sheets-bot.service`.

## 5. Kebijakan Fitur Konsolidasi Progres Lapangan
- Fitur konsolidasi progres lapangan (ekstraksi kuantitas tarikan kabel, tiang tertanam, FAT/FDT dari chat grup WhatsApp) **DINONAKTIFKAN SEMENTARA** atas instruksi Fahmi, karena progres pekerjaan lapangan saat ini tidak dilaporkan di dalam grup WhatsApp.
- Jadwal berkala briefing konsolidasi lapangan di `scheduled_cron_jobs` dimatikan (`is_active = 0`).

