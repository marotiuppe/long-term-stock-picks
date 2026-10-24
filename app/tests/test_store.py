import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.store import Store


@pytest.fixture
def st():
    s = Store(":memory:")
    yield s
    s.close()


def test_defaults(st):
    st.ensure_user("a")
    assert st.get_plan("a") == "free"
    assert st.get_settings("a") == {"budget": 100000.0, "max_loss": 3000.0}
    st.set_settings("a", budget=50000, max_loss=1000)
    assert st.get_settings("a") == {"budget": 50000.0, "max_loss": 1000.0}


def test_holdings_crud_and_isolation(st):
    st.upsert_holding("a", "TCS", 10, 3500.5, "2026-01-02")
    st.upsert_holding("a", "TCS", 12, 3400)
    st.upsert_holding("b", "INFY", 5, 1500)
    a = st.list_holdings("a")
    assert [h["symbol"] for h in a] == ["TCS"] and a[0]["qty"] == 12
    assert [h["symbol"] for h in st.list_holdings("b")] == ["INFY"]
    assert st.delete_holding("b", "TCS") is False
    assert len(st.list_holdings("a")) == 1
    assert st.delete_holding("a", "TCS") is True
    assert st.list_holdings("a") == []


def test_validation(st):
    for args in [("a", "tcs lower!", 1, 1), ("a", "", 1, 1), ("a", "TCS", 0, 1),
                 ("a", "TCS", -1, 1), ("a", "TCS", 1, 0), ("a", "X'; DROP TABLE users;--", 1, 1),
                 ("a", "TCS", "abc", 1)]:
        with pytest.raises(ValueError):
            st.upsert_holding(*args)
    st.upsert_holding("a", "M&M", 1, 1)
    st.upsert_holding("a", "BAJAJ-AUTO", 1, 1)
    assert len(st.list_holdings("a")) == 2


def test_replace_holdings_atomic(st):
    st.upsert_holding("a", "TCS", 1, 1)
    st.replace_holdings("a", [{"symbol": "INFY", "qty": 2, "avg_price": 3}])
    assert [h["symbol"] for h in st.list_holdings("a")] == ["INFY"]
    with pytest.raises(ValueError):
        st.replace_holdings("a", [{"symbol": "TCS", "qty": 1, "avg_price": 1},
                                  {"symbol": "BAD", "qty": -1, "avg_price": 1}])
    assert [h["symbol"] for h in st.list_holdings("a")] == ["INFY"]


def test_watchlist_isolation(st):
    st.add_watch("a", "TCS")
    st.add_watch("a", "TCS")
    st.add_watch("b", "INFY")
    assert st.list_watchlist("a") == ["TCS"]
    assert st.list_watchlist("b") == ["INFY"]
    assert st.remove_watch("b", "TCS") is False
    assert st.remove_watch("a", "TCS") is True
    with pytest.raises(ValueError):
        st.add_watch("a", "bad sym")


def test_alert_dedupe_and_isolation(st):
    assert st.add_alert("a", "k1", "stop", "TCS", "hit", "2026-10-24") is True
    assert st.add_alert("a", "k1", "stop", "TCS", "hit", "2026-10-25") is False
    assert st.add_alert("b", "k1", "stop", "TCS", "hit", "2026-10-24") is True
    assert len(st.list_alerts("a")) == 1
    assert st.list_alerts("a")[0]["read"] is False
    st.mark_alerts_read("a")
    assert st.list_alerts("a")[0]["read"] is True
    assert st.list_alerts("b")[0]["read"] is False


def test_last_calls(st):
    st.set_last_calls("a", {"TCS": "BUY", "INFY": "WAIT"})
    st.set_last_calls("b", {"TCS": "WATCH"})
    assert st.get_last_calls("a") == {"TCS": "BUY", "INFY": "WAIT"}
    st.set_last_calls("a", {"TCS": "WAIT"})
    assert st.get_last_calls("a") == {"TCS": "WAIT"}
    assert st.get_last_calls("b") == {"TCS": "WATCH"}


def _fill(st, uid):
    st.upsert_holding(uid, "TCS", 1, 2)
    st.add_watch(uid, "INFY")
    st.set_settings(uid, budget=1, max_loss=1)
    st.add_alert(uid, "k", "stop", "TCS", "m", "2026-10-24")
    st.set_last_calls(uid, {"TCS": "BUY"})


def test_export_contains_everything(st):
    _fill(st, "a")
    _fill(st, "b")
    e = st.export_user("a")
    assert e["user"]["id"] == "a" and e["plan"] == "free"
    assert len(e["holdings"]) == 1 and e["watchlist"] == ["INFY"]
    assert e["settings"]["budget"] == 1.0 and len(e["alerts"]) == 1
    assert e["last_calls"] == {"TCS": "BUY"}


def test_delete_user_wipes_everything_only_that_user(st):
    _fill(st, "a")
    _fill(st, "b")
    st.delete_user("a")
    for t in ("holdings", "watchlist", "settings", "alerts", "last_calls", "users"):
        col = "id" if t == "users" else "user_id"
        n = st.db.execute("SELECT COUNT(*) FROM %s WHERE %s='a'" % (t, col)).fetchone()[0]
        assert n == 0, t
    assert len(st.list_holdings("b")) == 1 and len(st.list_alerts("b")) == 1
    # re-adding the same alert key after deletion works
    assert st.add_alert("a", "k", "stop", "TCS", "m", "2026-10-24") is True
