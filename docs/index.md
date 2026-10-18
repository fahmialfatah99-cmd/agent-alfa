# ALFA Sovereign AI

**Ekosistem AI otonom terpadu** — multi-agent swarm, 162 sovereign tools,
brain RAG hibrido, command center web, bot Telegram/Discord, dan vault
AES-256-GCM. Dashboard passkey WebAuthn aktif end-to-end.

Halaman beranda ini menyingkat; detail penuh masuk **README**.

## Mulai cepat

```bash
# 1) venv + dependensi
python3 -m venv venv
./venv/bin/pip install -e .

# 2) konfigurasi env (wajib Telegram token, classifier key, dsb.)
cp .env.example .env
#    isi: TELEGRAM_BOT_TOKEN, DASHBOARD_AUTH_TOKEN (wajib utk bind publik)

# 3) jalankan ketiganya
./scripts/run.sh          # dashboard + bot + CLI

# atau satuan
./venv/bin/python -m alfa.dashboard.app      # dashboard
./venv/bin/python -m alfa.bot.telegram_bot   # bot
./venv/bin/python -m alfa.core.cli           # CLI/panel
```

Rincian opsi lengkap: [Instalasi](INSTALL.md).

## Yang paham sebelum pakai

- **Keamanan produksi**: `DASHBOARD_AUTH_TOKEN` wajib bila bind publik; boot
  guard MENOLAK start `ALFA_UNRESTRICTED=true` + bind publik.
- **Passkey/WebAuthn** end-to-end aktif; butuh hostname (bukan IP) & HTTPS di produksi.
- **Vault** mencegah plaintext secret — migrasi otomatis di lifespan dashboard.

Ruang situasi: [Keamanan](security.md) ·
[Changelog](CHANGELOG.md) · [Kualitas kode](CODE_QUALITY.md)

## Peta situs

| Halaman | Isi |
| --- | --- |
| [README](about.md) | Fitur, struktur kode, konfigurasi env |
| [Instalasi](INSTALL.md) | Setup manual & requirement |
| [Arsitektur](DISCORD_BOT_CORE_ARCHITECTURE.md) | Kabel bot Telegram/Discord |
| [Keamanan](security.md) | Vault, RBAC, boot guard, WebAuthn |
| [Testing](TESTING.md) | Cara menjalankan suite |
| [Benchmark](BENCHMARK.md) · [Efisiensi](EFFICIENCY.md) | Angka dasar |
| [PostgreSQL](POSTGRES.md) | Backend DB produksi |
| [Changelog](CHANGELOG.md) | Perubahan tercatat |
