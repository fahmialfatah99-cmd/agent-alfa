"""Deliberasi swarm terstruktur: parsing giliran, pengumpulan proposal,
pemungutan suara, dan dissent.

Sebelum refactor, "diskusi" swarm hanyalah prompt-chain sekuensial tanpa
proposal/suara, dan persentase konsensus di UI adalah heuristik atas string
tahap. Modul `alfa.swarm.deliberation` menjadikan bagian itu terukur.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.swarm.deliberation import (  # noqa: E402
    Turn,
    apply_votes,
    build_context_digest,
    build_proposal_menu,
    collect_proposals,
    parse_turn,
)


class TestParseTurn:
    def test_json_bersih(self):
        raw = json.dumps(
            {
                "position": "Pakai Redis untuk cache",
                "evidence": "Latensi DB 800ms",
                "confidence": 0.8,
                "votes": [{"id": "p1-agen-a", "approve": True, "reason": "setuju"}],
            }
        )
        parsed = parse_turn(raw)
        assert parsed["parsed"] is True
        assert parsed["position"] == "Pakai Redis untuk cache"
        assert parsed["evidence"] == "Latensi DB 800ms"
        assert parsed["confidence"] == 0.8
        assert parsed["votes"] == [("p1-agen-a", True)]

    def test_json_tercampur_prosa(self):
        raw = 'Ini jawaban saya.\n{"position": "Pakai X", "confidence": 0.6}'
        parsed = parse_turn(raw)
        assert parsed["parsed"] is True
        assert parsed["position"] == "Pakai X"

    def test_bukan_json_jadi_teks_polos(self):
        parsed = parse_turn("Saya phylogeny fitur-fitur ini saja.")
        assert parsed["parsed"] is False
        assert parsed["position"].startswith("Saya")
        assert parsed["votes"] == []

    def test_kosong(self):
        parsed = parse_turn("")
        assert parsed["position"] == ""
        assert parsed["votes"] == []

    def test_vote_string_setuju_dikonversi(self):
        raw = json.dumps(
            {"position": "p", "votes": [{"id": "p1", "approve": "SETUJU"}]}
        )
        parsed = parse_turn(raw)
        assert parsed["votes"] == [("p1", True)]

    def test_confidence_dibatasi(self):
        raw = json.dumps({"position": "p", "confidence": 5.0})
        assert parse_turn(raw)["confidence"] == 1.0
        raw2 = json.dumps({"position": "p", "confidence": -2})
        assert parse_turn(raw2)["confidence"] == 0.0


class TestProposalCollection:
    def _turns(self):
        return [
            Turn(1, "Agen A", "Koder", "Pakai Redis", "bukti", 0.8, [], "raw"),
            Turn(1, "Agen B", "Analis", "Pakai PostgreSQL", "bukti2", 0.6, [], "raw"),
            Turn(2, "Agen A", "Koder", "Pakai Redis + TTL", "bukti", 0.9, [], "raw"),
        ]

    def test_posisi_terakhir_per_agen(self):
        proposals = collect_proposals(self._turns())
        assert len(proposals) == 2
        by_author = {p.author: p for p in proposals}
        assert by_author["Agen A"].summary == "Pakai Redis + TTL"
        assert by_author["Agen A"].round == 2

    def test_id_proposal_stabil(self):
        proposals = collect_proposals(self._turns())
        ids = {p.id for p in proposals}
        assert "p2-agen-a" in ids

    def test_tanpa_posisi_diabaikan(self):
        proposals = collect_proposals([Turn(1, "A", "R", "", "", 0.5, [], "raw")])
        assert proposals == []

    def test_menu_proposal_terbatas(self):
        turns = [Turn(1, f"A{i}", "R", f"posisi {i}", "", 0.5, [], "raw") for i in range(20)]
        menu = build_proposal_menu(collect_proposals(turns))
        assert menu.count("id=") <= 8


class TestVoteTally:
    def _proposals(self):
        return collect_proposals(
            [
                Turn(1, "Agen A", "Koder", "Pakai Redis", "", 0.8, [], "raw"),
                Turn(1, "Agen B", "Analis", "Pakai Postgres", "", 0.6, [], "raw"),
            ]
        )

    def test_suara_terhitung(self):
        props = self._proposals()
        pid_a = next(p.id for p in props if p.author == "Agen A")
        pid_b = next(p.id for p in props if p.author == "Agen B")
        tally = apply_votes(
            props,
            [
                ("Agen B", True, pid_a),
                ("Agen C", True, pid_a),
                ("Agen C", False, pid_b),
            ],
        )
        assert tally["total_voters"] == 3
        assert tally["total_proposals"] == 2
        assert tally["winner"]["id"] == pid_a
        assert tally["winner"]["votes_for"] == 2
        assert tally["winner"]["votes_against"] == 0
        assert tally["agreement"] == pytest.approx(2 / 3, rel=0.01)

    def test_dissent_tercatat(self):
        props = self._proposals()
        pid_a = next(p.id for p in props if p.author == "Agen A")
        tally = apply_votes(props, [("Agen C", False, pid_a)])
        assert len(tally["dissent"]) == 1
        assert tally["dissent"][0]["voter"] == "Agen C"
        assert tally["dissent"][0]["author"] == "Agen A"

    def test_suara_untuk_id_tak_known_diabaikan(self):
        tally = apply_votes(self._proposals(), [("Agen C", True, "p99-aneh")])
        assert tally["total_voters"] == 0
        assert tally["winner"] is None

    def test_tanpa_suara_tanpa_pemenang(self):
        tally = apply_votes(self._proposals(), [])
        assert tally["winner"] is None
        assert tally["agreement"] == 0.0


class TestContextDigest:
    def test_digest_terbatas_karakter(self):
        turns = [
            Turn(1, f"Agen {i}", "R", "x" * 500, "y" * 500, 0.5, [], "raw")
            for i in range(30)
        ]
        digest = build_context_digest(turns, max_chars=1000)
        assert len(digest) <= 1100
        assert "riwayat awal dipangkas" in digest

    def test_digest_kosong(self):
        assert "Alpha Lead" in build_context_digest([])
