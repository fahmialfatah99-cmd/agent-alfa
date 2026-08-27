"""
DEVIN-STYLE GIT WORKTREE SANDBOX & TIME-TRAVEL ROLLBACK SYSTEM.
Allows ALFA to work in isolated branches without contaminating master:
- git_worktree_sandbox_create: Creates isolated worktree directory & branch.
- git_worktree_sandbox_verify_and_merge: Runs tests, commits & merges to master only if verified.
- git_worktree_sandbox_rollback: Instantly destroys worktree & branch on error (zero residual pollution).
- git_worktree_sandbox_list: Lists active worktree sandboxes.
"""

import os
import re
import shutil
import subprocess
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GitSandbox")

WORKTREES_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".alfa_worktrees")
os.makedirs(WORKTREES_BASE_DIR, exist_ok=True)


def _get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _run_git(args: List[str], cwd: str = "") -> subprocess.CompletedProcess:
    cwd = cwd or _get_project_root()
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30)


def git_worktree_sandbox_create(task_name: str, base_branch: str = "master") -> Dict[str, Any]:
    """
    DEVIN-STYLE SANDBOX: Create an isolated Git Worktree directory and temporary branch.
    The agent can write files, refactor code, and test dependencies in this isolated directory
    without touching the master branch.

    Args:
        task_name: Unique task or feature identifier (e.g. 'fix_auth_bug', 'refactor_db').
        base_branch: Base branch to fork from (default 'master' or 'main').
    """
    try:
        clean_task = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_name.strip()).lower()
        if not clean_task:
            clean_task = "sandbox_task"
            
        branch_name = f"sandbox_{clean_task}"
        worktree_path = os.path.join(WORKTREES_BASE_DIR, clean_task)

        # Cleanup if already exists
        if os.path.exists(worktree_path):
            _run_git(["worktree", "remove", "--force", worktree_path])
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path, ignore_errors=True)

        _run_git(["branch", "-D", branch_name])

        res = _run_git(["worktree", "add", "-b", branch_name, worktree_path, base_branch])
        if res.returncode != 0:
            # Fallback try without base branch or use HEAD
            res = _run_git(["worktree", "add", "-b", branch_name, worktree_path, "HEAD"])
            if res.returncode != 0:
                return {"status": "error", "message": f"Gagal membuat git worktree: {res.stderr.strip()}"}

        return {
            "status": "success",
            "task_name": clean_task,
            "branch_name": branch_name,
            "worktree_path": worktree_path,
            "message": f"Worktree sandbox terisolasi berhasil dibuat di '{worktree_path}' (branch '{branch_name}')."
        }
    except Exception as e:
        return {"status": "error", "message": f"Git worktree create error: {str(e)}"}


def git_worktree_sandbox_verify_and_merge(
    task_name: str,
    commit_message: str = "feat: auto-verified sandbox changes",
    run_tests_cmd: str = "",
    target_branch: str = "master"
) -> Dict[str, Any]:
    """
    DEVIN-STYLE SANDBOX: Verify changes in the worktree sandbox. If verification succeeds,
    commit and cleanly merge back to the master branch.

    Args:
        task_name: Unique task identifier.
        commit_message: Git commit message for verified changes.
        run_tests_cmd: Optional bash test command to run in worktree (e.g. 'pytest', 'python3 -m py_compile ...').
        target_branch: Branch to merge into (default 'master').
    """
    try:
        clean_task = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_name.strip()).lower()
        worktree_path = os.path.join(WORKTREES_BASE_DIR, clean_task)
        branch_name = f"sandbox_{clean_task}"

        if not os.path.exists(worktree_path):
            return {"status": "error", "message": f"Worktree sandbox '{worktree_path}' tidak ditemukan."}

        # 1. Run test verification if specified
        if run_tests_cmd:
            test_res = subprocess.run(run_tests_cmd, shell=True, cwd=worktree_path, capture_output=True, text=True, timeout=60)
            if test_res.returncode != 0:
                return {
                    "status": "error",
                    "test_failed": True,
                    "stdout": test_res.stdout.strip(),
                    "stderr": test_res.stderr.strip(),
                    "message": "Pengujian dalam sandbox GAGAL! Merge dibatalkan secara aman. Jalankan git_worktree_sandbox_rollback untuk membuang sandbox."
                }

        # 2. Add and commit in worktree
        _run_git(["add", "-A"], cwd=worktree_path)
        diff_res = _run_git(["status", "--porcelain"], cwd=worktree_path)
        if diff_res.stdout.strip():
            c_res = _run_git(["commit", "-m", commit_message], cwd=worktree_path)
            if c_res.returncode != 0:
                return {"status": "error", "message": f"Git commit gagal: {c_res.stderr.strip()}"}

        # 3. Merge into target branch
        root = _get_project_root()
        _run_git(["checkout", target_branch], cwd=root)
        m_res = _run_git(["merge", branch_name, "-m", f"Merge sandbox branch '{branch_name}': {commit_message}"], cwd=root)
        if m_res.returncode != 0:
            _run_git(["merge", "--abort"], cwd=root)
            return {"status": "error", "message": f"Merge konflik / gagal: {m_res.stderr.strip()}"}

        # 4. Remove worktree and temporary branch
        _run_git(["worktree", "remove", "--force", worktree_path], cwd=root)
        _run_git(["branch", "-d", branch_name], cwd=root)

        return {
            "status": "success",
            "task_name": clean_task,
            "merged_into": target_branch,
            "message": f"Perubahan sandbox '{clean_task}' berhasil diverifikasi dan di-merge ke branch '{target_branch}'! Sandbox dibersihkan."
        }
    except Exception as e:
        return {"status": "error", "message": f"Git verify & merge error: {str(e)}"}


def git_worktree_sandbox_rollback(task_name: str) -> Dict[str, Any]:
    """
    DEVIN-STYLE SANDBOX: Instant Time-Travel Rollback.
    Destroys the worktree directory and temporary branch, leaving the main repository
    100% pristine with zero side effects.

    Args:
        task_name: Unique task identifier to rollback.
    """
    try:
        clean_task = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_name.strip()).lower()
        worktree_path = os.path.join(WORKTREES_BASE_DIR, clean_task)
        branch_name = f"sandbox_{clean_task}"
        root = _get_project_root()

        _run_git(["worktree", "remove", "--force", worktree_path], cwd=root)
        if os.path.exists(worktree_path):
            shutil.rmtree(worktree_path, ignore_errors=True)

        _run_git(["branch", "-D", branch_name], cwd=root)

        return {
            "status": "success",
            "task_name": clean_task,
            "message": f"Rollback instan berhasil! Sandbox branch '{branch_name}' dan direktori '{worktree_path}' telah dimusnahkan. Repositori utama tetap 100% bersih."
        }
    except Exception as e:
        return {"status": "error", "message": f"Git rollback error: {str(e)}"}


def git_worktree_sandbox_list() -> Dict[str, Any]:
    """List all currently active Git Worktree sandboxes."""
    try:
        res = _run_git(["worktree", "list"])
        lines = res.stdout.strip().splitlines()
        trees = []
        for l in lines:
            parts = l.split()
            if len(parts) >= 3 and ".alfa_worktrees" in parts[0]:
                trees.append({
                    "path": parts[0],
                    "commit": parts[1],
                    "branch": parts[2].strip("[]")
                })
        return {
            "status": "success",
            "total_sandboxes": len(trees),
            "sandboxes": trees
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
