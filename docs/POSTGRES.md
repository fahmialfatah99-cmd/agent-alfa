# Postgres — peta jalan jujur (belum dikerjakan)

Status: **belum didukung**. SQLite adalah satu-satunya backend yang diuji.
Dokumen ini mencatat penghalang konkret agar migrasi kelak tidak menebak.

## Penghalang terinventaris

1. **Placeholder `?`** — ±58 query di `alfa/core/db/*` (dan ratusan di modul
   lain) memakai gaya `qmark` SQLite; Postgres (`psycopg`) memakai `%s`.
2. **Fitur khusus SQLite**:
   - `PRAGMA journal_mode=WAL`, `busy_timeout` (`connection.py`, `queue.py`)
   - FTS5 full-text (`tools/filesystem/code_index.py`)
   - `sqlite-vss` vector index (`memory/vector.py`) — pengganti natural:
     `pgvector`
   - `ON CONFLICT(name) DO UPDATE` (`security/vault.py`) — beruntung sintaks
     ini juga valid di Postgres
   - `sqlite3.Row`, `lastrowid`, `AUTOINCREMENT`
3. **Koneksi tersebar** — `sqlite3.connect(DB_PATH)` dipanggil langsung di
   `vault.py`, `perm/store.py`, `swarm/queue.py`, dsb (bukan via pool
   `connection.py`), sehingga tidak ada satu titik potong.
4. **Transaksi implisit** — perilaku commit/autocommit SQLite diasumsikan di
   banyak tempat (`claim_next` memakai `BEGIN IMMEDIATE` eksplisit — itu
   pun sintaks SQLite).

## Rute yang disarankan (epic terpisah, bukan patch)

1. Pusatkan akses DB lewat satu modul koneksi (sudah ada
   `core/db/connection.py` — pindahkan pemanggil langsung ke sana).
2. Perkenalkan lapisan dialek kecil (`qmark` → `%s` rewrite + tipe
   kembalian baris) di titik pusat tersebut.
3. Ganti FTS5 → `tsvector`, `sqlite-vss` → `pgvector`, WAL → MVCC bawaan.
4. Dual-run CI: SQLite (default) + Postgres service container.

Perkiraan: 2–4 minggu kerja fokus + harness migrasi. Sampai saat itu,
batas yang benar: **single-node SQLite**, antrean durable menutupi
ketahanan proses, bukan skala horizontal.
