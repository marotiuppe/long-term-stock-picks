"""Page loads must not redo work: the saved scan is read once, /api/scan is serialized once per scan, responses are compressed."""
import gzip, json, os, sys, threading, time, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core.store import Store


def scan_data(asof="2026-10-23"):
    return {"stocks": [{"symbol": "TCS", "asof": asof, "name": "TCS"}], "buyDate": "2026-10-26", "quotes": {}, "trackReport": "x"}


@pytest.fixture
def db(monkeypatch):
    st = Store(":memory:")
    monkeypatch.setattr(server, "price_db", lambda: st)
    monkeypatch.setattr(server, "backfill_quotes", lambda d: None)
    monkeypatch.setattr(server, "SCAN_CHECK_SECONDS", 0)
    server.STATE.update(t=0, data=None, error=None, running=False)
    server.DETAIL.clear()
    return st


def test_saved_scan_in_the_database_is_read_once_not_on_every_call(db, monkeypatch):
    db.blob_put("scan-latest", {"t": 1000.0, "data": scan_data(), "detail": {"TCS": {"why": "w"}}}, now=1000.5)
    reads = []
    real = Store.blob_get
    monkeypatch.setattr(Store, "blob_get", lambda self, n: (reads.append(n), real(self, n))[1])
    assert server.load_scan() is True and server.STATE["t"] == 1000.0 and server.DETAIL["TCS"]["why"] == "w"
    for _ in range(5):
        assert server.load_scan() is False        # the stamp (1000.5) is above STATE["t"] (1000.0): the old code read the scan again every time
    assert reads == ["scan-latest"]


def test_a_newer_saved_scan_is_picked_up(db):
    db.blob_put("scan-latest", {"t": 1000.0, "data": scan_data(), "detail": {}}, now=1000.5)
    assert server.load_scan() is True
    db.blob_put("scan-latest", {"t": 2000.0, "data": scan_data("2026-10-24"), "detail": {}}, now=2000.5)
    assert server.load_scan() is True and server.STATE["t"] == 2000.0


def test_a_scan_saved_by_this_process_is_not_read_back(db, monkeypatch):
    server.STATE.update(t=time.time(), data=scan_data())
    server.save_scan()
    reads = []
    real = Store.blob_get
    monkeypatch.setattr(Store, "blob_get", lambda self, n: (reads.append(n), real(self, n))[1])
    assert server.load_scan() is False and reads == []


def test_database_checks_for_a_newer_scan_are_spaced_out(db, monkeypatch):
    monkeypatch.setattr(server, "SCAN_CHECK_SECONDS", 3600)
    db.blob_put("scan-latest", {"t": 1000.0, "data": scan_data(), "detail": {}}, now=1000.5)
    asks = []
    real = Store.blob_saved
    monkeypatch.setattr(Store, "blob_saved", lambda self, n: (asks.append(n), real(self, n))[1])
    server.load_scan(); server.load_scan(); server.load_scan()
    assert len(asks) == 1


def test_file_scan_is_read_once_too(tmp_path, monkeypatch):
    import pickle
    monkeypatch.setattr(server, "price_db", lambda: None)
    monkeypatch.setattr(server, "backfill_quotes", lambda d: None)
    server.STATE.update(t=0, data=None, error=None, running=False)
    path = server.scan_file()
    pickle.dump({"t": 1000.0, "data": scan_data(), "detail": {}}, open(path, "wb"))
    loads = []
    real = pickle.load
    monkeypatch.setattr(pickle, "load", lambda f: (loads.append(1), real(f))[1])
    assert server.load_scan() is True
    for _ in range(4):
        assert server.load_scan() is False
    assert len(loads) == 1


