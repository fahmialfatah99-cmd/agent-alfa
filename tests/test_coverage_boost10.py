"""Coverage batch 10: settings dashboard (env masking, key models) and
workspace search tools.

Hermetic: REPO_ROOT/HOME redirected to tmp, database isolated, subprocess
and ripgrep-free fallbacks exercised on real temp trees.
"""

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated sqlite for dashboard modules."""
    from alfa.core.db import connection as db_conn

    db_file = tmp_path / "settings_test.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_conn.init_db_sync()
    return db_file


# ── GET /api/settings ────────────────────────────────────────────────────────


class TestGetSystemSettings:
    def _call(self, sa):
        import asyncio

        return asyncio.run(sa.get_system_settings())

    def test_masks_long_secrets(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text(
            "TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGHIJK\n"
            "GEMINI_API_KEY=AIzaSyDUMMYKEY123456\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        out = self._call(sa)
        assert out["status"] == "success"
        blob = json.dumps(out)
        # raw secrets must never reach the API response
        assert "1234567890:ABCDEFGHIJK" not in blob
        assert "AIzaSyDUMMYKEY123456" not in blob
        assert out["env"]["has_bot_token"] is True
        assert out["env"]["has_gemini_key"] is True
        assert "..." in out["env"]["masked_bot_token"]
        assert "..." in out["env"]["masked_gemini_key"]

    def test_masks_short_secret_as_stars(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text("GEMINI_API_KEY=short\n", encoding="utf-8")
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        out = self._call(sa)
        assert out["env"]["masked_gemini_key"] == "***"

    def test_placeholder_token_is_not_flagged_present(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text(
            "TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here\n", encoding="utf-8"
        )
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        out = self._call(sa)
        assert out["env"]["has_bot_token"] is False

    def test_empty_env_gives_empty_mask(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        out = self._call(sa)
        assert out["env"]["masked_gemini_key"] == ""
        assert out["env"]["has_gemini_key"] is False
        assert out["env"]["gemini_model"] == "gemini-3.6-flash"

    def test_reads_prompt_file_when_present(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
        home = tmp_path / "home"
        (home / ".alfa").mkdir(parents=True)
        (home / ".alfa" / "system_prompt.txt").write_text(
            "Instruksi dari file", encoding="utf-8"
        )
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        monkeypatch.setenv("HOME", str(home))
        out = self._call(sa)
        assert out["env"]["system_instruction_source"] == "file"
        assert "Instruksi dari file" in out["env"]["system_instruction"]

    def test_env_prompt_when_no_file(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text("SYSTEM_INSTRUCTION=Dari env\n", encoding="utf-8")
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        out = self._call(sa)
        assert out["env"]["system_instruction_source"] == "env"
        assert "Dari env" in out["env"]["system_instruction"]

    def test_includes_db_settings(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa
        from alfa.core.db.connection import get_sync_db

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        with get_sync_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
                ("custom_flag", "on"),
            )
            conn.commit()
        out = self._call(sa)
        assert out["db_settings"].get("custom_flag") == "on"

    def test_missing_env_file_is_safe(self, db, tmp_path, monkeypatch):
        import alfa.dashboard.routes.system.settings_admin as sa

        repo = tmp_path / "repo"
        repo.mkdir()  # no .env at all
        monkeypatch.setattr(sa, "REPO_ROOT", str(repo))
        out = self._call(sa)
        assert out["status"] == "success"
        assert out["env"]["has_bot_token"] is False
        assert isinstance(out["vault_keys"], list)


# ── workspace search tools ───────────────────────────────────────────────────


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A small real directory tree for the search tools."""
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "ws"
    (root / "pkg").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "__pycache__").mkdir()
    (root / "a.py").write_text("import os\nprint('ALPHA')\n", encoding="utf-8")
    (root / "b.json").write_text('{"k": 1}', encoding="utf-8")
    (root / "pkg" / "c.py").write_text("def gamma():\n    pass\n", encoding="utf-8")
    (root / "node_modules" / "d.py").write_text("x = 1", encoding="utf-8")
    (root / "__pycache__" / "e.py").write_text("x = 1", encoding="utf-8")
    return root


