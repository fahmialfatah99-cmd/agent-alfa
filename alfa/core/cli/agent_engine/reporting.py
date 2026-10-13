"""Run reporting: execution log, honest reports, and last-run summaries."""

from __future__ import annotations

from typing import Any


class RunReporterMixin:
    """Record executions and render honest end-of-run reports."""

    # Tools whose args reference a file path (for touched-files reporting).
    FILE_ARG_KEYS = ("path", "file_path", "filepath", "target_file")

    def _log_execution(self, tool_name: str, args: dict[str, Any], result: str) -> None:
        """Record one tool execution for honest end-of-run reporting."""
        log = getattr(self, "_exec_log", None)
        if log is None:
            self._exec_log = log = []
        snippet = str(result or "")[:300].replace("\n", " | ")
        files = [str(args[k]) for k in self.FILE_ARG_KEYS if args.get(k)]
        log.append({"tool": tool_name, "files": files, "snippet": snippet})

    def _build_execution_report(self) -> str:
        """Honest report of what was ACTUALLY executed (opencode-style)."""
        log = getattr(self, "_exec_log", []) or []
        counts: dict[str, int] = {}
        for entry in log:
            counts[entry["tool"]] = counts.get(entry["tool"], 0) + 1
        files = sorted({f for e in log for f in e["files"]})
        pending = [t for t in self._pending_todos()]
        done = []
        try:
            done = [t for t in self.tools.todos.list() if t.get("done")]
        except Exception:
            pass
        lines = [
            "## ⚙️ Laporan Eksekusi (tanpa Final Answer model)",
            "",
            f"Total aksi tool: **{len(log)}** | "
            + ", ".join(f"`{t}`×{c}" for t, c in sorted(counts.items())),
        ]
        if files:
            lines += ["", "### 📝 Berkas tersentuh"] + [f"- `{f}`" for f in files]
        if done or pending:
            lines.append("")
            lines.append("### 📋 Todo")
            lines += [f"- ✅ #{t.get('id')} {t.get('task', '')}" for t in done]
            lines += [f"- ⬜ #{t.get('id')} {t.get('task', '')}" for t in pending]
        if log:
            last = log[-1]
            lines += [
                "",
                f"### 🔎 Observasi terakhir (`{last['tool']}`):",
                f"> {last['snippet'][:500]}",
            ]
        lines += [
            "",
            "### 💡 Lanjutannya",
            "- Perintah saya lagi (mis. `lanjutkan`) untuk meneruskan, atau "
            "`/todo list` untuk melihat sisa tugas.",
        ]
        return "\n".join(lines)

    def format_last_run(self) -> str:
        """Human-readable summary of the most recent agent run (real state)."""
        last = getattr(self, "last_run", None) or {}
        if not last.get("tools"):
            return "Belum ada eksekusi agent pada sesi ini."
        tools = last.get("tools", [])
        counts: dict[str, int] = {}
        for t in tools:
            counts[t] = counts.get(t, 0) + 1
        files = last.get("files", [])
        state = "selesai ✅" if last.get("finished") else "BELUM selesai ⏳"
        lines = [
            f"🔧 Tugas terakhir: {str(last.get('task', ''))[:120]}",
            f"Status: {state} | Turn: {last.get('turns', 0)} | "
            f"Aksi: {len(tools)} ({', '.join(f'{t}×{c}' for t, c in sorted(counts.items()))})",
        ]
        if files:
            lines.append("Berkas tersentuh: " + ", ".join(f"`{f}`" for f in files[:10]))
        if last.get("todos_pending"):
            lines.append(f"Todo tersisa: {last['todos_pending']} (lihat /todo list)")
        return "\n".join(lines)
