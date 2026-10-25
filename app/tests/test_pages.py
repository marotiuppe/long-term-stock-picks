import os
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server

APP = os.path.join(os.path.dirname(__file__), "..")
LANDING = "modules/landing/landing.html"   # served at "/"; it is not an app-shell page
PAGES = {"/index.html": "modules/home/index.html", "/stocks.html": "modules/stocks/stocks.html",
         "/etfs.html": "modules/stocks/etfs.html", "/bse.html": "modules/stocks/bse.html", "/portfolio.html": "modules/portfolio/portfolio.html",
         "/about.html": "modules/about/about.html", "/stock.html": "modules/stock/stock.html", "/settings.html": "modules/settings/settings.html",
         "/account.html": "modules/account/account.html"}


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setitem(server.STATE, "data", None)
    monkeypatch.setitem(server.STATE, "running", True)
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    s.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def get(url):
    try:
        r = OPENER.open(url, timeout=5)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, r.headers, r.read()


def page(name):
    return open(os.path.join(APP, name), "rb").read()


@pytest.mark.parametrize("path,file", sorted(PAGES.items()))
def test_each_page_serves_its_own_file(base, path, file):
    st, h, body = get(base + path)
    assert st == 200 and body == page(file)
    assert h["Content-Type"].startswith("text/html")
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]


def test_pages_differ(base):
    assert len({page(f) for f in set(PAGES.values())}) == len(set(PAGES.values()))


@pytest.mark.parametrize("old,new", [("/stocks", "/stocks.html"), ("/etfs", "/etfs.html"), ("/portfolio", "/portfolio.html"),
                                     ("/bse", "/bse.html"), ("/about", "/about.html"), ("/settings", "/settings.html"),
                                     ("/stock/TCS", "/stock.html?symbol=TCS"), ("/stock/M%26M", "/stock.html?symbol=M%26M"),
                                     ("/stock/TCS/", "/stock.html?symbol=TCS")])
def test_old_urls_redirect_to_the_new_pages(base, old, new):
    st, h, _ = get(base + old)
    assert st == 301 and h["Location"] == new


@pytest.mark.parametrize("path", ["/nothing", "/stock", "/stock/", "/stock/a/b", "/stocks/x", "/stock/<script>", "/portfolio/x", "/bse2",
                                  "/assets/js/nope.js", "/assets/js/../server.py", "/assets/css/x.html", "/assets/data/users.db", "/portfolio.js", "/chart.js",
                                  # a screen's folder holds Python and page sources next to its JS and CSS: only .js and .css may be served
                                  "/modules/stock/why.py", "/modules/portfolio/rules.py", "/modules/account/auth.py", "/modules/account/groww.py",
                                  "/modules/stock/stock.html", "/modules/stock/__init__.py", "/modules/stock/nope.js", "/modules/../server.py",
                                  "/modules/stock/../../server.py", "/modules/", "/modules/stock", "/modules/stock/", "/core/store.py", "/server.py",
                                  "/modules/Stock/stock.js", "/modules/stock/stock.js/x", "/modules/stock/..%2f..%2fserver.py"])
def test_unknown_paths_404(base, path):
    assert get(base + path)[0] == 404


@pytest.mark.parametrize("path,ctype", [("/assets/css/tokens.css", "text/css"), ("/assets/css/layout.css", "text/css"),
                                        ("/assets/css/components.css", "text/css"), ("/assets/js/shell.js", "javascript"),
                                        ("/assets/js/common.js", "javascript"), ("/assets/js/chart.js", "javascript"),
                                        ("/assets/js/holdings.js", "javascript"), ("/assets/js/attention.js", "javascript"), ("/assets/css/chart.css", "text/css"),
                                        # each screen's own page script and styles
                                        ("/modules/settings/settings.js", "javascript"), ("/modules/stock/stock.js", "javascript"),
                                        ("/modules/stock/tools.css", "text/css"), ("/modules/account/account.css", "text/css"),
                                        ("/modules/portfolio/portfolio.js", "javascript"), ("/modules/home/index.js", "javascript")])
def test_shared_assets_are_served(base, path, ctype):
    st, h, body = get(base + path)
    assert st == 200 and ctype in h["Content-Type"] and body


def test_api_unchanged(base):
    assert get(base + "/api/scan")[0] == 200
    assert get(base + "/api/stock?sym=NOPE")[0] == 404


