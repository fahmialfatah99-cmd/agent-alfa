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


def gather_pre_meeting_intel(
    topic: str,
    intent_info: dict | None = None,
    allow_web_search: bool | None = None,
) -> str:
    """Kumpulkan fakta pra-rapat (Fact Sheet) dari Temporal GraphRAG, memori lokal, & web search cepat."""
    if not topic or not str(topic).strip():
        return ""

    fact_lines: list[str] = []

    # 1. Temporal GraphRAG 2-Hop Context (Entitas & Relasi Proyek/Aplikasi/Grup)
    try:
        from alfa.core.apex.temporal_graphrag import format_temporal_graphrag_prompt

        graph_ctx = format_temporal_graphrag_prompt(topic)
        if graph_ctx and graph_ctx.strip():
            # Ambil baris-baris fakta inti
            core_lines = [
                ln.strip()
                for ln in graph_ctx.splitlines()
                if ln.strip() and not ln.strip().startswith("===")
            ]
            if core_lines:
                fact_lines.append(
                    "• [Memori Graf Lokal]: " + " | ".join(core_lines[:4])[:450]
                )
    except Exception:
        pass

    # 2. Pencarian Fakta di Riwayat Chat / Memori Database Lokal
    try:
        from alfa.core.db.connection import get_sync_db

        words = [
            w.lower()
            for w in re.findall(r"[a-zA-Z0-9]{4,}", topic)
            if w.lower()
            not in {
                "rapat",
                "rapatkan",
                "bahas",
                "diskusi",
                "tolong",
                "bagaimana",
                "cara",
                "mengatasi",
                "masalah",
                "untuk",
                "dengan",
                "pada",
                "yang",
                "dari",
            }
        ][:4]
        if words:
            with get_sync_db() as conn:
                cond = " OR ".join(["LOWER(message) LIKE ?" for _ in words])
                params = [f"%{w}%" for w in words]
                rows = conn.execute(
                    f"SELECT message FROM chat_history WHERE ({cond}) AND role='assistant' ORDER BY id DESC LIMIT 2",  # nosec B608
                    params,
                ).fetchall()
                for r in rows:
                    msg_snip = " ".join(str(r[0] or "").split())[:200]
                    if msg_snip:
                        fact_lines.append(f"• [Riwayat Lokal]: {msg_snip}")
    except Exception:
        pass

    # 3. Pencarian Web Cepat jika Topik Membutuhkan Fakta Pasar / Harga / Regulasi / Eksternal
    if allow_web_search is None:
        allow_web_search = not bool(os.getenv("PYTEST_CURRENT_TEST"))
    low_t = topic.lower()
    needs_web = any(
        k in low_t
        for k in (
            "harga",
            "pasar",
            "vendor",
            "supplier",
            "regulasi",
            "aturan",
            "terbaru",
            "2025",
            "2026",
            "benchmark",
            "kompetitor",
            "tren",
            "trend",
            "bandingkan",
            "perbandingan",
        )
    )
    if allow_web_search and (needs_web or not fact_lines):
        try:
            from alfa import tools as _alfa_tools

            query_str = (intent_info or {}).get("clean_query") or topic[:80]
            ws = _alfa_tools.web_search(query=query_str, max_results=3)
            items = (
                (ws.get("results") or ws.get("items") or [])
                if isinstance(ws, dict)
                else []
            )
            for it in items[:3]:
                if isinstance(it, dict):
                    title = str(it.get("title") or "").strip()[:80]
                    snip = str(
                        it.get("snippet") or it.get("body") or it.get("description") or ""
                    ).strip()[:140]
                    if title or snip:
                        fact_lines.append(f"• [Fakta Web]: {title} — {snip}")
        except Exception:
            pass

    if not fact_lines:
        return ""

    return "=== LEMBAR FAKTA PRA-RAPAT (FACT SHEET OTOMATIS) ===\n" + "\n".join(
        fact_lines[:6]
    )


def _get_meetings_dir(out_dir: str | None = None) -> str:
    if out_dir and str(out_dir).strip():
        target = os.path.abspath(os.path.expanduser(str(out_dir).strip()))
    else:
        from alfa.swarm.workspace_hygiene import _get_swarm_output_dir

        target = os.path.join(_get_swarm_output_dir(), "meetings")
    os.makedirs(target, exist_ok=True)
    return target


