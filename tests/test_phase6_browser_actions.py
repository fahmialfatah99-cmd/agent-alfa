"""Phase 6 coverage: public browser tools (open/click/type/screenshot/task).

Hermetic: Camoufox, planner LLM, snapshot DOM, dan fallback web di-mock.
Tidak ada browser atau jaringan nyata yang dijalankan.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def ba(monkeypatch, tmp_path):
    from alfa.tools.web.browser import actions

    monkeypatch.setattr(actions, "SANDBOX_DIR", str(tmp_path))
    monkeypatch.setattr(actions, "_ref_index", lambda ref: int(ref[1:]) if ref.startswith("e") and ref[1:].isdigit() else -1)
    monkeypatch.setattr(actions, "_index_ok", lambda idx, elements: 0 <= idx < len(elements))
    return actions


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.idx = None
        self.first = self

    def nth(self, idx):
        self.idx = idx
        return self

    def click(self, timeout=0):
        if self.page.fail_click:
            raise RuntimeError("klik gagal")  # noqa: TRY003
        self.page.calls.append(("click", self.selector, self.idx))

    def fill(self, text, timeout=0):
        if self.page.fail_fill:
            raise RuntimeError("fill gagal")  # noqa: TRY003
        self.page.calls.append(("fill", self.selector, text, timeout))

    def press_sequentially(self, text, delay=0):
        if self.page.fail_press:
            raise RuntimeError("press gagal")  # noqa: TRY003
        self.page.calls.append(("press", text, delay))


class FakePage:
    def __init__(self, url="https://x.test", closed=False):
        self.url = url
        self.closed = closed
        self.calls = []
        self.fail_click = False
        self.fail_fill = False
        self.fail_press = False
        self.fail_goto = False
        self.plan_actions = None

    def goto(self, url, wait_until=None, timeout=None):
        if self.fail_goto:
            raise RuntimeError("goto gagal")  # noqa: TRY003
        self.url = url
        self.calls.append(("goto", url, wait_until, timeout))

    def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))

    def title(self):
        return "Judul"

    def is_closed(self):
        return self.closed

    def locator(self, selector):
        return FakeLocator(self, selector)

    def screenshot(self, path=None, full_page=False):
        with open(path, "wb") as f:
            f.write(b"png")
        self.calls.append(("screenshot", path, full_page))

    def evaluate(self, script):
        self.calls.append(("evaluate", script))


def test_open_url_empty(ba, monkeypatch):
    monkeypatch.setattr(ba, "_normalize_url", lambda url: "")
    assert ba.browser_open_url.__wrapped__("") == {"status": "error", "message": "URL kosong."}


def test_open_url_rest_success_and_fail(ba, monkeypatch):
    from alfa.tools.web.browser import camofox_rest

    monkeypatch.setattr(ba, "_normalize_url", lambda url: url)
    monkeypatch.setattr(camofox_rest, "prefer_rest", lambda: True)
    monkeypatch.setattr(
        camofox_rest, "rest_open_url", lambda url: {"status": "success", "url": url}
    )
    assert ba.browser_open_url.__wrapped__("https://a.test")["status"] == "success"

    monkeypatch.setattr(
        camofox_rest, "rest_open_url", lambda url: {"status": "error", "message": "down"}
    )
    page = FakePage()
    monkeypatch.setattr(ba, "_ensure_page", lambda: page)
    monkeypatch.setattr(ba, "_snapshot", lambda p: ([1, 2], "desc"))
    out = ba.browser_open_url.__wrapped__("https://a.test")
    assert out["status"] == "success" and out["engine"] == "camoufox_python"
    assert ba._STATE["elements"] == [1, 2]
    assert ("goto", "https://a.test", "domcontentloaded", 45000) in page.calls


def test_open_url_scrapling_and_error(ba, monkeypatch):
    monkeypatch.setattr(ba, "_normalize_url", lambda url: url)
    from alfa.tools.web.browser import camofox_rest

    monkeypatch.setattr(camofox_rest, "prefer_rest", lambda: False)
    monkeypatch.setattr(ba, "_ensure_page", lambda: None)
    monkeypatch.setattr(
        ba,
        "_scrapling_snapshot",
        lambda url: {"interactive_elements": "els", "page_content_preview": "prev"},
    )
    out = ba.browser_open_url.__wrapped__("https://b.test")
    assert out["engine"] == "scrapling_stealth_fallback"
    assert out["url"] == "https://b.test"

    monkeypatch.setattr(
        ba, "_ensure_page", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    out = ba.browser_open_url.__wrapped__("https://c.test")
    assert out["status"] == "error" and "boom" in out["message"]


def test_click_element_paths(ba, monkeypatch):
    monkeypatch.setattr(ba, "_ensure_page", lambda: None)
    out = ba.browser_click_element.__wrapped__("e1")
    assert out["status"] == "error"

    page = FakePage()
    monkeypatch.setattr(ba, "_ensure_page", lambda: page)
    ba._STATE["elements"] = ["a", "b"]
    monkeypatch.setattr(ba, "_snapshot", lambda p: (["c"], "desc"))
    out = ba.browser_click_element.__wrapped__("e1")
    assert out["status"] == "success"
    assert ("click", ba._INTERACTIVE_SEL, 1) in page.calls
    assert ba._STATE["elements"] == ["c"]

    out = ba.browser_click_element.__wrapped__("css=#x")
    assert out["status"] == "success"
    assert ("click", "css=#x", None) in page.calls

    page.fail_click = True
    out = ba.browser_click_element.__wrapped__("e0")
    assert out["status"] == "error" and "Gagal klik" in out["message"]

    monkeypatch.setattr(ba, "_ensure_page", lambda: (_ for _ in ()).throw(RuntimeError("outer")))
    out = ba.browser_click_element.__wrapped__("e0")
    assert out["status"] == "error" and "outer" in out["message"]


def test_type_text_paths(ba, monkeypatch):
    monkeypatch.setattr(ba, "_ensure_page", lambda: None)
    assert ba.browser_type_text.__wrapped__("e1", "x")["status"] == "error"

    page = FakePage()
    monkeypatch.setattr(ba, "_ensure_page", lambda: page)
    ba._STATE["elements"] = ["a"]
    out = ba.browser_type_text.__wrapped__("e0", "halo")
    assert out["status"] == "success"
    assert ("fill", ba._INTERACTIVE_SEL, "halo", 8000) in page.calls

    out = ba.browser_type_text.__wrapped__("input[name=q]", "teks")
    assert out["status"] == "success"

    page.fail_fill = True
    out = ba.browser_type_text.__wrapped__("e0", "fallback")
    assert out["status"] == "success"
    assert any(c[0] == "press" for c in page.calls)

    page.fail_press = True
    out = ba.browser_type_text.__wrapped__("e0", "gagal")
    assert out["status"] == "error" and "Gagal mengetik" in out["message"]

    monkeypatch.setattr(ba, "_ensure_page", lambda: (_ for _ in ()).throw(RuntimeError("outer")))
    out = ba.browser_type_text.__wrapped__("e0", "x")
    assert out["status"] == "error"


def test_screenshot_and_close(ba, monkeypatch, tmp_path):
    monkeypatch.setattr(ba, "_ensure_page", lambda: None)
    assert ba.browser_capture_screenshot.__wrapped__()["status"] == "error"

    page = FakePage()
    monkeypatch.setattr(ba, "_ensure_page", lambda: page)
    out = ba.browser_capture_screenshot.__wrapped__()
    assert out["status"] == "success"
    assert (tmp_path / "browser_screenshot.png").read_bytes() == b"png"

    monkeypatch.setattr(ba, "_ensure_page", lambda: (_ for _ in ()).throw(OSError("x")))
    assert ba.browser_capture_screenshot.__wrapped__()["status"] == "error"

    monkeypatch.setattr(ba, "_close_browser", lambda: None)
    assert ba.browser_close_tab.__wrapped__()["status"] == "success"

    def boom():
        raise OSError("close")

    monkeypatch.setattr(ba, "_close_browser", boom)
    assert ba.browser_close_tab.__wrapped__()["status"] == "error"


def _run_task(ba, monkeypatch, page, plans, task="cari berita", max_steps=3):
    monkeypatch.setattr(ba, "_normalize_url", lambda url: url or "https://normal.test")
    monkeypatch.setattr(ba, "_ensure_page", lambda: page)
    monkeypatch.setattr(ba, "_snapshot", lambda p: ([1, 2, 3], "snap"))
    monkeypatch.setattr(ba, "_page_summary", lambda p: "ringkasan halaman")
    iterator = iter(plans)
    monkeypatch.setattr(ba, "_plan_next_action", lambda *a: next(iterator))
    return ba.browser_use_autonomous_task.__wrapped__(task, "https://start.test", max_steps)


def test_autonomous_task_empty_and_fallback(ba, monkeypatch):
    assert ba.browser_use_autonomous_task.__wrapped__("  ")["status"] == "error"

    monkeypatch.setattr(ba, "_ensure_page", lambda: None)
    monkeypatch.setattr(
        ba,
        "_research_fallback",
        lambda task, url: {"status": "partial", "task": task},
    )
    out = ba.browser_use_autonomous_task.__wrapped__("riset", "https://a", 99)
    assert out["status"] == "partial"


def test_autonomous_task_all_actions(ba, monkeypatch):
    page = FakePage()
    plans = [
        {"action": "click", "ref": "e1", "reason": "klik"},
        {"action": "click", "ref": "e99", "reason": "klik invalid"},
        {"action": "type", "ref": "e0", "text": "halo", "reason": "isi"},
        {"action": "type", "ref": "css=#q", "text": "x", "reason": "isi css"},
        {"action": "scroll"},
        {"action": "goto", "url": "https://next.test"},
        {"action": "done", "reason": "selesai"},
    ]
    out = _run_task(ba, monkeypatch, page, plans, max_steps=12)
    assert out["status"] == "success"
    assert out["steps_completed"] == 7
    assert out["final_url"] == "https://next.test"
    results = [s.get("result") for s in out["steps"]]
    assert "diklik" in results
    assert "terisi" in results
    assert "scroll down" in results


def test_autonomous_task_partial_planner_error_and_closed(ba, monkeypatch):
    page = FakePage()
    monkeypatch.setattr(ba, "_normalize_url", lambda url: url)
    monkeypatch.setattr(ba, "_ensure_page", lambda: page)
    monkeypatch.setattr(ba, "_snapshot", lambda p: ([1], "snap"))
    monkeypatch.setattr(ba, "_page_summary", lambda p: "ringkasan")
    monkeypatch.setattr(
        ba,
        "_plan_next_action",
        lambda *a: (_ for _ in ()).throw(RuntimeError("llm mati")),
    )
    monkeypatch.setattr(ba, "_heuristic_plan", lambda task, els, cap: {"action": "scroll"})
    out = ba.browser_use_autonomous_task.__wrapped__("tugas", "https://a", 2)
    assert out["status"] == "partial"
    assert "heuristik" in out["final_summary"]

    page.closed = True
    out = ba.browser_use_autonomous_task.__wrapped__("tugas", "https://a", 2)
    assert out["status"] == "partial" and out["steps_completed"] == 0


def test_autonomous_task_step_error_and_goto_error(ba, monkeypatch):
    page = FakePage()
    page.fail_goto = True
    page.fail_click = True
    plans = [
        {"action": "click", "ref": "e0"},
        {"action": "goto", "url": ""},
        {"action": "done"},
    ]
    out = _run_task(ba, monkeypatch, page, plans)
    assert out["status"] == "success"
    assert out["steps"][0]["result"].startswith("ERROR:")

    monkeypatch.setattr(ba, "_ensure_page", lambda: (_ for _ in ()).throw(RuntimeError("outer")))
    out = ba.browser_use_autonomous_task.__wrapped__("x", "https://a")
    assert out["status"] == "error"


def test_research_fallback(ba, monkeypatch):
    monkeypatch.setattr(
        ba, "web_search", lambda **k: (_ for _ in ()).throw(RuntimeError("search down"))
    )
    out = ba._research_fallback("tugas", "https://a")
    assert out["status"] == "error" and "riset teks" in out["message"]

    monkeypatch.setattr(
        ba,
        "web_search",
        lambda **k: {
            "status": "success",
            "results": [
                {"title": "A", "link": "https://a"},
                {"title": "B"},
                {"title": "C", "link": "https://c"},
            ],
        },
    )
    monkeypatch.setattr(
        ba,
        "fetch_web_page_content",
        lambda **k: {"content": "isi" * 300},
    )
    out = ba._research_fallback("tugas", "https://start")
    assert out["status"] == "partial"
    assert len(out["insights_gathered"]) == 2
    assert len(out["insights_gathered"][0]["content_snippet"]) == 500

    monkeypatch.setattr(
        ba,
        "fetch_web_page_content",
        lambda **k: (_ for _ in ()).throw(RuntimeError("fetch")),
    )
    out = ba._research_fallback("tugas", "https://start")
    assert out["status"] == "partial"

    monkeypatch.setattr(ba, "web_search", lambda **k: {"status": "error"})
    out = ba._research_fallback("tugas", "https://start")
    assert out["status"] == "partial" and out["steps"] == []
