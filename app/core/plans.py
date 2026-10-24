"""Plans and feature flags (P7). Everything is free today except two pro-only features."""

PLAN_ORDER = ["free", "pro"]

FEATURES = {
    "scan": "free",
    "watchlist": "free",
    "portfolio": "free",
    "portfolio_import": "free",
    "alerts": "free",
    "csv_export": "free",
    "data_export": "free",
    "all_horizons": "free",
    "broker_api_sync": "pro",
    "alert_email": "pro",
}


def can(plan, feature):
    """plan is a plan name or a dict with a 'plan' key. Unknown feature or plan -> False."""
    if isinstance(plan, dict):
        plan = plan.get("plan")
    need = FEATURES.get(feature)
    if need is None or plan not in PLAN_ORDER:
        return False
    return PLAN_ORDER.index(plan) >= PLAN_ORDER.index(need)
