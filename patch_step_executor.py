
with open("alfa/swarm/step_executor.py") as f:
    content = f.read()

old_decompose = """async def _decompose_task(
    topic: str, participants: list[dict[str, Any]]
) -> dict[str, str]:
    \"\"\"Ask the planner to break the topic into one concrete subtask per agent.\"\"\"
    roster = ", ".join(f"{a['name']} ({a.get('role', '')})" for a in participants)
    prompt = (
        f"Anda misi planner swarm. TOPIK: {topic}\\n"
        f"TIM: {roster}\\n\\n"
        "Pecah topik ini menjadi SATU subtask konkret dan dapat dieksekusi sistem "
        "(bukan rencana abstrak) untuk setiap anggota tim.\\n"
        "Balas HANYA array JSON tanpa teks lain: "
        '[{"name": "<nama persis dari tim>", "task": "<instruksi spesifik maksimal 25 kata>"}]'
    )
    try:
        raw = await generate_agent_response(
            {"name": "Mission Planner", "provider": "gemini"},
            prompt,
            "Kamu planner teknis. Output WAJIB array JSON murni tanpa penjelasan.",
        )
        m = re.search(r"\\[.*\\]", raw or "", re.DOTALL)
        if not m:
            return {}
        items = json.loads(m.group(0))
        valid_names = {a["name"] for a in participants}
        mapping = {}
        for it in items if isinstance(items, list) else []:
            nm = (it or {}).get("name", "").strip()
            tk = (it or {}).get("task", "").strip()
            if nm in valid_names and tk:
                mapping[nm] = tk
        return mapping
    except Exception as dec_err:
        logger.warning("Task decomposition failed, using generic tasks: %r", dec_err)
        return {}"""

new_decompose = """async def _decompose_task(
    topic: str, participants: list[dict[str, Any]]
) -> dict[str, Any]:
    \"\"\"Ask the planner to break the topic into one concrete subtask per agent with dependencies.\"\"\"
    roster = ", ".join(f"{a['name']} ({a.get('role', '')})" for a in participants)
    prompt = (
        f"Anda misi planner swarm. TOPIK: {topic}\\n"
        f"TIM: {roster}\\n\\n"
        "Pecah topik ini menjadi SATU subtask konkret dan dapat dieksekusi sistem "
        "(bukan rencana abstrak) untuk setiap anggota tim.\\n"
        "Tentukan juga 'depends_on', yaitu daftar nama anggota tim lain yang tugasnya harus selesai SEBELUM tugas ini bisa dimulai (boleh kosong jika bisa paralel).\\n"
        "Balas HANYA array JSON tanpa teks lain: "
        '[{"name": "<nama persis dari tim>", "task": "<instruksi spesifik maksimal 25 kata>", "depends_on": ["<nama_agen_lain>"]}]'
    )
    try:
        raw = await generate_agent_response(
            {"name": "Mission Planner", "provider": "gemini"},
            prompt,
            "Kamu planner teknis. Output WAJIB array JSON murni tanpa penjelasan.",
        )
        m = re.search(r"\\[.*\\]", raw or "", re.DOTALL)
        if not m:
            return {}
        items = json.loads(m.group(0))
        valid_names = {a["name"] for a in participants}
        mapping = {}
        for it in items if isinstance(items, list) else []:
            nm = (it or {}).get("name", "").strip()
            tk = (it or {}).get("task", "").strip()
            deps = (it or {}).get("depends_on", [])
            if not isinstance(deps, list):
                deps = []
            deps = [d.strip() for d in deps if d.strip() in valid_names and d.strip() != nm]
            if nm in valid_names and tk:
                mapping[nm] = {"task": tk, "depends_on": deps}
        return mapping
    except Exception as dec_err:
        logger.warning("Task decomposition failed, using generic tasks: %r", dec_err)
        return {}"""

if old_decompose in content:
    content = content.replace(old_decompose, new_decompose)
    with open("alfa/swarm/step_executor.py", "w") as f:
        f.write(content)
    print("Replaced _decompose_task in step_executor.py")
else:
    print("Could not find old _decompose_task")
