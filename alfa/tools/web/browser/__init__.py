"""Browser automation tools (split from monolithic browser.py)."""

from alfa.tools.web.browser.actions import (
    browser_capture_screenshot,
    browser_click_element,
    browser_close_tab,
    browser_open_url,
    browser_type_text,
    browser_use_autonomous_task,
)
from alfa.tools.web.visual_tester import (
    browser_visual_test_page as browser_visual_test_page,
)

__all__ = [
    "browser_capture_screenshot",
    "browser_click_element",
    "browser_close_tab",
    "browser_open_url",
    "browser_type_text",
    "browser_use_autonomous_task",
    "browser_visual_test_page",
]
