import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(__file__)
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("name", ["test_portfolio_ui.js", "test_holdings_ui.js"])
def test_browser_helpers_under_node(name):
    r = subprocess.run([NODE, os.path.join(HERE, name)], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "ok" in r.stdout
