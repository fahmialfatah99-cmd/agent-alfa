
with open("alfa/swarm/engine.py") as f:
    content = f.read()

# First we need to inject _execute_agents_parallel function
# Let's add it before conduct_multi_agent_meeting

parallel_func = """async def _execute_agents_parallel(
    participants: list[dict[str, Any]],
    subtask_map: dict[str, Any],
    topic: str,
    intent_info: dict[str, Any],
    session_id: str,
    mode: str,
    execution_steps: list[dict[str, Any]],
    ctx_lines: list[str],
    failed_steps: list[dict[str, Any]]
) -> bool:
    from alfa.swarm import workspace_hygiene
    has_deps = False
    if subtask_map:
        for t in subtask_map.values():
            if isinstance(t, dict) and "depends_on" in t and t["depends_on"]:
                has_deps = True
                break

    if not has_deps:
        _parallel = os.getenv("ALFA_SWARM_PARALLEL", "on").strip().lower() != "off"
        try:
            _wave_size = max(1, int(os.getenv("ALFA_SWARM_MAX_CONCURRENT", "3")))
        except ValueError:
            _wave_size = 3
        if not _parallel:
            _wave_size = 1

        for wave_start in range(0, len(participants), _wave_size):
            wave = participants[wave_start : wave_start + _wave_size]
            if _cancel_requested():
                log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_start // _wave_size + 1}.")
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                return True

            err_ctx_snapshot = _build_error_context(failed_steps)
            try:
                wave_results: list[Any] = await asyncio.gather(
                    *[
                        _execute_agent_step(
                            a,
                            _build_task_desc(
                                a,
                                err_ctx_snapshot,
                                subtask_map=subtask_map,
                                topic=topic,
                                ctx_lines=ctx_lines,
                            ),
                            topic=topic,
                            intent_info=intent_info,
                        )
                        for a in wave
                    ],
                    return_exceptions=True,
                )
            except Exception as wave_err:
                logger.error(f"Wave execution error: {wave_err}")
                wave_results = [wave_err] * len(wave)

            for agent, res in zip(wave, wave_results, strict=True):
                if isinstance(res, Exception):
                    step_result = {
                        "agent_name": agent["name"],
                        "tool_used": None,
                        "execution_summary": f"[EXCEPTION] {res}",
                        "deliverable_file": None,
                    }
                    passed, feedback = False, str(res)
                else:
                    step_result, passed, feedback = res

                if not passed and step_result.get("tool_used") != "strategic_orchestration":
                    failed_steps.append({
                        "agent_name": agent["name"],
                        "tool_used": step_result.get("tool_used"),
                        "feedback": feedback,
                        "execution_summary": step_result.get("execution_summary", ""),
                    })
                    _record_step_error(session_id, step_result, feedback)

                step_result["verification"] = "PASS" if passed else ("FAIL" if step_result.get("tool_used") != "strategic_orchestration" else "N/A")
                log_live("VERIFY", f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}")
                execution_steps.append(step_result)

                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="running",
                        )
                    except Exception:
                        pass
                brief = (step_result.get("execution_summary") or "")[:180].replace("\\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
        return False

    agent_names = [a["name"] for a in participants]
    agent_by_name = {a["name"]: a for a in participants}

    in_degree = {name: 0 for name in agent_names}
    adj_list = {name: [] for name in agent_names}

    for name in agent_names:
        info = subtask_map.get(name, {})
        deps = info.get("depends_on", []) if isinstance(info, dict) else []
        for dep in deps:
            if dep in agent_names:
                adj_list[dep].append(name)
                in_degree[name] += 1

    queue = [name for name in agent_names if in_degree[name] == 0]
    completed = set()

    if not queue and agent_names:
        log_live("WARN", "⚠️ Terdeteksi siklus pada dependensi! Beralih ke fallback sekuensial.")
        return await _execute_agents_parallel(participants, {}, topic, intent_info, session_id, mode, execution_steps, ctx_lines, failed_steps)

    wave_num = 1
    while queue:
        if _cancel_requested():
            log_live("CANCEL", f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_num}.")
            if _CHECKPOINT_AVAILABLE:
                try:
                    _SwarmCheckpoint.mark_cancelled(session_id)
                except Exception:
                    pass
            return True

        wave_names = queue[:]
        wave = [agent_by_name[n] for n in wave_names]
        queue = []

        err_ctx_snapshot = _build_error_context(failed_steps)
        try:
            wave_results: list[Any] = await asyncio.gather(
                *[
                    _execute_agent_step(
                        a,
                        _build_task_desc(
                            a,
                            err_ctx_snapshot,
                            subtask_map=subtask_map,
                            topic=topic,
                            ctx_lines=ctx_lines,
                        ),
                        topic=topic,
                        intent_info=intent_info,
                    )
                    for a in wave
                ],
                return_exceptions=True,
            )
        except Exception as wave_err:
            logger.error(f"Wave execution error: {wave_err}")
            wave_results = [wave_err] * len(wave)

        for agent, res in zip(wave, wave_results, strict=True):
            if isinstance(res, Exception):
                step_result = {
                    "agent_name": agent["name"],
                    "tool_used": None,
                    "execution_summary": f"[EXCEPTION] {res}",
                    "deliverable_file": None,
                }
                passed, feedback = False, str(res)
            else:
                step_result, passed, feedback = res

            if not passed and step_result.get("tool_used") != "strategic_orchestration":
                failed_steps.append({
                    "agent_name": agent["name"],
                    "tool_used": step_result.get("tool_used"),
                    "feedback": feedback,
                    "execution_summary": step_result.get("execution_summary", ""),
                })
                _record_step_error(session_id, step_result, feedback)

            step_result["verification"] = "PASS" if passed else ("FAIL" if step_result.get("tool_used") != "strategic_orchestration" else "N/A")
            log_live("VERIFY", f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}")
            execution_steps.append(step_result)

            if _CHECKPOINT_AVAILABLE:
                try:
                    _SwarmCheckpoint.save(
                        session_id=session_id,
                        topic=topic,
                        mode=mode,
                        participants=participants,
                        steps=execution_steps,
                        steps_done=len(execution_steps),
                        status="running",
                    )
                except Exception:
                    pass

            brief = (step_result.get("execution_summary") or "")[:180].replace("\\n", " ")
            ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
            completed.add(agent["name"])

        for name in wave_names:
            for neighbor in adj_list[name]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        wave_num += 1

    if len(completed) < len(agent_names):
        remaining = [name for name in agent_names if name not in completed]
        log_live("WARN", f"⚠️ Agen tersisa karena dependensi macet: {remaining}. Menjalankan fallback!")
        wave = [agent_by_name[n] for n in remaining]
        err_ctx_snapshot = _build_error_context(failed_steps)
        try:
            wave_results: list[Any] = await asyncio.gather(
                *[
                    _execute_agent_step(
                        a,
                        _build_task_desc(
                            a,
                            err_ctx_snapshot,
                            subtask_map=subtask_map,
                            topic=topic,
                            ctx_lines=ctx_lines,
                        ),
                        topic=topic,
                        intent_info=intent_info,
                    )
                    for a in wave
                ],
                return_exceptions=True,
            )
            for agent, res in zip(wave, wave_results, strict=True):
                if isinstance(res, Exception):
                    step_result = {
                        "agent_name": agent["name"],
                        "tool_used": None,
                        "execution_summary": f"[EXCEPTION] {res}",
                        "deliverable_file": None,
                    }
                    passed, feedback = False, str(res)
                else:
                    step_result, passed, feedback = res

                if not passed and step_result.get("tool_used") != "strategic_orchestration":
                    failed_steps.append({
                        "agent_name": agent["name"],
                        "tool_used": step_result.get("tool_used"),
                        "feedback": feedback,
                        "execution_summary": step_result.get("execution_summary", ""),
                    })
                    _record_step_error(session_id, step_result, feedback)

                step_result["verification"] = "PASS" if passed else ("FAIL" if step_result.get("tool_used") != "strategic_orchestration" else "N/A")
                log_live("VERIFY", f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}")
                execution_steps.append(step_result)

                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="running",
                        )
                    except Exception:
                        pass
                brief = (step_result.get("execution_summary") or "")[:180].replace("\\n", " ")
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")
        except Exception:
            pass

    return False

async def conduct_multi_agent_meeting("""