class TestSearchWorkspaceFiles:
    def test_glob_match(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.search_workspace_files("*.py", base_dir=str(tree), max_results=50)
        assert out["status"] == "success"
        names = {os.path.basename(f) for f in out["files"]}
        assert "a.py" in names
        assert "c.py" in names
        # heavy dirs must be skipped
        assert not any("node_modules" in f for f in out["files"])
        assert not any("__pycache__" in f for f in out["files"])

    def test_respects_max_results(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.search_workspace_files("*.py", base_dir=str(tree), max_results=1)
        assert out["matches_count"] == 1
        assert len(out["files"]) == 1

    def test_substring_fallback(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.search_workspace_files("gamma", base_dir=str(tree), max_results=50)
        assert out["status"] == "success"

    def test_no_match_returns_empty(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.search_workspace_files("*.zzz", base_dir=str(tree))
        assert out["status"] == "success"
        assert out["files"] == []


class TestGrepWorkspace:
    def test_finds_text(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.grep_workspace("ALPHA", base_dir=str(tree))
        assert out["status"] == "success"
        assert out["matches_count"] >= 1

    def test_file_pattern_filter(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.grep_workspace("pass", base_dir=str(tree), file_pattern="*.py")
        assert out["status"] == "success"

    def test_no_match(self, tree):
        from alfa.tools.filesystem import search as s

        out = s.grep_workspace("TIDAK_ADA_SAMA_SINI", base_dir=str(tree))
        assert out["status"] in ("success", "error")


class TestFindUserFiles:
    """`folder` is a SUBDIRECTORY name inside ~/Downloads|Documents|Desktop|Pictures."""

    @pytest.fixture
    def home_with_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        dl = tmp_path / "Downloads" / "semua"
        dl.mkdir(parents=True)
        # NOTE: find_user_files skips files < 1024 bytes, so pad every fixture
        # file past that threshold.
        big = "x" * 2048
        (dl / "b.json").write_text(big, encoding="utf-8")
        (dl / "photo.png").write_bytes(b"x" * 2048)
        (dl / "notes.txt").write_text(big, encoding="utf-8")
        (dl / "node_modules").mkdir()
        (dl / "node_modules" / "dep.json").write_text(big, encoding="utf-8")
        return tmp_path

    def test_by_type_data(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="data", folder="semua")
        assert out["status"] == "success"
        assert out["total"] >= 1
        assert any(f["name"] == "b.json" for f in out["files"])

    def test_by_type_image(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="image", folder="semua")
        assert out["status"] == "success"
        assert any(f["name"] == "photo.png" for f in out["files"])

    def test_comma_separated_types(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="data,doc", folder="semua")
        names = out["files"]
        assert any(f["name"] == "b.json" for f in names)
        assert any(f["name"] == "notes.txt" for f in names)

    def test_unknown_type_falls_back_to_all(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="tipe-hantu", folder="semua")
        assert out["status"] == "success"
        assert out["total"] >= 3

    def test_type_all(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="all", folder="semua")
        assert out["status"] == "success"
        assert out["total"] >= 3

    def test_result_shape(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="data", folder="semua")
        first = out["files"][0]
        assert set(first) >= {"path", "name", "size_mb", "modified"}
        assert Path(first["path"]).exists()

    def test_pattern_filter(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(pattern="b", file_types="data", folder="semua")
        assert out["status"] == "success"
        assert all("b.json" in f["name"] for f in out["files"])

    def test_skips_heavy_dirs(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="data", folder="semua")
        assert not any("node_modules" in f["path"] for f in out["files"])

    def test_missing_folder_returns_empty(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="data", folder="tidak-ada")
        assert out["status"] == "success"
        assert out["total"] == 0

    def test_no_folder_scans_standard_dirs(self, home_with_files):
        from alfa.tools.filesystem import search as s

        out = s.find_user_files(file_types="data")
        assert out["status"] == "success"
        assert isinstance(out["files"], list)


class TestCompressFolder:
    def test_creates_zip(self, tree, tmp_path, monkeypatch):
        from alfa.tools.filesystem import search as s

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        monkeypatch.setenv("HOME", str(tmp_path / "home-out"))
        (tmp_path / "home-out").mkdir()
        out = s.compress_folder_to_zip(str(tree), "hasil")
        assert out["status"] == "success"
        zpath = out.get("output_path") or out.get("zip_path") or out.get("file_path")
        assert zpath and Path(zpath).exists()
        names = zipfile.ZipFile(zpath).namelist()
        assert any(n.endswith("a.py") for n in names)
        # the tool zips exactly what the caller asked for (no implicit filtering)
        assert any("node_modules" in n for n in names)

    def test_missing_folder(self, tmp_path, monkeypatch):
        from alfa.tools.filesystem import search as s

        out = s.compress_folder_to_zip(str(tmp_path / "tidak-ada"), "x")
        assert out["status"] == "error"


class TestSendFileToChat:
    def test_missing_file(self, tmp_path, monkeypatch):
        from alfa.tools.filesystem import search as s

        out = s.send_file_to_chat(str(tmp_path / "hilang.txt"))
        assert out["status"] == "error"
