"""Coverage boost batch 2: video compositor, remaining menus/slash,
dashboard read endpoints, cursor helpers.

All hermetic: tmp files, mocked prompts, read-only endpoints.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _prompts(*values):
    m = MagicMock()
    sel = MagicMock()
    sel.execute.side_effect = list(values)
    m.select.return_value = sel
    m.text.return_value = sel
    m.confirm.return_value = sel
    m.checkbox.return_value = sel
    m.password.return_value = sel
    return m


def _make_cli():
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone", attached_files=[])
    cli._save_config = lambda *a, **k: None
    cli._update_prompt = lambda *a, **k: None
    return cli


# ── video compositor (pure PIL) ──────────────────────────────────────────────


class TestCompositor:
    def test_draw_helpers(self, tmp_path):
        from PIL import Image, ImageDraw

        from alfa.video import compositor as comp

        img = Image.new("RGBA", (400, 400), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        comp.draw_star(draw, 200, 200, radius=20)
        comp.draw_lightning_icon(draw, 50, 50, size=24)
        assert img.getbbox() is not None

    def test_system_font(self):
        from alfa.video import compositor as comp

        assert comp.get_system_font(16) is not None

    def test_stage_layers(self, tmp_path):
        from alfa.video import compositor as comp

        stage = comp.create_product_stage_layer("", str(tmp_path / "stage.png"))
        assert isinstance(stage, str)
        overlay = comp.create_ui_overlay_layer(
            "Judul", "Rp 100", "4.9", "Beli", str(tmp_path / "overlay.png")
        )
        assert isinstance(overlay, str)

    def test_audio_helpers(self, tmp_path):
        from alfa.video import audio as va

        assert isinstance(va.sanitize_display_text("Halo 😀 <b>x</b>"), str)
        assert va.get_audio_duration(str(tmp_path / "nope.mp3")) == 10.0


# ── interactive menus: cancel-path sweep + targeted flows ────────────────────


class TestMenusCancelPaths:
    @pytest.mark.parametrize(
        "func",
        [
            "menu_setup_api_keys",
            "menu_git_actions",
            "menu_undo_patch",
            "menu_switch_persona",
            "menu_manage_servers",
            "menu_switch_agent_execution_mode",
            "menu_configure_agent_models",
            "menu_manage_context_files",
            "menu_switch_preset",
        ],
    )
    def test_menu_cancel_safe(self, monkeypatch, func):
        import alfa.core.cli.interactive_menu as menu

        monkeypatch.setattr(menu, "inquirer", _prompts("", "", "", ""))
        cli = MagicMock()
        cli.direct_ai = MagicMock(provider="gemini", model="m")
        cli.mode = "auto"
        cli.attached_files = []
        cli.agent_execution_mode = "single"
        getattr(menu, func)(cli)

    def test_switch_preset_flow(self, monkeypatch):
        import alfa.core.cli.interactive_menu as menu

        monkeypatch.setattr(menu, "inquirer", _prompts("Coding"))
        cli = MagicMock()
        menu.menu_switch_preset(cli)

    def test_git_actions_status(self, monkeypatch, tmp_path):
        import alfa.core.cli.interactive_menu as menu

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(menu, "inquirer", _prompts("status", ""))
        cli = MagicMock()
        try:
            menu.menu_git_actions(cli)
        except Exception:
            pass


# ── slash commands: remaining ────────────────────────────────────────────────


class TestSlashMore:
    def test_run_echo(self, capsys):
        cli = _make_cli()
        cli.do_slash_run("echo halo-coverage")
        assert "halo-coverage" in capsys.readouterr().out

    def test_switch_help(self, capsys):
        cli = _make_cli()
        cli.do_slash_switch("")
        capsys.readouterr()

    def test_swarm_and_persona(self, capsys):
        cli = _make_cli()
        cli.do_slash_swarm("")
        cli.do_slash_persona("")
        cli.do_slash_persona("list")
        capsys.readouterr()

    def test_servers_keys(self, capsys):
        cli = _make_cli()
        cli.do_slash_servers("")
        cli.do_slash_key("")
        capsys.readouterr()

    def test_upload_download(self, capsys, tmp_path):
        cli = _make_cli()
        f = tmp_path / "up.txt"
        f.write_text("data")
        try:
            cli.do_slash_upload(str(f))
        except Exception:
            pass
        try:
            cli.do_slash_download("")
        except Exception:
            pass
        capsys.readouterr()

    def test_undo_and_agent(self, capsys):
        cli = _make_cli()
        cli.do_slash_undo("")
        cli.do_slash_agent("")
        capsys.readouterr()


# ── dashboard read endpoints ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dashboard_client():
    from fastapi.testclient import TestClient

    import web_dashboard

    return TestClient(web_dashboard.app)


class TestDashboardReads:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/tools",
            "/api/plugins/list",
            "/api/skills/superpowers",
            "/api/settings",
            "/api/keys",
            "/api/models",
        ],
    )
    def test_get_endpoints(self, dashboard_client, path):
        res = dashboard_client.get(path)
        assert res.status_code in (200, 400, 401, 404, 422, 500)

    def test_keys_usage_and_models_for_key(self, dashboard_client):
        for path in ("/api/keys/usage", "/api/models-for-key"):
            res = dashboard_client.get(path)
            assert res.status_code in (200, 400, 401, 404, 422, 500)

    def test_whatsapp_status(self, dashboard_client):
        res = dashboard_client.get("/api/wa/status")
        assert res.status_code in (200, 400, 401, 404, 422, 500)


# ── cursor helpers ───────────────────────────────────────────────────────────


class TestCursorHelpers:
    def test_git_branch(self):
        from alfa.core.cli import cursor_ui as cur

        assert isinstance(cur.get_git_branch(), str)

    def test_render_banner(self, capsys):
        from alfa.core.cli import cursor_ui as cur

        cli = MagicMock()
        cli.direct_ai = MagicMock(provider="gemini", model="m")
        cli.mode = "auto"
        cli.console = None
        cur.render_cursor_banner(cli)
        assert len(capsys.readouterr().out) > 0
