"""Phase 6 coverage: universal high-volume scraper engine.

Hermetic: DDGS, HTTP client, direktori export, dan DB SQLite diarahkan ke
``tmp_path``; tidak ada jaringan yang dibuka.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture
def us(monkeypatch, tmp_path):
    from alfa.scrapers import universal as mod

    exports = tmp_path / "exports"
    (exports / "CSV").mkdir(parents=True)
    (exports / "JSON").mkdir(parents=True)
    monkeypatch.setattr(mod, "MASTER_EXPORT_DIR", str(exports))
    monkeypatch.setattr(mod, "DB_PATH", str(tmp_path / "scraper.db"))
    monkeypatch.setattr(
        mod,
        "time",
        SimpleNamespace(time=lambda: 1700000000.0, sleep=lambda seconds: None),
    )
    mod._init_master_scraper_db()
    return mod


class FakeDDGS:
    """Kelas DuckDuckGo palsu: ``text()`` diprogram per tes."""

    queries: list[str] = []
    handler = staticmethod(lambda q, max_results=0: [])

    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query, max_results=0):
        FakeDDGS.queries.append(query)
        return FakeDDGS.handler(query, max_results=max_results)


def _install_ddgs(monkeypatch, us, handler):
    FakeDDGS.queries = []
    FakeDDGS.handler = staticmethod(handler)
    monkeypatch.setattr(us, "DDGS", FakeDDGS)
    return FakeDDGS


def _result(idx, url=None, title="Judul", body=""):
    return {
        "title": title,
        "href": url or f"https://www.tokopedia.com/{idx}",
        "body": body,
    }


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def test_ddgs_retry_success_after_failures(us):
    calls = {"n": 0}

    class DDGS:
        def text(self, query, max_results=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("SSL handshake")  # noqa: TRY003
            return [{"href": "https://x"}]

    out = us._ddgs_text_with_retry(DDGS(), "q", max_results=5)
    assert out == [{"href": "https://x"}]
    assert calls["n"] == 3


def test_ddgs_retry_all_fail_then_raise(us):
    class DDGS:
        def text(self, query, max_results=0):
            raise RuntimeError("rate limit")  # noqa: TRY003

    with pytest.raises(RuntimeError, match="rate limit"):
        us._ddgs_text_with_retry(DDGS(), "q", max_results=5, attempts=2)


def test_ddgs_retry_no_attempts(us):
    class DDGS:
        def text(self, query, max_results=0):  # noqa: ARG002
            raise AssertionError("tidak boleh dipanggil")  # noqa: TRY003

    with pytest.raises(RuntimeError, match="DDGS gagal"):
        us._ddgs_text_with_retry(DDGS(), "q", max_results=5, attempts=0)


# ---------------------------------------------------------------------------
# scrape_universal_keyword
# ---------------------------------------------------------------------------


def test_scrape_keyword_without_ddgs_package(us, monkeypatch):
    monkeypatch.setattr(us, "DDGS", None)
    out = us.scrape_universal_keyword("laptop")
    assert out["status"] == "error"
    assert "ddgs" in out["message"]


def test_scrape_keyword_success_with_fallback(us, monkeypatch, tmp_path):
    def handler(q, max_results=0):
        if q.startswith("site:"):
            return []
        return [
            _result(
                1,
                url="https://www.tokopedia.com/murah",
                title="Murah Berkualitas - Tokopedia",
                body="Harga Rp 50.000 hubungi 081234567890 atau admin@tok.com",
            ),
            _result(
                2,
                url="https://lain.test/x",
                title="Tanpa Info",
                body="Produk bagus",
            ),
        ]

    _install_ddgs(monkeypatch, us, handler)
    out = us.scrape_universal_keyword("laptop murah", category="all_marketplace", limit=10)

    assert out["status"] == "success"
    assert out["total_scraped"] == 2
    assert out["query"] == "laptop murah"
    first = out["items"][0]
    assert first["title"] == "Murah Berkualitas"
    assert first["price"] == "Rp 50.000"
    assert first["phone_wa"] == "081234567890"
    assert first["email"] == "admin@tok.com"
    assert first["domain"] == "tokopedia.com"
    assert first["no"] == 1
    assert out["items"][1]["price"] == "Cek di Halaman"
    assert out["items"][1]["phone_wa"] == "N/A"

    json_path = out["json_path"]
    csv_path = out["csv_path"]
    with open(json_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["total_items"] == 2
    assert "csv_download_url" in out and "json_download_url" in out
    from pathlib import Path

    assert len(Path(csv_path).read_text(encoding="utf-8").splitlines()) == 3

    batches = us.list_all_scrape_batches()
    assert len(batches) == 1
    assert batches[0]["name"].startswith("Scrape_all_marketplace_laptop_murah")
    assert batches[0]["total_items"] == 2


def test_scrape_keyword_hits_limit_without_fallback(us, monkeypatch):
    def handler(q, max_results=0):
        return [
            _result(i, url=f"https://s{i}.test/{i}", title=f"Produk {i}")
            for i in range(max_results)
        ]

    _install_ddgs(monkeypatch, us, handler)
    out = us.scrape_universal_keyword("sepatu", category="shopee", limit=10)
    assert out["status"] == "success"
    assert out["total_scraped"] == 10
    # Query pertama sudah memenuhi limit sehingga fallback tidak dipanggil.
    assert len(FakeDDGS.queries) == 1


def test_scrape_keyword_unknown_category_uses_google_templates(us, monkeypatch):
    def handler(q, max_results=0):
        if "terbaru" in q or "rekomendasi" in q or "review" in q:
            return []
        return [_result(9, url="https://umum.test/1", title="Umum")]

    _install_ddgs(monkeypatch, us, handler)
    out = us.scrape_universal_keyword("gadget", category="kategori_asing", limit=50)
    assert out["status"] == "success"
    assert out["category"] == "kategori_asing"


def test_scrape_keyword_all_queries_fail(us, monkeypatch):
    def handler(q, max_results=0):
        raise OSError("SSL/blokir")  # noqa: TRY003

    _install_ddgs(monkeypatch, us, handler)
    out = us.scrape_universal_keyword("laptop", category="shopee", limit=10)
    assert out["status"] == "error"
    assert out["failed_queries"] > 0
    assert out["items"] == []
    assert "gagal" in out["message"]


def test_scrape_keyword_empty_results_without_failures(us, monkeypatch):
    _install_ddgs(monkeypatch, us, lambda q, max_results=0: [])
    out = us.scrape_universal_keyword("tidakada", limit=10)
    assert out["status"] == "success"
    assert out["total_scraped"] == 0
    assert out["items"] == []


def test_scrape_keyword_deduplicates_urls(us, monkeypatch):
    def handler(q, max_results=0):
        return [
            _result(1, url="https://sama.test/1", title="A"),
            _result(2, url="https://sama.test/1", title="B"),
            _result(3, url="https://sama.test/2", title="C"),
        ]

    _install_ddgs(monkeypatch, us, handler)
    out = us.scrape_universal_keyword("dup", category="shopee", limit=10)
    urls = [i["url"] for i in out["items"]]
    assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# scrape_custom_urls_or_selectors
# ---------------------------------------------------------------------------


def _fake_fast(monkeypatch, results):
    from alfa import scrapers as scrapers_pkg

    fake = types.ModuleType("alfa.scrapers.fast")
    fake.scrape_with_fast_tls = lambda url: results[url]
    fake.scrape_with_camoufox = lambda url: results[url]
    monkeypatch.setitem(sys.modules, "alfa.scrapers.fast", fake)
    monkeypatch.setattr(scrapers_pkg, "fast", fake, raising=False)
    return fake


def test_custom_urls_rejects_empty_list(us, monkeypatch, tmp_path):
    out = us.scrape_custom_urls_or_selectors([])
    assert out["status"] == "error"
    assert "Tidak ada URL valid" in out["message"]

    out = us.scrape_custom_urls_or_selectors(["  ", "ftp://bukan-web"])
    assert out["status"] == "error"


def test_custom_urls_success(us, monkeypatch, tmp_path):
    results = {
        "https://a.test": {
            "status": "success",
            "url": "https://a.test",
            "method": "Fast TLS",
            "data": {
                "title": "Judul Halaman",
                "price": "Rp 9.900",
                "image_url": "https://img/1.jpg",
                "description": "Deskripsi",
            },
        },
        "https://b.test": {
            "status": "success",
            "url": "https://b.test",
            "title": "Judul Cadangan",
            "data": {},
        },
        "https://c.test": {
            "status": "error",
            "url": "https://c.test",
            "error": "timeout",
        },
        "https://d.test": {
            "status": "success",
            "url": "https://d.test",
            "method": "Camoufox",
            "data": {"title": "D", "price": "", "image_url": "", "description": ""},
        },
    }
    _fake_fast(monkeypatch, results)

    out = us.scrape_custom_urls_or_selectors(
        ["https://a.test", " https://b.test ", "https://c.test", "bukan-url"],
        concurrency=2,
    )
    assert out["status"] == "success"
    assert out["total_requested"] == 3
    assert out["total_successful"] == 2
    by_url = {i["url"]: i for i in out["items"]}
    assert by_url["https://a.test"]["title"] == "Judul Halaman"
    assert by_url["https://a.test"]["price"] == "Rp 9.900"
    assert by_url["https://a.test"]["method"] == "Fast TLS"
    assert by_url["https://b.test"]["title"] == "Judul Cadangan"
    assert by_url["https://b.test"]["price"] == "N/A"
    assert by_url["https://c.test"]["title"] == "Gagal Mengambil Data"
    assert by_url["https://c.test"]["description"] == "timeout"

    out2 = us.scrape_custom_urls_or_selectors(["https://d.test"], use_camoufox=True)
    assert out2["items"][0]["method"] == "Camoufox"
    assert out2["items"][0]["title"] == "D"


def test_custom_urls_engine_exception_recorded(us, monkeypatch):
    from alfa import scrapers as scrapers_pkg

    def boom(url):
        raise OSError("koneksi putus")  # noqa: TRY003

    fake = types.ModuleType("alfa.scrapers.fast")
    fake.scrape_with_fast_tls = boom
    fake.scrape_with_camoufox = boom
    monkeypatch.setitem(sys.modules, "alfa.scrapers.fast", fake)
    monkeypatch.setattr(scrapers_pkg, "fast", fake, raising=False)

    out = us.scrape_custom_urls_or_selectors(["https://x.test"])
    assert out["status"] == "success"
    assert out["total_successful"] == 0
    assert out["items"][0]["description"] == "koneksi putus"


# ---------------------------------------------------------------------------
# list_all_scrape_batches
# ---------------------------------------------------------------------------


def test_list_batches_empty(us, monkeypatch, tmp_path):
    assert us.list_all_scrape_batches() == []


def test_list_batches_respects_limit(us, monkeypatch, tmp_path):
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "scraper.db"))
    for i in range(5):
        conn.execute(
            "INSERT INTO master_scrapes (batch_id, name, mode, target, total_items, data_json, csv_file, json_file) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"b{i}", f"Batch {i}", "keyword_shopee", "q", i, "[]", f"csv/{i}", f"json/{i}"),
        )
    conn.commit()
    conn.close()

    items = us.list_all_scrape_batches(limit=2)
    assert len(items) == 2
    assert set(items[0]) >= {
        "id",
        "batch_id",
        "name",
        "mode",
        "target",
        "total_items",
        "csv_download_url",
        "json_download_url",
        "created_at",
    }
    assert "csv_download_url" in items[0]
    assert any("csv/0" in item["csv_download_url"] for item in items)
