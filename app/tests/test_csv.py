import json, os, shutil, subprocess

import pytest

HTML = os.path.join(os.path.dirname(__file__), "..", "assets", "js", "picks-table.js")
NODE = shutil.which("node")

HARNESS = """
const H=[['10d','10 days'],['1m','1 month'],['3m','3 months'],['6m','6 months']];
const hname=k=>H.find(h=>h[0]==k)[1];
const VL={BUY:'Buy',WAIT:'Wait',WATCH:'Watch',DOWNTREND:'Downtrend'};
const input=JSON.parse(process.argv[1]);
let D=input.D,hz=input.hz;
%s
process.stdout.write(JSON.stringify(toCsv(input.L)));
"""


def run_csv(L, hz="1m"):
    src = open(HTML, encoding="utf-8").read()
    code = src[src.index("/*csv*/"):src.index("/*endcsv*/")]
    D = {"buyDate": "2026-10-26", "sellDates": {"10d": "2026-11-09", "1m": "2026-11-24", "3m": "2027-01-22", "6m": "2027-04-30"}}
    out = subprocess.run([NODE, "-e", HARNESS % code, json.dumps({"D": D, "hz": hz, "L": L})],
                         capture_output=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def stock(sym, name, verdict, price=1234.5):
    fc = {k: {"p10": -0.08, "p50": 0.02, "p90": 0.12, "pgain": 0.61} for k in ("10d", "1m", "3m", "6m")}
    return {"symbol": sym, "name": name, "verdict": verdict, "price": price, "stop": price * 0.9, "stopPct": 0.1, "forecast": fc}


pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def test_csv_matches_rows_and_columns():
    text = run_csv([stock("TCS", "Tata Consultancy Services", "BUY"), stock("INFY", "Infosys", "WATCH")])
    lines = text.lstrip("﻿").strip().split("\r\n")
    assert text.startswith("﻿")              # BOM so Excel reads the rupee sign
    assert len(lines) == 3
    assert lines[0].startswith("Symbol,Name,Call,Price (₹)")
    assert lines[1] == "TCS,Tata Consultancy Services,Buy,1234.5,1111.05,-10,2,-8,12,61,2026-10-26,2026-11-24,NSE"
    assert lines[2].split(",")[10] == ""          # no buy date unless the call is Buy


def test_csv_uses_chosen_horizon():
    text = run_csv([stock("TCS", "Tata", "BUY")], hz="6m")
    assert "over 6 months" in text and text.strip().endswith("2027-04-30,NSE")


def test_csv_quotes_commas_and_blocks_formulas():
    text = run_csv([stock("M&M", 'Mahindra, "M&M" Ltd', "BUY"), stock("X", "=HYPERLINK(1)", "WATCH")])
    assert '"Mahindra, ""M&M"" Ltd"' in text
    assert "'=HYPERLINK(1)" in text


def test_csv_empty_list_has_header_only():
    assert len(run_csv([]).strip().split("\r\n")) == 1


def test_csv_button_is_not_bound_by_the_filter_chip_handler():
    # Regression: the CSV button has class chip, and a bare '.chip' selector gave it the filter handler (browser QA bug)
    src = open(HTML, encoding="utf-8").read()
    assert "querySelectorAll('.chip')" not in src
    assert "querySelectorAll('.chip[data-k]')" in src
