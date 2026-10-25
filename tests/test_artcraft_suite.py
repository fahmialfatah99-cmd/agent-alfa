"""Unit tests for ArtCraft Suite tools and capability mapping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from alfa.tools.desktop.artcraft import (
    _resolve_app_key,
    artcraft_get_capabilities,
    artcraft_launch_gui,
    artcraft_run_cli,
)


def test_resolve_app_key():
    assert _resolve_app_key("photocraft") == "photocraft"
    assert _resolve_app_key("PhotoCraft") == "photocraft"
    assert _resolve_app_key("ai.storyteller.cadcraft") == "cadcraft"
    assert _resolve_app_key("gridcraft-cli") == "gridcraft"
    assert _resolve_app_key("LightCraft Studio") == "lightcraft"
    assert _resolve_app_key("pdfcraft") == "pdfcraft"
    assert _resolve_app_key("designcraft") == "designcraft"
    assert _resolve_app_key("random_non_existent") is None


def test_artcraft_get_capabilities():
    caps = artcraft_get_capabilities()
    assert caps["status"] == "success"
    assert caps["total_apps"] == 6
    assert "photocraft" in caps["apps"]
    assert "cadcraft" in caps["apps"]
    assert "gridcraft" in caps["apps"]
    assert "lightcraft" in caps["apps"]
    assert "pdfcraft" in caps["apps"]
    assert "designcraft" in caps["apps"]
    assert "artcraft_launcher" in caps["apps"]

    # Verify metadata fields
    photo_meta = caps["apps"]["photocraft"]
    assert ".psd" in photo_meta["formats_read"]
    assert "convert" in photo_meta["cli_subcommands"]


def test_artcraft_run_cli_unknown_app():
    res = artcraft_run_cli("unknown_xyz", "info")
    assert res["status"] == "error"
    assert "tidak dikenal" in res["message"]


def test_artcraft_run_cli_success():
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(
            returncode=0,
            stdout="PhotoCraft 0.15.1 document info\n",
            stderr="",
        )
        res = artcraft_run_cli(
            "photocraft",
            "info",
            args=["sample.psd", "--compact"],
        )
        assert res["status"] == "success"
        assert res["app"] == "PhotoCraft"
        assert "document info" in res["stdout"]

        mock_subproc.assert_called_once()
        cmd = mock_subproc.call_args[0][0]
        assert "flatpak" in cmd
        assert "ai.storyteller.photocraft" in cmd
        assert "--command=photocraft-cli" in cmd
        assert "info" in cmd
        assert "sample.psd" in cmd


def test_artcraft_launch_gui_unknown_app():
    res = artcraft_launch_gui("unknown_app")
    assert res["status"] == "error"
    assert "tidak dikenal" in res["message"]


def test_artcraft_launch_gui_success(tmp_path):
    dummy_file = tmp_path / "design.dxf"
    dummy_file.write_text("0\nSECTION\n", encoding="utf-8")

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock(pid=12345)
        mock_popen.return_value = mock_proc

        res = artcraft_launch_gui(
            "cadcraft",
            file_path=str(dummy_file),
            control_port=7985,
        )
        assert res["status"] == "success"
        assert res["pid"] == 12345
        assert res["control_port"] == 7985

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "flatpak" in cmd
        assert "ai.storyteller.cadcraft" in cmd
        assert "--control" in cmd
        assert "7985" in cmd
        assert str(dummy_file) in cmd


def test_tools_registered_in_registry():
    from alfa.tools.registry import AVAILABLE_TOOLS, TOOL_DOMAINS

    names = [getattr(t, "__name__", "") for t in AVAILABLE_TOOLS]
    assert "artcraft_get_capabilities" in names
    assert "artcraft_run_cli" in names
    assert "artcraft_launch_gui" in names

    assert "artcraft_get_capabilities" in TOOL_DOMAINS["media"]
    assert "artcraft_run_cli" in TOOL_DOMAINS["media"]
    assert "artcraft_launch_gui" in TOOL_DOMAINS["media"]
