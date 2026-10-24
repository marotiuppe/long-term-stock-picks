"""The service pings its own public /health so a free host does not put it to sleep."""
import os, sys, threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server


def test_url_comes_from_keepalive_url_then_render_and_is_none_locally(monkeypatch):
    monkeypatch.delenv("KEEPALIVE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert server.keepalive_url() is None
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://app.onrender.com/")
    assert server.keepalive_url() == "https://app.onrender.com/health"
    monkeypatch.setenv("KEEPALIVE_URL", "https://example.com")
    assert server.keepalive_url() == "https://example.com/health"
    monkeypatch.setenv("KEEPALIVE_URL", "not a url")
    assert server.keepalive_url() is None


def test_keepalive_calls_the_url_and_survives_errors():
    stop, calls = threading.Event(), []

    def opener(u):
        calls.append(u)
        if len(calls) == 1:
            raise OSError("offline")
        if len(calls) == 3:
            stop.set()
    server.keepalive(stop, "https://app.onrender.com/health", every=0.01, opener=opener)
    assert calls == ["https://app.onrender.com/health"] * 3
