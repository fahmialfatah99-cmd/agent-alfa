"""Software factory ALFA — scaffold + verifikasi multi-tenant.

Pecah dari modul monolitik `software_factory.py` (1.090 baris). **Import path
publik tidak berubah**: `from alfa.core.apex.software_factory import ...`.
"""

from alfa.core.apex.software_factory._audit import (
    _audit_html_files,
    _audit_python_files,
)
from alfa.core.apex.software_factory._build import (
    build_and_verify_fullstack_app,
    build_and_verify_multifile_repo,
    parse_stack_trace_locations,
)
from alfa.core.apex.software_factory._db import (
    get_software_factory_metrics,
    init_software_factory_tables,
)
from alfa.core.apex.software_factory._heal import (
    _auto_heal_html,
    _heal_backend_and_anti_mockup,
    _read_text_file,
)
from alfa.core.apex.software_factory._verify import (
    _restore_backups,
    _run_live_http_smoke_test,
    _validate_test_command,
    verify_fullstack_project_e2e,
)

__all__ = [
    "_audit_html_files",
    "_audit_python_files",
    "_auto_heal_html",
    "_heal_backend_and_anti_mockup",
    "_read_text_file",
    "_restore_backups",
    "_run_live_http_smoke_test",
    "_validate_test_command",
    "build_and_verify_fullstack_app",
    "build_and_verify_multifile_repo",
    "get_software_factory_metrics",
    "init_software_factory_tables",
    "parse_stack_trace_locations",
    "verify_fullstack_project_e2e",
]
