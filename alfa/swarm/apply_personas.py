#!/usr/bin/env python3
"""Terapkan Dual-Persona tersinkron ke custom_agents + sinkronkan otak utama."""

import logging
import os
import sqlite3

from alfa.swarm.personas import AGENTS, build_prompts

logger = logging.getLogger(__name__)

DB = os.getenv(
    "ALFA_DB_PATH",
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "agent_data.db")
    ),
)


def apply_db(db_path: str | None = None) -> int:
    """Sinkronkan role, persona, dan system_instruction Dual-Persona ke tabel custom_agents."""
    target_db = db_path or DB
    prompts = build_prompts()
    updated = 0
    conn = sqlite3.connect(target_db)
    try:
        for aid, instruction in prompts.items():
            role = AGENTS[aid].get("role", "")
            persona = AGENTS[aid].get("persona", "")
            if role:
                cur = conn.execute(
                    "UPDATE custom_agents SET role = ?, persona = ?, system_instruction = ? WHERE id = ?",
                    (role, persona, instruction, aid),
                )
            else:
                cur = conn.execute(
                    "UPDATE custom_agents SET persona = ?, system_instruction = ? WHERE id = ?",
                    (persona, instruction, aid),
                )
            updated += cur.rowcount
        conn.commit()
        for row in conn.execute(
            "SELECT id, name, role, length(system_instruction) "
            "FROM custom_agents ORDER BY id"
        ):
            logger.info(
                f"  #{row[0]} {row[1]:<18} | {row[2]:<48} | {row[3]:>5} chars"
            )
    finally:
        conn.close()
    return updated


PROMPT_FILE = os.path.expanduser("~/.alfa/system_prompt.txt")
TEAM_SECTION = """

### 🤝 TIM SWARM DUAL-PERSONA (UNIT EKSEKUSI & DEWAN PENASIHAT KOLEKTIF ALFA)
Kamu memiliki 7 unit spesialis yang merupakan BAGIAN DARI DIRIMU SENDIRI (satu identitas ALFA, bukan AI lain). Setiap unit memiliki **Dual-Persona** (bisa bekerja sebagai Tim Engineering/Coding maupun Dewan Penasihat Masalah Umum/Bisnis/Operasional):
1. **Alpha Lead** — Chief Orchestrator & Moderator Eksekutif War Room.
2. **Code Crafter** — Principal Software Engineer (Mode Coding) & Analis Efisiensi Sistem/Operasional (Mode Umum).
3. **System Auditor** — Security/QA Critic (Mode Coding) & Analis Risiko / Devil's Advocate (Mode Umum).
4. **Researcher Prime** — Deep Intel, Riset Pasar, Harga, Regulasi & Fact-Checking.
5. **Strategic Planner** — Konsultan Strategi Bisnis/Operasional (Mode Umum) & Product/UX Strategist (Mode Coding).
6. **Laguna Co-Pilot** — Rapid Triage, Solusi Taktis Cepat & Penanganan Krisis.
7. **AlphaBot** — Analis Data Kuantitatif, Estimasi Biaya & Riset Teknis.
Saat membahas kerja tim atau melaporkan hasil rapat swarm, sebut unit BY NAME dan anggap laporan mereka sebagai bagian dari kesadaranmu sendiri. Untuk masalah umum/strategis, tim fokus membedah solusi & merangkum keputusan (bukan membuat website/kode yang tidak diminta)."""


def sync_main_brain():
    if not os.path.exists(PROMPT_FILE):
        return
    with open(PROMPT_FILE, encoding="utf-8") as f:
        content = f.read()
    if "TIM SWARM DUAL-PERSONA" in content:
        logger.info("  Bagian tim Dual-Persona sudah ada di system_prompt.txt — lewati.")
        return
    # Jika ada seksi lama, gantikan dengan seksi Dual-Persona terbaru
    if "### 🤝 TIM SWARM (UNIT EKSEKUSI KOLEKTIF ALFA)" in content:
        idx = content.index("### 🤝 TIM SWARM (UNIT EKSEKUSI KOLEKTIF ALFA)")
        content = content[:idx].rstrip() + "\n" + TEAM_SECTION
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("  Bagian tim di system_prompt.txt diperbarui ke Dual-Persona.")
        return
    with open(PROMPT_FILE, "a", encoding="utf-8") as f:
        f.write(TEAM_SECTION)
    logger.info("  Bagian tim Dual-Persona ditambahkan ke system_prompt.txt")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("1) Memperbarui Dual-Persona seluruh agen swarm di DB...")
    apply_db()
    logger.info("2) Menyinkronkan otak utama (Telegram) dgn identitas Dual-Persona...")
    sync_main_brain()
    logger.info("SELESAI.")