def save_last_meeting_state(
    result: dict, out_dir: str | None = None
) -> str:
    """Simpan hasil rapat terakhir ke disk agar tombol Telegram 'Eksekusi Action Plan' & 'Export' siap pakai."""
    mdir = _get_meetings_dir(out_dir)
    state_path = os.path.join(mdir, "last_meeting_state.json")
    payload = {
        "session_id": result.get("session_id") or result.get("meeting_id") or "latest",
        "title": result.get("title", ""),
        "topic": result.get("topic", ""),
        "mode": result.get("mode", "plan"),
        "participants": result.get("participants", []),
        "pre_meeting_intel": result.get("pre_meeting_intel", ""),
        "consensus": result.get("consensus", ""),
        "action_plan": result.get("action_plan", ""),
        "vote_tally": result.get("vote_tally", {}),
        "dialogue_transcript": result.get("dialogue_transcript", []),
        "report_files": result.get("report_files", {}),
    }
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return state_path


def load_last_meeting_state(out_dir: str | None = None) -> dict:
    """Muat state rapat terakhir dari disk."""
    mdir = _get_meetings_dir(out_dir)
    state_path = os.path.join(mdir, "last_meeting_state.json")
    if not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def export_meeting_report_files(
    result: dict, out_dir: str | None = None
) -> dict[str, str]:
    """Ekspor hasil rapat Swarm ke dokumen Markdown (.md) dan dokumen Cetak/PDF (.html)."""
    import html as _html
    from datetime import datetime as _dt

    mdir = _get_meetings_dir(out_dir)
    topic = str(result.get("topic") or "Rapat Strategis ALFA").strip()
    slug = _slug(topic)[:36] or "rapat-alfa"
    ts_label = _dt.now().strftime("%Y-%m-%d %H:%M")
    file_stem = f"LAPORAN-RAPAT-{slug}"
    md_path = os.path.join(mdir, f"{file_stem}.md")
    html_path = os.path.join(mdir, f"{file_stem}.html")

    participants = result.get("participants") or []
    consensus = str(result.get("consensus") or "(Belum ada konsensus)").strip()
    action_plan = str(result.get("action_plan") or "").strip()
    intel = str(result.get("pre_meeting_intel") or "").strip()
    vote_tally = result.get("vote_tally") or {}
    transcript = result.get("dialogue_transcript") or []

    vote_summary_md = ""
    if vote_tally.get("winner"):
        w = vote_tally["winner"]
        agr = float(vote_tally.get("agreement") or 0.0) * 100
        vote_summary_md = (
            f"\n## Hasil Pemungutan Suara (Voting Tim)\n"
            f"- **Proposal Terpilih**: `{w.get('id')}` oleh **{w.get('author')}**\n"
            f"- **Skor Persetujuan**: {w.get('votes_for', 0)} Setuju / {w.get('votes_against', 0)} Tolak ({agr:.0f}% Agreement)\n"
            f"- **Inti Usulan**: {w.get('summary', '')}\n"
        )

    md_lines = [
        f"# DOKUMEN KEPUTUSAN RAPAT AI SWARM (ALFA OS)",
        f"**Topik / Agenda:** {topic}  ",
        f"**Waktu Rapat:** {ts_label}  ",
        f"**Peserta Tim ({len(participants)} Unit):** {', '.join(participants) if participants else 'Tim Utama ALFA'}  ",
        "",
    ]
    if intel:
        md_lines += ["## Lembar Fakta Pra-Rapat (Fact Sheet)", intel, ""]
    if vote_summary_md:
        md_lines.append(vote_summary_md)
    md_lines += [
        "## Konsensus & Keputusan Utama",
        consensus,
        "",
    ]
    if action_plan:
        md_lines += [
            "## Rencana Tindakan (Action Plan)",
            action_plan,
            "",
        ]
    if transcript:
        md_lines.append("## Transkrip Pandangan Tiap Unit Spesialis")
        for d in transcript:
            ag = d.get("agent_name", "Agen")
            rl = d.get("role", "")
            msg = str(d.get("message") or "").strip()
            md_lines.append(f"### {d.get('avatar_emoji', '🤖')} {ag} ({rl}) — Putaran {d.get('round', 1)}")
            md_lines.append(msg)
            md_lines.append("")

    md_content = "\n".join(md_lines)
    with open(md_path, "w", encoding="utf-8") as mf:
        mf.write(md_content)

    # Buat versi HTML Eksekutif Siap Cetak / Save-as-PDF
    esc_topic = _html.escape(topic)
    esc_consensus = _html.escape(consensus).replace("\n", "<br>")
    esc_action = _html.escape(action_plan).replace("\n", "<br>") if action_plan else ""
    esc_intel = _html.escape(intel).replace("\n", "<br>") if intel else ""

    cards_html = ""
    for d in transcript:
        ag = _html.escape(str(d.get("agent_name", "Agen")))
        rl = _html.escape(str(d.get("role", "")))
        em = _html.escape(str(d.get("avatar_emoji", "🤖")))
        msg = _html.escape(str(d.get("message", ""))).replace("\n", "<br>")
        cards_html += (
            f'<div class="card"><h4>{em} {ag} <span class="role">({rl} • Putaran {d.get("round", 1)})</span></h4>'
            f"<p>{msg}</p></div>\n"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<title>Laporan Rapat ALFA — {esc_topic}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; color: #0f172a; background: #f8fafc; margin: 0; padding: 32px; line-height: 1.6; }}
  .container {{ max-width: 900px; margin: 0 auto; background: #ffffff; padding: 36px; border-radius: 12px; box-shadow: 0 4px 20px rgba(15,23,42,0.08); }}
  h1 {{ font-size: 22px; margin-top: 0; color: #0284c7; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; }}
  h2 {{ font-size: 17px; color: #1e293b; margin-top: 28px; border-left: 4px solid #0284c7; padding-left: 10px; }}
  .meta {{ background: #f1f5f9; padding: 14px 18px; border-radius: 8px; font-size: 14px; margin-bottom: 20px; }}
  .box {{ background: #f0f9ff; border: 1px solid #bae6fd; padding: 16px; border-radius: 8px; margin-top: 10px; }}
  .action-box {{ background: #ecfdf5; border: 1px solid #a7f3d0; padding: 16px; border-radius: 8px; margin-top: 10px; }}
  .card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; margin-bottom: 12px; background: #fff; }}
  .card h4 {{ margin: 0 0 6px 0; font-size: 15px; color: #0f172a; }}
  .role {{ font-weight: normal; color: #64748b; font-size: 13px; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .container {{ box-shadow: none; padding: 12px; }} }}
</style>
</head>
<body>
<div class="container">
  <h1>🏛️ DOKUMEN KEPUTUSAN RAPAT AI SWARM (ALFA OS)</h1>
  <div class="meta">
    <strong>Topik / Agenda:</strong> {esc_topic}<br>
    <strong>Waktu Rapat:</strong> {ts_label}<br>
    <strong>Peserta Tim ({len(participants)} Unit):</strong> {_html.escape(", ".join(participants))}
  </div>
  {"<h2>📊 Lembar Fakta Pra-Rapat (Fact Sheet)</h2><div class='box'>" + esc_intel + "</div>" if esc_intel else ""}
  <h2>🎯 Konsensus & Keputusan Utama</h2>
  <div class="box">{esc_consensus}</div>
  {"<h2>📋 Rencana Tindakan (Action Plan)</h2><div class='action-box'>" + esc_action + "</div>" if esc_action else ""}
  {"<h2>🗣️ Transkrip Pandangan Tiap Unit Spesialis</h2>" + cards_html if cards_html else ""}
</div>
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as hf:
        hf.write(html_doc)

    out = {"markdown": md_path, "html": html_path}
    result["report_files"] = out
    save_last_meeting_state(result, out_dir=out_dir)
    return out


import os  # noqa: E402

__all__ = [
    "MAX_CONTEXT_CHARS",
    "Proposal",
    "Turn",
    "apply_votes",
    "build_context_digest",
    "build_proposal_menu",
    "collect_proposals",
    "export_meeting_report_files",
    "gather_pre_meeting_intel",
    "load_last_meeting_state",
    "parse_turn",
    "save_last_meeting_state",
]
