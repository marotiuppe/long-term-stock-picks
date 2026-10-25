"""A shared link shows the title, a description and the logo card: Open Graph and Twitter tags with absolute URLs, and the image itself."""
import html, os, re, struct, sys, threading, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server

PAGES = ["/", "/index.html", "/stocks.html", "/portfolio.html", "/about.html", "/privacy.html", "/terms.html", "/cookies.html", "/disclaimer.html"]


@pytest.fixture
def srv(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setattr(server, "price_db", lambda: None)
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def metas(text):
    return {m[1]: html.unescape(m[2]) for m in re.findall(r'<meta (property|name)="((?:og|twitter):[a-z:_]+)" content="([^"]*)"', text)}


def fetch(url, headers=None):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"}))
    return r.read(), r.headers


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_a_complete_preview_with_absolute_urls(srv, monkeypatch, path):
    monkeypatch.setenv("SITE_URL", "https://stocks.example.com/")
    m = metas(fetch(srv + path)[0].decode())
    assert m["og:image"] == "https://stocks.example.com/assets/icons/og-image.png" == m["twitter:image"]
    assert m["og:url"] == "https://stocks.example.com" + ("" if path == "/" else path)
    assert m["og:title"] and m["og:description"] and m["og:type"] == "website" and m["twitter:card"] == "summary_large_image"
    assert (m["og:image:width"], m["og:image:height"], m["og:image:type"]) == ("1200", "630", "image/png") and m["og:image:alt"]
    for k in ("og:image", "og:url", "twitter:image"):
        assert m[k].startswith("https://")                      # a relative address does not work for a link preview


def test_title_and_description_come_from_the_page_itself(srv, monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://stocks.example.com")
    m = metas(fetch(srv + "/")[0].decode())
    assert m["og:title"].startswith("Long-Term Stock Picks | NSE buy-and-hold")
    assert "buy date" in m["og:description"].lower()
    p = metas(fetch(srv + "/privacy.html")[0].decode())
    assert p["og:title"] == "Privacy Policy | Long-Term Stock Picks"


def test_app_pages_without_a_description_get_the_default_one(srv, monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://stocks.example.com")
    t = fetch(srv + "/index.html")[0].decode()
    assert t.count('<meta name="description"') == 1 and metas(t)["og:description"] == server.SOCIAL_DESCRIPTION


def test_base_address_comes_from_site_url_then_render_then_the_host_header(srv, monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://long-term-stock-picks.onrender.com")
    assert metas(fetch(srv + "/")[0].decode())["og:image"] == "https://long-term-stock-picks.onrender.com/assets/icons/og-image.png"
    monkeypatch.setenv("SITE_URL", "https://custom.example.org")
    assert metas(fetch(srv + "/")[0].decode())["og:image"].startswith("https://custom.example.org/")
    monkeypatch.delenv("SITE_URL")
    monkeypatch.delenv("RENDER_EXTERNAL_URL")
    host = srv.split("//")[1]
    assert metas(fetch(srv + "/")[0].decode())["og:image"] == f"http://{host}/assets/icons/og-image.png"


def test_a_hostile_host_header_cannot_break_out_of_the_tags(monkeypatch):
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    base = server.site_base({"Host": 'evil.com"><script>alert(1)</script>'})
    assert '"' not in base and "<" not in base and ">" not in base
    out = server.add_social_tags(b"<html><head><title>T</title></head></html>", "/", base).decode()
    assert "<script>" not in out


def test_a_page_that_already_has_the_tags_is_left_alone():
    page = b'<html><head><title>T</title><meta property="og:title" content="Mine"></head></html>'
    assert server.add_social_tags(page, "/", "https://x.example") == page


def test_the_share_image_is_served_and_is_a_1200_by_630_png_under_300kb(srv):
    body, h = fetch(srv + server.SOCIAL_IMAGE)
    assert h["Content-Type"] == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", body[16:24]) == (1200, 630)
    assert len(body) < 300_000                                   # WhatsApp drops preview images above about 300 KB


def test_the_stats_page_is_not_given_a_preview(srv, monkeypatch):
    monkeypatch.setenv("STATS_TOKEN", "x" * 40)
    assert b"og:image" not in fetch(srv + "/stats.html")[0]
