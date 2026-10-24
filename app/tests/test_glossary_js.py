import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(__file__)
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_glossary_and_share_under_node():
    r = subprocess.run([NODE, os.path.join(HERE, "test_glossary.js")], capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "ok" in r.stdout
