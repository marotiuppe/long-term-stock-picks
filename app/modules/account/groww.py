"""Read-only holdings sync from Groww, using the signed-in user's own API key and secret (Groww Trading API, Python SDK).

Only two SDK calls are made: get_access_token and get_holdings_for_user. Nothing here places, changes or cancels an order.
Keys are encrypted at rest (Fernet) with a master key kept outside the database (env STOCKPICKS_SECRET_KEY, or the file
app/data/groww.key created on first use). That protects a copied or backed-up users.db; it does not protect against someone who
controls this machine. Keys and secrets are never logged, never returned by the API, and never part of the data export.
"""
import os
import re
import threading
import time

from core.paths import APP_DIR as HERE   # the app folder, not this module's folder
from core.paths import DATA_DIR
KEY_PATH = os.path.join(DATA_DIR, "groww.key")
SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
MIN_GAP = 5           # seconds between syncs for one user (Groww caps access-token requests at 150 a day); short so a typo is not a lockout
FIELD_MAX = 4000
_lock = threading.Lock()
_last = {}


class GrowwError(Exception):
    """A failure the user can understand. kind: rejected, forbidden, rate, unreachable, missing_sdk, bad_response."""
    CODES = {"rejected": 400, "forbidden": 400, "rate": 429, "unreachable": 502, "missing_sdk": 501, "bad_response": 502}

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind, self.message = kind, message

    @property
    def status(self):
        return self.CODES.get(self.kind, 502)


# ---------- encryption ----------
def _fernet_key():
    from cryptography.fernet import Fernet
    key = os.environ.get("STOCKPICKS_SECRET_KEY", "").strip().encode()
    if not key:
        with _lock:
            if not os.path.exists(KEY_PATH):
                os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
                fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(Fernet.generate_key())
            with open(KEY_PATH, "rb") as fh:
                key = fh.read().strip()
    return key


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(_fernet_key())


def encrypt(text):
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token):
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise ValueError("The saved key can no longer be read. Enter it again.")


def hint(api_key):
    """Enough to recognise which key is saved, not enough to use it."""
    k = str(api_key or "")
    return "••••" + k[-4:] if len(k) >= 12 else "saved"


def clean_credentials(key, secret):
    """-> (key, secret), stripped. Raises ValueError with a message the user can act on."""
    key, secret = str(key or "").strip(), str(secret or "").strip()
    if not key or not secret:
        raise ValueError("Enter both the Groww API key and the API secret.")
    for name, v in (("API key", key), ("API secret", secret)):
        if len(v) < 8 or len(v) > FIELD_MAX:
            raise ValueError("The %s looks wrong. Copy it again from the Groww Cloud API Keys page." % name)
        if re.search(r"\s|[\x00-\x1f]", v):
            raise ValueError("The %s has spaces or line breaks in it. Copy it again." % name)
    return key, secret


def rate_ok(uid, now=None):
    now = time.time() if now is None else now
    with _lock:
        if now - _last.get(uid, 0) < MIN_GAP:
            return False
        _last[uid] = now
        return True


# ---------- holdings ----------
def _num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def normalize_holdings(resp):
    """Groww response -> (rows, skipped). rows: {symbol, qty, avg_price, pledged}. A symbol listed twice is combined at its
    weighted average price. Nothing is invented: a row without a usable symbol, quantity and price is skipped with a reason."""
    items = resp.get("holdings") if isinstance(resp, dict) else resp
    if not isinstance(items, list):
        raise GrowwError("bad_response", "Groww answered, but not with a holdings list. Try again later.")
    by, skipped = {}, []
    for h in items:
        if not isinstance(h, dict):
            skipped.append({"symbol": "?", "reason": "Groww sent an entry this app could not read"})
            continue
        sym = str(h.get("trading_symbol") or "").strip().upper()
        if not SYMBOL_RE.match(sym):
            skipped.append({"symbol": sym[:20] or "?", "reason": "Unusual symbol"})
            continue
        qty, avg = _num(h.get("quantity")), _num(h.get("average_price"))
        if qty is None or qty <= 0:
            other = [(label, _num(h.get(k))) for k, label in (("pledge_quantity", "pledged"), ("demat_locked_quantity", "locked in demat"),
                     ("groww_locked_quantity", "locked at Groww"), ("t1_quantity", "T+1"), ("demat_free_quantity", "free in demat"))]
            extra = ", ".join("%s %g" % (label, v) for label, v in other if v)
            # Groww's docs do not say how net quantity relates to these fields, so say what it sent instead of guessing
            skipped.append({"symbol": sym, "reason": "Groww lists no net quantity" + (" (but %s)" % extra if extra else "")})
            continue
        if avg is None or avg <= 0:
            skipped.append({"symbol": sym, "reason": "Groww gave no average price"})
            continue
        cur = by.setdefault(sym, {"symbol": sym, "qty": 0.0, "cost": 0.0, "pledged": 0.0})
        cur["qty"] += qty
        cur["cost"] += qty * avg
        cur["pledged"] += _num(h.get("pledge_quantity")) or 0.0
    rows = []
    for c in by.values():
        q = c["qty"]
        rows.append({"symbol": c["symbol"], "qty": int(q) if q == int(q) else round(q, 4), "avg_price": round(c["cost"] / q, 4),
                     "pledged": c["pledged"]})
    return sorted(rows, key=lambda r: r["symbol"]), skipped


