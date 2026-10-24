"""The database price cache: one row per symbol, whole-history replace, slim rows for filtered-out stocks."""
import datetime

from core import pgdb
from core.store import SCHEMA, Store

D = datetime.date


def bars(n=3, close=100.0):
    return [(D(2026, 10, 1 + i), close + 1, close - 1, close + i, close + i, 1000 + i) for i in range(n)]


def test_roundtrip_keeps_dates_and_numbers():
    st = Store(":memory:")
    st.price_save({"TCS": bars(), "^NSEI": bars(2, 24000.0)})
    got = st.price_load()
    assert got["TCS"] == bars() and got["^NSEI"] == bars(2, 24000.0)
    assert isinstance(got["TCS"][0][0], datetime.date)


def test_slim_rows_keep_only_the_quote():
    st = Store(":memory:")
    q = {"price": 12.5, "prev": 12.0, "asof": "2026-10-23", "why": "thin"}
    st.price_save({"PENNY": q})
    assert st.price_load()["PENNY"] == q
    assert st._all("SELECT bars FROM price_cache")[0]["bars"] is None


def test_save_replaces_the_whole_history():
    st = Store(":memory:")
    st.price_save({"A": bars(5)})
    st.price_save({"A": bars(2, 50.0)})
    assert st.price_load()["A"] == bars(2, 50.0)


def test_fetched_after_skips_older_rows():
    st = Store(":memory:")
    st.price_save({"OLD": bars()}, now=1000.0)
    st.price_save({"NEW": bars()}, now=2000.0)
    assert set(st.price_load(1500.0)) == {"NEW"}
    assert set(st.price_load()) == {"OLD", "NEW"}


def test_empty_and_unreadable_rows_are_skipped():
    st = Store(":memory:")
    assert st.price_save({"X": None, "Y": []}) == 0
    st.price_save({"OK": bars()})
    st._run("INSERT INTO price_cache(symbol, fetched, why, quote, bars) VALUES('BAD', 1, NULL, NULL, ?)", (b"not zlib",))
    assert set(st.price_load()) == {"OK"}


def test_postgres_schema_has_the_price_table_with_bytea():
    sql = " ".join(pgdb.schema_statements(SCHEMA))
    assert "price_cache(symbol TEXT PRIMARY KEY, fetched DOUBLE PRECISION NOT NULL, why TEXT, quote TEXT, bars BYTEA)" in sql
