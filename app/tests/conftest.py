import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules.stocks import lists


@pytest.fixture(autouse=True)
def isolated_lists(tmp_path, monkeypatch):
    """No test may read or write the owner's real app/data/lists.json or the saved scan in app/cache."""
    monkeypatch.setattr(lists, "PATH", str(tmp_path / "lists.json"))
    import server
    monkeypatch.setattr(server, "scan_file", lambda: str(tmp_path / "scan-latest.pkl"))
    server._seen_scan[0] = server._scan_checked[0] = 0.0      # per-process memory of the saved scan and of the serialized /api/scan
    server._scan_body[:] = [None, b""]
    from core.store import Store
    monkeypatch.setattr(server, "_store", Store(":memory:"))       # a scan run by a test must not write app/data/users.db
    server._views.clear()                                    # page views counted by one test must not leak into the next
