"""
Autonomous Subagent Swarm Engine for Telegram AI Bot.
Allows spawning background AI workers that run complex multi-step reasoning, research,
coding, or analysis independently without blocking the user Telegram chat session.
"""

import asyncio
import os
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import database

logger = logging.getLogger("SubagentSwarm")

_global_telegram_app = None
_global_telegram_loop = None


def set_telegram_app(app):
    """Set global Telegram application instance for background notification delivery."""
    global _global_telegram_app, _global_telegram_loop
    _global_telegram_app = app
    try:
        _global_telegram_loop = asyncio.get_running_loop()
    except RuntimeError:
        _global_telegram_loop = None


def get_telegram_app():
    return _global_telegram_app


def get_telegram_loop():
    return _global_telegram_loop


async def _run_subagent_worker(task_id: str, user_id: int, chat_id: int, role: str, task_description: str):
    """
    Background worker loop for an autonomous subagent.
    Runs an independent ReAct agent turn with specialized role instructions.
    """
    logger.info(f"Subagent worker [{task_id}] started for user {user_id}. Role: {role}")
    
    from bot import run_agent_turn, safe_send_message
    
    subagent_prompt = (
        f"[SUBAGENT TASK: {role.upper()}]\n"
        f"Anda adalah Subagent Mandiri ({role}) yang ditugaskan untuk menyelesaikan tugas berikut secara tuntas.\n"
        f"Gunakan semua tools yang relevan (web search, browser, terminal, file, python, analisis data) secara mandiri.\n\n"
        f"TUGAS:\n{task_description}\n\n"
        f"Sajikan hasil akhir secara lengkap, terstruktur, mendalam, dan siap digunakan oleh pengguna."
    )
    
    try:
        result = await run_agent_turn(user_id=user_id, user_prompt=subagent_prompt, chat_id=chat_id)
        database.update_subagent_task_sync(task_id=task_id, status="completed", result=result)
        logger.info(f"Subagent [{task_id}] completed successfully.")
        
        app = get_telegram_app()
        if app and chat_id:
            completion_msg = (
                f"🤖 **[LAPORAN SUBAGENT: {role.upper()}]**\n"
                f"📌 *Tugas ID:* `{task_id}`\n\n"
                f"{result}"
            )
            await safe_send_message(app, chat_id, completion_msg)
            
            from tools import SANDBOX_DIR, is_internal_sandbox_artifact, is_source_code_file
            if os.path.exists(SANDBOX_DIR):
                for fname in os.listdir(SANDBOX_DIR):
                    fpath = os.path.join(SANDBOX_DIR, fname)
                    if is_internal_sandbox_artifact(fname):
                        continue
                    if is_source_code_file(fname):
                        continue
                    if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                        try:
                            ext = os.path.splitext(fname)[1].lower()
                            if ext in ['.png', '.jpg', '.jpeg']:
                                with open(fpath, "rb") as pf:
                                    await app.bot.send_photo(chat_id=chat_id, photo=pf, caption=f"📸 Lampiran Subagent: {fname}")
                            elif ext in ['.pdf', '.xlsx', '.pptx', '.zip', '.csv', '.json', '.txt']:
                                with open(fpath, "rb") as df:
                                    await app.bot.send_document(chat_id=chat_id, document=df, caption=f"📄 Dokumen Subagent: {fname}")
                            os.remove(fpath)
                        except Exception as err:
                            logger.error(f"Error dispatching subagent media {fname}: {err}")
    except Exception as e:
        logger.error(f"Subagent [{task_id}] encountered error: {e}", exc_info=True)
        database.update_subagent_task_sync(task_id=task_id, status="failed", result=str(e))
        
        app = get_telegram_app()
        if app and chat_id:
            error_msg = f"⚠️ **Subagent [{role}] Gagal Menyelesaikan Tugas:**\n`{str(e)}`"
            await safe_send_message(app, chat_id, error_msg)


def spawn_subagent(user_id: int, chat_id: int, role: str, task_description: str) -> Dict[str, Any]:
    """Spawn a new background autonomous subagent."""
    task_id = f"sub_{uuid.uuid4().hex[:8]}"
    database.save_subagent_task_sync(
        task_id=task_id,
        user_id=user_id,
        chat_id=chat_id,
        role=role,
        description=task_description
    )
    
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run_subagent_worker(task_id, user_id, chat_id, role, task_description))
    except RuntimeError:
        pass
        
    return {
        "status": "success",
        "task_id": task_id,
        "role": role,
        "message": f"Subagent [{role}] dengan ID '{task_id}' telah diluncurkan di latar belakang. Anda akan menerima notifikasi laporan begitu selesai."
    }
