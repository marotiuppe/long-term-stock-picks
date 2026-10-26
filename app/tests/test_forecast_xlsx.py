"""The Excel forecast sheet: tomorrow's (or any period's) forecast with a column to type the real close into, and formulas that check it."""
import datetime, io, os, sys, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
from core import forecast_xlsx

openpyxl = pytest.importorskip("openpyxl")

ASOF = datetime.date.today() - datetime.timedelta(days=1)


def stock(sym, price, score, call="WATCH", etf=False, name=None, p10=-0.03, p50=0.0, p90=0.04, pgain=0.5):
    f = {"p10": p10, "p25": p10 / 2, "p50": p50, "p75": p90 / 2, "p90": p90, "pgain": pgain, "n": 1000}
    return {"symbol": sym, "name": name or sym + " Ltd", "exchange": "NSE", "etf": etf, "price": price, "asof": ASOF.isoformat(),
            "score": score, "verdict": call, "forecast": {"1d": f, "1m": dict(f, p10=-0.1, p90=0.12)}}


STOCKS = [stock("LOW", 100.0, 10), stock("TOP", 250.0, 90, call="BUY"), stock("ETFX", 50.0, 40, etf=True),
          stock("EVIL", 10.0, 5, name='=HYPERLINK("http://x","click")')]


def load(raw):
    return openpyxl.load_workbook(io.BytesIO(raw))


def build(**kw):
    return forecast_xlsx.build(STOCKS, kw.get("hz", "1d"), kw.get("days", 1), kw.get("target", ASOF + datetime.timedelta(days=1)), "26 Oct 2026 23:10")


def test_sheets_header_and_one_row_per_stock_best_score_first():
    wb = load(build())
    assert wb.sheetnames == ["Forecast", "Check", "About"]
    ws = wb["Forecast"]
    assert [ws.cell(1, c).value for c in (1, 7, 8, 12, 14, 16, 17, 18)] == [
        "Symbol", "Last close (Rs)", "Forecast for the close of", "Low (Rs)", "High (Rs)", "ACTUAL close (Rs): type it in", "Actual change %", "Inside low to high?"]
    assert ws.max_row == 1 + len(STOCKS)
    assert [ws.cell(r, 1).value for r in range(2, 6)] == ["TOP", "ETFX", "LOW", "EVIL"]       # by score, highest first
    assert ws.freeze_panes == "C2" and ws.auto_filter.ref.startswith("A1:T")


def test_row_values_and_the_forecast_prices():
    ws = load(build())["Forecast"]
    top = {ws.cell(1, c).value: ws.cell(2, c).value for c in range(1, 21)}
    assert top["Symbol"] == "TOP" and top["Type"] == "Stock" and top["Call"] == "Buy" and top["Last close (Rs)"] == 250.0
    assert top["Low case % (10th)"] == -0.03 and top["High case % (90th)"] == 0.04 and top["Chance of a rise"] == 0.5
    assert top["Low (Rs)"] == 242.5 and top["Middle (Rs)"] == 250.0 and top["High (Rs)"] == 260.0      # price x (1 + case)
    assert ws.cell(3, 4).value == "ETF"


def test_dates_are_real_dates_and_the_target_is_the_forecast_date():
    ws = load(build(target=ASOF + datetime.timedelta(days=3)))["Forecast"]
    assert ws.cell(2, 6).value.date() == ASOF and ws.cell(2, 8).value.date() == ASOF + datetime.timedelta(days=3)
    assert "dd-mmm-yyyy" in ws.cell(2, 8).number_format


def test_the_actual_close_column_is_empty_yellow_and_the_checks_are_formulas():
    ws = load(build())["Forecast"]
    for r in range(2, 6):
        assert ws.cell(r, 16).value is None and ws.cell(r, 16).fill.fgColor.rgb.endswith("FFF2B3")
    assert ws["Q2"].value == '=IF(P2="","",P2/G2-1)'
    assert ws["R2"].value == '=IF(P2="","",IF(AND(P2>=L2,P2<=N2),"Yes","No"))'
    assert ws["S2"].value == '=IF(P2="","",IF(P2>G2,"Yes","No"))'
    assert ws["T2"].value == '=IF(P2="","",Q2-J2)'


def test_a_company_name_that_looks_like_a_formula_stays_text():
    ws = load(build())["Forecast"]
    cell = ws.cell(5, 2)
    assert cell.value == '=HYPERLINK("http://x","click")' and cell.data_type == "s"


def test_another_horizon_uses_its_own_forecast():
    ws = load(build(hz="1m", days=20))["Forecast"]
    assert ws["I2"].value == -0.1 and ws["K2"].value == 0.12
    assert "20 trading days" in load(build(hz="1m", days=20))["About"]["A3"].value


def test_stocks_without_a_forecast_for_the_period_are_left_out():
    odd = dict(stock("ODD", 5.0, 1)); odd["forecast"] = {"1m": odd["forecast"]["1m"]}
    wb = load(forecast_xlsx.build(STOCKS + [odd], "1d", 1, ASOF + datetime.timedelta(days=1), "x"))
    assert "ODD" not in [wb["Forecast"].cell(r, 1).value for r in range(2, wb["Forecast"].max_row + 1)]


