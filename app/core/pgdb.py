"""PostgreSQL backend for Store. It wraps a psycopg connection so Store's SQLite-style SQL (? placeholders, INSERT OR IGNORE,
lastrowid, rowid) runs unchanged. Used when DATABASE_URL is set. Needs: pip install "psycopg[binary]"."""
import re

import psycopg

# SQLite types and keywords in SCHEMA, mapped to their PostgreSQL form.
_SCHEMA_SUBS = [
    (r"INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"),
    (r"\bREAL\b", "DOUBLE PRECISION"),            # PostgreSQL REAL is 4 bytes: too coarse for prices
    (r"\bINTEGER\b", "BIGINT"),                   # session expiry is epoch seconds
    (r"BLOB", "BYTEA"),
    (r"username TEXT UNIQUE COLLATE NOCASE", "username TEXT"),
    (r"(CREATE TABLE IF NOT EXISTS alerts\()", r"\1seq BIGSERIAL, "),   # stands in for SQLite's rowid
]
_SCHEMA_EXTRA = ["CREATE UNIQUE INDEX IF NOT EXISTS accounts_username_ci ON accounts(lower(username))"]
_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\b", re.I)


class Row(tuple):
    """A result row that reads like sqlite3.Row: by position, by column name, and dict(row)."""
    _cols = ()

    def __getitem__(self, k):
        return tuple.__getitem__(self, self._cols.index(k) if isinstance(k, str) else k)

    def keys(self):
        return list(self._cols)


def _row_factory(cursor):
    cols = tuple(c.name for c in (cursor.description or ()))
    cls = type("Row", (Row,), {"_cols": cols})
    return lambda values: cls(values)


def translate(sql):
    """SQLite SQL -> PostgreSQL. Returns (sql, wants_id)."""
    s = sql.replace("%", "%%").replace("?", "%s")
    if re.match(r"\s*INSERT OR IGNORE INTO", s, re.I):
        s = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", s, count=1, flags=re.I) + " ON CONFLICT DO NOTHING"
    s = re.sub(r"\browid\b", "seq", s)
    s = re.sub(r"(WHERE\s+)username\s*=\s*%s", r"\1lower(username)=lower(%s)", s)   # SQLite's NOCASE column
    wants_id = bool(re.match(r"\s*INSERT INTO (lots|price_alerts)\b", s, re.I))
    if wants_id:
        s += " RETURNING id"
    return s, wants_id


def schema_statements(schema):
    for pat, rep in _SCHEMA_SUBS:
        schema = re.sub(pat, rep, schema)
    return [x.strip() for x in schema.split(";") if x.strip()] + _SCHEMA_EXTRA


class Result:
    def __init__(self, rows, rowcount, lastrowid=None):
        self._rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class PgConnection:
    """Same surface Store uses on sqlite3: execute, executemany, commit, rollback, close. A write opens a transaction that lasts
    until commit/rollback, so Store's multi-statement changes stay atomic. A read-only call commits at once, so no connection is
    left idle inside a transaction."""
    IntegrityError = psycopg.errors.IntegrityError

    def __init__(self, url):
        self.url = url
        self._dirty = False
        self._connect()

    def _connect(self):
        self.conn = psycopg.connect(self.url, autocommit=False)
        self._dirty = False

    def _exec(self, fn):
        try:
            return fn()
        except psycopg.OperationalError:   # the host dropped an idle connection: reconnect once, unless a transaction was lost
            if self._dirty or not (self.conn.closed or self.conn.broken):
                raise
            self._connect()
            return fn()

    def execute(self, sql, args=()):
        sql, wants_id = translate(sql)

        def run():
            cur = self.conn.cursor()
            cur.execute(sql, tuple(args))
            rows, lastid = [], None
            if cur.description:
                cur.row_factory = _row_factory(cur)
                rows = cur.fetchall()
                if wants_id and rows:
                    lastid = rows[0][0]
            return Result(rows, cur.rowcount, lastid)
        res = self._exec(run)
        if _WRITE.match(sql):
            self._dirty = True
        elif not self._dirty:
            self.conn.commit()
        return res

    def executemany(self, sql, seq):
        sql, _ = translate(sql)
        cur = self._exec(lambda: self.conn.cursor())
        cur.executemany(sql, [tuple(a) for a in seq])
        self._dirty = True
        return Result([], cur.rowcount)

    def init_schema(self, schema):
        for st in schema_statements(schema):
            self.conn.execute(st)
        self.conn.commit()

    def commit(self):
        self.conn.commit()
        self._dirty = False

    def rollback(self):
        self.conn.rollback()
        self._dirty = False

    def close(self):
        self.conn.close()
