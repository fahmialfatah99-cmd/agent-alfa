"""Coverage for system-monitoring package, CLI todos, and permission store.

All hermetic: read-only calls, dry-runs, invalid-action error paths, and
temporary directories. No system state is mutated.
"""

from pathlib import Path

from alfa.core.cli.agent_engine.permissions import PermissionStore
from alfa.core.cli.agent_engine.todos import TodoManager
from alfa.tools.system import monitoring as mon


class TestMonitoringTools:
    def test_get_system_stats(self):
        res = mon.get_system_stats()
        assert isinstance(res, dict)
        assert res.get("status") == "success"

    def test_control_hardware_invalid(self):
        res = mon.control_linux_hardware(action="tindakan_tak_ada_xyz")
        assert isinstance(res, dict)

    def test_list_processes(self):
        res = mon.list_running_processes()
        assert isinstance(res, dict)

    def test_kill_nonexistent(self):
        res = mon.kill_process("proses_tak_ada_xyz_12345")
        assert isinstance(res, dict)

    def test_clean_storage_dry_run(self):
        res = mon.clean_system_storage(dry_run=True)
        assert isinstance(res, dict)

    def test_services_invalid_action(self):
        res = mon.manage_system_services(
            service_name="svc_tak_ada_xyz", action="tindakan_tak_ada_xyz"
        )
        assert isinstance(res, dict)

    def test_crontab_list(self):
        res = mon.manage_crontab_jobs(action="list")
        assert isinstance(res, dict)

    def test_diagnose_no_fix(self):
        res = mon.auto_diagnose_and_heal_system(fix_issues=False)
        assert isinstance(res, dict)

    def test_guardian_status(self):
        res = mon.proactive_system_guardian_config(action="status")
        assert isinstance(res, dict)

    def test_ambient_status(self):
        res = mon.proactive_ambient_agent_config(action="status")
        assert isinstance(res, dict)


class TestTodoManager:
    def test_add_list_done_clear(self, tmp_path):
        m = TodoManager(tmp_path)
        a = m.add("Tugas A")
        b = m.add("Tugas B")
        assert a["id"] != b["id"]
        assert len(m.list()) == 2
        assert m.done(a["id"]) is True
        assert m.done(9999) is False
        assert "Tugas A" in m.summary()
        assert m.clear(done_only=True) == 1
        assert len(m.list()) == 1
        assert m.clear(done_only=False) == 1
        assert m.list() == []

    def test_persist_reload(self, tmp_path):
        m = TodoManager(tmp_path)
        m.add("Persist me")
        m2 = TodoManager(tmp_path)
        assert any(t["task"] == "Persist me" for t in m2.list())

    def test_empty_summary(self, tmp_path):
        assert "Belum ada" in TodoManager(tmp_path).summary()


class TestPermissionStore:
    def test_defaults(self, tmp_path):
        s = PermissionStore(path=Path(tmp_path) / "p.json")
        assert s.get("run_command") == "ask"
        assert s.get("list_directory") == "allow"

    def test_set_reset_persist(self, tmp_path):
        path = Path(tmp_path) / "p.json"
        s = PermissionStore(path=path)
        assert s.set("run_command", "deny") is True
        assert s.set("run_command", "bogus") is False
        assert PermissionStore(path=path).get("run_command") == "deny"
        assert s.reset("run_command") is True
        assert s.reset("run_command") is False
        assert s.get("run_command") == "ask"
