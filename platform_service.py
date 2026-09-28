"""FITVERSE 4.0 platform service layer.

Health integrations (user-consented only), a unified fitness data layer over the
existing tables, personalized recommendations, cardio analysis, notification
center helpers, and the AI companion engine.

Honesty rules enforced throughout:
- No fake health data. If an integration lacks credentials, the API reports
  exactly what configuration is missing.
- No medical claims. All guidance is general fitness/wellness advice.
- Google Fit tokens are stored server-side and never sent to the frontend.
- Groq (GROQ_API_KEY) powers the AI surfaces; everything degrades gracefully to
  the deterministic engine, which always works — even with zero configuration.
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

from server import connect, now  # shared DB helpers

try:
    import ai_service  # settings/targets reuse
except Exception:  # pragma: no cover
    ai_service = None

try:
    import intelligence
except Exception:  # pragma: no cover
    intelligence = None


# ---------------------------------------------------------------------------
# Notification center
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES = [
    ("friend", 1), ("message", 1), ("achievement", 1), ("challenge", 1),
    ("workout", 1), ("hydration", 1), ("event", 1), ("community", 1),
    ("business", 1), ("ai", 1),
]


def ensure_prefs(db: sqlite3.Connection, uid: int) -> None:
    db.executemany(
        "INSERT OR IGNORE INTO notification_prefs (user_id,category,enabled,sound) VALUES (?,?,?,0)",
        [(uid, c, e) for c, e in DEFAULT_CATEGORIES])


def get_prefs(db: sqlite3.Connection, uid: int) -> dict:
    ensure_prefs(db, uid)
    rows = db.execute("SELECT category,enabled,sound FROM notification_prefs WHERE user_id=?", (uid,)).fetchall()
    return {r["category"]: {"enabled": bool(r["enabled"]), "sound": bool(r["sound"])} for r in rows}


def notify(db: sqlite3.Connection, uid: int, ntype: str, title: str, body: str, link: str | None = None) -> None:
    """Insert a notification if the user hasn't muted this category."""
    if uid <= 0:
        return
    prefs = get_prefs(db, uid)
    if prefs and not prefs.get(ntype, {"enabled": True})["enabled"]:
        return
    db.execute(
        "INSERT INTO notifications (user_id,type,title,body,link_url,is_read,created_at) VALUES (?,?,?,?,?,0,?)",
        (uid, ntype, title[:120], body[:400], link, now()))


def list_notifications(uid: int, unread_only: bool = False) -> dict:
    with connect() as db:
        q = "SELECT id,type,title,body,link_url,is_read,created_at FROM notifications WHERE user_id=?"
        if unread_only:
            q += " AND is_read=0"
        rows = [dict(r) for r in db.execute(q + " ORDER BY id DESC LIMIT 100", (uid,))]
        unread = db.execute("SELECT count(*) FROM notifications WHERE user_id=? AND is_read=0", (uid,)).fetchone()[0]
        prefs = get_prefs(db, uid)
    return {"items": rows, "unread": unread, "prefs": prefs}


def unread_count(uid: int) -> int:
    with connect() as db:
        return db.execute("SELECT count(*) FROM notifications WHERE user_id=? AND is_read=0", (uid,)).fetchone()[0]


# ---------------------------------------------------------------------------
# Google Fit integration (free OAuth, read-only scope; tokens stay server-side)
# ---------------------------------------------------------------------------

GOOGLE_ACTIVITY_NAMES = {1: "Cycling", 7: "Walking", 8: "Running", 10: "Hiking",
                         28: "Aerobics", 82: "Swimming (open water)", 83: "Swimming (pool)",
                         88: "Treadmill", 96: "Rowing", 103: "Strength training",
                         106: "Stair climbing", 109: "Yoga", 119: "Basketball", 120: "Soccer"}


def google_fit_config(base_url: str = "") -> dict:
    env_redirect = os.environ.get("GOOGLE_FIT_REDIRECT_URI", "")
    return {
        "client_id": os.environ.get("GOOGLE_FIT_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_FIT_CLIENT_SECRET", ""),
        "redirect_uri": env_redirect or ((base_url.rstrip("/") + "/api/health/google/callback") if base_url else ""),
    }


def google_fit_status(uid: int, base_url: str = "") -> dict:
    cfg = google_fit_config(base_url)
    with connect() as db:
        row = db.execute(
            "SELECT status,scopes,connected_at,last_synced_at FROM health_connections WHERE user_id=? AND provider='google_fit'",
            (uid,)).fetchone()
    connected = bool(row and row["status"] == "connected")
    return {
        "provider": "google_fit",
        "connected": connected,
        "configured": bool(cfg["client_id"] and cfg["client_secret"]),
        "missing": [k for k, v in (("GOOGLE_FIT_CLIENT_ID", cfg["client_id"]), ("GOOGLE_FIT_CLIENT_SECRET", cfg["client_secret"])) if not v],
        "scopes": row["scopes"] if row else "",
        "connected_at": row["connected_at"] if row else None,
        "last_synced_at": row["last_synced_at"] if row else None,
        "authorize_url": _google_authorize_url(cfg) if (cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"]) else None,
    }


def _google_authorize_url(cfg: dict) -> str:
    params = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/fitness.activity.read",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def google_fit_exchange(uid: int, code: str, base_url: str = "") -> dict:
    """Exchange an OAuth code for tokens. Tokens stay server-side."""
    cfg = google_fit_config(base_url)
    if not (cfg["client_id"] and cfg["client_secret"]):
        return {"ok": False, "error": "Google Fit is not configured on this server. Set GOOGLE_FIT_CLIENT_ID and GOOGLE_FIT_CLIENT_SECRET environment variables."}
    data = urllib.parse.urlencode({
        "code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"], "grant_type": "authorization_code",
    }).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            tok = json.loads(resp.read().decode())
    except Exception as exc:
        return {"ok": False, "error": f"Google token exchange failed: {exc}"}
    with connect() as db:
        db.execute(
            """INSERT INTO health_connections (user_id,provider,status,scopes,external_user_id,access_token,refresh_token,token_expires_at,connected_at,last_synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,NULL)
               ON CONFLICT(user_id,provider) DO UPDATE SET status='connected',scopes=excluded.scopes,
                 access_token=excluded.access_token,refresh_token=excluded.refresh_token,
                 token_expires_at=excluded.token_expires_at""",
            (uid, "google_fit", "connected", "fitness.activity.read", "",
             tok.get("access_token", ""), tok.get("refresh_token", ""),
             (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))).isoformat(timespec="seconds"), now()))
    sync_stats = google_fit_sync(uid)
    return {"ok": True, "synced": sync_stats}


