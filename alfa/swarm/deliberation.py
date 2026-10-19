"""Deliberasi swarm terstruktur: proposal, pemungutan suara, dan hitungan real.

Sebelum ini, "diskusi" swarm hanyalah prompt-chain sekuensial: setiap agen
meneruskan seluruh teks sebelumnya ke prompt berikutnya, lalu satu panggilan
LLM terakhir oleh kapten menulis "konsensus". Tidak ada proposal, tidak ada
suara, dan persentase konsensus di UI hanyalah heuristik atas string tahap.

Modul ini memberi lapisan deliberasi yang bisa diukur:

* **Proposal** — setiap agen，提出 posisi + bukti + tingkat keyakinan.
* **Pemungutan suara** — sejak putaran ke-2, tiap agen memberi suara
  (SETUJU / TOLAK) atas proposal yang sudah ada, dengan alasan.
* **Tally** — dihitung mekanis dari suara terkumpul, bukan dari tebakan LLM.
* **Dissent** — agen yang menolak tetap tercatat dan dilaporkan.

Konteks yang dikirim ke agen dipangkas ke batas karakter agar tidak tumbuh
O(putaran × agen × panjang) seperti sebelumnya.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

#: Batas karakter konteks per giliran agar prompt tidak membengkak.
MAX_CONTEXT_CHARS = 4000

#: Batas jumlah proposal yang bisa dipilih (dipakai di prompt pemungutan).
MAX_PROPOSALS_IN_PROMPT = 8

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Proposal:
    """Satu usulan solusi dari seorang agen."""

    id: str
    author: str
    round: int
    summary: str
    evidence: str = ""
    confidence: float = 0.5
    votes_for: int = 0
    votes_against: int = 0

    @property
    def score(self) -> int:
        return self.votes_for - self.votes_against


@dataclass
class Turn:
    """Satu giliran agen: posisi + bukti + suara."""

    round: int
    agent: str
    role: str
    position: str = ""
    evidence: str = ""
    confidence: float = 0.5
    votes: list[tuple[str, bool]] = field(default_factory=list)
    raw: str = ""

    @property
    def proposal_id(self) -> str:
        return f"p{self.round}-{_slug(self.agent)}"


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return out or "agen"


def _coerce_float(value: object, default: float = 0.5) -> float:
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, num))


def parse_turn(raw: str) -> dict:
    """Parse structured turn dari output agen.

    Agen diminta menjawab JSON; kalau tidak (provider bermasalah / model
    tidak patuh), teks polos dipakai apa adanya sebagai posisi.
    """
    text = str(raw or "").strip()
    if not text:
        return {
            "position": "",
            "evidence": "",
            "confidence": 0.5,
            "votes": [],
            "parsed": False,
        }
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            votes: list[tuple[str, bool]] = []
            raw_votes = data.get("votes")
            if isinstance(raw_votes, list):
                for v in raw_votes:
                    if not isinstance(v, dict):
                        continue
                    ref = str(v.get("id") or v.get("proposal") or "").strip()
                    if not ref:
                        continue
                    approve = v.get("approve")
                    if approve is None:
                        approve = v.get("setuju")
                    if isinstance(approve, str):
                        approve = approve.strip().lower() in (
                            "setuju",
                            "ya",
                            "true",
                            "1",
                            "approve",
                            "yes",
                        )
                    votes.append((ref, bool(approve)))
            return {
                "position": str(data.get("position") or data.get("posisi") or "").strip(),
                "evidence": str(data.get("evidence") or data.get("bukti") or "").strip(),
                "confidence": _coerce_float(data.get("confidence")),
                "votes": votes,
                "parsed": True,
            }
    return {
        "position": text[:600],
        "evidence": "",
        "confidence": 0.5,
        "votes": [],
        "parsed": False,
    }


def collect_proposals(turns: list[Turn]) -> list[Proposal]:
    """Kumpulkan proposal unik — posisi terakhir tiap agen (putaran terbaru)."""
    latest: dict[str, Turn] = {}
    for t in turns:
        if not t.position:
            continue
        latest[t.agent] = t
    proposals: list[Proposal] = []
    for agent, t in latest.items():
        proposals.append(
            Proposal(
                id=t.proposal_id,
                author=agent,
                round=t.round,
                summary=t.position[:400],
                evidence=t.evidence[:400],
                confidence=t.confidence,
            )
        )
    return proposals


def apply_votes(
    proposals: list[Proposal], votes: list[tuple[str, bool, str]]
) -> dict:
    """Terapkan suara ke proposal dan hitung hasilnya.

    ``votes`` = list of (voter, approve, proposal_id).
    Return dict rekap: total pemili, daftar proposal, pemenang, dissent.
    """
    by_id = {p.id: p for p in proposals}
    dissent: list[dict] = []
    counted = 0
    for voter, approve, pid in votes:
        prop = by_id.get(pid)
        if prop is None:
            continue
        counted += 1
        if approve:
            prop.votes_for += 1
        else:
            prop.votes_against += 1
            dissent.append(
                {
                    "voter": voter,
                    "proposal_id": pid,
                    "author": prop.author,
                }
            )
    winner = None
    if proposals:
        best = sorted(
            proposals, key=lambda p: (-p.score, -p.votes_for, p.id)
        )[0]
        if best.votes_for > 0 or best.votes_against > 0:
            winner = {
                "id": best.id,
                "author": best.author,
                "summary": best.summary,
                "votes_for": best.votes_for,
                "votes_against": best.votes_against,
                "confidence": best.confidence,
            }
    total_possible = max(1, counted)
    agreement: float = 0.0
    if winner:
        votes_for = winner.get("votes_for")
        agreement = float(votes_for if isinstance(votes_for, int) else 0) / float(
            total_possible
        )
    return {
        "total_voters": counted,
        "total_proposals": len(proposals),
        "winner": winner,
        "dissent": dissent,
        "agreement": round(agreement, 4),
        "proposals": [
            {
                "id": p.id,
                "author": p.author,
                "round": p.round,
                "summary": p.summary,
                "votes_for": p.votes_for,
                "votes_against": p.votes_against,
                "score": p.score,
                "confidence": p.confidence,
            }
            for p in proposals
        ],
    }


def build_proposal_menu(proposals: list[Proposal]) -> str:
    """Daftar proposal bernomor untuk dilampirkan ke prompt pemungutan suara."""
    if not proposals:
        return "(Belum ada proposal dari putaran sebelumnya.)"
    lines = []
    for p in proposals[:MAX_PROPOSALS_IN_PROMPT]:
        lines.append(
            f"- id={p.id} | oleh {p.author} | keyakinan {p.confidence:.2f} | {p.summary}"
        )
    return "\n".join(lines)


def build_context_digest(turns: list[Turn], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Ringkasan obrolan untuk prompt — dipangkas ke batas karakter.

    Versi lama mengirim SELURUH riwayat obrolan setiap giliran, sehingga
    prompt tumbuh O(putaran × agen × panjang) dan lambat/mahal.
    """
    if not turns:
        return "(Sesi baru saja dibuka oleh Alpha Lead)"
    lines = [
        f"[{t.agent} - {t.role}] posisi: {t.position[:220]}"
        + (f" | bukti: {t.evidence[:160]}" if t.evidence else "")
        for t in turns
    ]
    out = "\n".join(lines)
    if len(out) > max_chars:
        # Pertahankan giliran paling akhir (konteks terbaru paling relevan).
        out = "... (riwayat awal dipangkas) ...\n" + out[-max_chars:]
    return out


__all__ = [
    "MAX_CONTEXT_CHARS",
    "Proposal",
    "Turn",
    "apply_votes",
    "build_context_digest",
    "build_proposal_menu",
    "collect_proposals",
    "parse_turn",
]
