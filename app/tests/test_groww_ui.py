import json, os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "..", "modules", "portfolio", "groww.js").replace("\\", "/")


@pytest.mark.skipif(not shutil.which("node"), reason="Node is not installed")
def test_summary_lines():
    code = ("const g=require(%s);console.log(JSON.stringify([g.summary({added:2,updated:1,unchanged:0,skipped:[{symbol:'ZZ',reason:'Not a stock'}],"
            "pledged:[{symbol:'INFY',qty:5}],not_in_groww:['TATSILV']}),g.summary({})]))" % json.dumps(JS))
    out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    a, empty = out
    assert a[0]["tone"] == "ok" and "Groww returned 4 holdings" in a[0]["text"] and "Synced 3: 2 new, 1 updated" in a[0]["text"]
    assert any("ZZ was skipped" in l["text"] for l in a) and any("INFY (5)" in l["text"] for l in a) and any("TATSILV" in l["text"] for l in a)
    assert empty[0]["text"] == "Groww returned no holdings to import."


@pytest.mark.skipif(not shutil.which("node"), reason="Node is not installed")
def test_details_table_lists_every_entry_and_escapes():
    code = ("const g=require(%s);console.log(JSON.stringify([g.detailsTable([{symbol:'TCS',qty:10,avg_price:3500,pledged:2,outcome:'new'},"
            "{symbol:'<b>X</b>',outcome:'skipped',reason:'Not a stock or ETF this app knows'}]),g.detailsTable([]),g.summary({returned:6,added:2,skipped:[{symbol:'A',reason:'r'}]})]))" % json.dumps(JS))
    html, empty, summ = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    assert "(2)" in html and "TCS" in html and "Added" in html and "2 pledged" in html and "Skipped: Not a stock" in html
    assert "<b>X</b>" not in html and "&lt;b&gt;X&lt;/b&gt;" in html          # symbols from Groww are escaped
    assert empty == ""
    assert summ[0]["text"].startswith("Groww returned 6 holdings. Synced 2")


@pytest.mark.skipif(not shutil.which("node"), reason="Node is not installed")
def test_summary_explains_holdings_outside_the_scan():
    code = "const g=require(%s);console.log(JSON.stringify([g.summary({returned:3,added:3,unscanned:['SBL','OILIETF']}),g.summary({returned:1,added:1,unscanned:['SBL']})]))" % json.dumps(JS)
    two, one = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    t = [l["text"] for l in two if "stock scan" in l["text"]][0]
    assert t.startswith("2 holdings (SBL, OILIETF) are not in this app's stock scan") and "counted in the amount invested" in t and "no price" in t
    assert "1 holding (SBL) is not in" in [l["text"] for l in one if "stock scan" in l["text"]][0]
