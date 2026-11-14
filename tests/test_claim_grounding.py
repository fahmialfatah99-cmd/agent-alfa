"""Tes grounding atribusi tool/library pada balasan agen."""

from __future__ import annotations

from alfa.core.brain import claim_grounding as cg


def _call(tool: str, args: str = "") -> dict[str, str]:
    item = {"tool": tool}
    if args:
        item["args"] = args
    return item


def test_false_tesseract_claim_is_flagged():
    issues = cg.verify_attribution_claims(
        "Berhasil aku ekstrak dan baca detail dengan OCR tesseract.",
        [_call("inspect_field_surat_jalan_image")],
    )
    assert [issue.term for issue in issues] == ["tesseract"]


def test_tesseract_grounded_by_bash_args_is_clean():
    issues = cg.verify_attribution_claims(
        "Berhasil aku ekstrak dengan OCR tesseract.",
        [_call("execute_bash_command", "tesseract surat.png hasil.txt")],
    )
    assert issues == []


def test_conditional_and_negated_mentions_are_clean():
    text = "Saya bisa memakai OCR tesseract jika perlu."
    assert cg.verify_attribution_claims(text, [_call("vision_tool")]) == []
    assert (
        cg.verify_attribution_claims("Aku tidak memakai tesseract.", [])
        == []
    )


def test_definition_and_code_block_mentions_are_clean():
    assert (
        cg.verify_attribution_claims("Tesseract adalah OCR open source.", [])
        == []
    )
    assert (
        cg.verify_attribution_claims(
            "```bash\ntesseract input.png output\n```", []
        )
        == []
    )


def test_inline_code_claim_is_still_flagged():
    issues = cg.verify_attribution_claims(
        "Berhasil aku pakai `tesseract` untuk membaca struk.", []
    )
    assert [issue.term for issue in issues] == ["tesseract"]


def test_unexecuted_backticked_tool_is_flagged():
    issues = cg.verify_attribution_claims(
        "Saya sudah menjalankan `execute_bash_command` untuk cek file.", []
    )
    assert [issue.term for issue in issues] == ["execute_bash_command"]


def test_executed_backticked_tool_is_clean():
    issues = cg.verify_attribution_claims(
        "Saya sudah menjalankan `execute_bash_command` untuk cek file.",
        [_call("execute_bash_command")],
    )
    assert issues == []


def test_duplicate_aliases_are_deduplicated():
    issues = cg.verify_attribution_claims(
        "Berhasil pakai pytesseract dan tesseract.", []
    )
    assert len(issues) == 1


def test_guard_appends_warning_with_recorded_tools():
    final, issues = cg.apply_attribution_guard(
        "Berhasil aku ekstrak dengan OCR tesseract.",
        [_call("inspect_field_surat_jalan_image")],
    )
    assert issues
    assert "Catatan atribusi" in final
    assert "inspect_field_surat_jalan_image" in final


def test_guard_is_idempotent():
    first, issues = cg.apply_attribution_guard(
        "Berhasil aku ekstrak dengan OCR tesseract.", []
    )
    assert issues
    second, issues_again = cg.apply_attribution_guard(first, [])
    assert second == first
    assert issues_again == []


class _VerifierError(RuntimeError):
    """Kegagalan verifier tiruan."""

    def __init__(self) -> None:
        super().__init__("verifier rusak")


def test_guard_swallows_verification_errors(monkeypatch):
    def boom(_reply, _calls):
        raise _VerifierError

    monkeypatch.setattr(cg, "verify_attribution_claims", boom)
    reply = "Berhasil aku ekstrak dengan OCR tesseract."
    final, issues = cg.apply_attribution_guard(reply, [])
    assert final == reply
    assert issues == []


def test_warning_limits_to_three_issues():
    final, issues = cg.apply_attribution_guard(
        "Berhasil pakai tesseract, whisper, ffmpeg, dan playwright.", []
    )
    assert len(issues) == 4
    assert "…dan 1 klaim lain." in final


def test_no_claim_means_no_warning():
    final, issues = cg.apply_attribution_guard(
        "Saya menemukan dokumentasi tesseract di folder proyek.", []
    )
    assert final == "Saya menemukan dokumentasi tesseract di folder proyek."
    assert issues == []
