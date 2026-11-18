"""Dashboard API for Devin-style git worktree sandboxes (coding mode).

Endpoint bersifat admin-only dan memakai headless permission gate yang sama
dengan tool explorer: ``git_worktree_sandbox_create/merge/rollback`` tetap
HIGH sehingga hanya berjalan bila operator sudah memberi allowlist/trust.
Tidak ada auto-merge; semua aksi eksplisit dari pengguna.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from alfa.dashboard.common import get_primary_user_id, logger
from alfa.dashboard.routes.auth import require_admin

coding_router = APIRouter(
    prefix="/api/coding",
    tags=["coding"],
    dependencies=[Depends(require_admin)],
)


def _check_gate(tool_name: str, args: dict[str, Any]) -> None:
    from alfa.core.perm import gate as permission_gate

    uid = get_primary_user_id()
    denial = permission_gate.check_headless_approval(
        uid, tool_name, json.dumps(args, ensure_ascii=False, default=str)
    )
    if denial:
        raise HTTPException(status_code=403, detail=denial)


@coding_router.get("/worktrees")
async def list_coding_worktrees(request: Request):
    """Daftar worktree sandbox yang aktif (read-only)."""
    _check_gate("git_worktree_sandbox_list", {})
    from alfa.tools.filesystem.git_sandbox import git_worktree_sandbox_list

    result = await asyncio.to_thread(git_worktree_sandbox_list)
    return {"status": "success", "result": result}


@coding_router.post("/worktrees")
async def create_coding_worktree(request: Request, payload: dict[str, Any]):
    """Buat worktree terisolasi untuk tugas coding."""
    task_name = str(payload.get("task_name") or "").strip()
    if not task_name:
        raise HTTPException(status_code=400, detail="task_name wajib diisi")
    base_branch = str(payload.get("base_branch") or "master").strip()
    args = {"task_name": task_name, "base_branch": base_branch}
    _check_gate("git_worktree_sandbox_create", args)

    from alfa.tools.filesystem.git_sandbox import git_worktree_sandbox_create

    result = await asyncio.to_thread(
        git_worktree_sandbox_create, task_name, base_branch
    )
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "gagal"))
    logger.info("[Coding] worktree dibuat: %s", result.get("task_name"))
    return {"status": "success", "result": result}


@coding_router.post("/worktrees/{task_name}/merge")
async def merge_coding_worktree(
    task_name: str, request: Request, payload: dict[str, Any] | None = None
):
    """Verifikasi (opsional jalankan test) lalu merge worktree secara eksplisit."""
    body = payload or {}
    commit_message = str(
        body.get("commit_message") or "feat: auto-verified sandbox changes"
    )
    run_tests_cmd = str(body.get("run_tests_cmd") or "")
    target_branch = str(body.get("target_branch") or "master")
    args = {
        "task_name": task_name,
        "commit_message": commit_message,
        "run_tests_cmd": run_tests_cmd,
        "target_branch": target_branch,
    }
    _check_gate("git_worktree_sandbox_verify_and_merge", args)

    from alfa.tools.filesystem.git_sandbox import (
        git_worktree_sandbox_verify_and_merge,
    )

    result = await asyncio.to_thread(
        git_worktree_sandbox_verify_and_merge,
        task_name,
        commit_message,
        run_tests_cmd,
        target_branch,
    )
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "gagal"))
    return {"status": "success", "result": result}


@coding_router.post("/worktrees/{task_name}/rollback")
async def rollback_coding_worktree(task_name: str, request: Request):
    """Musnahkan worktree + branch sandbox tanpa menyentuh branch utama."""
    _check_gate("git_worktree_sandbox_rollback", {"task_name": task_name})
    from alfa.tools.filesystem.git_sandbox import git_worktree_sandbox_rollback

    result = await asyncio.to_thread(git_worktree_sandbox_rollback, task_name)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "gagal"))
    return {"status": "success", "result": result}


__all__ = ["coding_router"]
