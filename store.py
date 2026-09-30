# -*- coding: utf-8 -*-
"""FITVERSE storage layer.

WHY THIS EXISTS
---------------
Render's free tier has an EPHEMERAL disk: every redeploy or spin-down wipes
the local SQLite file, and any in-memory session dict dies with the process.
This module fixes persistence with the smallest possible change:

1. PERSISTENT SESSIONS (always on, both modes)
   Sessions live in a real `sessions` table instead of the old in-memory
   `SESSIONS = {}` dict. Tokens are random (secrets.token_urlsafe), stored
   server-side with a 30-day expiry, and never appear in URLs. Logout deletes
   the row. Restarting the server no longer logs anyone out.

2. CLOUD DATABASE (Turso/libsql) — ON BY DEFAULT when URL+token exist
   REVERTED-REVERT (2026-09-29): the earlier perf complaint is fixed by the
   persistent-connection client below, so cloud mode is now the default the
   moment FITVERSE_DB_URL + FITVERSE_DB_TOKEN are both set — no extra flag
   needed (Render users kept forgetting FITVERSE_DB_MODE and losing data).
   To force local SQLite anyway (dev only), set FITVERSE_DB_MODE=sqlite.
   Cloud storage means sessions, workouts, nutrition, friends, challenges,
   health imports and AI history SURVIVE redeploys, spin-downs and restarts.

The returned object mirrors the small sqlite3 surface this app actually uses
(`with connect() as db:` + execute/fetchone/fetchall/lastrowid/rowcount/
executescript/executemany), so none of the ~80 existing call sites change.
SQL errors raise sqlite3.OperationalError, preserving existing
`except sqlite3.OperationalError` handling (e.g. idempotent ALTER TABLE).
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection, HTTPSConnection

SESSION_TTL_DAYS = 365  # stay signed in for a year — only manual sign-out ends a session

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


_REMOTE_MODE_VALUES = ("remote", "turso", "libsql", "1", "true", "yes", "on")


_REMOTE_OFF_VALUES = ("sqlite", "local", "0", "false", "no", "off")


def _remote_db_enabled() -> bool:
    """Cloud DB is on whenever URL+token exist. Set FITVERSE_DB_MODE=sqlite to force local."""
    if not _env("FITVERSE_DB_URL") or not _env("FITVERSE_DB_TOKEN"):
        return False
    return _env("FITVERSE_DB_MODE").lower() not in _REMOTE_OFF_VALUES


def storage_mode() -> str:
    return "libsql-remote" if _remote_db_enabled() else "sqlite"


def sessions_mode() -> str:
    return "database"


# ---------------------------------------------------------------------------
# remote (libsql / Turso over HTTP v2 pipeline) implementation
# ---------------------------------------------------------------------------

def _arg(v):
    """Encode one Python parameter into libsql pipeline arg form.

    IMPORTANT: the HTTP v2 / hrana encoding rules (validated against real
    Turso): integers are sent as JSON STRINGS (precision escape hatch),
    but floats must be raw JSON NUMBERS — a float value sent as a string
    is rejected with HTTP 400. Blobs use base64 in the `value` field.
    """
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "value": base64.b64encode(bytes(v)).decode("ascii")}
    return {"type": "text", "value": str(v)}


def _dec(v):
    """Decode one libsql value cell into a Python value."""
    t = v.get("type")
    if t == "null":
        return None
    if t in ("integer",):
        return int(v["value"])
    if t in ("float", "real"):
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v["value"])
    return v.get("value")


def _is_readonly_sql(sql: str) -> bool:
    """True for plain SELECT statements — the only kind safe to micro-cache."""
    s = sql.lstrip(" \t\r\n(;\"").upper()
    return s.startswith("SELECT") or s.startswith("WITH")


class _Row:
    """Lightweight read-only row: index access, name access, .keys(), dict()."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, vals):
        self._cols = list(cols)
        self._vals = list(vals)

    def keys(self):
        return list(self._cols)

    def __len__(self):
        return len(self._vals)

    def __contains__(self, k):
        return k in self._cols

    def __iter__(self):
        return iter(self._cols)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._vals[k]
        try:
            return self._vals[self._cols.index(k)]
        except ValueError:
            raise KeyError(k)

    def get(self, k, default=None):
        return self._vals[self._cols.index(k)] if k in self._cols else default


