"""
Unit test untuk database, enkripsi AES-256-GCM, dan pengaturan user.
Menggunakan database SQLite temporer agar database produksi tidak tersentuh.
"""
import database
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestKeyEncryption:
    def test_roundtrip(self):
        plain = "sk-test-secret-key-12345"
        enc = database.encrypt_key(plain)
        assert enc != plain
        assert enc.startswith("enc1:")
        assert database.decrypt_key(enc) == plain

    def test_nonce_unik(self):
        plain = "kunci_rahasia_sama"
        enc1 = database.encrypt_key(plain)
        enc2 = database.encrypt_key(plain)
        assert enc1 != enc2, "Nonce harus acak per enkripsi"
        assert database.decrypt_key(enc1) == plain
        assert database.decrypt_key(enc2) == plain

    def test_idempotent_on_encrypted(self):
        plain = "my-secret-key"
        enc = database.encrypt_key(plain)
        assert database.encrypt_key(enc) == enc

    def test_legacy_plaintext_passthrough(self):
        legacy = "legacy-plaintext-without-prefix"
        assert database.decrypt_key(legacy) == legacy

    def test_empty_none_handling(self):
        assert database.encrypt_key("") == ""
        assert database.decrypt_key("") == ""
        assert database.decrypt_key(None) == ""


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Fixture untuk database SQLite baru dan bersih di direktori temp."""
    db_file = str(tmp_path / "test_agent_data.db")
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db_sync()
    return db_file


class TestDatabaseOperations:
    def test_init_db_creates_tables(self, temp_db):
        with database.get_sync_db() as conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            assert "api_keys" in tables
            assert "custom_agents" in tables
            assert "user_settings" in tables

    def test_custom_agents_default_model(self, temp_db):
        """Verifikasi agen yang di-seed menggunakan gemini-3.6-flash bukan model deprecated."""
        agents = database.list_custom_agents_sync()
        assert len(agents) > 0
        for a in agents:
            # Tidak ada yang boleh memakai gemini-2.5 atau gemini-3.5
            assert "gemini-2.5" not in a.get("model", "")
            assert "gemini-3.5" not in a.get("model", "")

    def test_add_and_update_custom_agent(self, temp_db):
        res = database.add_custom_agent_sync(
            name="Security Tester",
            role="Pentester",
            persona="Teliti",
            system_instruction="Audit semua",
            provider="gemini",
            model="gemini-3.6-flash"
        )
        assert res["status"] == "success"
        agent_id = res["id"]

        agents = database.list_custom_agents_sync()
        agent_names = [a["name"] for a in agents]
        assert "Security Tester" in agent_names

        # Update
        database.update_custom_agent_sync(agent_id, {"role": "Lead Pentester"})
        updated = database.get_custom_agent_sync(agent_id)
        assert updated["role"] == "Lead Pentester"

    def test_api_keys_encryption_at_rest(self, temp_db):
        """Kunci yang disimpan di tabel api_keys harus terenkripsi dengan prefix enc1:."""
        res = database.add_api_key_sync(
            name="Test Gemini Vault",
            provider="gemini",
            api_key="AIzaSyTestSecret12345",
            default_model="gemini-3.6-flash"
        )
        assert res["status"] == "success"
        key_id = res["id"]

        # Cek raw storage di sqlite
        with database.get_sync_db() as conn:
            raw_val = conn.execute("SELECT api_key FROM api_keys WHERE id=?", (key_id,)).fetchone()[0]
            assert raw_val.startswith("enc1:")
            assert raw_val != "AIzaSyTestSecret12345"

        # Cek via helper get_api_key_by_id_sync yang mendekripsi otomatis
        decrypted = database.get_api_key_by_id_sync(key_id)
        assert decrypted["api_key"] == "AIzaSyTestSecret12345"
