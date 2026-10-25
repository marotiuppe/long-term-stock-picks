"""SQLite persistence (P3), or PostgreSQL when a database URL is given (core/pgdb.py). Every method is scoped by user_id; SQL is parameterised only."""
import datetime
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import zlib

from modules.portfolio import positions
from modules.portfolio import rules

SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
DEFAULT_SETTINGS = {"budget": 100000.0, "max_loss": 3000.0}
SCHEMA_VERSION = 2   # PRAGMA user_version. 1: holdings as one row per symbol. 2: transactions (lots), rule settings, alert state.

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, plan TEXT NOT NULL DEFAULT 'free', created TEXT);
CREATE TABLE IF NOT EXISTS holdings(user_id TEXT NOT NULL, symbol TEXT NOT NULL, qty REAL NOT NULL,
  avg_price REAL NOT NULL, first_buy_date TEXT, source TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS watchlist(user_id TEXT NOT NULL, symbol TEXT NOT NULL, PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS settings(user_id TEXT PRIMARY KEY, budget REAL NOT NULL, max_loss REAL NOT NULL);
CREATE TABLE IF NOT EXISTS alerts(user_id TEXT NOT NULL, key TEXT NOT NULL, kind TEXT, symbol TEXT,
  message TEXT, date TEXT, read INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id, key));
CREATE TABLE IF NOT EXISTS last_calls(user_id TEXT NOT NULL, symbol TEXT NOT NULL, verdict TEXT,
  PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS lots(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK(side IN ('buy','sell')), qty REAL NOT NULL, price REAL NOT NULL, date TEXT,
  fees REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', created TEXT);
CREATE INDEX IF NOT EXISTS lots_user_symbol ON lots(user_id, symbol);
CREATE TABLE IF NOT EXISTS rule_settings(user_id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS holding_settings(user_id TEXT NOT NULL, symbol TEXT NOT NULL, target_weight REAL,
  review_price REAL, sector TEXT, PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS alert_state(user_id TEXT NOT NULL, key TEXT NOT NULL, state TEXT NOT NULL,
  until TEXT, fingerprint TEXT NOT NULL, PRIMARY KEY(user_id, key));
CREATE TABLE IF NOT EXISTS groww_creds(user_id TEXT PRIMARY KEY, key_enc TEXT NOT NULL, secret_enc TEXT NOT NULL, hint TEXT,
  saved TEXT, last_sync TEXT, last_count INTEGER);
CREATE TABLE IF NOT EXISTS accounts(user_id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, pw_hash TEXT, created TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS groww_ids(id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS groww_ids_user ON groww_ids(user_id);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, via TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS results_seen(user_id TEXT NOT NULL, symbol TEXT NOT NULL, quarter_end TEXT NOT NULL,
  detected TEXT, PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS notes(user_id TEXT NOT NULL, symbol TEXT NOT NULL, text TEXT NOT NULL, updated TEXT,
  PRIMARY KEY(user_id, symbol));
CREATE TABLE IF NOT EXISTS price_alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, symbol TEXT NOT NULL,
  kind TEXT NOT NULL, value REAL NOT NULL, created TEXT, last_fired TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS price_alerts_user ON price_alerts(user_id, symbol);
CREATE TABLE IF NOT EXISTS page_views(day TEXT NOT NULL, path TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, path));
CREATE TABLE IF NOT EXISTS blobs(name TEXT PRIMARY KEY, saved REAL NOT NULL, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS price_cache(symbol TEXT PRIMARY KEY, fetched REAL NOT NULL, why TEXT, quote TEXT, bars BLOB);
"""
NOTE_MAX = 5000
PRICE_ALERT_MAX = 20
PRICE_ALERT_KINDS = ("below", "above", "off_high")


def _symbol(sym):
    s = str(sym or "").strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValueError("invalid symbol: %r" % (sym,))
    return s


def _positive(v, name):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if not f > 0 or f == float("inf"):
        raise ValueError("%s must be > 0" % name)
    return f


class Store:
    def __init__(self, path=":memory:"):
        self._lock = threading.RLock()
        self.path = path
        self.pg = str(path).startswith(("postgres://", "postgresql://"))
        with self._lock:
            if self.pg:
                from core import pgdb
                self.db = pgdb.PgConnection(path)
                self.db.init_schema(SCHEMA)   # a new database has no version-1 data to migrate
                return
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(SCHEMA)
            self.db.commit()
            self._migrate()

    def _migrate(self):
        """Version 1 kept one (qty, average price) row per symbol. Version 2 keeps transactions. Each old row becomes one
        opening buy, so quantity and average price are unchanged. A copy of the database file is kept first."""
        ver = self.db.execute("PRAGMA user_version").fetchone()[0]
        if ver >= SCHEMA_VERSION:
            return
        old = self.db.execute("SELECT user_id, symbol, qty, avg_price, first_buy_date FROM holdings").fetchall()
        if old and self.path != ":memory:" and os.path.exists(self.path):
            try:
                shutil.copyfile(self.path, self.path + ".bak-v1")
            except OSError:
                pass
        try:
            for r in old:
                self.db.execute("INSERT INTO lots(user_id, symbol, side, qty, price, date, fees, note, created) VALUES(?,?,?,?,?,?,0,?,?)",
                                (r["user_id"], r["symbol"], "buy", r["qty"], r["avg_price"], r["first_buy_date"],
                                 "Opening position entered before transactions were tracked", time.strftime("%Y-%m-%d")))
            self.db.execute("DELETE FROM holdings")
            self.db.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _integrity_errors(self):
        return (sqlite3.IntegrityError, self.db.IntegrityError) if self.pg else sqlite3.IntegrityError

    def _run(self, sql, args=()):
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # users
    def ensure_user(self, uid):
        uid = str(uid)
        self._run("INSERT OR IGNORE INTO users(id, plan, created) VALUES(?, 'free', ?)",
                  (uid, time.strftime("%Y-%m-%d")))
        return uid

    def get_plan(self, uid):
        r = self._all("SELECT plan FROM users WHERE id=?", (str(uid),))
        return r[0]["plan"] if r else "free"

    # holdings: derived from transactions (lots)
    def _positions(self, uid):
        by = {}
        for l in self._all("SELECT id, symbol, side, qty, price, date, fees, note FROM lots WHERE user_id=? ORDER BY symbol, id", (str(uid),)):
            by.setdefault(l["symbol"], []).append(l)
        return by

    def list_holdings(self, uid):
        out = []
        for sym, ls in sorted(self._positions(uid).items()):
            try:
                p = positions.replay(ls)
            except ValueError:
                continue
            if p["qty"] > 0:
                out.append({"symbol": sym, "qty": p["qty"], "avg_price": p["avg_cost"], "first_buy_date": p["first_buy"],
                            "source": "lots", "invested": p["invested"], "realized": p["realized"]})
        return out

    def list_positions(self, uid):
        """Every symbol that has transactions, including fully sold ones: {symbol: replay() result}."""
        out = {}
        for sym, ls in self._positions(uid).items():
            try:
                out[sym] = positions.replay(ls)
            except ValueError:
                continue
        return out

    def list_lots(self, uid, symbol=None):
        q, a = "SELECT id, symbol, side, qty, price, date, fees, note FROM lots WHERE user_id=?", [str(uid)]
        if symbol:
            q += " AND symbol=?"
            a.append(_symbol(symbol))
        rows = self._all(q + " ORDER BY symbol, COALESCE(date,'0000'), id", tuple(a))
        for r in rows:
            r["qty"] = positions._n(r["qty"])      # whole shares read back as 400, not 400.0
        return rows

    def _check_history(self, uid, symbol):
        positions.replay(self._all("SELECT id, symbol, side, qty, price, date, fees FROM lots WHERE user_id=? AND symbol=?", (str(uid), symbol)))

    def add_lot(self, uid, lot):
        """lot: output of positions.validate_lot. Raises ValueError (and stores nothing) if the history stops adding up."""
        self.ensure_user(uid)
        with self._lock:
            try:
                cur = self.db.execute("INSERT INTO lots(user_id, symbol, side, qty, price, date, fees, note, created) VALUES(?,?,?,?,?,?,?,?,?)",
                                      (str(uid), lot["symbol"], lot["side"], lot["qty"], lot["price"], lot.get("date"), lot.get("fees", 0),
                                       lot.get("note", ""), time.strftime("%Y-%m-%d")))
                self._check_history(uid, lot["symbol"])
                self.db.commit()
                return cur.lastrowid
            except Exception:
                self.db.rollback()
                raise

    def update_lot(self, uid, lot_id, lot):
        with self._lock:
            row = self.db.execute("SELECT symbol FROM lots WHERE user_id=? AND id=?", (str(uid), int(lot_id))).fetchone()
            if not row:
                raise KeyError("no such transaction")
            try:
                self.db.execute("UPDATE lots SET symbol=?, side=?, qty=?, price=?, date=?, fees=?, note=? WHERE user_id=? AND id=?",
                                (lot["symbol"], lot["side"], lot["qty"], lot["price"], lot.get("date"), lot.get("fees", 0), lot.get("note", ""),
                                 str(uid), int(lot_id)))
                for sym in {row["symbol"], lot["symbol"]}:
                    self._check_history(uid, sym)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def delete_lot(self, uid, lot_id):
        with self._lock:
            row = self.db.execute("SELECT symbol FROM lots WHERE user_id=? AND id=?", (str(uid), int(lot_id))).fetchone()
            if not row:
                return False
            try:
                self.db.execute("DELETE FROM lots WHERE user_id=? AND id=?", (str(uid), int(lot_id)))
                self._check_history(uid, row["symbol"])   # removing a buy must not strand a later sale
                self.db.commit()
                return True
            except Exception:
                self.db.rollback()
                raise

    def import_lots(self, uid, lots, replace=False):
        """lots: cleaned dicts. All or nothing. Exact duplicates of an existing transaction are skipped. -> (added, skipped)."""
        self.ensure_user(uid)
        with self._lock:
            try:
                if replace:
                    self.db.execute("DELETE FROM lots WHERE user_id=?", (str(uid),))
                have = {(r["symbol"], r["side"], r["qty"], round(r["price"], 4), r["date"], round(r["fees"], 2)) for r in
                        self._all("SELECT symbol, side, qty, price, date, fees FROM lots WHERE user_id=?", (str(uid),))}
                added = skipped = 0
                touched = set()
                for l in lots:
                    k = (l["symbol"], l["side"], l["qty"], round(l["price"], 4), l.get("date"), round(l.get("fees", 0), 2))
                    if k in have:
                        skipped += 1
                        continue
                    have.add(k)
                    self.db.execute("INSERT INTO lots(user_id, symbol, side, qty, price, date, fees, note, created) VALUES(?,?,?,?,?,?,?,?,?)",
                                    (str(uid), l["symbol"], l["side"], l["qty"], l["price"], l.get("date"), l.get("fees", 0), l.get("note", ""), time.strftime("%Y-%m-%d")))
                    touched.add(l["symbol"])
                    added += 1
                for sym in touched:
                    self._check_history(uid, sym)
                self.db.commit()
                return added, skipped
            except Exception:
                self.db.rollback()
                raise

    # legacy "one row per symbol" interface (paste import, POST /api/holdings): sets the position as one opening buy
    def upsert_holding(self, uid, symbol, qty, avg_price, first_buy_date=None, source="manual"):
        s = _symbol(symbol)
        q = _positive(qty, "qty")
        p = _positive(avg_price, "avg_price")
        self.ensure_user(uid)
        with self._lock:
            self.db.execute("DELETE FROM lots WHERE user_id=? AND symbol=?", (str(uid), s))
            self.db.execute("INSERT INTO lots(user_id, symbol, side, qty, price, date, fees, note, created) VALUES(?,?,?,?,?,?,0,?,?)",
                            (str(uid), s, "buy", q, p, first_buy_date, ("Synced from Groww on " + time.strftime("%Y-%m-%d")) if source == "groww" else
                            "Position entered as a quantity and an average price" if source != "import" else "Imported",
                             time.strftime("%Y-%m-%d")))
            self.db.commit()

    def delete_holding(self, uid, symbol):
        return self._run("DELETE FROM lots WHERE user_id=? AND symbol=?", (str(uid), str(symbol).strip().upper())).rowcount > 0

    def replace_holdings(self, uid, rows):
        """rows: dicts with symbol, qty, avg_price and optional first_buy_date, source.
        Validates everything first so a bad row leaves existing holdings untouched."""
        clean = []
        for r in rows:
            clean.append((str(uid), _symbol(r.get("symbol")), "buy", _positive(r.get("qty"), "qty"), _positive(r.get("avg_price"), "avg_price"),
                          r.get("first_buy_date"), 0, "Imported", time.strftime("%Y-%m-%d")))
        self.ensure_user(uid)
        with self._lock:
            try:
                self.db.execute("DELETE FROM lots WHERE user_id=?", (str(uid),))
                self.db.executemany("INSERT INTO lots(user_id, symbol, side, qty, price, date, fees, note, created) VALUES(?,?,?,?,?,?,?,?,?)", clean)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    # accounts, sessions and Groww identity links (see auth.py). A guest is just a user id with no account row.
    def is_account_id(self, uid):
        return bool(self._all("SELECT 1 FROM accounts WHERE user_id=?", (str(uid),)))

    def get_account(self, uid):
        r = self._all("SELECT user_id, username, pw_hash, created FROM accounts WHERE user_id=?", (str(uid),))
        return r[0] if r else None

    def account_by_username(self, name):
        r = self._all("SELECT user_id, username, pw_hash FROM accounts WHERE username=?", (str(name),))
        return r[0] if r else None

    def create_account(self, uid, username=None, pw_hash=None):
        """Turns the user id into an account (its data stays). Raises ValueError('username taken') or ValueError('already an account')."""
        self.ensure_user(uid)
        with self._lock:
            try:
                self.db.execute("INSERT INTO accounts(user_id, username, pw_hash, created) VALUES(?,?,?,?)",
                                (str(uid), username, pw_hash, time.strftime("%Y-%m-%d")))
                self.db.commit()
            except self._integrity_errors():
                self.db.rollback()
                if username and self.account_by_username(username):
                    raise ValueError("username taken")
                raise ValueError("already an account")

    def set_credentials(self, uid, pw_hash, username=None):
        with self._lock:
            try:
                if username is not None:
                    self.db.execute("UPDATE accounts SET pw_hash=?, username=? WHERE user_id=?", (pw_hash, username, str(uid)))
                else:
                    self.db.execute("UPDATE accounts SET pw_hash=? WHERE user_id=?", (pw_hash, str(uid)))
                self.db.commit()
            except self._integrity_errors():
                self.db.rollback()
                raise ValueError("username taken")

    def touch_login(self, uid):
        self._run("UPDATE accounts SET last_login=? WHERE user_id=?", (time.strftime("%Y-%m-%d %H:%M"), str(uid)))

    def user_for_groww(self, hashes):
        """-> (user_id or None, conflict). conflict is True when the ids belong to two different accounts."""
        owners = {r["user_id"] for h in hashes for r in self._all("SELECT user_id FROM groww_ids WHERE id_hash=?", (h,))}
        return (next(iter(owners)) if len(owners) == 1 else None), len(owners) > 1

    def link_groww_ids(self, uid, hashes):
        with self._lock:
            for h in hashes:
                row = self.db.execute("SELECT user_id FROM groww_ids WHERE id_hash=?", (h,)).fetchone()
                if row and row["user_id"] != str(uid):
                    self.db.rollback()
                    raise ValueError("linked elsewhere")
                self.db.execute("INSERT OR IGNORE INTO groww_ids(id_hash, user_id) VALUES(?,?)", (h, str(uid)))
            self.db.commit()

    def unlink_groww_ids(self, uid):
        self._run("DELETE FROM groww_ids WHERE user_id=?", (str(uid),))

    def groww_linked(self, uid):
        return bool(self._all("SELECT 1 FROM groww_ids WHERE user_id=? LIMIT 1", (str(uid),)))

    def create_session(self, uid, tok_hash, via, now, ttl):
        self._run("DELETE FROM sessions WHERE expires<?", (int(now),))
        self._run("INSERT INTO sessions(token_hash, user_id, created, expires, via) VALUES(?,?,?,?,?)", (tok_hash, str(uid), int(now), int(now + ttl), via))

    def get_session(self, tok_hash, now):
        r = self._all("SELECT user_id, created, via FROM sessions WHERE token_hash=? AND expires>=?", (tok_hash, int(now)))
        return r[0] if r else None

    def delete_session(self, tok_hash):
        self._run("DELETE FROM sessions WHERE token_hash=?", (tok_hash,))

    def delete_other_sessions(self, uid, keep_hash):
        self._run("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (str(uid), keep_hash or ""))

    # Groww API credentials: stored encrypted (the caller encrypts), never returned by any read except get_groww for a sync
    def set_groww(self, uid, key_enc, secret_enc, hint):
        self.ensure_user(uid)
        self._run("INSERT INTO groww_creds(user_id, key_enc, secret_enc, hint, saved) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET key_enc=excluded.key_enc, secret_enc=excluded.secret_enc, hint=excluded.hint, saved=excluded.saved",
                  (str(uid), key_enc, secret_enc, hint, time.strftime("%Y-%m-%d")))

    def get_groww(self, uid):
        r = self._all("SELECT key_enc, secret_enc FROM groww_creds WHERE user_id=?", (str(uid),))
        return r[0] if r else None

    def groww_status(self, uid):
        """What the page may show: whether a key is saved, a short hint, and when it last synced. No key material."""
        r = self._all("SELECT hint, saved, last_sync, last_count FROM groww_creds WHERE user_id=?", (str(uid),))
        if not r:
            return {"saved": False, "hint": None, "saved_on": None, "last_sync": None, "last_count": None}
        return {"saved": True, "hint": r[0]["hint"], "saved_on": r[0]["saved"], "last_sync": r[0]["last_sync"], "last_count": r[0]["last_count"]}

    def mark_groww_sync(self, uid, count):
        self._run("UPDATE groww_creds SET last_sync=?, last_count=? WHERE user_id=?", (time.strftime("%Y-%m-%d %H:%M"), int(count), str(uid)))

    def delete_groww(self, uid):
        return self._run("DELETE FROM groww_creds WHERE user_id=?", (str(uid),)).rowcount > 0

    # watchlist
    def list_watchlist(self, uid):
        return [r["symbol"] for r in self._all(
            "SELECT symbol FROM watchlist WHERE user_id=? ORDER BY symbol", (str(uid),))]

    def add_watch(self, uid, symbol):
        s = _symbol(symbol)
        self.ensure_user(uid)
        self._run("INSERT OR IGNORE INTO watchlist(user_id, symbol) VALUES(?,?)", (str(uid), s))

    def remove_watch(self, uid, symbol):
        return self._run("DELETE FROM watchlist WHERE user_id=? AND symbol=?",
                         (str(uid), str(symbol).strip().upper())).rowcount > 0

    # settings
    def get_settings(self, uid):
        r = self._all("SELECT budget, max_loss FROM settings WHERE user_id=?", (str(uid),))
        return r[0] if r else dict(DEFAULT_SETTINGS)

    def set_settings(self, uid, budget=None, max_loss=None):
        cur = self.get_settings(uid)
        b = cur["budget"] if budget is None else _positive(budget, "budget")
        m = cur["max_loss"] if max_loss is None else _positive(max_loss, "max_loss")
        self.ensure_user(uid)
        self._run("INSERT INTO settings(user_id, budget, max_loss) VALUES(?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET budget=excluded.budget, max_loss=excluded.max_loss",
                  (str(uid), b, m))
        return {"budget": b, "max_loss": m}

    # alerts
    def add_alert(self, uid, key, kind, symbol, message, date):
        self.ensure_user(uid)
        return self._run("INSERT OR IGNORE INTO alerts(user_id, key, kind, symbol, message, date, read) "
                         "VALUES(?,?,?,?,?,?,0)",
                         (str(uid), str(key), kind, symbol, message, date)).rowcount > 0

    def list_alerts(self, uid):
        rows = self._all("SELECT key, kind, symbol, message, date, read FROM alerts "
                         "WHERE user_id=? ORDER BY date DESC, rowid DESC", (str(uid),))
        for r in rows:
            r["read"] = bool(r["read"])
        return rows

    def mark_alerts_read(self, uid):
        return self._run("UPDATE alerts SET read=1 WHERE user_id=? AND read=0", (str(uid),)).rowcount

    # alert rules, per-stock settings, dismissed or snoozed alerts, results already seen
    def get_rules(self, uid):
        r = self._all("SELECT json FROM rule_settings WHERE user_id=?", (str(uid),))
        try:
            return rules.normalize_settings(json.loads(r[0]["json"]) if r else {})
        except ValueError:
            return rules.normalize_settings({})

    def set_rules(self, uid, raw):
        clean = rules.normalize_settings(raw)   # raises ValueError with a message naming the field
        self.ensure_user(uid)
        self._run("INSERT INTO rule_settings(user_id, json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET json=excluded.json",
                  (str(uid), json.dumps(clean)))
        return clean

    def get_hsettings(self, uid):
        return {r["symbol"]: {"target_weight": r["target_weight"], "review_price": r["review_price"], "sector": r["sector"]}
                for r in self._all("SELECT symbol, target_weight, review_price, sector FROM holding_settings WHERE user_id=?", (str(uid),))}

    def set_hsetting(self, uid, symbol, **fields):
        """Fields present in the call are set; None clears. target_weight 0-100, review_price > 0, sector up to 40 characters."""
        s = _symbol(symbol)
        cur = self.get_hsettings(uid).get(s, {"target_weight": None, "review_price": None, "sector": None})
        if "target_weight" in fields:
            v = fields["target_weight"]
            if v in (None, ""):
                cur["target_weight"] = None
            else:
                v = float(v)
                if not 0 < v <= 100:
                    raise ValueError("Target weight must be more than 0 and at most 100")
                cur["target_weight"] = round(v, 2)
        if "review_price" in fields:
            v = fields["review_price"]
            cur["review_price"] = None if v in (None, "") else round(_positive(v, "Review price"), 4)
        if "sector" in fields:
            v = str(fields["sector"] or "").strip()
            if len(v) > 40:
                raise ValueError("Sector is too long (40 characters at most)")
            cur["sector"] = v or None
        self.ensure_user(uid)
        self._run("INSERT INTO holding_settings(user_id, symbol, target_weight, review_price, sector) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(user_id, symbol) DO UPDATE SET target_weight=excluded.target_weight, review_price=excluded.review_price, sector=excluded.sector",
                  (str(uid), s, cur["target_weight"], cur["review_price"], cur["sector"]))
        return cur

    def get_states(self, uid):
        return {r["key"]: {"state": r["state"], "until": r["until"], "fingerprint": r["fingerprint"]}
                for r in self._all("SELECT key, state, until, fingerprint FROM alert_state WHERE user_id=?", (str(uid),))}

    def set_state(self, uid, key, state, fingerprint, until=None):
        if state not in ("dismissed", "snoozed", "seen"):
            raise ValueError("state must be dismissed, snoozed or seen")
        self.ensure_user(uid)
        self._run("INSERT INTO alert_state(user_id, key, state, until, fingerprint) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(user_id, key) DO UPDATE SET state=excluded.state, until=excluded.until, fingerprint=excluded.fingerprint",
                  (str(uid), str(key)[:86], state, until, str(fingerprint)[:120]))

    def clear_states(self, uid, keys):
        with self._lock:
            self.db.executemany("DELETE FROM alert_state WHERE user_id=? AND key=?", [(str(uid), k) for k in keys])
            self.db.commit()

    def get_seen(self, uid):
        return {r["symbol"]: {"end": r["quarter_end"], "detected": r["detected"]}
                for r in self._all("SELECT symbol, quarter_end, detected FROM results_seen WHERE user_id=?", (str(uid),))}

    def set_seen(self, uid, symbol, quarter_end, detected=None):
        self.ensure_user(uid)
        self._run("INSERT INTO results_seen(user_id, symbol, quarter_end, detected) VALUES(?,?,?,?) "
                  "ON CONFLICT(user_id, symbol) DO UPDATE SET quarter_end=excluded.quarter_end, detected=excluded.detected",
                  (str(uid), _symbol(symbol), quarter_end, detected))

    # last calls
    def get_last_calls(self, uid):
        return {r["symbol"]: r["verdict"] for r in self._all(
            "SELECT symbol, verdict FROM last_calls WHERE user_id=?", (str(uid),))}

    def set_last_calls(self, uid, calls):
        """Make the stored calls equal `calls`, writing only what differs. Called on every page load, so an unchanged set writes nothing."""
        uid = str(uid)
        new = {_symbol(k): v for k, v in dict(calls).items()}
        old = self.get_last_calls(uid)
        gone, changed = [s for s in old if s not in new], [(uid, s, v) for s, v in new.items() if old.get(s) != v]
        if not gone and not changed:
            return
        self.ensure_user(uid)
        with self._lock:
            try:
                if gone:
                    self.db.executemany("DELETE FROM last_calls WHERE user_id=? AND symbol=?", [(uid, s) for s in gone])
                if changed:
                    self.db.executemany("INSERT INTO last_calls(user_id, symbol, verdict) VALUES(?,?,?) "
                                        "ON CONFLICT(user_id, symbol) DO UPDATE SET verdict=excluded.verdict", changed)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    # notes: one plain-text note per stock
    def get_note(self, uid, symbol):
        r = self._all("SELECT symbol, text, updated FROM notes WHERE user_id=? AND symbol=?", (str(uid), _symbol(symbol)))
        return r[0] if r else {"symbol": _symbol(symbol), "text": "", "updated": None}

    def list_notes(self, uid):
        rows = self._all("SELECT symbol, text, updated FROM notes WHERE user_id=? ORDER BY updated DESC, symbol", (str(uid),))
        return [{"symbol": r["symbol"], "updated": r["updated"], "preview": " ".join(r["text"].split())[:80]} for r in rows]

    def set_note(self, uid, symbol, text):
        """Empty (or whitespace-only) text deletes the note. Over NOTE_MAX characters is an error, never truncated."""
        s = _symbol(symbol)
        if not isinstance(text, str):
            raise ValueError("note text must be a string")
        if len(text) > NOTE_MAX:
            raise ValueError("A note can be at most %d characters (this one is %d)" % (NOTE_MAX, len(text)))
        if not text.strip():
            self._run("DELETE FROM notes WHERE user_id=? AND symbol=?", (str(uid), s))
            return {"symbol": s, "text": "", "updated": None}
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.ensure_user(uid)
        self._run("INSERT INTO notes(user_id, symbol, text, updated) VALUES(?,?,?,?) "
                  "ON CONFLICT(user_id, symbol) DO UPDATE SET text=excluded.text, updated=excluded.updated", (str(uid), s, text, now))
        return {"symbol": s, "text": text, "updated": now}

    def delete_note(self, uid, symbol):
        return self._run("DELETE FROM notes WHERE user_id=? AND symbol=?", (str(uid), _symbol(symbol))).rowcount > 0

    # price alerts
    def list_price_alerts(self, uid, symbol=None):
        q, a = "SELECT id, symbol, kind, value, created, last_fired, active FROM price_alerts WHERE user_id=?", [str(uid)]
        if symbol:
            q += " AND symbol=?"
            a.append(_symbol(symbol))
        rows = self._all(q + " ORDER BY symbol, id", tuple(a))
        for r in rows:
            r["active"] = bool(r["active"])
        return rows

    def add_price_alert(self, uid, symbol, kind, value):
        s = _symbol(symbol)
        if kind not in PRICE_ALERT_KINDS:
            raise ValueError("kind must be below, above or off_high")
        v = _positive(value, "value")
        if kind == "off_high" and not 1 <= v <= 90:
            raise ValueError("The percentage must be between 1 and 90")
        v = round(v, 4)
        self.ensure_user(uid)
        with self._lock:
            have = self.db.execute("SELECT COUNT(*) FROM price_alerts WHERE user_id=? AND active=1", (str(uid),)).fetchone()[0]
            if have >= PRICE_ALERT_MAX:
                raise ValueError("You can have at most %d price alerts. Delete one first" % PRICE_ALERT_MAX)
            if self.db.execute("SELECT 1 FROM price_alerts WHERE user_id=? AND symbol=? AND kind=? AND value=?", (str(uid), s, kind, v)).fetchone():
                raise ValueError("You already have this price alert")
            cur = self.db.execute("INSERT INTO price_alerts(user_id, symbol, kind, value, created, last_fired, active) VALUES(?,?,?,?,?,NULL,1)",
                                  (str(uid), s, kind, v, time.strftime("%Y-%m-%d")))
            self.db.commit()
            return cur.lastrowid

    def set_price_alert_active(self, uid, alert_id, active):
        """active True re-arms (clears 'reached'); False pauses. -> False if it is not this user's alert."""
        with self._lock:
            row = self.db.execute("SELECT 1 FROM price_alerts WHERE user_id=? AND id=?", (str(uid), int(alert_id))).fetchone()
            if not row:
                return False
            if active:
                have = self.db.execute("SELECT COUNT(*) FROM price_alerts WHERE user_id=? AND active=1 AND id<>?", (str(uid), int(alert_id))).fetchone()[0]
                if have >= PRICE_ALERT_MAX:
                    raise ValueError("You can have at most %d price alerts. Delete one first" % PRICE_ALERT_MAX)
                self.db.execute("UPDATE price_alerts SET active=1, last_fired=NULL WHERE user_id=? AND id=?", (str(uid), int(alert_id)))
            else:
                self.db.execute("UPDATE price_alerts SET active=0 WHERE user_id=? AND id=?", (str(uid), int(alert_id)))
            self.db.commit()
            return True

    def mark_price_alert_fired(self, uid, alert_id, date):
        self._run("UPDATE price_alerts SET last_fired=? WHERE user_id=? AND id=?", (str(date), str(uid), int(alert_id)))

    def delete_price_alert(self, uid, alert_id):
        return self._run("DELETE FROM price_alerts WHERE user_id=? AND id=?", (str(uid), int(alert_id))).rowcount > 0

    # price cache: one row per symbol, shared by every user. A stock that passes the scan's quality filter keeps its whole history in
    # `bars` (zlib JSON); a filtered-out one keeps only `why` and its last-close `quote`. Yahoo adjusts old closes after a dividend or split,
    # so a symbol's history is always replaced whole, never appended to.
    def price_save(self, items, now=None):
        """items: {symbol: bars list of (date, high, low, close, adj, volume) | slim quote dict}."""
        rows = []
        for sym, v in items.items():
            if isinstance(v, dict):
                rows.append((sym, now or time.time(), v.get("why"), json.dumps(v), None))
            elif v:
                payload = [[r[0].isoformat(), r[1], r[2], r[3], r[4], r[5]] for r in v]
                rows.append((sym, now or time.time(), None, None, zlib.compress(json.dumps(payload).encode())))
        if not rows:
            return 0
        with self._lock:
            try:
                self.db.executemany("INSERT INTO price_cache(symbol, fetched, why, quote, bars) VALUES(?,?,?,?,?) "
                                    "ON CONFLICT(symbol) DO UPDATE SET fetched=excluded.fetched, why=excluded.why, quote=excluded.quote, bars=excluded.bars", rows)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return len(rows)

    @staticmethod
    def _bars(blob):
        return [(datetime.date.fromisoformat(x[0]), x[1], x[2], x[3], x[4], x[5]) for x in json.loads(zlib.decompress(bytes(blob)))]

    def price_load(self, fetched_after=None):
        """{symbol: bars | slim dict} for rows fetched at or after the given time (any age when None). Holds every history in memory:
        the scan uses price_index and price_one instead."""
        q, a = "SELECT symbol, quote, bars FROM price_cache", ()
        if fetched_after is not None:
            q, a = q + " WHERE fetched>=?", (float(fetched_after),)
        out = {}
        for r in self._all(q, a):
            try:
                if r["bars"] is not None:
                    out[r["symbol"]] = self._bars(r["bars"])
                elif r["quote"]:
                    out[r["symbol"]] = json.loads(r["quote"])
            except Exception:
                continue   # one unreadable row is fetched again, it must not fail the load
        return out

    def price_index(self, fetched_after=None):
        """Like price_load without the histories: {symbol: slim dict, or True when the symbol has bars stored}. Small enough for a
        512 MB host; fetch a history with price_one."""
        q, a = "SELECT symbol, quote, CASE WHEN bars IS NULL THEN 0 ELSE 1 END AS has FROM price_cache", ()
        if fetched_after is not None:
            q, a = q + " WHERE fetched>=?", (float(fetched_after),)
        out = {}
        for r in self._all(q, a):
            try:
                if r["has"]:
                    out[r["symbol"]] = True
                elif r["quote"]:
                    out[r["symbol"]] = json.loads(r["quote"])
            except Exception:
                continue
        return out

    def price_one(self, symbol):
        """One symbol's bars (oldest first), or None when it has none stored or the row is unreadable."""
        r = self._all("SELECT bars FROM price_cache WHERE symbol=?", (str(symbol),))
        try:
            return self._bars(r[0]["bars"]) if r and r[0]["bars"] is not None else None
        except Exception:
            return None

    # named JSON documents shared by every user (the finished scan), zlib-compressed
    def blob_put(self, name, obj, now=None):
        value = zlib.compress(json.dumps(obj).encode())
        self._run("INSERT INTO blobs(name, saved, value) VALUES(?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET saved=excluded.saved, value=excluded.value", (name, now or time.time(), value))

    def blob_saved(self, name):
        """When the document was saved (epoch seconds), or None. Cheap: does not read the document."""
        r = self._all("SELECT saved FROM blobs WHERE name=?", (name,))
        return r[0]["saved"] if r else None

    def blob_get(self, name):
        """The document, or None when absent or unreadable."""
        r = self._all("SELECT value FROM blobs WHERE name=?", (name,))
        try:
            return json.loads(zlib.decompress(bytes(r[0]["value"]))) if r else None
        except Exception:
            return None

    # named binary files (downloaded lists and company facts), zlib-compressed, under a "file:" prefix in the same table
    def raw_put(self, name, data, now=None):
        self._run("INSERT INTO blobs(name, saved, value) VALUES(?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET saved=excluded.saved, value=excluded.value", ("file:" + name, now or time.time(), zlib.compress(bytes(data))))

    def raw_get(self, name):
        """(bytes, saved-at epoch seconds) or None when absent or unreadable."""
        r = self._all("SELECT saved, value FROM blobs WHERE name=?", ("file:" + name,))
        try:
            return (zlib.decompress(bytes(r[0]["value"])), r[0]["saved"]) if r else None
        except Exception:
            return None

    # anonymous page-view counters: a number per page per day. No IP address, cookie, user or anything else that identifies a visitor.
    def views_add(self, day, counts):
        """counts: {path: number of views} to add to that day."""
        rows = [(str(day), str(p)[:100], int(n)) for p, n in counts.items() if int(n) > 0]
        if not rows:
            return 0
        with self._lock:
            try:
                self.db.executemany("INSERT INTO page_views(day, path, views) VALUES(?,?,?) "
                                    "ON CONFLICT(day, path) DO UPDATE SET views = page_views.views + excluded.views", rows)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return len(rows)

    def views_summary(self, today, days=30):
        """Totals for the stats page: all-time, today, the last `days` days (newest first) and the pages by views."""
        first = (datetime.date.fromisoformat(today) - datetime.timedelta(days=days - 1)).isoformat()
        total = self._all("SELECT COALESCE(SUM(views), 0) AS n, MIN(day) AS since FROM page_views")[0]
        by_day = self._all("SELECT day, SUM(views) AS views FROM page_views WHERE day>=? GROUP BY day ORDER BY day DESC", (first,))
        by_page = self._all("SELECT path, SUM(views) AS views FROM page_views WHERE day>=? GROUP BY path ORDER BY views DESC, path", (first,))
        return {"total": int(total["n"]), "since": total["since"], "today": int(next((r["views"] for r in by_day if r["day"] == today), 0)),
                "days": days, "byDay": [{"day": r["day"], "views": int(r["views"])} for r in by_day],
                "byPage": [{"path": r["path"], "views": int(r["views"])} for r in by_page]}

    def price_clear(self):
        self._run("DELETE FROM price_cache")

    # account
    def export_user(self, uid):
        uid = str(uid)
        u = self._all("SELECT id, plan, created FROM users WHERE id=?", (uid,))
        return {"user": u[0] if u else None, "plan": self.get_plan(uid),
                "schema_version": SCHEMA_VERSION, "lots": self.list_lots(uid), "rules": self.get_rules(uid),
                "holding_settings": self.get_hsettings(uid),
                "holdings": self.list_holdings(uid), "watchlist": self.list_watchlist(uid),
                "settings": self.get_settings(uid), "alerts": self.list_alerts(uid),
                "last_calls": self.get_last_calls(uid),
                "notes": self._all("SELECT symbol, text, updated FROM notes WHERE user_id=? ORDER BY symbol", (uid,)),
                "price_alerts": self.list_price_alerts(uid),
                "account": self._account_summary(uid)}

    def _account_summary(self, uid):
        """For the data export: whether there is an account, never the password hash, session tokens or Groww ids."""
        a = self.get_account(uid)
        return {"is_account": bool(a), "username": a["username"] if a else None, "has_password": bool(a and a["pw_hash"]),
                "groww_linked": self.groww_linked(uid)}

    def delete_user(self, uid):
        uid = str(uid)
        with self._lock:
            for t in ("holdings", "watchlist", "settings", "alerts", "last_calls", "lots", "rule_settings", "holding_settings", "alert_state", "results_seen", "notes", "price_alerts", "groww_creds", "accounts", "groww_ids", "sessions"):
                self.db.execute("DELETE FROM %s WHERE user_id=?" % t, (uid,))
            self.db.execute("DELETE FROM users WHERE id=?", (uid,))
            self.db.commit()

    def close(self):
        with self._lock:
            self.db.close()
