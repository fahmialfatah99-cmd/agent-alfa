"""Tes guard verifikasi klaim artefak (anti false-success)."""

from __future__ import annotations

import os
import time

from openpyxl import Workbook

from alfa.core.brain import artifact_verify as av


def _make_xlsx(path, sheets=("Rekap Material", "Kabel & Aksesoris")):
    wb = Workbook()
    wb.active.title = sheets[0]
    for name in sheets[1:]:
        wb.create_sheet(name)
    wb.save(path)
    return path


def _fresh(path, when: float | None = None) -> None:
    stamp = when if when is not None else time.time()
    os.utime(path, (stamp, stamp))


def test_claim_with_fresh_file_is_clean(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path)
    _fresh(path)
    reply = f"File master sudah selesai aku perbarui di `{path}`."
    assert av.verify_artifact_claims(reply, time.time() - 10) == []


def test_claim_with_stale_file_is_flagged(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path)
    old = time.time() - 600
    _fresh(path, old)
    reply = f"File master sudah selesai aku perbarui di `{path}`."
    issues = av.verify_artifact_claims(reply, time.time() - 10)
    assert len(issues) == 1
    assert "tidak berubah" in issues[0].reason


def test_claim_with_missing_file_is_flagged(tmp_path):
    path = tmp_path / "hilang.xlsx"
    reply = f"Laporan sudah dibuat di `{path}`."
    issues = av.verify_artifact_claims(reply, time.time() - 10)
    assert len(issues) == 1
    assert "tidak ditemukan" in issues[0].reason


def test_reading_a_file_is_not_a_mutation_claim(tmp_path):
    path = tmp_path / "input.xlsx"
    _make_xlsx(path)
    _fresh(path, time.time() - 600)
    reply = f"Saya sudah membaca `{path}` dan menemukan 3 anomali."
    assert av.verify_artifact_claims(reply, time.time() - 10) == []


def test_missing_sheet_is_flagged(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path)
    _fresh(path)
    reply = (
        f"File rekap di `{path}` sudah selesai aku perbarui.\n"
        "Sheet Baru: `Monitoring Stok & Selisih`"
    )
    issues = av.verify_artifact_claims(reply, time.time() - 10)
    assert len(issues) == 1
    assert "Monitoring Stok & Selisih" in issues[0].reason
    assert "tidak ditemukan" in issues[0].reason


def test_present_sheet_is_clean(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path, sheets=("Rekap Material", "Monitoring Stok & Selisih"))
    _fresh(path)
    reply = (
        f"File rekap di `{path}` sudah selesai aku perbarui.\n"
        "Sheet Baru: `Monitoring Stok & Selisih`"
    )
    assert av.verify_artifact_claims(reply, time.time() - 10) == []


def test_guard_appends_warning(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path)
    _fresh(path, time.time() - 600)
    reply = f"File master sudah selesai aku perbarui di `{path}`."
    guarded, issues = av.apply_artifact_guard(reply, time.time() - 10)
    assert issues
    assert guarded.startswith(reply)
    assert "Verifikasi otomatis" in guarded
    assert str(path) in guarded


class _VerifierError(RuntimeError):
    """Kegagalan verifier tiruan."""


def test_guard_is_idempotent(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path)
    _fresh(path, time.time() - 600)
    reply = f"File master sudah selesai aku perbarui di `{path}`."
    guarded, issues = av.apply_artifact_guard(reply, time.time() - 10)
    assert issues
    guarded_again, issues_again = av.apply_artifact_guard(guarded, time.time() - 10)
    assert guarded_again == guarded
    assert issues_again == []


def test_guard_swallows_verification_errors(monkeypatch):
    def boom(_reply, _start):
        raise _VerifierError

    monkeypatch.setattr(av, "verify_artifact_claims", boom)
    reply = "File sudah diperbarui di `/tmp/x.xlsx`."
    guarded, issues = av.apply_artifact_guard(reply, time.time())
    assert guarded == reply
    assert issues == []


def test_paths_are_deduplicated(tmp_path):
    path = tmp_path / "rekap.xlsx"
    _make_xlsx(path)
    _fresh(path, time.time() - 600)
    reply = (
        f"File `{path}` sudah diperbarui. "
        f"Ringkasan `{path}` juga sudah diperbarui."
    )
    issues = av.verify_artifact_claims(reply, time.time() - 10)
    assert len(issues) == 1