def _scrub(text, *secrets):
    text = str(text or "")
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text[:200]


def _signed_in_call(api_key, secret, sdk, call):
    """Sign in with the user's key and secret, run one read-only SDK call, and turn every failure into a GrowwError."""
    try:
        if sdk is None:
            import growwapi as sdk
        token = sdk.GrowwAPI.get_access_token(api_key=api_key, secret=secret)
        return call(sdk.GrowwAPI(token))
    except ImportError:
        raise GrowwError("missing_sdk", "The Groww library is not installed on this computer. Run: pip install -r requirements.txt")
    except GrowwError:
        raise
    except Exception as e:      # the SDK raises its own types; match by name so a missing or changed SDK cannot crash the server
        name = type(e).__name__
        code = str(getattr(e, "code", ""))
        if name in ("GrowwAPIAuthenticationException",) or code == "401":
            raise GrowwError("rejected", "Groww did not accept this key and secret, or today's approval is missing. Approve the key on the "
                                         "Groww Cloud API Keys page, then try again.")
        if name == "GrowwAPIAuthorisationException" or code == "403":
            raise GrowwError("forbidden", "Groww refused access. Check that your Trading API subscription is active and the key may read holdings.")
        if name == "GrowwAPIRateLimitException" or code == "429":
            raise GrowwError("rate", "Groww says there were too many requests. Wait a minute and try again.")
        if code == "400":
            raise GrowwError("rejected", "Groww said: %s" % _scrub(getattr(e, "msg", "") or "Bad request", api_key, secret))
        if name in ("GrowwAPITimeoutException", "Timeout", "ConnectionError", "ReadTimeout", "ConnectTimeout", "HTTPError", "SSLError"):
            raise GrowwError("unreachable", "Could not reach Groww. Check your internet connection and try again.")
        raise GrowwError("unreachable", "Groww returned an error (%s). Try again later." % name)


def fetch_holdings(api_key, secret, sdk=None):
    """Sign in with the user's key and secret, read holdings once, return normalize_holdings(). Raises GrowwError."""
    return normalize_holdings(_signed_in_call(api_key, secret, sdk, lambda c: c.get_holdings_for_user(timeout=20)))


def fetch_profile(api_key, secret, sdk=None):
    """Who owns this key: {'vendor_user_id', 'ucc'} (strings, either may be empty). Used to sign in with Groww. Raises GrowwError."""
    resp = _signed_in_call(api_key, secret, sdk, lambda c: c.get_user_profile(timeout=20))
    if not isinstance(resp, dict):
        raise GrowwError("bad_response", "Groww answered, but not with an account profile. Try again later.")
    out = {k: str(resp.get(k) or "").strip()[:120] for k in ("vendor_user_id", "ucc")}
    if not (out["vendor_user_id"] or out["ucc"]):
        raise GrowwError("bad_response", "Groww did not return an account id, so it cannot be used to sign in.")
    return out


def master_secret():
    """The app's master key bytes (used to encrypt Groww keys and to hash Groww account ids). Never returned by any API."""
    return _fernet_key()
