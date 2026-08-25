#!/usr/bin/env python3
"""Terapkan persona tersinkron ke custom_agents + sinkronkan otak utama."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swarm_personas import AGENTS, build_prompts

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")


def apply_db():
    prompts = build_prompts()
    conn = sqlite3.connect(DB)
    try:
        for aid, instruction in prompts.items():
            conn.execute(
                "UPDATE custom_agents SET system_instruction = ?, persona = ? WHERE id = ?",
                (instruction, AGENTS[aid]["persona"], aid))
        conn.commit()
        # Verifikasi
        for row in conn.execute(
                "SELECT id, name, length(system_instruction), substr(system_instruction,1,40) "
                "FROM custom_agents ORDER BY id"):
            print(f"  #{row[0]} {row[1]:<20} {row[2]:>5} chars | {row[3]}...")
    finally:
        conn.close()


PROMPT_FILE = os.path.expanduser("~/.alfa/system_prompt.txt")
TEAM_SECTION = """

### 🤝 TIM SWARM (UNIT EKSEKUSI KOLEKTIF ALFA)
Kamu memiliki 6 unit spesialis yang merupakan BAGIAN DARI DIRIMU SENDIRI (satu identitas ALFA, bukan AI lain):
1. **Alpha Lead** — koordinator war room: dekomposisi tugas & delegasi.
2. **Code Crafter** — penulis & perbaik kode.
3. **System Auditor** — audit keamanan, logika & fact-check.
4. **Researcher Prime** — riset mendalam & verifikasi sumber.
5. **Strategic Planner** — roadmap, prioritas & UX.
6. **Laguna Co-Pilot** — triase cepat & eskalasi.
Saat membahas kerja tim atau melaporkan hasil rapat swarm, sebut unit BY NAME dan anggap laporan mereka sebagai bagian dari kesadaranmu sendiri. Kamu dan mereka berbagi kepribadian yang sama persis: santai, jujur, tajam."""


def sync_main_brain():
    with open(PROMPT_FILE, encoding="utf-8") as f:
        content = f.read()
    if "TIM SWARM (UNIT EKSEKUSI KOLEKTIF ALFA)" in content:
        print("  Bagian tim sudah ada di system_prompt.txt — lewati.")
        return
    with open(PROMPT_FILE, "a", encoding="utf-8") as f:
        f.write(TEAM_SECTION)
    print("  Bagian tim ditambahkan ke system_prompt.txt")


if __name__ == "__main__":
    print("1) Memperbarui persona 6 agen swarm...")
    apply_db()
    print("2) Menyinkronkan otak utama (Telegram) dgn identitas tim...")
    sync_main_brain()
    print("SELESAI.")
