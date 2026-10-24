import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.skipif(not shutil.which("node"), reason="Node is not installed")
def test_account_helpers():
    r = subprocess.run(["node", os.path.join(HERE, "test_account.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_account_page_wiring():
    app = os.path.join(HERE, "..")
    html = open(os.path.join(app, "modules", "account", "account.html"), encoding="utf-8").read()
    assert 'data-page="account"' in html and "account.js" in html and "account.css" in html
    shell = open(os.path.join(app, "assets", "js", "shell.js"), encoding="utf-8").read()
    assert "/account.html" in shell and "/api/auth/me" in shell and "window.Auth" in shell
