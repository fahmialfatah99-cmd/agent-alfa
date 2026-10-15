"""Meeting execution-step helpers extracted from the swarm orchestrator."""

import logging
import os
from typing import Any

from alfa.swarm import workspace_hygiene
from alfa.swarm.live_logger import log_live
from alfa.swarm.step_executor import _verify_step_result, execute_swarm_task_step
from alfa.swarm.workspace_hygiene import _cancel_requested

logger = logging.getLogger(__name__)


def _build_task_desc(
    agent: dict[str, Any],
    err_ctx: str,
    *,
    subtask_map: dict[str, Any],
    topic: str,
    ctx_lines: list[str],
) -> str:
    agent_info = subtask_map.get(agent["name"])
    if isinstance(agent_info, dict):
        task_str = agent_info.get("task", "")
    else:
        task_str = agent_info

    td = (
        task_str
        or f"Eksekusi modul {agent['role']} untuk '{topic[:60]}'"
    )
    if err_ctx:
        td += f"\n\n{err_ctx}"
    target_fol = workspace_hygiene._get_target_folder()
    if target_fol:
        td += (
            f"\n\nFOLDER KERJA WAJIB: {target_fol}\n"
            f"SEMUA file yang dibaca/ditulis WAJIB di dalam folder ini. "
            f"Pada execute_bash_command: sertakan working_dir='{target_fol}' "
            f"dan gunakan PATH RELATIF (folder ter-mount sebagai /workspace). "
            f"Untuk mengubah isi file, PAKAI edit_file_precise/write_local_file "
            f"dengan path lengkap '{target_fol}/<nama>'. "
            f"DILARANG membuat proyek di lokasi lain."
        )
    if ctx_lines:
        td += (
            "\n\nKONTEKS HASIL AGEN GELOMBANG SEBELUMNYA (gunakan bila relevan):\n- "
            + "\n- ".join(ctx_lines[-3:])
        )
    td += (
        "\n\nDELIVERABLE WAJIB (tanpa kecuali): akhiri dengan MINIMAL 1 file nyata "
        "di folder kerja. Tugas riset/audit/kajian → tulis LAPORAN-<TOPIK-SINGKAT>.md "
        "(temuan + bukti + sumber). Tugas tanpa file baru = GAGAL otomatis oleh verifikator."
    )
    return td


async def _execute_agent_step(
    agent: dict[str, Any],
    task_desc: str,
    *,
    topic: str,
    intent_info: dict[str, Any],
):
    log_live("EXEC", f"⚙️ {agent['name']} mulai eksekusi: {task_desc[:90]}")
    step_result = await execute_swarm_task_step(agent, task_desc, topic, intent_info)
    if step_result.get("deliverable_file"):
        log_live(
            "FILE",
            f"📁 {agent['name']} menghasilkan berkas: {os.path.basename(step_result['deliverable_file'])}",
        )

    passed, feedback = await _verify_step_result(task_desc, step_result)
    attempts = 0
    while (
        not passed
        and attempts < 1
        and step_result.get("tool_used") != "strategic_orchestration"
        and not _cancel_requested()
    ):
        attempts += 1
        logger.warning(
            f"Step '{agent['name']}' FAILED verification: {feedback} - retrying with corrections..."
        )
        retry_desc = (
            f"{task_desc}\n"
            f"PERCOBAAN SEBELUMNYA DITOLAK VERIFIKATOR: {feedback}\n"
            f"Kerjakan ulang dan pastikan menghasilkan bukti nyata (file/data/output)."
        )
        step_result = await execute_swarm_task_step(
            agent, retry_desc, topic, intent_info
        )
        step_result["retry_count"] = attempts
        passed, feedback = await _verify_step_result(retry_desc, step_result)
    return step_result, passed, feedback
