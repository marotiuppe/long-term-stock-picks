import json, os, shutil, subprocess, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import api_me
from core.store import Store, NOTE_MAX

U = {"TCS", "INFY"}


def h(st, uid, method, path, body=None, query=""):
    return api_me.handle(method, path, query, json.dumps(body).encode() if body is not None else b"", st, uid, {"stocks": []}, U)


def test_store_crud_and_isolation():
    s = Store(":memory:")
    assert s.get_note("a", "TCS") == {"symbol": "TCS", "text": "", "updated": None}
    s.set_note("a", "tcs", "<b>hello</b>\nline2")
    s.set_note("b", "TCS", "mine")
    assert s.get_note("a", "TCS")["text"] == "<b>hello</b>\nline2"
    assert s.get_note("b", "TCS")["text"] == "mine"
    s.set_note("a", "TCS", "v2")
    assert s.get_note("a", "TCS")["text"] == "v2" and len(s.list_notes("a")) == 1
    assert s.list_notes("a")[0]["preview"] == "v2"
    s.set_note("a", "TCS", "   ")          # blank deletes
    assert s.list_notes("a") == [] and s.get_note("b", "TCS")["text"] == "mine"
    assert s.delete_note("b", "TCS") and not s.delete_note("b", "TCS")


def test_validation():
    s = Store(":memory:")
    with pytest.raises(ValueError):
        s.set_note("a", "bad sym!", "x")
    with pytest.raises(ValueError):
        s.set_note("a", "TCS", "x" * (NOTE_MAX + 1))
    with pytest.raises(ValueError):
        s.set_note("a", "TCS", 123)
    s.set_note("a", "TCS", "x" * NOTE_MAX)
    assert len(s.get_note("a", "TCS")["text"]) == NOTE_MAX


def test_export_and_delete_include_notes():
    s = Store(":memory:")
    s.set_note("a", "TCS", "keep")
    assert s.export_user("a")["notes"][0]["text"] == "keep"
    s.delete_user("a")
    assert s.list_notes("a") == [] and s.export_user("a")["notes"] == []


def test_api_handler():
    s = Store(":memory:")
    assert h(s, "a", "PUT", "/api/notes", {"symbol": "TCS", "text": "hi"})[1]["text"] == "hi"
    assert h(s, "a", "GET", "/api/notes", query="sym=TCS")[1]["text"] == "hi"
    assert h(s, "b", "GET", "/api/notes", query="sym=TCS")[1]["text"] == ""
    assert h(s, "a", "GET", "/api/notes")[1]["notes"][0]["symbol"] == "TCS"
    code, r = h(s, "a", "POST", "/api/notes", {"symbol": "TCS", "text": "y" * 5001})
    assert code == 400 and "5000" in r["error"]
    assert h(s, "a", "GET", "/api/notes", query="sym=bad!")[0] == 400
    assert h(s, "a", "POST", "/api/notes", {"text": "x"})[0] == 400
    assert h(s, "a", "DELETE", "/api/notes", query="sym=TCS") == (200, {"deleted": True})
    assert h(s, "a", "PUT", "/api/notes", {"symbol": "TCS", "text": "z"})[0] == 200
    assert h(s, "a", "PUT", "/api/notes", {"symbol": "TCS", "text": ""})[1]["text"] == ""
    assert h(s, "a", "GET", "/api/notes")[1]["notes"] == []


def test_import_ignores_notes():
    data = {"lots": [{"symbol": "TCS", "side": "buy", "qty": 1, "price": 10, "date": "2026-01-01"}], "notes": [{"symbol": "TCS", "text": "x"}]}
    s = Store(":memory:")
    code, r = api_me.handle("POST", "/api/transactions/import", "", json.dumps({"format": "json", "data": data}).encode(), s, "a", {"stocks": []}, U)
    assert code == 200 and s.list_notes("a") == []


def test_same_origin_enforced_for_writes():
    assert not api_me.same_origin({"Origin": "http://evil.example", "Host": "localhost:8000"})
    assert api_me.same_origin({"Origin": "http://localhost:8000", "Host": "localhost:8000"})


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_helpers():
    js = os.path.join(os.path.dirname(__file__), "..", "modules", "stock", "notes.js").replace("\\", "/")
    code = ("const h=require(%s);" % json.dumps(js) +
            "console.log(JSON.stringify([h.counter(1234),h.statusText({text:'a',saved:'',saving:false}),h.statusText({err:true,text:'a',saved:'a'}),"
            "h.statusText({text:'a',saved:'a',savedAt:new Date(2026,0,1,14,32)})]))")
    out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    assert out == ["1,234 / 5,000", "Saving…", "Could not save, retry", "Saved 14:32"]