def test_every_page_loads_the_shared_files_and_only_existing_ones():
    for f in sorted(set(PAGES.values())):
        t = page(f).decode()
        for need in ('href="/assets/css/tokens.css"', 'href="/assets/css/layout.css"', 'href="/assets/css/components.css"',
                     'src="/assets/js/shell.js"', 'src="/assets/js/common.js"', "<main id=\"app\""):
            assert need in t, (f, need)
        assert t.index("shell.js") < t.index("common.js")
        assert re.search(r'data-page="\w+" data-title="[^"]+"', t), f
        for ref in re.findall(r'(?:src|href)="(/(?:assets|modules)/[^"]+)"', t):
            assert os.path.isfile(os.path.join(APP, ref[1:])), (f, ref)
    # the shell is shared, not pasted into each page
    for f in set(PAGES.values()):
        assert b'aria-label="Main"' not in page(f)


def test_shell_has_nav_and_links():
    t = open(os.path.join(APP, "assets", "js", "shell.js"), encoding="utf-8").read()
    for href in ("/index.html", "/stocks.html", "/etfs.html", "/bse.html", "/portfolio.html", "/settings.html", "/about.html"):
        assert href in t
    assert 'aria-label="Main"' in t and "aria-current" in t and "localStorage" in t


def test_portfolio_script_loads_before_the_page_script():
    t = page("modules/portfolio/portfolio.html").decode()
    assert t.index("/modules/portfolio/portfolio.js") < t.index("/modules/portfolio/portfolio-page.js")


def test_csv_and_import_code_markers_exist():
    t = open(os.path.join(APP, "assets", "js", "picks-table.js"), encoding="utf-8").read()
    assert "/*csv*/" in t and "/*endcsv*/" in t and "/*imp*/" in t and "/*endimp*/" in t


def test_manifest_makes_the_app_installable(base):
    import json
    st, h, body = get(base + "/manifest.webmanifest")
    m = json.loads(body)
    assert st == 200 and "manifest+json" in h["Content-Type"]
    assert m["display"] == "standalone" and m["start_url"] == "/index.html" and m["short_name"]
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes and any(i["purpose"] == "maskable" for i in m["icons"])
    for i in m["icons"]:
        s2, h2, b2 = get(base + i["src"])
        assert s2 == 200 and h2["Content-Type"] == "image/png" and b2[:4] == b"\x89PNG"


def test_every_page_links_the_manifest_and_covers_the_safe_area():
    for f in sorted(set(PAGES.values()) | {LANDING}):
        t = page(f).decode()
        assert 'rel="manifest" href="/manifest.webmanifest"' in t and "viewport-fit=cover" in t, f


@pytest.mark.parametrize("path", ["/assets/icons/../../server.py", "/assets/icons/x.js", "/assets/js/icon.png", "/assets/icons/nope.png"])
def test_icon_folder_serves_only_images(base, path):
    assert get(base + path)[0] == 404


def test_landing_page_is_served_at_root_and_the_app_home_at_index(base):
    st, h, body = get(base + "/")
    assert st == 200 and "text/html" in h["Content-Type"]
    assert b"Long-term stock picks" in body and b'href="/index.html"' in body and b'id="main"' in body
    assert b"No proven edge" in body or b"no proven edge" in body.lower()      # the honest numbers stay on the front page
    st2, h2, home = get(base + "/index.html")
    assert st2 == 200 and b'data-page="home"' in home and b"landing.css" not in home


def test_landing_page_files_load_and_it_defaults_to_dark(base):
    t = page(LANDING).decode()
    assert '<html lang="en" data-theme="dark">' in t
    for ref in re.findall(r'(?:src|href)="(/(?:assets|modules)/[^"]+)"', t):
        assert os.path.isfile(os.path.join(APP, ref[1:])), ref
        assert get(base + ref)[0] == 200, ref
    css = open(os.path.join(APP, "assets", "css", "tokens.css"), encoding="utf-8").read()
    assert "@media(prefers-color-scheme:dark)" not in css      # dark is the default; light only when chosen
    assert ":root:not([data-theme=light]){" in css
    js = open(os.path.join(APP, "assets", "js", "shell.js"), encoding="utf-8").read()
    assert "prefers-color-scheme" not in js and "t === 'light' ? 'light' : 'dark'" in js


def test_manifest_colors_match_the_dark_default():
    import json
    m = json.load(open(os.path.join(APP, "manifest.webmanifest"), encoding="utf-8"))
    assert m["background_color"] == "#0F1419" and m["theme_color"] == "#0F1419"
