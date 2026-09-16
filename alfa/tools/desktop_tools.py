"""Desktop GUI automation, vision, screenshot, and webcam tools.

Facade re-exporting from modular subpackage alfa.tools.desktop.
"""

from alfa.tools.desktop import (
    capture_desktop_screenshot,
    capture_webcam_frame,
    desktop_click_coordinate,
    desktop_launch_app,
    desktop_type_keys,
    read_clipboard,
    record_desktop_screen,
    show_desktop_notification,
    vision_click_target,
    write_to_clipboard,
)
from alfa.tools.desktop import *  # noqa: F401, F403
