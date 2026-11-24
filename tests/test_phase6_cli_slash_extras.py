"""Phase 6 coverage: slash-command mixin (/resume, /copy, /init, /commitmsg, /stats).

Hermetic: session store, clipboard tool, git, input, dan AI di-mock.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from alfa.core.cli.slash.extras import SlashExtrasMixin


class FakeCLI(SlashExtrasMixin):
    """Host minimal untuk SlashExtrasMixin tanpa CLI penuh."""

    def __init__(self):
        self.config: dict = {}
        self.chat_history: list[dict] = []
        self.direct_ai = SimpleNamespace(
            provider="gemini",
            model="gemini-test",
            generate=lambda **kwargs: "feat(cli): tambah fitur uji",
        )
        self.session_token: str | None = None
        self.mode = "chat"
        self.agent_mode = False
        self.agent_execution_mode = ""
        self._session_start: float | None = None


class _ServerStats:
    def do_slash_stats(self, arg) -> None:
        print("STATISTIK SERVER")


class ServerCLI(SlashExtrasMixin, _ServerStats):
    def __init__(self):
        self.config = {}
        self.chat_history = []
        self.direct_ai = SimpleNamespace(provider="x", model="y")
        self.session_token = "token-123"
        self._session_start = None


@pytest.fixture
def extras(monkeypatch):
    from alfa.core.cli.slash import extras as mod

    captured: list[tuple] = []

    def fake_print(msg, status="info"):
        captured.append((msg, status))

    monkeypatch.setattr(mod, "print_status", fake_print)
    mod.captured = captured
    return mod


def _messages(extras):
    return "\n".join(msg for msg, _ in extras.captured)


# ---------------------------------------------------------------------------
# /resume
# ---------------------------------------------------------------------------


def test_resume_session_not_found(extras, monkeypatch):
    from alfa.core.cli import session_store

    monkeypatch.setattr(session_store, "LAST_SESSION_NAME", "terakhir")
    loaded: list[str] = []

    class FakeStore:
        def load(self, name):
            loaded.append(name)
            return None

    monkeypatch.setattr(session_store, "SessionStore", FakeStore)
    cli = FakeCLI()
    cli.do_slash_resume("")
    assert loaded == ["terakhir"]
    assert "tidak ditemukan" in _messages(extras)


def test_resume_session_loads_history_and_extras(extras, monkeypatch):
    from alfa.core.cli import session_store

    class FakeStore:
        def load(self, name):
            return {
                "chat_history": [
                    {"role": "user", "content": "halo"},
                    {"role": "assistant", "content": "hai"},
                    "bukan-dict",
                    {"role": "system", "content": "system"},
                ],
                "extra": {
                    "agent_mode": True,
                    "agent_execution_mode": "autonomous",
                },
                "workspace": "/workspace/uji",
            }

    monkeypatch.setattr(session_store, "SessionStore", FakeStore)
    cli = FakeCLI()
    cli.do_slash_resume("  proyek  ")
    assert [m["role"] for m in cli.chat_history] == ["user", "assistant", "system"]
    assert cli.agent_mode is True
    assert cli.agent_execution_mode == "autonomous"
    assert "dilanjutkan" in _messages(extras)
    assert "/workspace/uji" in _messages(extras)


def test_resume_without_extras(extras, monkeypatch):
    from alfa.core.cli import session_store

    class FakeStore:
        def load(self, name):
            return {"chat_history": [], "extra": {}, "workspace": "-"}

    monkeypatch.setattr(session_store, "SessionStore", FakeStore)
    cli = FakeCLI()
    cli.do_slash_resume("kosong")
    assert cli.agent_mode is False
    assert "dilanjutkan" in _messages(extras)


# ---------------------------------------------------------------------------
# /copy
# ---------------------------------------------------------------------------


def test_copy_without_history(extras):
    cli = FakeCLI()
    cli.do_slash_copy("1")
    assert "Belum ada jawaban" in _messages(extras)


def test_copy_success_and_missing_index(extras, monkeypatch):
    cli = FakeCLI()
    cli.chat_history = [
        {"role": "user", "content": "tanya"},
        {"role": "assistant", "content": "jawaban pertama"},
        {"role": "assistant", "content": "jawaban kedua"},
    ]
    copied: list[str] = []
    monkeypatch.setattr(
        cli, "_copy_to_clipboard", lambda text: copied.append(text) or True
    )
    cli.do_slash_copy("2")
    assert copied == ["jawaban pertama"]
    assert "karakter disalin" in _messages(extras)

    extras.captured.clear()
    cli.do_slash_copy("9")
    assert "tidak ditemukan" in _messages(extras)


def test_copy_clipboard_failure(extras, monkeypatch):
    cli = FakeCLI()
    cli.chat_history = [{"role": "assistant", "content": "jawaban"}]
    monkeypatch.setattr(cli, "_copy_to_clipboard", lambda text: False)
    cli.do_slash_copy("")
    assert "Clipboard tidak tersedia" in _messages(extras)


def test_copy_to_clipboard_tools(extras, monkeypatch):
    cli = FakeCLI()
    run_calls: list[list] = []

    monkeypatch.setattr(
        extras.shutil,
        "which",
        lambda name: "/usr/bin/xsel" if name == "xsel" else None,
    )
    monkeypatch.setattr(
        extras.subprocess,
        "run",
        lambda cmd, **kw: run_calls.append(cmd) or SimpleNamespace(),
    )
    assert cli._copy_to_clipboard("teks") is True
    assert run_calls[0][0] == "xsel"

    run_calls.clear()

    def failing_run(cmd, **kwargs):
        run_calls.append(cmd)
        raise OSError("xclip gagal")  # noqa: TRY003

    monkeypatch.setattr(
        extras.shutil,
        "which",
        lambda name: "/usr/bin/xclip" if name == "xclip" else None,
    )
    monkeypatch.setattr(extras.subprocess, "run", failing_run)

    copied: list[str] = []
    mod = types.ModuleType("pyperclip")
    mod.copy = copied.append
    monkeypatch.setitem(sys.modules, "pyperclip", mod)
    assert cli._copy_to_clipboard("teks") is True
    assert copied == ["teks"]


def test_copy_to_clipboard_all_fail(extras, monkeypatch):
    cli = FakeCLI()
    monkeypatch.setattr(extras.shutil, "which", lambda name: None)

    mod = types.ModuleType("pyperclip")

    def boom(text):
        raise RuntimeError("clipboard mati")  # noqa: TRY003

    mod.copy = boom
    monkeypatch.setitem(sys.modules, "pyperclip", mod)
    assert cli._copy_to_clipboard("teks") is False


# ---------------------------------------------------------------------------
# /init
# ---------------------------------------------------------------------------


def test_init_existing_file_warning(extras, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ALFA.md").write_text("lama", encoding="utf-8")
    cli = FakeCLI()
    cli.do_slash_init("")
    assert "sudah ada" in _messages(extras)
    assert (tmp_path / "ALFA.md").read_text(encoding="utf-8") == "lama"


def test_init_generates_file(extras, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / ".gitignore").write_text("*", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    cli = FakeCLI()
    cli.repomap_gen = SimpleNamespace(generate_repomap=lambda: "peta repositori")
    cli.do_slash_init("--force")
    content = (tmp_path / "ALFA.md").read_text(encoding="utf-8")
    assert "Struktur Direktori" in content
    assert "src/" in content
    assert "peta repositori" in content
    assert ".gitignore" not in content
    assert "node_modules" not in content
    assert "dibuat di" in _messages(extras)


def test_init_repomap_failure(extras, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def boom():
        raise OSError("repomap gagal")  # noqa: TRY003

    class BrokenRepomap:
        generate_repomap = staticmethod(boom)

    cli = FakeCLI()
    cli.repomap_gen = BrokenRepomap()
    cli.do_slash_init("")
    content = (tmp_path / "ALFA.md").read_text(encoding="utf-8")
    assert "- (kosong)" in content
    assert "```\n\n```" in content


def test_init_repomap_import_fallback(extras, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cli = FakeCLI()
    # Tanpa repomap_gen: parser jatuh ke import RepomapGenerator (gagal -> "").
    import alfa.core.cli.slash.extras as mod

    fake_repomap = types.ModuleType("alfa.core.cli.agent_engine.repomap")

    def boom(path):
        raise RuntimeError("repomap rusak")  # noqa: TRY003

    fake_repomap.RepomapGenerator = boom
    monkeypatch.setitem(
        sys.modules, "alfa.core.cli.agent_engine.repomap", fake_repomap
    )
    cli.do_slash_init("")
    assert (tmp_path / "ALFA.md").exists()
    assert mod.logger is not None


def test_init_write_failure(extras, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cli = FakeCLI()
    cli.repomap_gen = SimpleNamespace(generate_repomap=lambda: "")

    def boom(self, *a, **k):
        raise OSError("read-only")  # noqa: TRY003

    monkeypatch.setattr(Path, "write_text", boom)
    cli.do_slash_init("")
    assert "Gagal menulis ALFA.md" in _messages(extras)


# ---------------------------------------------------------------------------
# /commitmsg
# ---------------------------------------------------------------------------


def test_commitmsg_no_changes(extras, monkeypatch):
    cli = FakeCLI()
    monkeypatch.setattr(
        extras.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(stdout="  ", stderr=""),
    )
    cli.do_slash_commitmsg("")
    assert "Tidak ada perubahan" in _messages(extras)


def test_commitmsg_git_error(extras, monkeypatch):
    cli = FakeCLI()

    def boom(cmd, **kwargs):
        raise OSError("git tidak ditemukan")  # noqa: TRY003

    monkeypatch.setattr(extras.subprocess, "run", boom)
    cli.do_slash_commitmsg("")
    assert "Gagal membaca git diff" in _messages(extras)


def test_commitmsg_success_with_staged_diff(extras, monkeypatch, capsys):
    cli = FakeCLI()
    calls: list[list] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(stdout="diff staged", stderr="")
        if cmd[:3] == ["git", "commit", "-am"]:
            return SimpleNamespace(stdout="committed", stderr="")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(extras.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    cli.do_slash_commitmsg("")
    out = capsys.readouterr().out
    assert "Pesan commit" in out
    assert calls[-1][:3] == ["git", "commit", "-am"]
    assert "committed" in out


def test_commitmsg_unstaged_diff_declined(extras, monkeypatch, capsys):
    cli = FakeCLI()

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(stdout="", stderr="")
        return SimpleNamespace(stdout="diff kerja", stderr="")

    monkeypatch.setattr(extras.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    cli.do_slash_commitmsg("")
    assert "Commit dibatalkan" in _messages(extras)
    assert "Pesan commit" in capsys.readouterr().out


def test_commitmsg_generate_error(extras, monkeypatch):
    cli = FakeCLI()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="diff isi", stderr="")

    def boom(**kwargs):
        raise RuntimeError("AI mati")  # noqa: TRY003

    cli.direct_ai.generate = boom
    monkeypatch.setattr(extras.subprocess, "run", fake_run)
    cli.do_slash_commitmsg("")
    assert "Gagal generate pesan" in _messages(extras)


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


def test_stats_local_without_start_time(extras, capsys):
    cli = FakeCLI()
    cli.chat_history = [
        {"role": "user", "content": "satu"},
        {"role": "assistant", "content": "jawaban"},
    ]
    cli.do_slash_stats("")
    out = capsys.readouterr().out
    assert "Statistik Sesi Lokal" in out
    assert "Durasi        : -" in out
    assert "2 (1 dari user)" in out
    assert "gemini/gemini-test" in out


def test_stats_with_duration_and_mode(extras, capsys, monkeypatch):
    cli = FakeCLI()
    cli._session_start = 1000.0
    cli.chat_history = [{"role": "user", "content": "x" * 10}]
    cli.mode = "swarm"
    monkeypatch.setattr(extras, "time", SimpleNamespace(time=lambda: 1042.0))
    cli.do_slash_stats("")
    out = capsys.readouterr().out
    assert "42 detik" in out
    assert "Mode          : swarm" in out


def test_stats_server_path(extras, capsys):
    cli = ServerCLI()
    cli.do_slash_stats("")
    out = capsys.readouterr().out
    assert "STATISTIK SERVER" in out
    assert "Statistik Sesi Lokal" not in out


def test_stats_server_super_missing_method(extras, capsys):
    cli = FakeCLI()
    cli.session_token = "token-123"
    cli.do_slash_stats("")
    out = capsys.readouterr().out
    assert "Statistik Sesi Lokal" in out
