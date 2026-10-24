import copy, datetime, json, os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core import update_holidays as uh

D = datetime.date


def nse(*dates):
    return {"CM": [{"tradingDate": d} for d in dates]}


# full 2026 list in NSE's date format (16 weekdays, same as the stored official list)
GOOD_2026 = nse(*[D.fromisoformat(d).strftime("%d-%b-%Y") for d in
                  json.load(open(uh.PATH, encoding="utf-8"))["years"]["2026"]["dates"]])


@pytest.fixture
def stored(tmp_path):
    path = tmp_path / "holidays.json"
    path.write_text((open(uh.PATH, encoding="utf-8").read()), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def restore_server_holidays():
    old = server.HOLIDAY_DOC
    yield
    server.set_holidays(old)


def test_add_td_skips_listed_2027_holiday():
    # 2027-01-26 (Tue) is a listed holiday: 1 trading day after Mon 25 Jan is Wed 27 Jan
    assert server.add_td(D(2027, 1, 25), 1) == D(2027, 1, 27)


def test_add_td_skips_weekend_and_holiday_in_2026():
    assert server.add_td(D(2026, 12, 24), 1) == D(2026, 12, 28)   # 25 Dec holiday, then weekend


def test_plan_crossing_2027_is_provisional():
    w = server.holiday_warnings(["2026-12-30", "2027-03-01"])
    assert w == {"2027": "provisional"}


def test_official_year_has_no_warning():
    assert server.holiday_warnings(["2026-11-02"]) == {}


def test_removed_year_shows_missing_warning():
    doc = copy.deepcopy(server.HOLIDAY_DOC)
    del doc["years"]["2027"]
    server.set_holidays(doc)
    assert server.holiday_warnings(["2027-03-01"]) == {"2027": "missing"}
    assert D(2027, 1, 26) not in {D.fromisoformat(d) for d in server.NSE_HOLIDAYS}


def test_good_response_updates_one_year_and_keeps_provisional(stored):
    changed, _ = uh.update(stored, D(2026, 12, 2), lambda: GOOD_2026)
    doc = uh.load(stored)
    assert changed and doc["years"]["2026"]["checked"] == "2026-12-02"
    assert doc["years"]["2026"]["status"] == "official"
    assert doc["years"]["2027"]["status"] == "provisional" and doc["years"]["2028"]["status"] == "provisional"
    assert doc["lastCheck"] == "2026-12-02"


@pytest.mark.parametrize("bad", [{}, {"CM": []}, {"CM": [{"tradingDate": "nonsense"}] * 12}, nse("26-Jan-2026"),
                                 [], None, {"FO": []}])
def test_bad_response_changes_nothing(stored, bad):
    before = open(stored, encoding="utf-8").read()
    changed, msgs = uh.update(stored, D(2026, 12, 2), lambda: bad)
    assert not changed and "keeping stored list" in msgs[0]
    assert open(stored, encoding="utf-8").read() == before


def test_network_error_changes_nothing(stored):
    def boom():
        raise OSError("blocked")
    before = open(stored, encoding="utf-8").read()
    assert uh.update(stored, D(2026, 12, 2), boom)[0] is False
    assert open(stored, encoding="utf-8").read() == before


def test_official_year_not_replaced_by_shorter_list(stored):
    shorter = nse(*[f"{d:02d}-Jan-2026" for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15)])   # 11 weekdays, official has 16
    changed, msgs = uh.update(stored, D(2026, 12, 2), lambda: shorter)
    doc = uh.load(stored)
    assert len(doc["years"]["2026"]["dates"]) == 16
    assert any("2026" in m and "stored list" in m for m in msgs)


def test_weekend_dates_are_dropped():
    out = uh.parse_cm(nse("26-Jan-2026", "03-Mar-2026", "26-Mar-2026", "31-Mar-2026", "03-Apr-2026", "14-Apr-2026",
                          "01-May-2026", "28-May-2026", "26-Jun-2026", "14-Sep-2026", "02-Oct-2026", "28-Mar-2026"))
    assert "2026-03-28" not in out[2026]   # Saturday


def test_schedule():
    doc = {"lastCheck": "2026-10-24", "years": {}}
    assert not uh.due(doc, D(2026, 10, 24))        # already checked today
    assert not uh.due(doc, D(2026, 11, 5))         # mid-month, recent
    assert uh.due(doc, D(2026, 11, 1))             # the 1st
    assert uh.due(doc, D(2026, 12, 2))             # December: daily
    assert uh.due(doc, D(2026, 12, 3) + datetime.timedelta(days=40))   # overdue catch-up
    assert uh.due({"lastCheck": None, "years": {}}, D(2026, 10, 24))   # never checked


def test_maybe_update_skips_when_not_due(stored):
    doc = uh.load(stored)
    doc["lastCheck"] = "2026-10-24"
    uh.save(doc, stored)
    called = []
    changed, _ = uh.maybe_update(stored, D(2026, 11, 5), lambda: called.append(1))
    assert not changed and not called


def test_stale_alert_after_45_days():
    assert uh.stale_alert({"lastCheck": "2026-10-24"}, D(2026, 11, 20)) is None
    assert "46 days" in uh.stale_alert({"lastCheck": "2026-10-24"}, D(2026, 12, 9))
