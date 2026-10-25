"""Desktop tools package re-exporting screenshot, webcam, input automation, and clipboard tools."""

from alfa.tools.desktop.app_manager import install_or_update_desktop_app
from alfa.tools.desktop.artcraft import (
    artcraft_get_capabilities,
    artcraft_launch_gui,
    artcraft_run_cli,
)
from alfa.tools.desktop.capture import (
    capture_desktop_screenshot,
    capture_webcam_frame,
    record_desktop_screen,
)
from alfa.tools.desktop.input_automation import (
    desktop_click_coordinate,
    desktop_launch_app,
    desktop_type_keys,
    open_url_in_default_browser,
    open_url_in_system_browser,
    vision_click_target,
)
from alfa.tools.desktop.system_ui import (
    read_clipboard,
    show_desktop_notification,
    write_to_clipboard,
)

__all__ = [
    "artcraft_get_capabilities",
    "artcraft_launch_gui",
    "artcraft_run_cli",
    "capture_desktop_screenshot",
    "capture_webcam_frame",
    "record_desktop_screen",
    "desktop_click_coordinate",
    "desktop_type_keys",
    "desktop_launch_app",
    "install_or_update_desktop_app",
    "vision_click_target",
    "open_url_in_system_browser",
    "open_url_in_default_browser",
    "read_clipboard",
    "write_to_clipboard",
    "show_desktop_notification",
]