content = content.replace("async def conduct_multi_agent_meeting(", parallel_func)

# Now, inside conduct_multi_agent_meeting, replace the block:
old_exec_block = """        _parallel = os.getenv("ALFA_SWARM_PARALLEL", "on").strip().lower() != "off"
        try:
            _wave_size = max(1, int(os.getenv("ALFA_SWARM_MAX_CONCURRENT", "3")))
        except ValueError:
            _wave_size = 3
        if not _parallel:
            _wave_size = 1
        for wave_start in range(0, len(participants), _wave_size):
            wave = participants[wave_start : wave_start + _wave_size]
            if _cancel_requested():
                log_live(
                    "CANCEL",
                    f"⏹ Eksekusi dihentikan pengguna sebelum gelombang {wave_start // _wave_size + 1}.",
                )
                swarm_cancelled = True
                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.mark_cancelled(session_id)
                    except Exception:
                        pass
                break

            err_ctx_snapshot = _build_error_context(failed_steps)

            try:
                wave_results: list[Any] = await asyncio.gather(
                    *[
                        _execute_agent_step(
                            a,
                            _build_task_desc(
                                a,
                                err_ctx_snapshot,
                                subtask_map=subtask_map,
                                topic=topic,
                                ctx_lines=ctx_lines,
                            ),
                            topic=topic,
                            intent_info=intent_info,
                        )
                        for a in wave
                    ],
                    return_exceptions=True,
                )
            except Exception as wave_err:
                logger.error(f"Wave execution error: {wave_err}")
                wave_results = [wave_err] * len(wave)

            for agent, res in zip(wave, wave_results, strict=True):
                if isinstance(res, Exception):
                    step_result = {
                        "agent_name": agent["name"],
                        "tool_used": None,
                        "execution_summary": f"[EXCEPTION] {res}",
                        "deliverable_file": None,
                    }
                    passed, feedback = False, str(res)
                else:
                    step_result, passed, feedback = res

                if (
                    not passed
                    and step_result.get("tool_used") != "strategic_orchestration"
                ):
                    failed_steps.append(
                        {
                            "agent_name": agent["name"],
                            "tool_used": step_result.get("tool_used"),
                            "feedback": feedback,
                            "execution_summary": step_result.get(
                                "execution_summary", ""
                            ),
                        }
                    )
                    _record_step_error(session_id, step_result, feedback)

                step_result["verification"] = (
                    "PASS"
                    if passed
                    else (
                        "FAIL"
                        if step_result.get("tool_used") != "strategic_orchestration"
                        else "N/A"
                    )
                )
                log_live(
                    "VERIFY",
                    f"{'✅ PASS' if passed else '❌ FAIL'} — {agent['name']} ({step_result.get('tool_used')}){(': ' + feedback[:80]) if not passed and feedback else ''}",
                )
                execution_steps.append(step_result)

                if _CHECKPOINT_AVAILABLE:
                    try:
                        _SwarmCheckpoint.save(
                            session_id=session_id,
                            topic=topic,
                            mode=mode,
                            participants=participants,
                            steps=execution_steps,
                            steps_done=len(execution_steps),
                            status="cancelled" if swarm_cancelled else "running",
                        )
                    except Exception:
                        pass

                brief = (step_result.get("execution_summary") or "")[:180].replace(
                    "\\n", " "
                )
                ctx_lines.append(f"{step_result['agent_name']} -> {brief}")"""

new_exec_block = """        swarm_cancelled = await _execute_agents_parallel(
            participants,
            subtask_map,
            topic,
            intent_info,
            session_id,
            mode,
            execution_steps,
            ctx_lines,
            failed_steps
        )"""

# Also fix the part where it logs PLAN
old_plan = """        if subtask_map:
            logger.info("Task decomposition OK: %s", list(subtask_map.keys()))
            for _n, _t in subtask_map.items():
                log_live("PLAN", f"🗂️ {_n}: {_t[:90]}")"""

new_plan = """        if subtask_map:
            logger.info("Task decomposition OK: %s", list(subtask_map.keys()))
            for _n, _t in subtask_map.items():
                tk = _t["task"] if isinstance(_t, dict) else _t
                deps = _t.get("depends_on", []) if isinstance(_t, dict) else []
                log_live("PLAN", f"🗂️ {_n}: {tk[:90]} (Deps: {deps})")"""

content = content.replace(old_plan, new_plan)
if old_exec_block in content:
    content = content.replace(old_exec_block, new_exec_block)
    with open("alfa/swarm/engine.py", "w") as f:
        f.write(content)
    print("Replaced execution block in engine.py")
else:
    print("Could not find old execution block")