def _google_token(uid: int) -> str | None:
    with connect() as db:
        row = db.execute("SELECT access_token,refresh_token,token_expires_at FROM health_connections WHERE user_id=? AND provider='google_fit' AND status='connected'", (uid,)).fetchone()
    if not row:
        return None
    exp = row["token_expires_at"]
    if exp:
        try:
            if datetime.fromisoformat(exp) <= datetime.now(timezone.utc) and row["refresh_token"]:
                cfg = google_fit_config()
                data = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"], "grant_type": "refresh_token", "refresh_token": row["refresh_token"]}).encode()
                req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    tok = json.loads(resp.read().decode())
                with connect() as db:
                    db.execute("UPDATE health_connections SET access_token=?,refresh_token=?,token_expires_at=? WHERE user_id=? AND provider='google_fit'",
                               (tok.get("access_token"), tok.get("refresh_token"),
                                (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))).isoformat(timespec="seconds"), uid))
                return tok.get("access_token")
        except Exception:
            pass
    return row["access_token"] or None


def google_fit_sync(uid: int) -> dict:
    """Fetch authorized Google Fit workout sessions into health_activities."""
    token = _google_token(uid)
    if not token:
        return {"ok": False, "error": "Not connected"}
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/fitness/v1/users/me/sessions?maxResults=200",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return {"ok": False, "error": f"Google Fit sync failed: {exc}"}
    sessions = data.get("session", [])
    inserted = 0
    with connect() as db:
        for s in sessions:
            start = s.get("startTime", "") or ""
            end = s.get("endTime", "") or ""
            dur = 0
            if start and end:
                try:
                    dur = int((datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds())
                except Exception:
                    dur = 0
            eid = str(s.get("id") or start or now())
            db.execute(
                """INSERT OR IGNORE INTO health_activities
                   (user_id,provider,external_id,sport,name,distance_km,moving_s,elev_m,kcal,avg_hr,max_hr,avg_pace_sec_km,started_at,raw_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, "google_fit", eid, GOOGLE_ACTIVITY_NAMES.get(s.get("activityType"), "Workout"),
                 str(s.get("name") or ""), 0, max(0, dur), 0, 0, 0, 0, 0, (start or now())[:19], "{}", now()))
            inserted += 1
        db.execute("UPDATE health_connections SET last_synced_at=? WHERE user_id=? AND provider='google_fit'", (now(), uid))
    return {"ok": True, "fetched": len(sessions), "stored": inserted}


def import_takeout_days(uid: int, days: list) -> dict:
    """Zero-setup import: Google Takeout Fit export (daily steps + distance)."""
    n_steps = n_act = 0
    with connect() as db:
        for d in days[:400]:
            try:
                day = str(d.get("day", ""))[:10]
                steps = int(d.get("steps") or 0)
                km = round(float(d.get("distance_km") or 0), 2)
            except Exception:
                continue
            if not day or len(day) != 10:
                continue
            if steps > 0:
                db.execute(
                    """INSERT INTO daily_metrics (user_id,day,steps,source,updated_at) VALUES (?,?,?,?,?)
                       ON CONFLICT(user_id,day) DO UPDATE SET steps=MAX(steps,excluded.steps),source=excluded.source,updated_at=excluded.updated_at""",
                    (uid, day, steps, "google_fit_takeout", now()))
                n_steps += 1
            if km > 0:
                cur = db.execute(
                    """INSERT OR IGNORE INTO health_activities
                       (user_id,provider,external_id,sport,name,distance_km,moving_s,elev_m,kcal,avg_hr,max_hr,avg_pace_sec_km,started_at,raw_json,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, "google_fit", f"takeout-{day}", "Imported", "Google Fit daily distance", km, 0, 0, 0, 0, 0, 0, day + "T00:00:00", "{}", now()))
                n_act += cur.rowcount
    return {"ok": True, "days": n_steps, "activities": n_act}


# ---------------------------------------------------------------------------
# Health Connect — honest capability + real file import (no fake data)
# ---------------------------------------------------------------------------

# What a web app can and cannot do with Health Connect, stated plainly.
HEALTH_CONNECT_NOTE = (
    "Health Connect (Android) is a device-local API: a website cannot read it directly — "
    "only a native Android app (or Google Fit authorization) can. FITVERSE never fakes "
    "health data. Real paths that work today: (1) export a ZIP from the Health Connect app "
    "(Settings → Export data) or from Google Takeout and import the files here — everything "
    "is parsed and stored in YOUR account; (2) connect Google Fit for automatic sync; "
    "(3) log metrics manually. A future FITVERSE Android app can sync Health Connect automatically."
)


def health_connect_status(uid: int) -> dict:
    """Capability report for the Health page: honest about what is possible."""
    with connect() as db:
        row = db.execute(
            "SELECT status,last_synced_at FROM health_connections WHERE user_id=? AND provider='health_connect'",
            (uid,)).fetchone()
        imported = db.execute(
            "SELECT count(*) FROM daily_metrics WHERE user_id=? AND source LIKE 'health_connect%'",
            (uid,)).fetchone()[0]
        acts = db.execute(
            "SELECT count(*) FROM health_activities WHERE user_id=? AND provider='health_connect'",
            (uid,)).fetchone()[0]
    return {
        "provider": "health_connect",
        "connected": False,  # a web page cannot hold a device-local connection
        "available": True,   # file import IS available today
        "native_bridge": False,
        "imported_days": imported,
        "imported_activities": acts,
        "last_imported_at": row["last_synced_at"] if row else None,
        "android_app_required_for_auto_sync": True,
        "note": HEALTH_CONNECT_NOTE,
        "how_to": [
            "On your Android phone: Health Connect app → ⚙ Settings → 'Export data' → save the ZIP.",
            "Unzip it on your PC (or use Google Takeout → Fit). Files are usually daily steps, distance, exercise sessions or a merged JSON/CSV.",
            "On FITVERSE → Health page → 'Import health data file' → pick the file(s). Data lands in your account instantly.",
        ],
    }


def import_health_connect_records(uid: int, records: list, source_label: str = "health_connect_import") -> dict:
    """Store REAL user-provided health records (Health Connect export / Takeout Fit).
    Accepts a flexible record shape so raw exports parse without ceremony:
      {"type": "steps"|"sleep_min"|"resting_hr"|"weight_kg"|"hydration_ml"|"workout",
       "day": "YYYY-MM-DD", "value": number,
       workout extras: "name"/"sport", "duration_min", "distance_km", "kcal"}
    Unknown types are counted as skipped — never guessed, never faked."""
    n_days = n_acts = skipped = 0
    with connect() as db:
        for r in (records or [])[:1000]:
            if not isinstance(r, dict):
                skipped += 1
                continue
            rtype = str(r.get("type") or r.get("metric") or "").strip().lower()
            day = str(r.get("day") or r.get("date") or "")[:10]
            try:
                val = float(r.get("value") or r.get("amount") or 0)
            except (TypeError, ValueError):
                val = 0
            aliases = {"steps": "steps", "step_count": "steps", "sleep": "sleep_min", "sleep_minutes": "sleep_min", "sleep_min": "sleep_min",
                       "resting_hr": "resting_hr", "heart_rate": "resting_hr", "weight": "weight_kg", "weight_kg": "weight_kg",
                       "hydration": "hydration_ml", "water": "hydration_ml", "hydration_ml": "hydration_ml"}
            metric = aliases.get(rtype)
            if metric and day and len(day) == 10 and val > 0:
                col = {"steps": "steps", "sleep_min": "sleep_min", "resting_hr": "resting_hr",
                       "weight_kg": "weight_kg", "hydration_ml": "hydration_ml"}[metric]
                db.execute(
                    f"""INSERT INTO daily_metrics (user_id,day,{col},source,updated_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(user_id,day) DO UPDATE SET {col}=COALESCE(MAX({col},excluded.{col}),excluded.{col}),
                        source=excluded.source,updated_at=excluded.updated_at""",
                    (uid, day, int(val) if metric != "weight_kg" else round(val, 1), source_label, now()))
                n_days += 1
            elif rtype in ("workout", "exercise", "exercise_session", "activity") and day:
                name = str(r.get("name") or r.get("sport") or "Imported workout")[:60]
                try:
                    dur_s = int(float(r.get("duration_min") or 0) * 60)
                except (TypeError, ValueError):
                    dur_s = 0
                try:
                    km = round(float(r.get("distance_km") or 0), 2)
                except (TypeError, ValueError):
                    km = 0
                try:
                    kcal = int(float(r.get("kcal") or 0))
                except (TypeError, ValueError):
                    kcal = 0
                db.execute(
                    """INSERT OR IGNORE INTO health_activities
                       (user_id,provider,external_id,sport,name,distance_km,moving_s,elev_m,kcal,avg_hr,max_hr,avg_pace_sec_km,started_at,raw_json,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, "health_connect", f"hc-{day}-{name}-{dur_s}", name, name, km, dur_s, 0, kcal, 0, 0, 0,
                     day + "T00:00:00", "{}", now()))
                n_acts += max(0, db.execute("SELECT changes()").fetchone()[0])
            else:
                skipped += 1
        db.execute(
            """INSERT INTO health_connections (user_id,provider,status,connected_at,last_synced_at)
               VALUES (?,?,?,?,?) ON CONFLICT(user_id,provider) DO UPDATE SET
               status='connected',last_synced_at=excluded.last_synced_at""",
            (uid, "health_connect", "connected", now(), now()))
    return {"ok": True, "days_stored": n_days, "activities_stored": n_acts, "skipped": skipped,
            "note": "Real data stored to your account. Nothing is estimated or invented."}


def health_disconnect(uid: int, provider: str) -> dict:
    with connect() as db:
        db.execute("UPDATE health_connections SET status='disconnected',access_token='',refresh_token='' WHERE user_id=? AND provider=?", (uid, provider))
        if provider == "google_fit":
            db.execute("DELETE FROM health_activities WHERE user_id=? AND provider='google_fit'", (uid,))
        elif provider == "health_connect":
            db.execute("DELETE FROM health_activities WHERE user_id=? AND provider='health_connect'", (uid,))
            db.execute("DELETE FROM daily_metrics WHERE user_id=? AND source LIKE 'health_connect%'", (uid,))
    return {"ok": True}


def connections_status(uid: int) -> dict:
    """All integrations + what the web app can/cannot do today (honest)."""
    return {
        "items": [
            google_fit_status(uid),
            health_connect_status(uid),
        ],
        "privacy": "Health data stays on your account, is never public, and is used only for your own insights. Disconnect or 'Remove imported data' anytime.",
    }


# ---------------------------------------------------------------------------
# Unified fitness data layer (real data only, from existing tables)
# ---------------------------------------------------------------------------

def unified_overview(uid: int) -> dict:
    with connect() as db:
        game = db.execute("SELECT xp,streak FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
        s = ai_service.get_settings(db, uid) if ai_service else {}
        t = ai_service.targets_from_profile(s) if ai_service else {}
        week_sessions = db.execute(
            "SELECT count(*) c, COALESCE(sum(est_kcal),0) k, COALESCE(sum(duration_min),0) m FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-7 days')", (uid,)).fetchone()
        cardio_km = db.execute(
            """SELECT COALESCE(sum(wl.distance_km),0) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
               WHERE ws.user_id=? AND wl.distance_km>0 AND ws.created_at>=date('now','-7 days')""", (uid,)).fetchone()[0]
        today_macros = db.execute(
            "SELECT COALESCE(sum(kcal),0) kcal, COALESCE(sum(protein_g),0) protein FROM nutrition_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()
        water = db.execute("SELECT COALESCE(sum(ml),0) FROM water_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()[0]
        weight = db.execute("SELECT weight_kg,entry_date FROM progress_entries WHERE user_id=? AND weight_kg>0 ORDER BY entry_date DESC LIMIT 1", (uid,)).fetchone()
        metrics = db.execute("SELECT steps,sleep_min,resting_hr,weight_kg,source FROM daily_metrics WHERE user_id=? ORDER BY day DESC LIMIT 1", (uid,)).fetchone()
        cons = db.execute("SELECT provider,status,last_synced_at FROM health_connections WHERE user_id=? AND status='connected'", (uid,)).fetchall()
    return {
        "streak": game["streak"] if game else 0,
        "xp": game["xp"] if game else 0,
        "goal": s.get("goal", "") if isinstance(s, dict) else "",
        "week": {"sessions": week_sessions["c"], "kcal": week_sessions["k"], "minutes": week_sessions["m"], "cardio_km": round(cardio_km, 1)},
        "today": {
            "kcal": today_macros["kcal"], "kcal_target": t.get("kcal_target", 0),
            "protein": today_macros["protein"], "protein_target": t.get("protein_target", 0),
            "water_ml": water, "water_target_ml": t.get("water_target_ml", 0),
        },
        "weight_kg": weight["weight_kg"] if weight else (metrics["weight_kg"] if metrics and metrics["weight_kg"] else None),
        "metrics": dict(metrics) if metrics else None,
        "connections": [dict(c) for c in cons],
    }


# ---------------------------------------------------------------------------
# Cardio analysis — real distance/duration/pace/HR where available
# ---------------------------------------------------------------------------

def cardio_analysis(uid: int) -> dict:
    with connect() as db:
        rows = db.execute(
            """SELECT ws.created_at day, ws.duration_min, wl.distance_km, ws.est_kcal
               FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
               WHERE ws.user_id=? AND wl.distance_km>0 AND ws.created_at>=date('now','-56 days')
               ORDER BY ws.created_at""", (uid,)).fetchall()
        hrows = db.execute(
            """SELECT started_at day, sport, moving_s, distance_km, elev_m, kcal, avg_hr, max_hr, avg_pace_sec_km
               FROM health_activities WHERE user_id=? AND started_at>=date('now','-56 days') ORDER BY started_at""", (uid,)).fetchall()
    acts = []
    for r in rows:
        if r["duration_min"] and r["distance_km"]:
            acts.append({"day": r["day"][:10], "sport": "workout", "min": r["duration_min"], "km": r["distance_km"], "hr": 0})
    for r in hrows:
        if r["moving_s"] or r["distance_km"]:
            acts.append({"day": r["day"][:10], "sport": r["sport"], "min": round(r["moving_s"] / 60), "km": r["distance_km"], "hr": r["avg_hr"] or 0})
    if len(acts) < 2:
        return {"insufficient": True,
                "need": "Log cardio workouts with distance (running, cycling, walking) — or connect Google Fit — and I'll analyze pace, duration and consistency here.",
                "have": len(acts)}
    import datetime as _dt
    today = _dt.date.today().isoformat()
    cut = (_dt.date.today() - _dt.timedelta(days=28)).isoformat()
    recent = [a for a in acts if a["day"] >= cut]
    prior = [a for a in acts if a["day"] < cut]
    recent_km = sum(a["km"] for a in recent)
    recent_min = sum(a["min"] for a in recent)
    weeks = max(1, round(len(recent) / 7, 1))
    pace_now = (recent_min / recent_km) if (recent_km and recent_min) else 0
    pace_prior = (sum(a["min"] for a in prior) / sum(a["km"] for a in prior)) if (prior and sum(a["km"] for a in prior) and sum(a["min"] for a in prior)) else 0
    pace_trend = None
    if pace_prior and pace_now:
        pace_trend = round((pace_prior - pace_now) / pace_prior * 100, 1)  # + = faster
    hrs = [a["hr"] for a in recent if a["hr"]]
    days = sorted({a["day"] for a in recent})
    gaps = [(_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days for a, b in zip(days, days[1:])]
    return {
        "insufficient": False,
        "window": "last 28 days",
        "sessions": len(recent),
        "total_km": round(recent_km, 1),
        "total_min": recent_min,
        "per_week": {"sessions": round(len(recent) / 4, 1), "km": round(recent_km / 4, 1)},
        "avg_pace_min_km": round(pace_now, 2) if pace_now else None,
        "pace_trend_pct": pace_trend,
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "longest_km": round(max(a["km"] for a in recent), 1) if recent else 0,
        "consistency_days": len(days),
        "typical_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
        "sports": sorted({a["sport"] for a in recent}),
    }


# ---------------------------------------------------------------------------
# Personalized recommendation — real activity patterns only
# ---------------------------------------------------------------------------

def recommendation(uid: int) -> dict:
    with connect() as db:
        s = ai_service.get_settings(db, uid) if ai_service else {}
        week = db.execute("SELECT count(*) c FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-7 days')", (uid,)).fetchone()["c"]
        hi = db.execute("SELECT count(*) c FROM workout_sessions ws JOIN workout_logs wl ON wl.session_id=ws.id WHERE ws.user_id=? AND wl.rpe>=8 AND ws.created_at>=date('now','-7 days')", (uid,)).fetchone()["c"]
        cardio = db.execute("SELECT count(*) c FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id WHERE ws.user_id=? AND wl.distance_km>0 AND ws.created_at>=date('now','-14 days')", (uid,)).fetchone()["c"]
        strength = db.execute("SELECT count(*) c FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id WHERE ws.user_id=? AND wl.weight>0 AND ws.created_at>=date('now','-14 days')", (uid,)).fetchone()["c"]
        last = db.execute("SELECT created_at FROM workout_sessions WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        water = db.execute("SELECT COALESCE(sum(ml),0) FROM water_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()[0]
        water_target = (ai_service.targets_from_profile(s) or {}).get("water_target_ml", 0) if ai_service else 0
    days_since = None
    if last:
        try:
            days_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).days
        except Exception:
            pass
    title, why = "", ""
    if days_since is None or days_since >= 5:
        title, why = "Ease back in with a 20-minute full-body session", "It's been a while since your last workout — start light and rebuild the habit."
    elif hi >= 3:
        title, why = "Recovery-focused session today", f"You've had {hi} high-intensity sessions in the last 7 days. Active recovery or mobility work will help you adapt."
    elif cardio >= 4 and strength <= 1:
        title, why = "Upper-body strength session", "You've been consistent with cardio but strength work is low this fortnight. Balance it out."
    elif strength >= 4 and cardio == 0:
        title, why = "Easy 25-minute cardio", "Lots of strength work lately — some easy cardio will help recovery and endurance."
    elif week >= ((s.get("days_per_week") or 3) if isinstance(s, dict) else 3):
        title, why = "You've hit your weekly target — keep the streak alive", "One more light session or an active rest day keeps momentum without overreaching."
    else:
        title, why = "Log your next planned session", "Consistency first: getting the session in matters more than making it perfect."
    tips = []
    if water_target and water < water_target * 0.5:
        tips.append(f"Hydration: {round(water/1000,1)}L so far — aim for {round(water_target/1000,1)}L today.")
    if days_since is not None and days_since >= 2:
        tips.append("Warm up 5–10 minutes before the main set.")
    return {"title": title, "why": why, "tips": tips, "days_since_last": days_since,
            "context": {"week_sessions": week, "high_intensity": hi, "cardio_sessions_14d": cardio, "strength_sessions_14d": strength}}


# ---------------------------------------------------------------------------
# Nutrition intelligence — real expenditure + intake context
# ---------------------------------------------------------------------------

def nutrition_intelligence(uid: int) -> dict:
    with connect() as db:
        s = ai_service.get_settings(db, uid) if ai_service else {}
        t = ai_service.targets_from_profile(s) if ai_service else {}
        burn7 = db.execute("SELECT COALESCE(sum(est_kcal),0) FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-7 days')", (uid,)).fetchone()[0]
        logs7 = db.execute("SELECT count(DISTINCT logged_on) d, COALESCE(avg(protein_g),0) p FROM (SELECT logged_on, sum(protein_g) protein_g FROM nutrition_logs WHERE user_id=? AND logged_on>=date('now','-7 days') GROUP BY logged_on)", (uid,)).fetchone()
        water7 = db.execute("SELECT count(*) FROM (SELECT logged_on, sum(ml) ml FROM water_logs WHERE user_id=? AND logged_on>=date('now','-7 days') GROUP BY logged_on HAVING sum(ml)>=?)", (uid, (t.get("water_target_ml") or 2000))).fetchone()[0]
    days_logged = logs7["d"] if logs7 else 0
    return {
        "burned_7d": burn7,
        "avg_daily_burn": round(burn7 / 7),
        "protein_target": t.get("protein_target", 0),
        "days_logged": days_logged,
        "protein_consistency_pct": round(days_logged / 7 * 100),
        "hydration_days_hit": water7,
        "note": "General fitness nutrition context only — not medical advice.",
        "guidance": _nutrition_guidance(uid, t, burn7, days_logged),
    }


def _nutrition_guidance(uid: int, t: dict, burn7: float, days_logged: int) -> list[str]:
    out = []
    goal = (t.get("goal") or "").lower()
    if burn7 > 2100 and "loss" not in goal:
        out.append("You burned ~" + str(round(burn7 / 7)) + " kcal/day from training — fuel sessions with carbs beforehand and protein after.")
    if days_logged < 4:
        out.append("Protein logging is patchy (under 4 of the last 7 days) — consistency here makes every other number more useful.")
    if t.get("protein_target"):
        out.append(f"Aim for roughly {t['protein_target']}g protein across the day; a palm-sized portion per meal is a simple anchor.")
    return out


# ---------------------------------------------------------------------------
# AI companion — broad knowledge + memory + optional LLM seam
# ---------------------------------------------------------------------------

EMERGENCY_TERMS = ("chest pain", "can't breathe", "cant breathe", "fainted", "passed out", "severe bleeding", "suicide", "heart attack", "stroke", "numb on one side")
INJURY_TERMS = ("injur", "pain", "hurts", "ache", "sprain", "strain", "tendon", "sharp pain", "swollen")


def _llm(messages: list[dict]) -> str | None:
    """Optional LLM (OpenAI-compatible). Groq first (GROQ_API_KEY), then any
    OpenAI-compatible API via FITVERSE_LLM_API/KEY. Returns None otherwise —
    every caller falls back to the deterministic engine."""
    try:
        import groq_ai
        if groq_ai.configured():
            sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
            chat_hist = [m for m in messages if m.get("role") in ("user", "assistant")][:-1]
            question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            reply = groq_ai.coach_reply(sys_msg, chat_hist, question)
            if reply:
                return reply
    except Exception:
        pass
    api = os.environ.get("FITVERSE_LLM_API", "").rstrip("/")
    key = os.environ.get("FITVERSE_LLM_KEY", "")
    model = os.environ.get("FITVERSE_LLM_MODEL", "gpt-4o-mini")
    if not (api and key):
        return None
    if not api:  # key given without API: default by key shape
        api = "https://openrouter.ai/api/v1" if key.startswith("sk-or-") else "https://api.openai.com/v1"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    if "openrouter.ai" in api:
        # OpenRouter best practice: honest attribution headers
        headers["HTTP-Referer"] = "https://fitverse.onrender.com"
        headers["X-Title"] = "FITVERSE"
        if "/" not in model:
            model = "meta-llama/llama-3.3-70b-instruct:free"  # free default unless a full OpenRouter model id is set
    try:
        body = json.dumps({"model": model, "messages": messages, "max_tokens": 500, "temperature": 0.6}).encode()
        req = urllib.request.Request(f"{api}/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode())["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _user_context(uid: int) -> dict:
    with connect() as db:
        s = ai_service.get_settings(db, uid) if ai_service else {}
        t = ai_service.targets_from_profile(s) if ai_service else {}
        week = db.execute("SELECT count(*) c, COALESCE(sum(duration_min),0) m FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-7 days')", (uid,)).fetchone()
        last = db.execute("SELECT title,created_at FROM workout_sessions WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        today = db.execute("SELECT COALESCE(sum(kcal),0) k, COALESCE(sum(protein_g),0) p FROM nutrition_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()
        water = db.execute("SELECT COALESCE(sum(ml),0) FROM water_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()[0]
        game = db.execute("SELECT xp,streak FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
    return {"goal": s.get("goal", "") if isinstance(s, dict) else "", "level": s.get("activity_level", "") if isinstance(s, dict) else "",
            "week_sessions": week["c"], "week_minutes": week["m"], "last_workout": (last["title"] + " on " + last["created_at"][:10]) if last else None,
            "today_kcal": today["k"], "kcal_target": t.get("kcal_target", 0), "today_protein": today["p"], "protein_target": t.get("protein_target", 0),
            "water_ml": water, "water_target_ml": t.get("water_target_ml", 0), "streak": game["streak"] if game else 0, "xp": game["xp"] if game else 0}


def _ctx_line(ctx: dict) -> str:
    bits = [f"Goal: {ctx['goal'] or 'general fitness'}"]
    bits.append(f"This week: {ctx['week_sessions']} workouts, {ctx['week_minutes']} min")
    if ctx["last_workout"]:
        bits.append(f"Last workout: {ctx['last_workout']}")
    bits.append(f"Today: {ctx['today_kcal']}/{ctx['kcal_target'] or '—'} kcal, {ctx['today_protein']}/{ctx['protein_target'] or '—'}g protein, {round(ctx['water_ml']/1000,1)}L water")
    bits.append(f"Streak: {ctx['streak']} days")
    return " | ".join(bits)


def _knowledge_reply(q: str, ctx: dict, uid: int) -> str | None:
    """Deterministic fitness knowledge engine — broad coverage, personal flavor."""
    ql = q.lower()

    def has(*ws):
        return any(w in ql for w in ws)

    # --- goals ---
    if has("gain muscle", "build muscle", "bulk", "get bigger", "hypertrophy"):
        return ("💪 Building muscle comes down to three levers: **progressive overload** (add reps or weight most weeks), **enough volume** (10–20 hard sets per muscle per week), and **eating enough** (small calorie surplus + ~1.6–2.2g protein per kg bodyweight).\n\nA simple split that works: push/pull/legs or upper/lower, 3–5 days a week, 6–12 rep range for most lifts. Your goal is set to " + (ctx['goal'] or 'general fitness') + " and you logged " + str(ctx['week_sessions']) + " sessions this week — hit 3+ consistently and progress compounds.")
    if has("lose fat", "fat loss", "lose weight", "cutting", "get lean", "weight loss"):
        return ("🔥 Sustainable fat loss = a moderate calorie deficit (300–500 kcal/day), high protein to keep muscle, and training you actually enjoy so you stay consistent.\n\nWhat moves the needle: daily steps (8–10k), 2–3 strength sessions a week to preserve muscle, and most of your plate from whole foods. Crash diets rebound — a 0.25–0.5 kg/week loss rate is the sweet spot. Your today's intake is " + str(ctx['today_kcal']) + " kcal" + (f" vs a {ctx['kcal_target']} kcal target" if ctx['kcal_target'] else "") + ".")
    if has("endurance", "stamina", "run faster", "5k", "10k", "long distance"):
        return ("🏃 Endurance builds with the 80/20 principle: ~80% of cardio at an easy, conversational pace, ~20% hard (intervals, tempo). Add no more than ~10% distance per week, and keep one long session weekly.\n\nConsistency beats intensity — three easy runs beat one brutal one. Check your Cardio tab in Progress for pace trends once you've logged a few sessions.")

    # --- training concepts ---
    if has("progressive overload") or (has("how", "get stronger") and has("stronger")):
        return ("📈 Progressive overload = gradually asking more of your body. In practice, any of these count: +1 rep at the same weight, +2.5kg when you hit the top of your rep range, an extra set, slower negatives, or shorter rest at the same output.\n\nTrack your lifts (the Workout logger does this automatically) and try to beat one number each session — not every session, but most weeks.")
    if has("sets", "reps", "set(", "rep range", "how many reps"):
        return ("🔢 Rep targets by goal:\n• **Strength:** 3–6 sets of 3–6 reps, heavy, long rests (2–4 min)\n• **Muscle growth:** 3–4 sets of 6–12 reps, 1–3 reps from failure\n• **Endurance/conditioning:** 2–3 sets of 12–20+ reps, short rests\n\nLeave 1–2 reps in the tank on most sets; take the last set close to failure on isolation work.")
    if has("split", "push pull", "upper lower", "bro split", "training days", "how to split"):
        return ("🗂 Splits by availability:\n• **2 days:** full body ×2\n• **3 days:** full body or push/pull/legs\n• **4 days:** upper/lower ×2\n• **5–6 days:** push/pull/legs repeat\n\nThe best split is the one you'll actually show up for. You're at " + str(ctx['week_sessions']) + " sessions/week right now — that fits a full-body or upper/lower pattern nicely.")
    if has("home workout", "no equipment", "at home", "bodyweight"):
        return ("🏠 Effective home session (3 rounds): 12 squats → 10 push-ups → 12 reverse lunges each leg → 30s plank → 10 glute bridges → 20s mountain climbers. Rest 60–90s between rounds.\n\nProgress it weekly: slow the tempo, add reps, elevate feet on push-ups, or move to single-leg squats. Bodyweight trains plenty — intensity is the variable, not equipment.")
    if has("beginner", "just started", "start working out", "new to fitness", "where do i start", "start gym"):
        return ("🌱 Welcome! The beginner superpower is that *everything works* at first. Keep it simple:\n• 3 days a week, full body: squat pattern, push, pull, hinge, core\n• 2–3 sets of 8–12, stop 2 reps before failure\n• Walk daily, sleep 7–9h, eat protein at each meal\n\nDo that for 8 weeks before optimizing anything. Consistency is the whole game — and FITVERSE streaks exist exactly for this. 🔥")
    if has("warmup", "warm up", "mobility", "stretch"):
        return ("🤸 A good warm-up is 5–10 minutes: 2–3 minutes easy cardio (skip, cycle, brisk walk), then dynamic moves for what you're training — leg swings and bodyweight squats for legs, arm circles and band pull-aparts for upper body. Save long static stretches for after training; before, you want movement, not relaxation.")

    # --- recovery ---
    if has("recovery", "rest day", "sore", "soreness", "doms", "tired", "fatigue", "overtraining"):
        return ("😴 Recovery is where adaptation happens. Basics that actually work: 7–9 hours of sleep, protein distributed through the day, easy movement on rest days (walks beat couch), and managing total stress.\n\nSoreness that lasts 3+ days or performance dropping several sessions in a row are your cues to dial back. You trained " + str(ctx['week_sessions']) + "× this week — if that included several max-effort days, an easy day is a smart call today.")
    if has("sleep"):
        return ("🛌 Sleep is the strongest legal performance enhancer: 7–9 hours. Consistent bed/wake times matter more than total hours; a dark, cool room helps; caffeine before ~2pm; screens dimmed in the last hour. Training hard on 5-hour sleep repeatedly is where injuries live.")

    # --- nutrition ---
    if has("calorie", "how much should i eat", "deficit", "surplus", "maintenance"):
        base = ("🍽 Calorie needs = your burn + goal adjustment. Your logged intake today is " + str(ctx['today_kcal']) + " kcal" + (f" against a {ctx['kcal_target']} kcal target" if ctx['kcal_target'] else "") + (f", and you've averaged ~{round(0)} training kcal this week" if False else "") + ".\n\nRule of thumb: fat loss → 300–500 below maintenance; muscle gain → 200–300 above. Weigh in 2–3×/week and adjust by ~100–200 kcal if the trend disagrees with the goal for 2+ weeks.")
        return base
    if has("protein"):
        return (f"🥩 Protein: roughly 1.6–2.2g per kg bodyweight daily. You're at {ctx['today_protein']}g today" + (f" of a {ctx['protein_target']}g target" if ctx['protein_target'] else "") + ".\n\nEasy wins: 30–40g per meal (palm of meat/fish, Greek yogurt, paneer/tofu, dal + rice combos, whey if handy). Spread it out — 3–4 feedings beat one giant dinner for muscle retention and appetite.")
    if has("carb", "rice", "oats", "bread"):
        return ("🍚 Carbs are training fuel, not the enemy. Prioritize them around workouts: rice, oats, potatoes, fruit, bread. A good default is 3–5g per kg bodyweight on training days, skewing to whole-food sources. If fat loss is the goal, you don't need to quit carbs — just keep portions deliberate and protein high.")
    if has("fat", "fats", "oil", "ghee", "nuts") and "fat loss" not in ql:
        return ("🥑 Fats keep hormones and joints happy — aim for ~0.8–1g per kg daily from nuts, seeds, olive oil, ghee, fatty fish, eggs. Keep them moderate if cutting (9 kcal/g adds up fast) but don't strip them to zero; that wrecks satiety and mood.")
    if has("meal idea", "what should i eat", "meal plan", "pre workout", "post workout", "before workout", "after workout"):
        return ("🍽 Simple templates:\n• **Pre-workout (1–2h before):** carbs + some protein — banana + yogurt, oats, rice + dal, toast + eggs\n• **Post-workout:** protein + carbs within a few hours — chicken/paneer + rice, eggs + toast, whey + fruit\n• **Any meal anchor:** a palm of protein, a fist of veg, a cupped hand of carbs, a thumb of fats\n\nUse the Nutrition scanner to log — it estimates macros from a description.")
    if has("hydrat", "water", "drink"):
        target = ctx['water_target_ml'] or 2500
        return (f"💧 Hydration target ~{round(target/1000,1)}L/day, more on sweaty training days. You're at {round(ctx['water_ml']/1000,1)}L today. Practical checks: pale-yellow urine, drink 500ml within the hour before training, sip during sessions over 45 minutes. Log glasses in Nutrition and FITVERSE nudges you.")

    # --- social / gamification ---
    if has("challenge", "compete", "join"):
        with connect() as db:
            n = db.execute("SELECT name FROM challenges WHERE is_active=1 ORDER BY id LIMIT 3").fetchall()
        names = ", ".join(c["name"] for c in n) if n else "the Challenges page"
        return (f"🏆 Challenges are the best consistency hack — social stakes beat willpower. Live right now: {names}.\n\nPick one that's ~20% beyond your current level, invite a friend (accountability doubles completion rates), and log progress after each session. Want me to open the Challenges page? Just say the word — or tap Challenges in the menu.")
    if has("streak", "motivation", "lazy", "dont feel like", "can't get up", "cant get up", "unmotivated"):
        return (f"🔥 Motivation follows action — the 5-minute rule works: commit to just 5 minutes; you'll usually finish. Your current streak is **{ctx['streak']} days**, and you're {ctx['week_sessions']} sessions into this week.\n\nShrink the task, not the goal: today's minimum is a 10-minute walk or one main lift. Streaks reward showing up, not perfection.")
    if has("plateau", "stuck", "not improving", "no progress"):
        return ("🏔 Plateaus usually mean one of: same stimulus too long (change reps/weights/exercise), recovery debt (sleep/food/stress), or volume too high *or* low. Rotate one variable at a time for 2–3 weeks and watch the trend, not single sessions. The Pattern Detector on your Fitness DNA page flags which one is most likely from your logs.")

    # --- exercises ---
    if has("squat", "deadlift", "bench", "press", "form", "technique") and has("how", "form", "technique"):
        return ("🏋 Form priorities that transfer to every main lift: brace your core like you're about to be tapped on the stomach, control the negative (2–3s), and stop the set when technique — not breath — breaks down.\n\nSpecifics: **Squat** — knees track over toes, hit at least parallel if mobility allows. **Deadlift** — bar over mid-foot, push the floor away, flat back. **Bench** — shoulder blades pinched, bar to lower chest, feet planted. Film a set from the side; it's the fastest coach.")
    if has("abs", "core", "six pack"):
        return ("🎯 Core: 2–3 focused sessions a week — planks (30–60s), hanging knee raises, cable/pallof presses, dead bugs. Abs are built in the gym but *revealed* by body-fat level, so pair them with your nutrition goal. Skip nothing-but-crunches; resistance beats reps.")

    return None


FOLLOWUP_NOUNS = ("chest", "leg", "arm", "back", "shoulder", "week", "day", "minutes", "min", "km", "run", "cardio", "gym", "train", "training", "workout", "session", "plan", "time", "home", "equipment", "diet", "eat", "protein", "calorie")


def _followup_reply(q: str, ctx: dict, last: str) -> str | None:
    """Context-aware answers for short follow-ups and common constraints."""
    ql = q.lower()
    import re as _re
    m = _re.search(r"(\d+)\s*(?:x|times|days|sessions?)\s*(?:a|per)?\s*week", ql)
    if m or "only" in ql and "week" in ql:
        n = int(m.group(1)) if m else 2
        splits = {2: "two full-body days (squat+push+pull each)", 3: "full body Mon/Wed/Fri or push-pull-legs",
                  4: "upper/lower ×2 — the sweet spot for most people", 5: "upper/lower ×2 + one arms/cardio day",
                  6: "push/pull/legs ×2 with one day genuinely easy"}
        plan = splits.get(n, "full-body sessions so every muscle gets hit 2–3× weekly")
        return (f"🗓 Training {n}× a week works fine — that's {plan}.\n\n"
                f"Two rules make limited days count: (1) every session covers a push, a pull, a squat/hinge and core, "
                f"(2) push the top sets close to failure so quality beats quantity. "
                f"You're currently at {ctx['week_sessions']} sessions this week — lock {n} into the Workout page and I'll track your consistency.")
    if _re.search(r"(\d+)\s*km.*(?:week|times)|run.*(?:\d+)\s*km", ql):
        return ("🏃 Nice — that running base helps recovery and heart health. To keep both progressing: run the easy ones genuinely easy "
                "(conversational pace), lift on different days or after easy runs, and eat enough carbs on double days. "
                "If strength is a priority, keep the two hard running sessions away from your heavy lower-body days.")
    if _re.search(r"(\d+)\s*(?:minutes|min|mins)\b", ql) or "short on time" in ql or "no time" in ql:
        m2 = _re.search(r"(\d+)", ql)
        t = int(m2.group(1)) if m2 else 30
        return (f"⏱ {t} minutes is plenty if you cut rest fluff: 3-minute warm-up, then a big lift (squat or push-up/bench or row) "
                f"supersetted with the opposite pattern, 3 rounds of 10–12, then one finisher (farmer carries or a 3-minute interval block). "
                f"Two focused {t}-minute sessions a week beat zero perfect ones — and your streak at {ctx['streak']} 🔥 survives on showing up.")
    if last:
        topic = last.split("\n")[0][:80]
        return (f"Building on that ({topic.lower().lstrip('🏋💪🔥🏃📈🔢🗂🏠🌱😴🥩🍚🥑🍽💧🏆🎯 ')}…): the key is applying it to your week — "
                f"you've got {ctx['week_sessions']} sessions logged, goal “{ctx['goal'] or 'general fitness'}”. "
                "Tell me one concrete constraint (days available, equipment, or time per session) and I'll turn it into a specific plan.")
    return None


def chat_reply(uid: int, message: str, conversation_id: int | None = None) -> dict:
    """Main companion entry: safety gate → memory → LLM (optional) → knowledge engine."""
    q = (message or "").strip()
    ql = q.lower()
    ctx = _user_context(uid)

    # conversation memory
    with connect() as db:
        if conversation_id:
            conv = db.execute("SELECT id FROM ai_conversations WHERE id=? AND user_id=?", (conversation_id, uid)).fetchone()
        else:
            conv = db.execute("SELECT id FROM ai_conversations WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        if not conv:
            cur = db.execute("INSERT INTO ai_conversations (user_id,title,created_at) VALUES (?,?,?)", (uid, q[:60] or "Coach chat", now()))
            cid = cur.lastrowid
        else:
            cid = conv["id"]
        history = [dict(r) for r in db.execute("SELECT role,content FROM ai_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12", (cid,))]
        db.execute("INSERT INTO ai_messages (conversation_id,role,content,created_at) VALUES (?,?,?,?)", (cid, "user", q[:500], now()))

    history = list(reversed(history))

    # safety: emergencies
    if any(t in ql for t in EMERGENCY_TERMS):
        reply = ("🚨 This sounds like it could be serious — please stop exercising and seek medical care now. "
                 "Contact local emergency services or a doctor. FITVERSE is a fitness companion, not a medical service, "
                 "and nothing I say replaces professional evaluation.")
        kind = "safety"
    elif any(t in ql for t in INJURY_TERMS):
        reply = ("🩹 For pain or injury, the safe general rule: stop the movement that hurts, apply the first-48h basics "
                 "(relative rest, ice if acute, gentle range as tolerated), and see a physiotherapist or doctor if it's sharp, "
                 "swollen, or persists beyond a few days. I'm a fitness companion, not a medical service — I can help you train "
                 "*around* most niggles safely once a professional has cleared the basics. Meanwhile, which area is bothering you "
                 "and did it start during a specific movement?")
        kind = "safety"
    else:
        # follow-up awareness: resolve "it/that/tomorrow" against last assistant topic
        last_assistant = next((h["content"] for h in reversed(history) if h["role"] == "coach"), "")
        if ql and len(q.split()) <= 6 and any(w in ql for w in ("yes", "yeah", "sure", "ok", "do it", "plan for me", "tomorrow", "today")) and last_assistant:
            reply = None  # let LLM/knowledge handle with context below
        else:
            reply = None

    if not reply:
        # try configured LLM with full memory + real context
        sys_prompt = (
            "You are FITVERSE's AI fitness companion: knowledgeable, warm, concise (under 180 words), and practical. "
            "You are NOT a doctor; give general fitness/wellness guidance only. "
            f"The user's real FITVERSE data: {_ctx_line(ctx)}. "
            "Use this data when relevant, never invent data the user doesn't have. Never recommend extreme dieting, dehydration, steroids, or unsafe training.")
        msgs = [{"role": "system", "content": sys_prompt}] + [
            {"role": "user" if h["role"] == "user" else "assistant", "content": h["content"]} for h in history[-10:]] + [
            {"role": "user", "content": q}]
        reply = _llm(msgs)
        kind = "ai" if reply else "brief"

    if not reply:
        # FITVERSE engine v5: composes the answer from the user's real data,
        # detected constraints, and constraints stated earlier in this chat —
        # rotating phrasings and topic-relevant details instead of canned text.
        try:
            import ai_engine
            prior_user_text = " . ".join(h["content"] for h in history if h["role"] == "user")[-800:]
            remembered = ai_engine.extract_constraints(prior_user_text) if prior_user_text else {}
            reply, kind, _ = ai_engine.composed_reply(uid, q, history, remembered)
        except Exception:
            reply, kind = None, "brief"

    if not reply:
        reply = _knowledge_reply(q, ctx, uid) or ""
        kind = "knowledge" if reply else "fallback"

    if not reply:
        last_assistant = next((h["content"] for h in reversed(history) if h["role"] == "coach"), "")
        reply = _followup_reply(q, ctx, last_assistant) or ""
        kind = "context" if reply else "fallback"

    if not reply:
        reply = ("I can help with training, nutrition, recovery, goals, challenges and your own FITVERSE data — try:\n"
                 "• \"Plan my week for muscle gain\"\n• \"How much protein do I need?\"\n• \"I only have 30 minutes — what should I do?\"\n• \"What challenge fits me?\"\n\n"
                 f"Meanwhile: you're at {ctx['week_sessions']} sessions this week, {ctx['today_protein']}g protein today, streak at {ctx['streak']} 🔥")

    with connect() as db:
        db.execute("INSERT INTO ai_messages (conversation_id,role,content,created_at) VALUES (?,?,?,?)", (cid, "coach", reply[:4000], now()))
    return {"ok": True, "reply": reply, "kind": kind, "conversationId": cid}


def compose_assist(uid: int, text: str) -> dict:
    """Composer assistant: polish wording + suggest hashtags via Groq.
    Honest fallback: returns the user's original text (never mangles without AI)."""
    if not text.strip():
        return {"ok": False, "error": "Write something first"}
    try:
        import groq_ai
        r = groq_ai.post_polish(text[:1000])
        if r:
            return {"ok": True, "engine": "groq", **r}
    except Exception:
        pass
    import re as _re
    from collections import Counter
    words = [w for w in _re.findall(r"[a-zA-Z]{4,}", text.lower())
             if w not in ("this", "that", "with", "just", "today", "about", "really", "have", "been")]
    tags = [w for w, _ in Counter(words).most_common(3)] or ["fitness"]
    return {"ok": True, "engine": "builtin", "text": text, "hashtags": tags + ["fitverse"]}


def daily_companion(uid: int) -> dict:
    """Morning brief — real data only; sections omitted when data is missing."""
    with connect() as db:
        s = ai_service.get_settings(db, uid) if ai_service else {}
        t = ai_service.targets_from_profile(s) if ai_service else {}
        week = db.execute("SELECT count(*) c FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-7 days')", (uid,)).fetchone()["c"]
        yesterday = db.execute("SELECT title,est_kcal FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-2 days') ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        today = db.execute("SELECT COALESCE(sum(kcal),0) k, COALESCE(sum(protein_g),0) p FROM nutrition_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()
        water = db.execute("SELECT COALESCE(sum(ml),0) FROM water_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()[0]
        game = db.execute("SELECT xp,streak FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
    rec = recommendation(uid)
    lines = []
    if yesterday:
        lines.append(f"You trained {yesterday['title']} recently" + (" — today could be a recovery or lighter session." if yesterday["est_kcal"] and yesterday["est_kcal"] > 450 else "."))
    else:
        lines.append("No sessions in the last couple of days — a short one today keeps the streak alive.")
    if week or (t.get("days_per_week") if isinstance(t, dict) else 0):
        lines.append(f"You're {week} workout{'s' if week != 1 else ''} into this week" + (f" (target {t['days_per_week']})." if isinstance(t, dict) and t.get("days_per_week") else "."))
    if t.get("water_target_ml"):
        glasses = round(water / 250)
        lines.append(f"Hydration: {glasses}/{round(t['water_target_ml']/250)} glasses so far.")
    ai_tip = None
    try:
        import groq_ai
        if groq_ai.configured():
            ai_tip = groq_ai.daily_tip(_ctx_line({**_user_context(uid), "goal": (s.get("goal") if isinstance(s, dict) else "") or "general fitness"}))
    except Exception:
        ai_tip = None
    return {
        "greeting": _part_of_day(),
        "streak": game["streak"] if game else 0,
        "recommendation": rec,
        "today": {"kcal": today["k"], "kcal_target": t.get("kcal_target", 0), "protein": today["p"], "protein_target": t.get("protein_target", 0)},
        "lines": lines,
        "ai_tip": ai_tip,  # Groq-generated when configured; None keeps the UI unchanged
        "build_prompt": "Build my plan",
    }


def _part_of_day() -> str:
    h = datetime.now().hour
    return "Good morning 👋" if h < 12 else "Good afternoon 👋" if h < 17 else "Good evening 👋"
