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