class _RemoteCursor:
    arraysize = 1

    def __init__(self, conn):
        self._conn = conn
        self._rows: list[_Row] = []
        self._pos = 0
        self.lastrowid = None
        self.rowcount = -1
        self.description = None

    # -- protocol ----------------------------------------------------------
    def execute(self, sql, params=()):
        # Tiny read-through cache for hot SELECTs (same connection = same
        # transaction view): a handler that re-reads the same row sees its
        # own writes through the DML path below, and the cache dies with the
        # connection. Purely a latency win — behaviour is identical.
        key = None
        cache = getattr(self._conn, "_cache", None)
        if cache is not None and _is_readonly_sql(sql) and len(params) <= 8:
            key = (sql, tuple(params))
            hit = cache.get(key)
            if hit and hit[0] > time.monotonic():
                _, self._rows, self.rowcount, self.description, self.lastrowid = hit
                self._pos = 0
                return self
        # _pipeline already raises sqlite3.OperationalError on any per-statement
        # error, so this single result is guaranteed to be an "ok" response.
        res = self._conn._query(sql, params)
        if res.get("type") == "error":
            raise sqlite3.OperationalError(str(res.get("message") or res.get("error") or "SQL error"))
        inner = res.get("response", {}).get("result", {})
        cols = [c.get("name") for c in inner.get("cols", [])]
        rows = [[_dec(cell) for cell in r] for r in inner.get("rows", [])]
        self._rows = [_Row(cols, r) for r in rows]
        self._pos = 0
        if "rows" in inner:            # SELECT-shaped result
            self.rowcount = -1
            self.description = [(c, None, None, None, None, None, None) for c in cols]
        else:                          # DML result
            self.rowcount = int(inner.get("affected_row_count") or 0)
            self.description = None
        lrid = inner.get("last_insert_rowid")
        self.lastrowid = int(lrid) if lrid is not None else None
        if key is not None and cache is not None and "rows" in inner:
            cache[key] = (time.monotonic() + _CACHE_MICRO_TTL,
                          list(self._rows), self.rowcount, self.description, self.lastrowid)
        return self

    # -- fetch API ---------------------------------------------------------
    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        r = self._rows[self._pos]
        self._pos += 1
        return r

    def fetchall(self):
        out = self._rows[self._pos:]
        self._pos = len(self._rows)
        return out

    def fetchmany(self, n=1):
        out = self._rows[self._pos:self._pos + n]
        self._pos = min(len(self._rows), self._pos + n)
        return out

    def close(self):
        self._rows = []

    def __iter__(self):
        return iter(self._rows[self._pos:])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_CACHE_MICRO_TTL = 5.0  # seconds; per-connection read cache for hot SELECTs


