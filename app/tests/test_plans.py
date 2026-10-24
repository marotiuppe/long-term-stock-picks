import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.plans import FEATURES, PLAN_ORDER, can


def test_order():
    assert PLAN_ORDER == ["free", "pro"]


def test_free_allowed_except_pro_features():
    for f, need in FEATURES.items():
        assert can("free", f) == (need == "free")
        assert can("pro", f) is True
    assert FEATURES["broker_api_sync"] == "pro" and FEATURES["alert_email"] == "pro"
    assert can("free", "portfolio") and not can("free", "broker_api_sync")


def test_user_dict_and_unknowns():
    assert can({"plan": "pro"}, "alert_email")
    assert not can({"plan": "free"}, "alert_email")
    assert not can("free", "nonexistent")
    assert not can("gold", "portfolio")
    assert not can(None, "portfolio")
