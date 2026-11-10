"""Regression tests untuk struktur paket `alfa.tools.system.integrations`.

Modul monolitik dipecah menjadi paket; import path publik tidak boleh
berubah dan fungsi inti WA harus tetap bisa dimock lewat
`alfa.tools.system.integrations._wa_api`.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

from alfa.tools.registry import TOOL_REGISTRY


def test_integrations_is_package_with_stable_public_api():
    import alfa.tools.system.integrations as pkg

    assert pkg.__file__.endswith("integrations/__init__.py")

    for sub in (
        "_api",
        "productivity",
        "whatsapp",
        "bot_control",
        "android",
        "database_query",
    ):
        assert importlib.import_module(f"alfa.tools.system.integrations.{sub}") is not None

    public_api = (
        "generate_secure_password",
        "list_wa_drive_uploads",
        "manage_wa_sheets_bot",
        "query_database",
        "schedule_reminder",
        "scrcpy_android_control",
        "start_focus_session",
        "wa_get_chats",
        "wa_get_history_archive",
        "wa_get_incoming",
        "wa_get_me",
        "wa_get_messages",
        "wa_get_records",
        "wa_list_formats",
        "wa_send_message",
    )
    for name in public_api:
        assert hasattr(pkg, name), f"{name} hilang dari API publik"
        assert name in TOOL_REGISTRY, f"{name} tidak terdaftar di registry"


def test_wa_api_patch_target_still_intercepts_calls():
    """Patch pada `alfa.tools.system.integrations._wa_api` harus tetap berlaku."""
    from alfa.tools.system.integrations import wa_get_chats

    with patch(
        "alfa.tools.system.integrations._wa_api",
        return_value={"status": "success", "chats": []},
    ) as mock_api:
        res = wa_get_chats(5)
    assert res.get("status") == "success"
    assert mock_api.called
