"""Vault DB path harus di-resolve dinamis — akar race test GDrive auth-mode.

Bug: ``alfa/security/vault.py`` mematok ``DB_PATH`` di waktu import. Bila fixture
test mengubah ``ALFA_DB_PATH`` setelah vault pernah diimport, SEMUA koneksi
vault tetap menunjuk DB lama → baris ``GDRIVE_OAUTH_TOKEN_JSON`` dari test
sebelumnya terbaca test selanjutnya → ``_detect_gdrive_auth_mode()`` salah
kembalikan "oauth" (flake urutan-tergantung).

Regresi ini menuntut: ubah ENV runtime → koneksi berikut mengikuti DB baru;
monkeypatch ATTR (pola test lama) juga tetap dihormati.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

TEST_VAULT_KEY = "ab" * 32  # 64 hex = 32 byte master key deterministik


@pytest.fixture(autouse=True)
def _isolated_key(monkeypatch):
    """Master key deterministik — jangan sentuh key file milik operator."""
    monkeypatch.setenv("VAULT_MASTER_KEY", TEST_VAULT_KEY)


def _vault():
    importlib.invalidate_caches()
    return importlib.import_module("alfa.security.vault")


def test_env_change_redirects_koneksi(monkeypatch, tmp_path):
    """Ubah ALFA_DB_PATH runtime → store & get mengikuti DB baru (bukan lama)."""
    vault_mod = _vault()
    db_a = str(tmp_path / "vault_a.db")
    db_b = str(tmp_path / "vault_b.db")

    monkeypatch.setenv("ALFA_DB_PATH", db_a)
    monkeypatch.setattr(vault_mod, "KEY_FILE", str(tmp_path / "key.bin"))
    vault_mod._init_vault_db()
    vault_mod.AlfaSecureVault().store_secret("KUNCI_API_1", "nilai-di-db-a")

    monkeypatch.setenv("ALFA_DB_PATH", db_b)
    vault_mod._init_vault_db()

    # DB BARU: tidak ada secret dari DB a
    v_b = vault_mod.AlfaSecureVault()
    assert v_b.get_secret("KUNCI_API_1") is None
    v_b.store_secret("KUNCI_API_1", "nilai-di-db-b")

    # kembali ke DB a: nilainya tetap ada (terasing dgn key yang sama)
    monkeypatch.setenv("ALFA_DB_PATH", db_a)
    got = vault_mod.AlfaSecureVault().get_secret("KUNCI_API_1")
    assert got is not None and got["value"] == "nilai-di-db-a"


def test_attr_patch_tetap_dihormati(monkeypatch, tmp_path):
    """Pola test lama: monkeypatch ATTR DB_PATH harus tetap diikuti koneksi."""
    vault_mod = _vault()
    db_c = str(tmp_path / "vault_c.db")

    monkeypatch.delenv("ALFA_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(vault_mod, "KEY_FILE", str(tmp_path / "key.bin"))
    monkeypatch.setattr(vault_mod, "DB_PATH", db_c)
    vault_mod._init_vault_db()

    v = vault_mod.AlfaSecureVault()
    v.store_secret("KUNCI_ATTR", "nilai-di-db-c")
    assert v.get_secret("KUNCI_ATTR")["value"] == "nilai-di-db-c"


def test_gdrive_auth_mode_tidak_tercemar_baris_vault_pdb_lama(monkeypatch, tmp_path):
    """Skenario flaky lengkap: oauth secret di DB lama, DB baru tanpa token → SA."""
    vault_mod = _vault()
    ga_mod = importlib.import_module("alfa.integrations.gdrive.auth")

    db_a = str(tmp_path / "vault_a.db")
    db_b = str(tmp_path / "vault_b.db")
    monkeypatch.setattr(ga_mod, "PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(vault_mod, "KEY_FILE", str(tmp_path / "key.bin"))

    # DB lama punya oauth token terenkripsi di vault
    monkeypatch.setenv("ALFA_DB_PATH", db_a)
    vault_mod._init_vault_db()
    vault_mod.AlfaSecureVault().store_secret(
        "GDRIVE_OAUTH_TOKEN_JSON", '{"refresh_token": "x"}'
    )
    assert ga_mod._detect_gdrive_auth_mode() == "oauth"

    # test berikutnya: DB baru KOSONG + token file tidak ada → env SA menang
    monkeypatch.setenv("ALFA_DB_PATH", db_b)
    vault_mod._init_vault_db()
    monkeypatch.setenv("GDRIVE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.delenv("gdrive_oauth_token_json", raising=False)
    assert ga_mod._detect_gdrive_auth_mode() == "service_account"
