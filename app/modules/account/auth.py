"""Accounts: password hashing, input rules, login throttling, session tokens and Groww-id hashing. Pure helpers, no I/O.

Passwords use scrypt (stdlib, N=2^15 r=8 p=3, the OWASP-listed setting for 32 MiB of memory) with a random salt, and the parameters are
stored in the hash string so they can be raised later. Session tokens are 32 random bytes; only their SHA-256 is stored, so a copied
database cannot be used to sign in. Groww account ids are stored only as HMAC-SHA256 under the app's master key.
"""
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time

SCRYPT = (2 ** 15, 8, 3)
MAXMEM = 96 * 1024 * 1024
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
PASSWORD_MIN, PASSWORD_MAX = 10, 200
SESSION_TTL = 30 * 24 * 3600
RECENT_GROWW = 15 * 60          # after a Groww sign-in the user may set a new password without the old one (account recovery)
SID_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


# ---------- passwords ----------
def _b64(b):
    return base64.b64encode(b).decode("ascii")


def hash_password(password, salt=None, params=SCRYPT):
    n, r, p = params
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (n, r, p, _b64(salt), _b64(dk))


def verify_password(password, stored):
    try:
        kind, n, r, p, salt, want = stored.split("$")
        if kind != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=MAXMEM, dklen=32)
        return hmac.compare_digest(_b64(dk), want)
    except (ValueError, TypeError, AttributeError):
        return False


_DUMMY = None


def burn_time(password):
    """Verify against a throwaway hash so an unknown username takes as long as a wrong password."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not-a-real-password")
    verify_password(password, _DUMMY)


def check_username(name):
    name = str(name or "").strip()
    if not USERNAME_RE.match(name):
        raise ValueError("Choose a username of 3 to 32 characters using letters, digits, dot, underscore or hyphen.")
    return name


def check_password(password, username=None):
    if not isinstance(password, str):
        raise ValueError("Enter a password.")
    if len(password) < PASSWORD_MIN:
        raise ValueError("Use a password of at least %d characters." % PASSWORD_MIN)
    if len(password) > PASSWORD_MAX:
        raise ValueError("That password is too long (%d characters at most)." % PASSWORD_MAX)
    if username and password.strip().lower() == str(username).strip().lower():
        raise ValueError("The password cannot be the same as the username.")
    return password


# ---------- throttling ----------
class Limiter:
    """Sliding-window failure counter per key. In memory: it resets when the server restarts, which is acceptable for a local app."""

    def __init__(self, limit, window):
        self.limit, self.window, self.hits, self.lock = limit, window, {}, threading.Lock()

    def wait(self, key, now=None):
        """Seconds until another attempt is allowed (0 when allowed)."""
        now = time.time() if now is None else now
        with self.lock:
            h = [t for t in self.hits.get(key, []) if now - t < self.window]
            self.hits[key] = h
            return int(self.window - (now - h[0])) + 1 if len(h) >= self.limit else 0

    def fail(self, key, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.hits.setdefault(key, []).append(now)
            if len(self.hits) > 5000:       # bound memory
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > self.window]:
                    self.hits.pop(k, None)

    def clear(self, key):
        with self.lock:
            self.hits.pop(key, None)

    def reset(self):
        with self.lock:
            self.hits.clear()


LOGIN_USER = Limiter(5, 15 * 60)     # wrong passwords for one username
LOGIN_IP = Limiter(20, 15 * 60)      # failed sign-ins from one address (password or Groww)
SIGNUP_IP = Limiter(10, 3600)        # accounts created from one address


def reset_limits():
    for l in (LOGIN_USER, LOGIN_IP, SIGNUP_IP):
        l.reset()


def wait_message(seconds):
    m = max(1, (seconds + 59) // 60)
    return "Too many attempts. Wait %d minute%s and try again." % (m, "" if m == 1 else "s")


# ---------- sessions and ids ----------
def new_token():
    return secrets.token_urlsafe(32)          # 43 characters


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def id_hash(kind, value, key):
    """Stable, non-reversible handle for a Groww id. kind is 'v' (vendor_user_id) or 'u' (ucc)."""
    return hmac.new(hashlib.sha256(b"groww-ids:" + key).digest(), ("%s:%s" % (kind, value)).encode("utf-8"), hashlib.sha256).hexdigest()
