
with open("alfa/swarm/meeting_steps.py") as f:
    content = f.read()

old_build = """def _build_task_desc(
    agent: dict[str, Any],
    err_ctx: str,
    *,
    subtask_map: dict[str, str],
    topic: str,
    ctx_lines: list[str],
) -> str:
    td = (
        subtask_map.get(agent["name"])
        or f"Eksekusi modul {agent['role']} untuk '{topic[:60]}'"
    )"""

new_build = """def _build_task_desc(
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
    )"""

if old_build in content:
    content = content.replace(old_build, new_build)
    with open("alfa/swarm/meeting_steps.py", "w") as f:
        f.write(content)
    print("Replaced _build_task_desc in meeting_steps.py")
else:
    print("Could not find old _build_task_desc")