@pytest.fixture
def srv(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setattr(server, "price_db", lambda: None)
    server.STATE.update(t=time.time(), error=None, running=False, data=dict(scan_data(), stocks=[
        {"symbol": f"S{i}", "asof": "2026-10-23", "name": "x" * 40} for i in range(400)]))
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def fetch(url, gz):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"} if gz else {})
    r = urllib.request.urlopen(req)
    return r.read(), r.headers


def test_scan_is_gzipped_for_clients_that_accept_it_and_plain_for_the_rest(srv):
    plain, h1 = fetch(srv + "/api/scan", False)
    zipped, h2 = fetch(srv + "/api/scan", True)
    assert h1.get("Content-Encoding") is None and h2["Content-Encoding"] == "gzip" and h2["Vary"] == "Accept-Encoding"
    assert gzip.decompress(zipped) == plain and len(zipped) < len(plain) / 4
    assert json.loads(plain)["status"] == "ready" and len(json.loads(plain)["stocks"]) == 400


def test_scan_json_is_serialized_once_until_something_changes(srv, monkeypatch):
    dumps = []
    real = json.dumps
    monkeypatch.setattr(server.json, "dumps", lambda o, *a, **k: (dumps.append(len(real(o)) > 5000), real(o, *a, **k))[1])
    for _ in range(4):
        fetch(srv + "/api/scan", True)
    assert dumps.count(True) == 1                     # one big serialization for four page loads
    server.STATE["error"] = "boom"                    # something visible in the answer changed
    assert json.loads(fetch(srv + "/api/scan", False)[0])["refreshError"] == "boom"


def test_pages_and_scripts_are_gzipped_and_small_things_are_not(srv):
    body, h = fetch(srv + "/assets/js/common.js", True)
    assert h["Content-Encoding"] == "gzip" and b"function" in gzip.decompress(body)
    body, h = fetch(srv + "/health", True)
    assert h.get("Content-Encoding") is None          # under the size threshold


def test_with_nothing_in_memory_the_saved_scan_is_always_read(db):
    db.blob_put("scan-latest", {"t": 1000.0, "data": scan_data(), "detail": {}}, now=1000.5)
    assert server.load_scan() is True
    server.STATE.update(t=0, data=None)               # memory lost: the next call must read it again even though it was seen
    assert server.load_scan() is True and server.STATE["data"]["buyDate"] == "2026-10-26"


# ---- downloaded files kept in the database instead of a folder that a restart wipes
def test_cachefs_uses_files_when_there_is_no_database(tmp_path):
    from core import cachefs
    assert cachefs.read("a.json", None, str(tmp_path)) is None
    cachefs.write("a.json", b"[1]", None, str(tmp_path))
    data, saved = cachefs.read("a.json", None, str(tmp_path))
    assert data == b"[1]" and abs(saved - time.time()) < 5 and not (tmp_path / "a.json.tmp").exists()


def test_cachefs_uses_the_database_when_there_is_one_and_files_when_a_folder_is_given(tmp_path, monkeypatch):
    from core import cachefs
    st = Store(":memory:")
    monkeypatch.setattr(cachefs, "backend", lambda: st)
    cachefs.write("EQUITY_L.csv", b"SYMBOL\nTCS\n", None, str(tmp_path))
    assert cachefs.read("EQUITY_L.csv", None, str(tmp_path))[0] == b"SYMBOL\nTCS\n" and not os.listdir(tmp_path)
    cachefs.write("x.json", b"{}", str(tmp_path), None)      # an explicit folder (the tests) is always files
    assert os.listdir(tmp_path) == ["x.json"] and cachefs.read("x.json", None, str(tmp_path)) is None


def test_restart_does_not_download_the_nse_list_again(monkeypatch):
    st = Store(":memory:")
    monkeypatch.setattr(server, "price_db", lambda: st)
    monkeypatch.setattr(server.cachefs, "backend", lambda: st)
    downloads = []

    class R:
        def read(self):
            downloads.append(1)
            return b"SYMBOL,NAME OF COMPANY, SERIES\nTCS,Tata Consultancy,EQ\n" + b"".join(b"S%d,Name %d,EQ\n" % (i, i) for i in range(150))
    monkeypatch.setattr(server.urllib.request, "urlopen", lambda *a, **k: R())
    first = server.load_universe()
    assert "TCS" in first and len(downloads) == 1
    again = server.load_universe()                      # a restart: nothing in memory, the database still has the file
    assert again == first and len(downloads) == 1


def test_bhavcopy_and_facts_survive_a_restart_in_the_database(monkeypatch):
    import datetime
    from modules.stocks import bhavcopy
    from core import cachefs, fundamentals
    st = Store(":memory:")
    monkeypatch.setattr(cachefs, "backend", lambda: st)
    calls = []
    monkeypatch.setattr(bhavcopy, "_download", lambda ex, day: calls.append(day) or b"x")
    monkeypatch.setattr(bhavcopy, "parse", lambda raw, ex: {"TCS": {"close": 1}})
    day = datetime.date(2026, 10, 23)
    assert bhavcopy.latest("NSE", today=day) == {"TCS": {"close": 1}} and len(calls) == 1
    bhavcopy._miss.clear()
    assert bhavcopy.latest("NSE", today=day) == {"TCS": {"close": 1}} and len(calls) == 1
    assert st.raw_get("bhav-NSE-2026-10-23.json") is not None
    fetched = []
    getter = lambda url: fetched.append(url) or {"timeseries": {"result": []}}
    fundamentals.get_facts("TCS", getter=getter)
    n = len(fetched)
    fundamentals.get_facts("TCS", getter=getter)
    assert len(fetched) == n and st.raw_get("fund-TCS.json") is not None


# ---- /api/me on every page load must not rewrite the market into the database
def test_set_last_calls_writes_only_what_changed():
    st = Store(":memory:")
    st.set_last_calls("u", {"TCS": "BUY", "INFY": "WAIT"})
    if not hasattr(st.db, "total_changes"):
        pytest.skip("counts changes with sqlite3 only")
    before = st.db.total_changes
    st.set_last_calls("u", {"TCS": "BUY", "INFY": "WAIT"})          # nothing changed: not one row is written
    assert st.db.total_changes == before
    st.set_last_calls("u", {"TCS": "WAIT"})                         # one change and one removal: two rows touched, not the whole set
    assert st.get_last_calls("u") == {"TCS": "WAIT"} and st.db.total_changes - before == 2


def test_me_stores_calls_only_for_held_and_watched_stocks():
    from core import api_me
    st = Store(":memory:")
    scan = {"stocks": [{"symbol": f"S{i}", "verdict": "BUY", "name": "n", "asof": "2026-10-23", "price": 10.0} for i in range(300)],
            "sellDates": {}, "generated": "x"}
    api_me.me_payload(st, "guest", scan)
    assert st.get_last_calls("guest") == {}                        # a visitor with nothing saved leaves nothing behind
    st.add_watch("guest", "S7")
    api_me.me_payload(st, "guest", scan)
    assert st.get_last_calls("guest") == {"S7": "BUY"}


def test_unchanged_pages_and_scripts_answer_304_with_an_etag(srv):
    import urllib.error
    r = urllib.request.urlopen(srv + "/assets/js/common.js")
    tag = r.headers["ETag"]
    assert tag.startswith('W/"') and len(r.read()) > 1000
    req = urllib.request.Request(srv + "/assets/js/common.js", headers={"If-None-Match": tag})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 304 and e.value.read() == b""
    changed = urllib.request.Request(srv + "/assets/js/common.js", headers={"If-None-Match": 'W/"1-1"'})
    assert urllib.request.urlopen(changed).status == 200            # a different copy is sent in full


def test_json_answers_are_never_cached_or_304(srv):
    r = urllib.request.urlopen(srv + "/api/scan")
    assert r.headers.get("ETag") is None and r.headers["Cache-Control"] == "no-store"


def test_get_store_builds_one_store_even_when_two_threads_ask_at_once(monkeypatch):
    built = []

    class Slow:
        def __init__(self, path):
            built.append(path)
            time.sleep(0.2)
    monkeypatch.setattr(server, "Store", Slow)
    monkeypatch.setattr(server, "_store", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    got = []
    ts = [threading.Thread(target=lambda: got.append(server.get_store())) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(built) == 1 and len({id(g) for g in got}) == 1


def test_a_failed_look_for_a_saved_scan_is_retried_at_once(db, monkeypatch):
    monkeypatch.setattr(server, "SCAN_CHECK_SECONDS", 3600)
    db.blob_put("scan-latest", {"t": 1000.0, "data": scan_data(), "detail": {}}, now=1000.5)
    real = Store.blob_saved
    monkeypatch.setattr(Store, "blob_saved", lambda self, n: (_ for _ in ()).throw(OSError("db down")))
    assert server.load_scan() is False
    monkeypatch.setattr(Store, "blob_saved", real)
    assert server.load_scan() is True                  # not blind for the next hour


def test_first_page_load_waits_for_the_startup_load_and_does_not_start_a_scan(db, monkeypatch):
    """At start-up the start-up thread and the first request both load the saved scan. The request used to skip its look (a pause was
    running), see no data and start a full scan."""
    db.blob_put("scan-latest", {"t": 1000.0, "data": scan_data(), "detail": {}}, now=1000.5)
    real = Store.blob_get
    monkeypatch.setattr(Store, "blob_get", lambda self, n: (time.sleep(0.4), real(self, n))[1])     # a slow read
    monkeypatch.setattr(server, "SCAN_CHECK_SECONDS", 3600)
    started = []
    monkeypatch.setattr(server, "start_scan", lambda force=False: started.append(force))
    startup = threading.Thread(target=server.load_scan)
    startup.start()
    time.sleep(0.1)                                     # the start-up thread is now in the middle of reading
    res = server.api_scan(False)                        # the first page load
    startup.join()
    assert res["status"] == "ready" and started == []
