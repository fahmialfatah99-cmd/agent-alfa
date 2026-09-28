"""Coverage batch 12: YouTube player helpers, workspace hygiene, step executor.

Hermetic: yt-dlp/ffplay/subprocess are mocked, and hygiene runs against
real temp trees.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── media/player helpers ─────────────────────────────────────────────────────


class TestPlayerHelpers:
    def test_which_returns_first_available(self, monkeypatch):
        from alfa.tools.media import player as p

        monkeypatch.setattr(
            p.shutil,
            "which",
            lambda n: "/usr/bin/yt-dlp" if n == "yt-dlp" else None,
        )
        assert p._ytdlp() == "/usr/bin/yt-dlp"
        assert p._which(["tidak-ada", "juga-tidak"]) is None

    def test_watch_url_shape(self):
        from alfa.tools.media import player as p

        url = p._watch_url("abc123")
        assert url == "https://www.youtube.com/watch?v=abc123"
        assert "autoplay=1" in p._watch_url("abc123", autoplay=True)

    def test_resolve_empty_query(self):
        from alfa.tools.media import player as p

        out = p._resolve("   ")
        assert out["ok"] is False
        assert "kosong" in out["error"].lower()

    def test_resolve_requires_yt_dlp(self, monkeypatch):
        from alfa.tools.media import player as p

        monkeypatch.setattr(p, "_ytdlp", lambda: None)
        out = p._resolve("lagu")
        assert out["ok"] is False
        assert "yt-dlp" in out["error"]

    def test_resolve_extracts_youtube_id(self, monkeypatch):
        from alfa.tools.media import player as p

        monkeypatch.setattr(p, "_ytdlp", lambda: "/usr/bin/yt-dlp")

        done = MagicMock()
        done.returncode = 0
        done.stdout = (
            '{"id": "vid123", "title": "Judul", "duration": 200, '
            '"webpage_url": "https://www.youtube.com/watch?v=vid123"}'
        )
        done.stderr = ""
        monkeypatch.setattr(p.subprocess, "run", lambda *a, **k: done)

        out = p._resolve("https://www.youtube.com/watch?v=vid123")
        assert out["ok"] is True
        assert out["id"] == "vid123"
        assert out["title"] == "Judul"
        assert out["watch_url"].endswith("v=vid123")
        assert out["url"] == "https://www.youtube.com/watch?v=vid123"

    def test_client_args_from_env(self, monkeypatch):
        from alfa.tools.media import player as p

        monkeypatch.setenv("ALFA_YT_PLAYER_CLIENT", "android web")
        args = p._client_args()
        assert args
        assert all(isinstance(a, str) for a in args)

    def test_kill_group_handles_none(self):
        from alfa.tools.media import player as p

        assert p._kill_group(None) is False

    def test_kill_group_terminates_group(self, monkeypatch):
        from alfa.tools.media import player as p

        seen = {}
        monkeypatch.setattr(p.os, "getpgid", lambda pid: 4242, raising=False)
        monkeypatch.setattr(
            p.os, "killpg", lambda pgid, sig: seen.update(pgid=pgid, sig=sig)
        )
        proc = MagicMock()
        proc.pid = 4242
        proc.poll.return_value = None  # still running
        assert p._kill_group(proc) is True
        assert seen["pgid"] == 4242
        assert seen["sig"] == 15  # SIGTERM

    def test_kill_group_noop_when_exited(self):
        from alfa.tools.media import player as p

        proc = MagicMock()
        proc.poll.return_value = 0  # already finished
        assert p._kill_group(proc) is False

    def test_kill_group_falls_back_to_terminate(self, monkeypatch):
        from alfa.tools.media import player as p

        def _boom(*a, **k):
            raise OSError("tidak ada proses grup")

        monkeypatch.setattr(p.os, "getpgid", _boom, raising=False)
        proc = MagicMock()
        proc.pid = 1
        proc.poll.return_value = None
        assert p._kill_group(proc) is True
        proc.terminate.assert_called_once()

    def test_stop_audio_without_process(self):
        from alfa.tools.media import player as p

        p._AUDIO_PROC = None
        out = p._stop_audio()
        assert "status" in out


# ── workspace hygiene ────────────────────────────────────────────────────────


class TestWorkspaceHygiene:
    def test_missing_dir_is_noop(self, tmp_path):
        from alfa.swarm import workspace_hygiene as wh

        out = wh.sanitize_project_directory(str(tmp_path / "tidak-ada"))
        assert out == {"deleted_files": 0, "pruned_dirs": 0}

    def test_empty_dir_is_noop(self, tmp_path):
        from alfa.swarm import workspace_hygiene as wh

        out = wh.sanitize_project_directory(str(tmp_path))
        assert out["deleted_files"] == 0

    def test_removes_junk_and_prunes_empty(self, tmp_path):
        from alfa.swarm import workspace_hygiene as wh

        root = tmp_path / "proj"
        (root / "sub").mkdir(parents=True)
        (root / ".DS_Store").write_bytes(b"x")
        (root / "Thumbs.db").write_bytes(b"x")
        (root / "keep.py").write_text("x = 1", encoding="utf-8")
        (root / "sub" / "junk.tmp").write_bytes(b"x")
        out = wh.sanitize_project_directory(str(root))
        assert out["deleted_files"] >= 2
        assert not (root / ".DS_Store").exists()
        assert (root / "keep.py").exists()

    def test_dependency_dirs_are_pruned(self, tmp_path):
        """node_modules & friends sit in _HARVEST_EXCLUDE, so they are DELETED."""
        from alfa.swarm import workspace_hygiene as wh

        root = tmp_path / "proj"
        (root / "node_modules").mkdir(parents=True)
        (root / "node_modules" / "index.js").write_text("x", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("y = 2", encoding="utf-8")
        out = wh.sanitize_project_directory(str(root))
        assert not (root / "node_modules").exists()
        assert (root / "src" / "main.py").exists()
        assert out["pruned_dirs"] >= 1

    def test_tmp_prefixed_dirs_are_pruned(self, tmp_path):
        from alfa.swarm import workspace_hygiene as wh

        root = tmp_path / "proj"
        (root / ".tmp_scratch").mkdir(parents=True)
        (root / ".tmp_scratch" / "x.bin").write_bytes(b"x")
        (root / "keep.py").write_text("y = 2", encoding="utf-8")
        wh.sanitize_project_directory(str(root))
        assert not (root / ".tmp_scratch").exists()
        assert (root / "keep.py").exists()

    def test_cancel_requires_active_meeting(self, monkeypatch):
        from alfa.swarm import workspace_hygiene as wh

        monkeypatch.setattr(wh, "MEETING_RUNNING", False)
        wh._clear_cancel_flag()
        assert wh.request_cancel_swarm() is False
        assert wh._cancel_requested() is False

    def test_cancel_flag_lifecycle(self, monkeypatch, tmp_path):
        from alfa.swarm import workspace_hygiene as wh

        monkeypatch.setattr(wh, "MEETING_RUNNING", True)
        monkeypatch.setattr(wh, "_get_swarm_output_dir", lambda: str(tmp_path / "out"))
        monkeypatch.setattr(wh, "_get_target_folder", lambda: str(tmp_path / "tgt"))
        wh._clear_cancel_flag()
        assert wh._cancel_requested() is False
        assert wh.request_cancel_swarm() is True
        assert wh._cancel_requested() is True
        wh._clear_cancel_flag()
        assert wh._cancel_requested() is False

    def test_accessors_return_strings(self):
        from alfa.swarm import workspace_hygiene as wh

        assert isinstance(wh._get_swarm_output_dir(), str)
        assert isinstance(wh._get_target_folder(), str)
        assert isinstance(wh._get_sandbox_snapshot(), set)

    def test_sandbox_project_dirs_is_set(self):
        from alfa.swarm import workspace_hygiene as wh

        assert isinstance(wh._sandbox_project_dirs(), set)


# ── step executor helpers ────────────────────────────────────────────────────


class TestStepExecutorHelpers:
    def test_extract_html_from_fence(self):
        from alfa.swarm.step_executor import _extract_html_doc

        got = _extract_html_doc("tadi ini:\n```html\n<html><body>Hi</body></html>\n```\nselesai")
        assert got == "<html><body>Hi</body></html>"

    def test_extract_html_from_doctype(self):
        from alfa.swarm.step_executor import _extract_html_doc

        text = "x <!DOCTYPE html><html>q</html> y"
        assert "<!DOCTYPE html>" in _extract_html_doc(text)

    def test_extract_html_from_bare_tag(self):
        from alfa.swarm.step_executor import _extract_html_doc

        got = _extract_html_doc("prefix <html>body</html>")
        assert got.startswith("<html>")

    def test_extract_html_none(self):
        from alfa.swarm.step_executor import _extract_html_doc

        assert _extract_html_doc("") == ""
        assert _extract_html_doc("tidak ada html di sini") == ""

    def test_validate_rejects_short(self):
        from alfa.swarm.step_executor import validate_python_code

        assert validate_python_code("x = 1") != ""
        assert validate_python_code("") != ""

    def test_validate_reports_line(self):
        from alfa.swarm.step_executor import validate_python_code

        bad = "def f(:\n    return 1\n" + "# padding to exceed the length gate" * 2
        err = validate_python_code(bad)
        assert "syntax error di baris" in err

    def test_validate_accepts_good_code(self):
        from alfa.swarm.step_executor import validate_python_code

        good = "def greet(name):\n    return f'halo {name}'\n\nprint(greet('dunia'))\n"
        assert validate_python_code(good) == ""
