"""Tests for the pure reply-audit predicates (no LLM needed)."""

from alfa.bot.reply_auditor import evaluate_reply_audits


def _kw(**over):
    base = dict(
        prompt_low="",
        reply_low="",
        meeting_intent=False,
        action_intent=False,
        new_meetings=0,
        executed_tool_names=[],
        art_before="sig1",
        art_after="sig1",
    )
    base.update(over)
    return base


def test_clean_reply():
    kind, parts = evaluate_reply_audits(**_kw(reply_low="Halo, ini jawaban biasa."))
    assert kind is None
    assert parts == []


def test_meeting_fabrication():
    kind, parts = evaluate_reply_audits(
        **_kw(
            meeting_intent=True,
            reply_low="rapat selesai, hasil rapat: semua peserta setuju dan ada action plan",
        )
    )
    assert kind == "RAPAT FIKTIF"
    assert any("conduct_ai_meeting" in p for p in parts)


def test_meeting_real_no_audit():
    kind, _ = evaluate_reply_audits(
        **_kw(meeting_intent=True, new_meetings=2, reply_low="rapat selesai")
    )
    assert kind is None


def test_artifact_missing():
    kind, parts = evaluate_reply_audits(
        **_kw(
            prompt_low="buatkan file laporan pdf",
            reply_low="file pdf sudah selesai saya buat",
        )
    )
    assert kind == "ARTEFAK BELUM DIBUAT"
    assert any("TIDAK ADA berkas" in p for p in parts)


def test_artifact_created_no_audit():
    kind, _ = evaluate_reply_audits(
        **_kw(
            prompt_low="buatkan file laporan",
            reply_low="file sudah selesai",
            art_after="sig2",
        )
    )
    assert kind is None


def test_action_not_executed():
    kind, parts = evaluate_reply_audits(
        **_kw(action_intent=True, reply_low="musik sudah diputar sekarang")
    )
    assert kind == "AKSI BELUM DIJALANKAN"
    assert any("TIDAK ADA tool aksi" in p for p in parts)


def test_action_executed_no_audit():
    kind, _ = evaluate_reply_audits(
        **_kw(
            action_intent=True,
            reply_low="musik sudah diputar",
            executed_tool_names=["play_youtube_music"],
        )
    )
    assert kind is None


def test_fix_instruction_present():
    kind, parts = evaluate_reply_audits(
        **_kw(action_intent=True, reply_low="sudah kubuka halamannya")
    )
    assert kind is not None
    assert parts[0].startswith("⛔")
    assert any("Dilarang klaim palsu" in p for p in parts)


def test_read_file_no_false_artifact_audit():
    """Verify that reading/summarizing an uploaded document does not falsely trigger ARTEFAK BELUM DIBUAT."""
    kind, parts = evaluate_reply_audits(
        **_kw(
            prompt_low="[spreadsheet excel: smdt lubuk linggau.xlsx] instruksi pengguna: baca ini",
            reply_low="berikut adalah laporan ringkas rincian material yang sudah saya baca dari file excel:",
            art_before="sig1",
            art_after="sig1",
        )
    )
    assert kind is None
    assert parts == []


def test_document_summary_requests_never_trigger_artifact_audit():
    """Ensure requests like 'baca ini dan buat ringkasan' or 'buat rangkuman' are treated as text requests."""
    # 1. 'baca ini dan buat ringkasan' with excel header and system hints
    raw_prompt = (
        "[spreadsheet excel: smdt lahat.xlsx]\n"
        "[file tersimpan di disk: /path/smdt_lahat.xlsx]\n"
        "instruksi pengguna: baca ini dan buat ringkasan\n"
        "[panduan ai untuk dokumen/berkas]: ringkas..."
    )
    kind, parts = evaluate_reply_audits(
        **_kw(
            prompt_low=raw_prompt,
            reply_low="berikut adalah ringkasan eksekutif analisis material smdt lahat dari spreadsheet excel:",
            art_before="sig1",
            art_after="sig1",
        )
    )
    assert kind is None
    assert parts == []

    # 2. 'buat rangkuman dari excel'
    kind2, parts2 = evaluate_reply_audits(
        **_kw(
            prompt_low="buat rangkuman dari file excel ini",
            reply_low="rangkuman data selesai saya siapkan di bawah ini:",
            art_before="sig1",
            art_after="sig1",
        )
    )
    assert kind2 is None
    assert parts2 == []

    # 3. 'buatkan kesimpulan dan analisis'
    kind3, parts3 = evaluate_reply_audits(
        **_kw(
            prompt_low="buatkan kesimpulan dan analisis dokumen",
            reply_low="analisis dokumen selesai, berikut kesimpulannya:",
            art_before="sig1",
            art_after="sig1",
        )
    )
    assert kind3 is None
    assert parts3 == []


def test_clean_telegram_markdown():
    from alfa.bot.helpers import clean_telegram_markdown

    raw = (
        "Siap Fahmi, terima kasih auditnya dan aku jujur akui: **belum ada berkas laporan baru yang dibuat ke disk**.\n\n"
        "### 📌 Ringkasan Eksekutif\n\n"
        "#### 1. Alokasi Material Masuk\n"
        "* **Kabel Fiber Optik**:\n"
        "  * 24C: 12.000 m\n"
        "  * 36C: 3.000 m\n"
        "* **Tiang**:\n"
        "  * 7m: 81 unit\n\n"
        "---\n\n"
        "| Item | Qty |\n"
        "|---|---|\n"
        "| Tiang | 81 |\n\n"
        "File referensi: SMDT_LAHAT.xlsx\n\n"
        "Status: **SELESAI** (Analisis dan ringkasan data selesai disajikan secara langsung. Belum ada berkas PDF/Excel eksternal yang dibuat).\n"
        "Kalau kamu mau ringkasan ini diexport jadi file PDF resmi, kasih tahu ya Mi!"
    )
    cleaned = clean_telegram_markdown(raw)

    # Internal apologies and footers removed
    assert "terima kasih auditnya" not in cleaned
    assert "belum ada berkas laporan baru" not in cleaned
    assert "Status: **SELESAI**" not in cleaned
    assert "Kalau kamu mau ringkasan ini diexport" not in cleaned

    # Headers converted to bold
    assert "###" not in cleaned
    assert "####" not in cleaned
    assert "📌 *Ringkasan Eksekutif*" in cleaned
    assert "🔹 *1. Alokasi Material Masuk*" in cleaned

    # Bullets converted
    assert "• *Kabel Fiber Optik*:" in cleaned
    assert "▫️ 24C: 12.000 m" in cleaned

    # Table wrapped in code block
    assert "```\n| Item | Qty |\n|---|---|\n| Tiang | 81 |\n```" in cleaned

    # Identifier underscore escaped
    assert "SMDT\\_LAHAT.xlsx" in cleaned

    # Asterisks are balanced (even count)
    assert cleaned.count("*") % 2 == 0