class RemoteConn:
    """sqlite3.Connection-shaped handle backed by the libsql HTTP API.

    PERF: one persistent HTTP(S) connection per handle (http.client), so a
    handler that runs N statements does ONE TCP+TLS handshake instead of N.
    On Render (far from Turso) that previously cost ~1s per statement; the
    connection is still created lazily and re-established transparently on
    any transport error, with the same 3-attempt retry + error text as before.
    """

    row_factory = None  # rows are always mapping/index accessible like sqlite3.Row
    in_transaction = False

    def __init__(self, url: str, token: str):
        # Turso hands out libsql:// URLs; its HTTP v2 pipeline is served over
        # HTTPS on the same host. Translate before handing to urllib.
        self._https = True
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        elif url.startswith("libsql+"):
            url = "https://" + url.split("://", 1)[1]
        elif url.startswith("http://"):
            self._https = False  # self-hosted/edge proxies on plain HTTP
            url = "http://" + url[len("http://"):]
        if not url.endswith("/"):
            url += "/"
        self._base = url
        self._path = "v2/pipeline"
        self._token = token
        self._closed = False
        self._http = None  # lazy: created on first statement
        self._cache: dict = {}  # per-connection micro-cache for hot reads

    def _connect_http(self):
        host = self._base.split("//", 1)[1].rstrip("/")
        if self._https:
            return HTTPSConnection(host, timeout=15)
        return HTTPConnection(host, timeout=15)

    def _close_http(self):
        if self._http is not None:
            try:
                self._http.close()
            except Exception:
                pass
            self._http = None

    # -- HTTP core ---------------------------------------------------------
    def _pipeline(self, stmts):
        body = json.dumps({
            "requests": [
                {"type": "execute", "stmt": {"sql": s, "args": [_arg(p) for p in ps]}}
                for s, ps in stmts
            ] + [{"type": "close"}]
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._token}"}
        last_err = None
        for attempt in range(3):  # small retry: transient network/5xx
            if self._http is None:
                self._http = self._connect_http()
            try:
                self._http.request("POST", "/" + self._path, body=body, headers=headers)
                resp = self._http.getresponse()
                payload_raw = resp.read()
                if resp.status >= 500 or resp.status == 429:
                    last_err = f"HTTP {resp.status}: {payload_raw[:300].decode('utf-8', 'replace')}"
                    self._close_http()
                    time.sleep(0.3 * (attempt + 1))
                    continue
                if resp.status >= 400:
                    # Surface Turso's own error text — it names the exact
                    # validation problem instead of a bare status code.
                    raise sqlite3.OperationalError(
                        f"remote database HTTP {resp.status}: {payload_raw[:300].decode('utf-8', 'replace')}")
                payload = json.loads(payload_raw.decode("utf-8"))
                results = payload.get("results", [])
                for r in results[:len(stmts)]:
                    if r.get("type") == "error":
                        raise sqlite3.OperationalError(str(r.get("message") or r.get("error") or "SQL error"))
                return results
            except sqlite3.OperationalError:
                raise  # real SQL error — do not retry
            except OSError as e:  # connection dropped / timed out — reconnect and retry
                last_err = repr(e)
                self._close_http()
                if attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
        raise sqlite3.OperationalError(f"remote database unreachable: {last_err}")

    def _query(self, sql, params=()):
        results = self._pipeline([(sql, tuple(params))])
        return results[0]

    # -- sqlite3-compatible surface ---------------------------------------
    def cursor(self, *a, **k):
        return _RemoteCursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq):
        """Batch all parameter sets into ONE pipeline request."""
        seq = list(seq)
        if not seq:
            cur = self.cursor()
            cur.rowcount = 0
            return cur
        results = self._pipeline([(sql, tuple(p)) for p in seq])
        affected = 0
        for r in results[:len(seq)]:
            if r.get("type") == "error":
                raise sqlite3.OperationalError(str(r.get("message") or "SQL error"))
            inner = r.get("response", {}).get("result", {})
            affected += int(inner.get("affected_row_count") or 0)
        cur = self.cursor()
        cur.rowcount = affected
        return cur

    def executescript(self, script):
        # Split on ";" AFTER stripping -- comments, never inside them. The
        # old split(";") chopped comments containing semicolons into broken
        # SQL fragments (Turso: 'SQL string could not be parsed: near
        # "serve_static"') and crashed boot on Render while local sqlite
        # parsed the same script fine.
        stmts, cur = [], []
        for line in script.splitlines():
            idx = line.find("--")
            code = line[:idx] if idx >= 0 else line
            cur.append(code)
            if ";" in code:
                stmt = "\n".join(cur).strip()
                if stmt.strip("; \n\t"):
                    stmts.append(stmt)
                cur = []
        tail = "\n".join(cur).strip()
        if tail.strip("; \n\t"):
            stmts.append(tail)
        if stmts:
            # _pipeline expects (sql, params) pairs — bare strings would
            # crash with 'too many values to unpack' at boot.
            self._pipeline([(s, ()) for s in stmts])
        c = self.cursor()
        return c

    def commit(self):
        return None  # every statement is committed by the server

    def rollback(self):
        return None

    def close(self):
        self._closed = True
        self._close_http()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False  # autocommit mode; nothing to commit/close


# ---------------------------------------------------------------------------
# dual-mode connect() — the single seam every module already imports
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# small connection pool — one handle per thread, kept warm between requests
# ---------------------------------------------------------------------------
_pool: dict[int, tuple] = {}
_pool_max = 64


