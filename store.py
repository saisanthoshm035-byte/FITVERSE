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

2. OPTIONAL REMOTE DATABASE (opt-in via environment)
   If FITVERSE_DB_URL + FITVERSE_DB_TOKEN are set, `connect()` returns a
   handle backed by a libsql/Turso database over its documented HTTP v2
   pipeline endpoint (https://docs.turso.tech/sdk/http/reference) using only
   the Python standard library. The free Turso tier keeps FITVERSE data
   persistent across Render redeploys and spin-downs.
   If the variables are absent, `connect()` returns a plain local sqlite3
   connection exactly as before — local development is 100% unchanged.

The returned object mirrors the small sqlite3 surface this app actually uses
(`with connect() as db:` + execute/fetchone/fetchall/lastrowid/rowcount/
executescript/executemany), so none of the ~80 existing call sites change.
SQL errors raise sqlite3.OperationalError, preserving existing
`except sqlite3.OperationalError` handling (e.g. idempotent ALTER TABLE).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SESSION_TTL_DAYS = 30

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def storage_mode() -> str:
    return "libsql-remote" if _env("FITVERSE_DB_URL") else "sqlite"


def sessions_mode() -> str:
    return "database"


# ---------------------------------------------------------------------------
# remote (libsql / Turso over HTTP v2 pipeline) implementation
# ---------------------------------------------------------------------------

def _arg(v):
    """Encode one Python parameter into libsql pipeline arg form."""
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": 1 if v else 0}
    if isinstance(v, int):
        return {"type": "integer", "value": v}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "value": bytes(v).hex()}
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
        return bytes.fromhex(v["value"])
    return v.get("value")


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


class RemoteConn:
    """sqlite3.Connection-shaped handle backed by the libsql HTTP API."""

    row_factory = None  # rows are always mapping/index accessible like sqlite3.Row
    in_transaction = False

    def __init__(self, url: str, token: str):
        if not url.endswith("/"):
            url += "/"
        self._url = url + "v2/pipeline"
        self._token = token
        self._closed = False

    # -- HTTP core ---------------------------------------------------------
    def _pipeline(self, stmts):
        body = json.dumps({
            "requests": [
                {"type": "execute", "stmt": {"sql": s, "args": [_arg(p) for p in ps]}}
                for s, ps in stmts
            ] + [{"type": "close"}]
        }).encode("utf-8")
        last_err = None
        for attempt in range(3):  # small retry: transient network/5xx
            req = urllib.request.Request(
                self._url, data=body, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._token}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                results = payload.get("results", [])
                for r in results[:len(stmts)]:
                    if r.get("type") == "error":
                        raise sqlite3.OperationalError(str(r.get("message") or r.get("error") or "SQL error"))
                return results
            except sqlite3.OperationalError:
                raise  # real SQL error — do not retry
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
                if isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429:
                    raise sqlite3.OperationalError(f"remote database HTTP {e.code}")
                last_err = e
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
        stmts = []
        for raw in script.split(";"):
            s = raw.strip()
            if s and not all(ln.strip().startswith("--") or not ln.strip() for ln in s.splitlines()):
                stmts.append((s, ()))
        if stmts:
            self._pipeline(stmts)
        cur = self.cursor()
        return cur

    def commit(self):
        return None  # every statement is committed by the server

    def rollback(self):
        return None

    def close(self):
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False  # autocommit mode; nothing to commit/close


# ---------------------------------------------------------------------------
# dual-mode connect() — the single seam every module already imports
# ---------------------------------------------------------------------------

def connect(database: str = "fitverse.db"):
    """Return a local sqlite3 connection, or a remote one when configured."""
    url, token = _env("FITVERSE_DB_URL"), _env("FITVERSE_DB_TOKEN")
    if url:
        return RemoteConn(url, token)
    db = sqlite3.connect(database, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
    except sqlite3.OperationalError:
        pass
    return db


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
