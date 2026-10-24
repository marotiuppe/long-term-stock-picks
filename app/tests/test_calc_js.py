import os
import shutil
import subprocess

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_calc_maths_under_node():
    r = subprocess.run([NODE, os.path.join(os.path.dirname(__file__), "test_calc.js")], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "ok" in r.stdout
