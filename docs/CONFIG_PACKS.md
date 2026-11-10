# Config Pack — data domain siap pakai

Config pack memuat **data domain** ALFA (daftar cluster, constraint simbolik
rekap material, peta nama mandor) dalam satu berkas JSON. Tujuannya: ALFA bisa
dipakai untuk wilayah/tenant lain **tanpa mengubah kode core**.

## Pack bawaan

| Pack | Isi |
|---|---|
| `default` | Data operasi ALFA saat ini (Lahat, Curup, Bengkulu, Lubuklinggau). Dipakai bila `ALFA_CONFIG_PACK` tidak diisi. |
| `demo` | Data sintetis untuk demo & uji otomatis — tanpa data operasi nyata. |

## Memakai pack

```bash
# di .env / ~/.config/alfa/secrets.env
ALFA_CONFIG_PACK=demo
```

Restart **hanya** `telegram-ai-bot.service` dan `alfa-dashboard.service`
(jangan pernah `wa-sheets-bot.service`).

## Bentuk berkas pack

Berkas berada di `alfa/config/packs/<nama>.json`:

```json
{
  "name": "contoh",
  "description": "Keterangan singkat pack",
  "clusters": ["ALFA", "BETA"],
  "summary_clusters": ["ALFA", "BETA"],
  "constraints": {
    "ALFA": {
      "cluster": "CLUSTER_ALFA",
      "mugi_bruto": 10,
      "mugi_retur": 2,
      "mugi_net": 8,
      "aqe_net": 5,
      "total_net": 13,
      "items": {"T72": 13}
    }
  },
  "mandor_names": {
    "7000000000001": "Mandor Demo Satu"
  }
}
```

- `clusters` — cluster yang dipantau (deteksi otomatis pada pesan lapangan).
- `summary_clusters` — cluster yang tampil di ringkasan World-Model.
- `constraints` — ground truth symbolic per cluster (dipakai Neuro-Symbolic
  Prover untuk mengoreksi total yang salah).
- `mandor_names` — pemetaan nomor WhatsApp/LID → nama mandor.

## Urutan prioritas

1. `ALFA_CONFIG_PACK` — pack JSON.
2. `ALFA_TRACKED_CLUSTERS` — daftar cluster dipisah koma.
3. `ALFA_DOMAIN_CONSTRAINTS_JSON` — path JSON atau objek JSON inline.
4. Nilai bawaan (pack `default`).

Pack yang tidak ditemukan **tidak** menggagalkan runtime: sistem kembali ke
pack `default` dan mencatat peringatan.

## Membuat pack baru

```bash
cp alfa/config/packs/demo.json alfa/config/packs/wilayah-baru.json
# edit nama, cluster, constraint, dan mandor
```

Pastikan invariant constraint konsisten (`mugi_bruto - mugi_retur == mugi_net`,
`mugi_net + aqe_net == total_net`, `sum(items) == total_net`) — jika tidak,
verifikasi simbolik dilewati dan tercatat di log.

## Verifikasi

```bash
venv/bin/python -c "from alfa.config.packs import available_packs; print(available_packs())"
venv/bin/python -m pytest tests/test_config_packs.py -q
```