def _pooled_remote(url: str, token: str):
    """Reuse one RemoteConn per thread; recycle if the previous one was closed."""
    global _pool
    entry = _pool.get(id(threading.current_thread()))
    if entry is not None:
        conn, cfg = entry
        if cfg == (url, token) and not conn._closed:
            return conn
    conn = RemoteConn(url, token)
    if len(_pool) >= _pool_max:
        _pool.clear()  # simple overflow: drop all, threads lazily reconnect
    _pool[id(threading.current_thread())] = (conn, (url, token))
    return conn


def connect(database: str = "fitverse.db"):
    """Return a local sqlite3 connection, or a pooled remote one when cloud mode is on."""
    url, token = _env("FITVERSE_DB_URL"), _env("FITVERSE_DB_TOKEN")
    if url and token and _remote_db_enabled():
        return _pooled_remote(url, token)
    db = sqlite3.connect(database, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
    except sqlite3.OperationalError:
        pass
    return db


def storage_report() -> dict:
    """Human-readable storage story for /api/health and the boot banner."""
    remote = bool(_env("FITVERSE_DB_URL") and _env("FITVERSE_DB_TOKEN") and _remote_db_enabled())
    return {
        "mode": "libsql-remote (cloud, persistent)" if remote else "sqlite (local, ephemeral on Render)",
        "cloud": remote,
        "warning": None if remote else "Set FITVERSE_DB_URL + FITVERSE_DB_TOKEN (Turso) or data resets on redeploys.",
    }


# ---------------------------------------------------------------------------
# persistent sessions (database-backed in BOTH modes — survives restarts)
# ---------------------------------------------------------------------------

SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at);
"""

_ensure_done = {"ok": False}
# tiny read-through cache so the SSE loop / hot paths don't re-hit the DB
# every request; invalidated immediately on logout. 60s staleness cap.
_cache: dict[str, tuple[float, int]] = {}
_CACHE_TTL = 60.0


def _ensure_sessions_table():
    if _ensure_done["ok"]:
        return
    with connect() as db:
        db.executescript(SESSIONS_TABLE_SQL)
    _ensure_done["ok"] = True


def _purge_expired(db) -> None:
    try:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now(),))
    except sqlite3.OperationalError:
        pass  # table not created yet — _ensure runs first in practice


def session_put(token: str, user_id: int) -> None:
    _ensure_sessions_table()
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec="seconds")
    with connect() as db:
        db.execute(
            "INSERT INTO sessions (token,user_id,created_at,expires_at) VALUES (?,?,?,?) "
            "ON CONFLICT(token) DO UPDATE SET user_id=excluded.user_id, expires_at=excluded.expires_at",
            (token, int(user_id), _now(), expires),
        )
        if os.urandom(1)[0] < 10:  # ~4% chance: lazy cleanup, no cron needed
            _purge_expired(db)
    _cache[token] = (time.time() + _CACHE_TTL, int(user_id))


def session_user(token: str) -> int:
    """Resolve a session token to a user id. 0 = anonymous/expired/unknown."""
    if not token:
        return 0
    hit = _cache.get(token)
    if hit and hit[0] > time.time():
        return hit[1]
    _ensure_sessions_table()
    try:
        with connect() as db:
            row = db.execute("SELECT user_id,expires_at FROM sessions WHERE token=?", (token,)).fetchone()
            if row is None:
                return 0
            if str(row["expires_at"]) <= _now():
                db.execute("DELETE FROM sessions WHERE token=?", (token,))
                _cache.pop(token, None)
                return 0
            uid = int(row["user_id"])
    except sqlite3.OperationalError:
        return 0  # sessions table not ready yet (first boot race) — treat as guest
    _cache[token] = (time.time() + _CACHE_TTL, uid)
    return uid


def session_drop(token: str) -> None:
    _cache.pop(token, None)
    if not token:
        return
    _ensure_sessions_table()
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))


def purge_expired_sessions() -> int:
    """Explicit cleanup (called at boot). Returns rows removed, best-effort."""
    _ensure_sessions_table()
    try:
        with connect() as db:
            cur = db.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now(),))
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    except sqlite3.OperationalError:
        return 0
