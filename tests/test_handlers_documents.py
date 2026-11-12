"""Tes handler dokumen bot: cache, pemulihan, dan aksi 1-klik.

Fokus pada jalur yang, bila salah, membuat pengguna **tidak mendapat balasan
sama sekali** setelah mengunggah dokumen:
- cache dokumen terakhir (RAM/disk/SQLite),
- tombol aksi `docact:*` (PDF & Excel instan 0-token + fallback LLM),
- eksekutor batch dokumen.

Semua hermetik: Telegram, LLM, dan pembuat berkas di-mock.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from alfa.bot.handlers import documents as docs


class _ServiceError(RuntimeError):
    """Kegagalan layanan tiruan."""


class _PdfBrokenError(_ServiceError):
    def __init__(self) -> None:
        super().__init__("pdf rusak")


class _ProviderDownError(_ServiceError):
    def __init__(self) -> None:
        super().__init__("provider mati")


class _LlmDownError(_ServiceError):
    def __init__(self) -> None:
        super().__init__("LLM mati")


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch, tmp_path):
    from alfa.bot.handlers import _state

    _state._RECENT_DOCS.clear()
    _state._DOC_BATCHES.clear()
    monkeypatch.setattr(
        _state, "_RECENT_DOCS_CACHE_PATH", str(tmp_path / "recent_docs.json")
    )
    monkeypatch.setattr(docs, "_RECENT_DOCS", _state._RECENT_DOCS)
    monkeypatch.setattr(docs, "_DOC_BATCHES", _state._DOC_BATCHES)
    monkeypatch.setattr(docs, "_RECENT_DOCS_CACHE_PATH", _state._RECENT_DOCS_CACHE_PATH)
    monkeypatch.setattr(docs, "sandbox_dir", lambda: str(tmp_path / "sandbox"))
    yield
    _state._RECENT_DOCS.clear()
    _state._DOC_BATCHES.clear()


def _update(chat_id: int = 100, user_id: int = 42, data: str = "") -> SimpleNamespace:
    query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
    return SimpleNamespace(
        callback_query=query if data else None,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=user_id),
        message=None,
    )


def _context() -> SimpleNamespace:
    sent = AsyncMock()
    sent.return_value = SimpleNamespace(delete=AsyncMock())
    return SimpleNamespace(bot=SimpleNamespace(send_message=sent))


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, context, chat_id, text, reply_to_message_id=None, reply_markup=None):
        self.calls.append({"text": text, "markup": reply_markup})
        return SimpleNamespace(message_id=1)

    @property
    def last_text(self) -> str:
        return self.calls[-1]["text"]


@pytest.fixture()
def sent(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(docs, "safe_send_message", rec)
    artifacts = AsyncMock()
    monkeypatch.setattr(docs, "check_artifacts_turn", artifacts)
    return rec


async def _fake_typing(_chat_id, _context, stop_event, _action):
    await stop_event.wait()


@pytest.fixture()
def typing(monkeypatch):
    monkeypatch.setattr(docs, "send_typing_loop", _fake_typing)


# ── cache dokumen ──────────────────────────────────────────────────────────


class TestRecentDocsCache:
    def test_save_and_reload_from_disk(self, tmp_path, monkeypatch):
        docs._RECENT_DOCS[7] = {
            "file_name": "do.pdf",
            "txt_ctx": "isi",
            "summary_reply": "ringkas",
        }
        docs._save_recent_docs_cache()
        data = json.loads((tmp_path / "recent_docs.json").read_text(encoding="utf-8"))
        assert data["7"]["file_name"] == "do.pdf"

        docs._RECENT_DOCS.clear()
        got = docs._get_or_recover_recent_doc(7)
        assert got is not None
        assert got["file_name"] == "do.pdf"

    def test_save_failure_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(docs, "_RECENT_DOCS_CACHE_PATH", "/proc/1/tidak-bisa/ditulis.json")
        docs._RECENT_DOCS[1] = {"file_name": "x"}
        docs._save_recent_docs_cache()  # tidak boleh melempar

    def test_invalid_cache_json_is_ignored(self, tmp_path, monkeypatch):
        bad = tmp_path / "recent_docs.json"
        bad.write_text("{bukan json", encoding="utf-8")
        monkeypatch.setattr(docs, "_RECENT_DOCS_CACHE_PATH", str(bad))
        assert docs._get_or_recover_recent_doc(99) is None


class TestSqliteRecovery:
    def _make_db(self, tmp_path, content: str, reply: str = "ringkasan AI") -> str:
        db = tmp_path / "agent_data.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE chat_history (id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT, content TEXT)"
        )
        conn.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, 'user', ?)",
            (42, content),
        )
        conn.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, 'assistant', ?)",
            (42, reply),
        )
        conn.commit()
        conn.close()
        return str(db)

    def test_recovers_from_chat_history(self, tmp_path, monkeypatch):
        import alfa.core.db.connection as conn_mod

        content = (
            "[LOCAL_DISK_PATH: /tmp/DOEID26101705.xls]\n"
            "[SPREADSHEET EXCEL: DOEID26101705.xls]\n\nMaterial: T73"
            "\n\nInstruksi Pengguna: ringkas"
        )
        monkeypatch.setattr(
            conn_mod, "DB_PATH", self._make_db(tmp_path, content, "• T73 : 94 btg")
        )
        got = docs._get_or_recover_recent_doc(555, 42)
        assert got is not None
        assert got["file_name"] == "DOEID26101705.xls"
        assert got["summary_reply"] == "• T73 : 94 btg"
        assert got["is_batch"] is False
        assert "LOCAL_DISK_PATH" in got["txt_ctx"]

    def test_recovers_batch_marker(self, tmp_path, monkeypatch):
        import alfa.core.db.connection as conn_mod

        content = (
            "[KUMPULAN 2 BERKAS DOKUMEN DIUNGGAH SEKALIGUS]:\n--- DOKUMEN 1\n"
            "[DOKUMEN PDF: a.pdf]"
        )
        monkeypatch.setattr(conn_mod, "DB_PATH", self._make_db(tmp_path, content))
        got = docs._get_or_recover_recent_doc(556, 42)
        assert got is not None
        assert got["is_batch"] is True
        assert got["file_name"] == "a.pdf"

    def test_no_matching_history_returns_none(self, tmp_path, monkeypatch):
        import alfa.core.db.connection as conn_mod

        monkeypatch.setattr(
            conn_mod, "DB_PATH", self._make_db(tmp_path, "obrolan biasa tanpa dokumen")
        )
        assert docs._get_or_recover_recent_doc(557, 42) is None

    def test_missing_db_is_handled(self, tmp_path, monkeypatch):
        import alfa.core.db.connection as conn_mod

        monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "nope.db"))
        # File dibuat kosong oleh sqlite3 saat connect; query gagal -> ditangkap.
        assert docs._get_or_recover_recent_doc(558, 42) is None


# ── parser ringkasan → tabel ───────────────────────────────────────────────


class TestParseSummaryIntoTable:
    def test_empty_returns_empty(self):
        assert docs._parse_summary_into_table("") == []

    def test_only_header_without_items_returns_empty(self):
        assert docs._parse_summary_into_table("Ringkasan biasa tanpa butir") == []

    def test_parses_sections_and_items(self):
        summary = (
            "*KABEL FIBER OPTIK:*\n"
            "• Kabel KU24 : 120 btg\n"
            "- Tiang 7m : 8 unit\n"
            "### Perangkat\n"
            "• ODP : 2 buah\n"
        )
        rows = docs._parse_summary_into_table(summary)
        assert rows[0] == [
            "No",
            "Kategori / Bagian",
            "Nama Material / Parameter",
            "Rincian / Kuantitas",
        ]
        assert ["1", "KABEL FIBER OPTIK", "Kabel KU24", "120 btg"] in rows
        assert ["3", "Perangkat", "ODP", "2 buah"] in rows

    def test_ignores_document_header_lines(self):
        summary = "*Dokumen: DO.pdf*\n• Item : 1 pcs"
        rows = docs._parse_summary_into_table(summary)
        assert len(rows) == 2
        assert rows[1][1] == "Ringkasan Umum"


# ── aksi dokumen 1-klik ────────────────────────────────────────────────────


class TestDocActionCallback:
    async def test_non_docact_returns_false(self, sent):
        assert await docs.handle_doc_action_callback(_update(), _context(), "btn_menu") is False

    async def test_expired_document_message(self, sent):
        ctx = _context()
        assert await docs.handle_doc_action_callback(_update(), ctx, "docact:pdf") is True
        text = ctx.bot.send_message.await_args.kwargs["text"]
        assert "kedaluwarsa" in text

    async def test_instant_pdf_path(self, sent, monkeypatch, tmp_path):
        docs._RECENT_DOCS[100] = {
            "file_name": "DO.xlsx",
            "txt_ctx": "isi",
            "summary_reply": "*Material:*\n• T73 : 94 btg",
        }
        calls: list[dict] = []

        def fake_pdf(**kwargs):
            calls.append(kwargs)
            return {"status": "success"}

        monkeypatch.setattr(
            "alfa.tools.media.pdf_builder.generate_pdf_report", fake_pdf
        )
        res = await docs.handle_doc_action_callback(_update(), _context(), "docact:pdf")
        assert res is True
        assert calls and calls[0]["filename"].startswith("Laporan_Resmi_DO")
        assert "PDF Resmi" in sent.last_text

    async def test_instant_excel_path(self, sent, monkeypatch):
        docs._RECENT_DOCS[100] = {
            "file_name": "DO.xlsx",
            "txt_ctx": "isi",
            "summary_reply": "*Material:*\n• T73 : 94 btg\n• T72 : 86 btg",
        }
        calls: list[dict] = []

        def fake_excel(**kwargs):
            calls.append(kwargs)
            return {"status": "success"}

        # modul yang BENAR (bug lama menunjuk alfa.tools.data.office_suite yang tidak ada)
        monkeypatch.setattr(
            "alfa.tools.media.documents.generate_excel_spreadsheet", fake_excel
        )
        res = await docs.handle_doc_action_callback(_update(), _context(), "docact:excel")
        assert res is True
        assert calls and calls[0]["headers"] == ["No", "Kategori / Bagian", "Nama Material / Parameter", "Rincian / Kuantitas"]
        assert "Spreadsheet Excel" in sent.last_text

    async def test_instant_builder_failure_falls_back_to_llm(
        self, sent, typing, monkeypatch
    ):
        docs._RECENT_DOCS[100] = {
            "file_name": "DO.xlsx",
            "txt_ctx": "isi",
            "summary_reply": "*Material:*\n• T73 : 94 btg",
        }

        def boom(**_kwargs):
            raise _PdfBrokenError()

        monkeypatch.setattr(
            "alfa.tools.media.pdf_builder.generate_pdf_report", boom
        )
        agent = AsyncMock(return_value="laporan dari LLM")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        res = await docs.handle_doc_action_callback(_update(), _context(), "docact:pdf")
        assert res is True
        agent.assert_awaited_once()
        assert sent.last_text == "laporan dari LLM"

    async def test_deep_action_uses_llm_and_cleans_status(
        self, sent, typing, monkeypatch
    ):
        docs._RECENT_DOCS[100] = {
            "file_name": "DO.xlsx",
            "txt_ctx": "isi",
            "summary_reply": "",
        }
        ctx = _context()
        agent = AsyncMock(return_value="audit selesai")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        res = await docs.handle_doc_action_callback(_update(), ctx, "docact:deep")
        assert res is True
        assert sent.last_text == "audit selesai"
        # pesan status "sedang diproses" dihapus lagi
        status_msg = ctx.bot.send_message.return_value
        status_msg.delete.assert_awaited_once()

    async def test_llm_failure_still_cleans_typing(
        self, sent, typing, monkeypatch
    ):
        docs._RECENT_DOCS[100] = {"file_name": "DO.xlsx", "txt_ctx": "isi", "summary_reply": ""}

        async def boom(**_kwargs):
            raise _ProviderDownError()

        monkeypatch.setattr(docs, "run_agent_turn", boom)
        ctx = _context()
        with pytest.raises(_ServiceError):
            await docs.handle_doc_action_callback(_update(), ctx, "docact:deep")
        ctx.bot.send_message.return_value.delete.assert_awaited_once()

    async def test_unknown_action_returns_false(self, sent, monkeypatch):
        docs._RECENT_DOCS[100] = {"file_name": "x", "txt_ctx": "isi", "summary_reply": ""}
        assert await docs.handle_doc_action_callback(_update(), _context(), "docact:foo") is False

    async def test_batch_prompt_includes_all_files(self, sent, typing, monkeypatch):
        docs._RECENT_DOCS[100] = {
            "file_name": "2 Berkas Gabungan",
            "file_names": ["a.pdf", "b.xlsx"],
            "docs_count": 2,
            "is_batch": True,
            "txt_ctx": "gabungan",
            "summary_reply": "",
        }
        agent = AsyncMock(return_value="ok")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        await docs.handle_doc_action_callback(_update(), _context(), "docact:pdf")
        prompt = agent.await_args.kwargs["user_prompt"]
        assert "2 dokumen" in prompt or "SELURUH 2" in prompt
        assert "a.pdf" in prompt and "b.xlsx" in prompt

    async def test_long_context_is_truncated(self, sent, typing, monkeypatch):
        docs._RECENT_DOCS[100] = {
            "file_name": "besar.txt",
            "txt_ctx": "A" * 20000,
            "summary_reply": "",
        }
        agent = AsyncMock(return_value="ok")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        await docs.handle_doc_action_callback(_update(), _context(), "docact:deep")
        prompt = agent.await_args.kwargs["user_prompt"]
        assert "dipangkas otomatis" in prompt
        assert len(prompt) < 20000

    async def test_old_sandbox_files_are_removed(self, sent, monkeypatch, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "lama.pdf").write_text("x", encoding="utf-8")
        (sandbox / "lama.txt").write_text("x", encoding="utf-8")
        docs._RECENT_DOCS[100] = {
            "file_name": "DO.txt",
            "txt_ctx": "isi",
            "summary_reply": "",
        }
        agent = AsyncMock(return_value="ok")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        await docs.handle_doc_action_callback(_update(), _context(), "docact:pdf")
        assert not (sandbox / "lama.pdf").exists()
        assert (sandbox / "lama.txt").exists()  # bukan target aksi


# ── eksekutor batch dokumen ────────────────────────────────────────────────


class TestExecuteDocumentBatch:
    async def test_empty_batch_returns_immediately(self, sent):
        await docs._execute_document_batch(100, {"docs": []})
        assert sent.calls == []

    async def test_single_document_reply_and_cache(
        self, sent, typing, monkeypatch
    ):
        agent = AsyncMock(return_value="• T73 : 94 btg")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        batch = {
            "docs": [
                {
                    "file_name": "DO.xlsx",
                    "mime_type": "application/vnd.ms-excel",
                    "txt_ctx": "isi material",
                    "part": None,
                    "caption": "",
                }
            ],
            "captions": [],
            "user_id": 42,
            "context": _context(),
            "latest_update": _update(),
            "turn_start_time": 0.0,
        }
        await docs._execute_document_batch(100, batch)
        assert sent.last_text == "• T73 : 94 btg"
        cached = docs._RECENT_DOCS[100]
        assert cached["file_name"] == "DO.xlsx"
        assert cached["summary_reply"] == "• T73 : 94 btg"
        # tombol aksi ikut dikirim
        assert sent.calls[-1]["markup"] is not None

    async def test_multi_document_batch_merges(self, sent, typing, monkeypatch):
        agent = AsyncMock(return_value="laporan gabungan")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        batch = {
            "docs": [
                {"file_name": "a.pdf", "mime_type": "application/pdf", "txt_ctx": "A", "part": None},
                {"file_name": "b.xlsx", "mime_type": "application/vnd.ms-excel", "txt_ctx": "B", "part": None},
            ],
            "captions": ["gabungkan"],
            "user_id": 42,
            "context": _context(),
            "latest_update": _update(),
            "turn_start_time": 0.0,
        }
        await docs._execute_document_batch(101, batch)
        prompt = agent.await_args.kwargs["user_prompt"]
        assert "[KUMPULAN 2 BERKAS DOKUMEN" in prompt
        assert "a.pdf" in prompt and "b.xlsx" in prompt
        cached = docs._RECENT_DOCS[101]
        assert cached["is_batch"] is True
        assert cached["docs_count"] == 2

    async def test_agent_failure_returns_apology(self, sent, typing, monkeypatch):
        async def boom(**_kwargs):
            raise _LlmDownError()

        monkeypatch.setattr(docs, "run_agent_turn", boom)
        batch = {
            "docs": [{"file_name": "a.txt", "mime_type": "text/plain", "txt_ctx": "A", "part": None}],
            "captions": [],
            "user_id": 42,
            "context": _context(),
            "latest_update": None,
            "turn_start_time": 0.0,
        }
        await docs._execute_document_batch(102, batch)
        assert "gagal diproses" in sent.last_text
        assert "_LlmDownError" in sent.last_text

    async def test_multimodal_parts_are_forwarded(self, sent, typing, monkeypatch):
        agent = AsyncMock(return_value="ok")
        monkeypatch.setattr(docs, "run_agent_turn", agent)
        part = object()
        batch = {
            "docs": [
                {
                    "file_name": "foto.png",
                    "mime_type": "image/png",
                    "txt_ctx": "",
                    "part": part,
                }
            ],
            "captions": [],
            "user_id": 42,
            "context": _context(),
            "latest_update": None,
            "turn_start_time": 0.0,
        }
        await docs._execute_document_batch(103, batch)
        assert agent.await_args.kwargs["multimodal_parts"] == [part]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