def test_an_empty_scan_still_makes_a_valid_workbook():
    wb = load(forecast_xlsx.build([], "1d", 1, ASOF, "x"))
    assert wb["Forecast"].max_row == 1 and wb["Check"]["B4"].value.startswith("=COUNTA(")


def test_check_sheet_formulas_calculate_correctly(tmp_path):
    """Type in actual closes and let a formula engine calculate the Check sheet; compare with the same numbers worked out in Python.
    Needs the optional `formulas` package (not a requirement of the app), so it skips without it."""
    pytest.importorskip("formulas")
    import formulas
    wb = load(build())
    ws = wb["Forecast"]
    actual = {2: 255.0, 3: 49.0, 4: 90.0, 5: 12.0}       # TOP rises (inside), ETFX falls (inside), LOW falls out of the range, EVIL rises out of it
    for r, v in actual.items():
        ws.cell(r, 16, v)
    path = str(tmp_path / "filled.xlsx")
    wb.save(path)
    sol = formulas.ExcelModel().loads(path).finish().calculate()
    got = lambda sheet, cell: sol["'[filled.xlsx]%s'!%s" % (sheet.upper(), cell)].value[0, 0]
    price = {2: 250.0, 3: 50.0, 4: 100.0, 5: 10.0}
    low, high = {r: price[r] * 0.97 for r in price}, {r: price[r] * 1.04 for r in price}
    assert got("Check", "B5") == 4
    assert got("Check", "B6") == pytest.approx(sum(low[r] <= actual[r] <= high[r] for r in actual) / 4)
    assert got("Check", "B7") == pytest.approx(sum(actual[r] > price[r] for r in actual) / 4)
    assert got("Forecast", "R4") == "No" and got("Forecast", "S3") == "No" and got("Forecast", "S2") == "Yes"
    assert got("Check", "B11") == 1 and got("Check", "B12") == 1.0     # TOP is the one Buy and it rose


# ---- the endpoint and the button
@pytest.fixture
def srv(monkeypatch):
    monkeypatch.setattr(server, "start_scan", lambda force=False: None)
    monkeypatch.setattr(server, "price_db", lambda: None)
    monkeypatch.setattr(server, "load_scan", lambda: False)
    server._xlsx.clear()
    server.STATE.update(t=1.0, error=None, running=False, data={"generated": "g", "stocks": [dict(s) for s in STOCKS]})
    s = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()
    server._xlsx.clear()


def fetch(url):
    try:
        r = urllib.request.urlopen(url)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_endpoint_returns_a_downloadable_workbook_named_for_the_forecast_date(srv):
    st, h, body = fetch(srv + "/api/forecast.xlsx?hz=1d")
    target = server.add_td(ASOF, 1).isoformat()
    assert st == 200 and h["Content-Type"] == server.XLSX_TYPE
    assert h["Content-Disposition"] == f'attachment; filename="forecast-1d-for-{target}.xlsx"'
    assert body[:2] == b"PK" and load(body)["Forecast"].max_row == 1 + len(STOCKS)


def test_default_period_is_tomorrow_and_other_periods_work(srv):
    assert "forecast-1d-for-" in fetch(srv + "/api/forecast.xlsx")[1]["Content-Disposition"]
    st, h, _ = fetch(srv + "/api/forecast.xlsx?hz=1m")
    assert st == 200 and "forecast-1m-for-" in h["Content-Disposition"]


def test_bad_period_is_refused_and_no_scan_means_try_later(srv):
    assert fetch(srv + "/api/forecast.xlsx?hz=banana")[0] == 400
    server.STATE.update(data=None)
    assert fetch(srv + "/api/forecast.xlsx?hz=1d")[0] == 503


def test_workbook_is_built_once_per_scan_not_once_per_click(srv, monkeypatch):
    built = []
    real = forecast_xlsx.build
    monkeypatch.setattr(forecast_xlsx, "build", lambda *a, **k: (built.append(1), real(*a, **k))[1])
    for _ in range(3):
        fetch(srv + "/api/forecast.xlsx?hz=1d")
    fetch(srv + "/api/forecast.xlsx?hz=2d")
    assert len(built) == 2


def test_the_button_is_on_the_picks_pages_and_follows_the_selected_period():
    js = open(os.path.join(os.path.dirname(__file__), "..", "assets", "js", "picks-table.js"), encoding="utf-8").read()
    assert 'id="xls"' in js and "/api/forecast.xlsx?hz=" in js
    assert "update(){tabs();xlsLabel();" in js and "'1d':'tomorrow'" in js
    csv = js[js.index("/*csv*/"):js.index("/*endcsv*/")]
    assert "forecast.xlsx" not in csv                      # the CSV code region (which another test loads on its own) is untouched


def test_openpyxl_is_a_declared_requirement():
    req = open(os.path.join(os.path.dirname(__file__), "..", "..", "requirements.txt"), encoding="utf-8").read()
    assert "openpyxl" in req
