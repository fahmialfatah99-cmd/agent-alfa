"""Desktop tools package re-exporting screenshot, webcam, input automation, and clipboard tools."""

from alfa.tools.desktop.capture import (
    capture_desktop_screenshot,
    capture_webcam_frame,
    record_desktop_screen,
)
from alfa.tools.desktop.input_automation import (
    desktop_click_coordinate,
    desktop_launch_app,
    desktop_type_keys,
    vision_click_target,
)
from alfa.tools.desktop.system_ui import (
    read_clipboard,
    show_desktop_notification,
    write_to_clipboard,
)

__all__ = [
    "capture_desktop_screenshot",
    "capture_webcam_frame",
    "record_desktop_screen",
    "desktop_click_coordinate",
    "desktop_type_keys",
    "desktop_launch_app",
    "vision_click_target",
    "read_clipboard",
    "write_to_clipboard",
    "show_desktop_notification",
]
