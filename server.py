"""FITVERSE MVP backend — stdlib-only HTTP API + SQLite persistence.

Run: python server.py
Then open: http://127.0.0.1:4173
"""
from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.resolve()
DATABASE = ROOT / "fitverse.db"

# PERF: SSE loops previously re-ran MAX(id)/dm_participants queries every tick for
# every connected client. We snapshot the small pieces that rarely change (who is
# in which DM thread, the global message high-water mark) and refresh them every
# ~30s. Message/notification DELIVERY itself stays live — those queries still run
# every tick, exactly as before, just on a reused connection instead of a new one.

# Load .env (gitignored) at boot: KEY=VALUE lines, without overriding real env vars.
# Local development uses this file; Render uses dashboard environment variables.
try:
    _env_file = ROOT / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
            if _k and _k not in os.environ:
                os.environ[_k] = _v
except Exception:
 pass  # .env is optional — real environment variables still work

import store  # persistent storage layer: database-backed sessions + optional remote DB
# NOTE: sessions now live in the DATABASE (table `sessions`) — a server restart,
# redeploy or Render spin-down no longer signs anyone out.

OAUTH_STATES: dict[str, float] = {}
TYPING: dict[int, tuple] = {}  # conversation_id -> (last typing timestamp, user_id)
DEMO_USER_ID = 1
_SNAP_CACHE: dict = {"at": 0.0, "msg_max": 0, "dm": {}}  # SSE helpers, refreshed ~30s


def _sse_snapshot(db) -> dict:
    """Cheap cached snapshot for the SSE loop (message high-water mark + DM map)."""
    now_t = time.time()
    if now_t - _SNAP_CACHE["at"] < 30.0 and _SNAP_CACHE["dm"]:
        return _SNAP_CACHE
    try:
        msg_max = db.execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0]
        dm: dict[int, list[int]] = {}
        for r in db.execute("SELECT conversation_id cid, user_id uid FROM dm_participants"):
            dm.setdefault(int(r["cid"]), []).append(int(r["uid"]))
        _SNAP_CACHE.update({"at": now_t, "msg_max": int(msg_max), "dm": dm})
    except sqlite3.OperationalError:
        pass  # tables not ready yet — keep whatever we had
    return _SNAP_CACHE


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(database: str | None = None):
    """Dual-mode DB handle — see store.py.

    Default: local SQLite file (unchanged behaviour, zero new dependencies).
    If FITVERSE_DB_URL + FITVERSE_DB_TOKEN are configured (Render deploys),
    returns a persistent remote libsql/Turso handle over plain HTTP.
    All existing call sites (server + ai/fitness/platform services) are
    untouched — they keep doing `with connect() as db: db.execute(...)`.
    """
    return store.connect(database or DATABASE)


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL UNIQUE, password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
  city TEXT NOT NULL DEFAULT 'Chennai', fitness_level TEXT NOT NULL DEFAULT 'Intermediate',
  fitness_goal TEXT NOT NULL DEFAULT 'General fitness', favorite_activity TEXT NOT NULL DEFAULT 'Basketball',
  preferred_time TEXT NOT NULL DEFAULT '5–7 PM', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_game_state (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  xp INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0, activities INTEGER NOT NULL DEFAULT 0,
  is_friend_with_rahul INTEGER NOT NULL DEFAULT 0, joined_activity INTEGER NOT NULL DEFAULT 0,
  challenge_status TEXT NOT NULL DEFAULT 'pending', booked_event INTEGER NOT NULL DEFAULT 0,
  liked_featured_post INTEGER NOT NULL DEFAULT 0, comments INTEGER NOT NULL DEFAULT 12,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS friendships (
  id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL REFERENCES users(id), addressee_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','blocked')), created_at TEXT NOT NULL,
  UNIQUE(requester_id, addressee_id)
);
CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, sport TEXT NOT NULL, starts_at TEXT NOT NULL,
  location_label TEXT NOT NULL, max_participants INTEGER NOT NULL, fitness_level TEXT NOT NULL,
  intensity TEXT NOT NULL, description TEXT, host_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_participants (
  activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, joined_at TEXT NOT NULL,
  PRIMARY KEY(activity_id, user_id)
);
CREATE TABLE IF NOT EXISTS challenges (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, challenge_type TEXT NOT NULL, target_value REAL,
  challenger_id INTEGER NOT NULL REFERENCES users(id), opponent_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK(status IN ('pending','active','completed')), winner_id INTEGER REFERENCES users(id),
  starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS communities (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL, activity TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS community_members (
  community_id INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL DEFAULT 'member', joined_at TEXT NOT NULL,
  PRIMARY KEY(community_id, user_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, starts_at TEXT NOT NULL,
  location_label TEXT NOT NULL, price_inr INTEGER NOT NULL, capacity INTEGER NOT NULL, organizer TEXT NOT NULL,
  description TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY, booking_code TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users(id),
  event_id INTEGER NOT NULL REFERENCES events(id), quantity INTEGER NOT NULL, status TEXT NOT NULL,
  qr_payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'fitness_update', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_likes (
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, PRIMARY KEY(post_id, user_id)
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS businesses (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, location_label TEXT NOT NULL,
  description TEXT NOT NULL, rating REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, reporter_id INTEGER NOT NULL REFERENCES users(id), target_type TEXT NOT NULL,
  target_id INTEGER NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, bio TEXT NOT NULL DEFAULT '',
  college_or_company TEXT, availability TEXT NOT NULL DEFAULT 'Weekdays', workout_intensity TEXT NOT NULL DEFAULT 'Moderate',
  preferred_location TEXT NOT NULL DEFAULT 'Campus', avatar_url TEXT, onboarding_completed INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_posts (
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, PRIMARY KEY(post_id,user_id)
);
CREATE TABLE IF NOT EXISTS challenge_participants (
  challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  progress REAL NOT NULL DEFAULT 0, completed_at TEXT, PRIMARY KEY(challenge_id,user_id)
);
CREATE TABLE IF NOT EXISTS activity_completions (
  activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  completed_at TEXT NOT NULL, PRIMARY KEY(activity_id,user_id)
);
CREATE TABLE IF NOT EXISTS xp_transactions (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, amount INTEGER NOT NULL,
  reason TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(user_id,source_type,source_id)
);
CREATE TABLE IF NOT EXISTS achievements (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL, icon TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_achievements (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, achievement_id INTEGER NOT NULL REFERENCES achievements(id) ON DELETE CASCADE,
  unlocked_at TEXT NOT NULL, PRIMARY KEY(user_id,achievement_id)
);
CREATE TABLE IF NOT EXISTS community_posts (
  id INTEGER PRIMARY KEY, community_id INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, created_at TEXT NOT NULL, UNIQUE(community_id,post_id)
);
CREATE TABLE IF NOT EXISTS business_events (
  business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  PRIMARY KEY(business_id,event_id)
);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), business_id INTEGER REFERENCES businesses(id),
  event_id INTEGER REFERENCES events(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), body TEXT NOT NULL, created_at TEXT NOT NULL,
  CHECK (business_id IS NOT NULL OR event_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at);
CREATE INDEX IF NOT EXISTS idx_xp_transactions_user ON xp_transactions(user_id,created_at);
CREATE INDEX IF NOT EXISTS idx_activity_participants_user ON activity_participants(user_id);

-- ===== FITVERSE 2.0: social graph, training, nutrition, progress, AI =====
CREATE TABLE IF NOT EXISTS follows (
  follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  followee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, PRIMARY KEY(follower_id, followee_id)
);
CREATE TABLE IF NOT EXISTS exercises (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, muscle TEXT NOT NULL, equipment TEXT NOT NULL,
  difficulty TEXT NOT NULL DEFAULT 'Intermediate', instructions TEXT NOT NULL DEFAULT '',
  mistakes TEXT NOT NULL DEFAULT '', met REAL NOT NULL DEFAULT 5.0
);
CREATE TABLE IF NOT EXISTS workout_sessions (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL,
  ended_at TEXT, duration_min INTEGER NOT NULL DEFAULT 0, total_volume REAL NOT NULL DEFAULT 0,
  est_kcal INTEGER NOT NULL DEFAULT 0, pr_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workout_logs (
  id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
  exercise_id INTEGER NOT NULL REFERENCES exercises(id), sets INTEGER NOT NULL DEFAULT 3,
  reps INTEGER NOT NULL DEFAULT 10, weight REAL NOT NULL DEFAULT 0, duration_min REAL NOT NULL DEFAULT 0,
  distance_km REAL NOT NULL DEFAULT 0, rpe INTEGER, is_pr INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workout_logs_session ON workout_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_workout_sessions_user ON workout_sessions(user_id, created_at);
CREATE TABLE IF NOT EXISTS nutrition_logs (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  meal TEXT NOT NULL DEFAULT 'breakfast', name TEXT NOT NULL, kcal INTEGER NOT NULL DEFAULT 0,
  protein_g REAL NOT NULL DEFAULT 0, carbs_g REAL NOT NULL DEFAULT 0, fat_g REAL NOT NULL DEFAULT 0,
  fiber_g REAL NOT NULL DEFAULT 0, qty REAL NOT NULL DEFAULT 1, logged_on TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nutrition_user_day ON nutrition_logs(user_id, logged_on);
CREATE TABLE IF NOT EXISTS foods (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kcal_per_100g INTEGER NOT NULL,
  protein_g REAL NOT NULL DEFAULT 0, carbs_g REAL NOT NULL DEFAULT 0, fat_g REAL NOT NULL DEFAULT 0, fiber_g REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS water_logs (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ml INTEGER NOT NULL, logged_on TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_water_user_day ON water_logs(user_id, logged_on);
CREATE TABLE IF NOT EXISTS progress_entries (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  weight_kg REAL, body_fat REAL, chest_cm REAL, waist_cm REAL, hips_cm REAL, arm_cm REAL,
  photo_path TEXT, note TEXT NOT NULL DEFAULT '', entry_date TEXT NOT NULL, created_at TEXT NOT NULL,
  is_public INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  age INTEGER, sex TEXT, height_cm REAL, weight_kg REAL, activity_level TEXT NOT NULL DEFAULT 'moderate',
  goal TEXT NOT NULL DEFAULT 'maintain', diet_pref TEXT NOT NULL DEFAULT 'balanced',
  days_per_week INTEGER NOT NULL DEFAULT 4, session_minutes INTEGER NOT NULL DEFAULT 45,
  equipment TEXT NOT NULL DEFAULT 'Full gym', kcal_target INTEGER, protein_target INTEGER,
  water_target_ml INTEGER NOT NULL DEFAULT 2500, is_private INTEGER NOT NULL DEFAULT 0,
  discoverable INTEGER NOT NULL DEFAULT 1, onboarded INTEGER NOT NULL DEFAULT 0,
  dna_cache TEXT, target_week INTEGER, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_conversations (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT 'Coach chat', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_messages (
  id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_workouts (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, plan_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocks (
  blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'block', created_at TEXT NOT NULL, PRIMARY KEY(blocker_id, blocked_id)
);
CREATE INDEX IF NOT EXISTS idx_follows_followee ON follows(followee_id);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id, created_at);
-- ===== FITVERSE 3.0: intelligence ecosystem =====
CREATE TABLE IF NOT EXISTS missions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mission_key TEXT NOT NULL, title TEXT NOT NULL, icon TEXT, description TEXT,
  metric TEXT NOT NULL, target INTEGER NOT NULL, reward_xp INTEGER NOT NULL DEFAULT 300,
  status TEXT NOT NULL DEFAULT 'active', invited_friend_id INTEGER, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_missions_user ON missions(user_id, status);
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'community',
  description TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_members (
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  joined_at TEXT NOT NULL, PRIMARY KEY(team_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_xp (
  id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, amount INTEGER NOT NULL,
  reason TEXT, source_type TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_team_xp_team ON team_xp(team_id);
CREATE TABLE IF NOT EXISTS post_reactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  reaction TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(post_id, user_id, reaction)
);
CREATE INDEX IF NOT EXISTS idx_reactions_post ON post_reactions(post_id);

-- ===== speed indexes: every hot panel query hits an index ==================
CREATE INDEX IF NOT EXISTS idx_daily_metrics_user_day ON daily_metrics(user_id, day);
CREATE INDEX IF NOT EXISTS idx_health_activities_user ON health_activities(user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_health_activities_start ON health_activities(started_at);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_community_members_user ON community_members(user_id);
CREATE INDEX IF NOT EXISTS idx_community_members_comm ON community_members(community_id);
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships(addressee_id, status);
CREATE INDEX IF NOT EXISTS idx_friendships_requester ON friendships(requester_id, status);
CREATE INDEX IF NOT EXISTS idx_ai_messages_conv ON ai_messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_user ON ai_conversations(user_id, id);
CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON blocks(blocker_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_feed_created ON posts(created_at);
CREATE INDEX IF NOT EXISTS idx_reactions_user ON post_reactions(user_id);

-- ===== FITVERSE 4.0: health integrations, business ecosystem, notification prefs =====
CREATE TABLE IF NOT EXISTS dm_participants (
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  last_read INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (conversation_id, user_id)
);
CREATE TABLE IF NOT EXISTS health_connections (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'connected',
  scopes TEXT NOT NULL DEFAULT '', external_user_id TEXT, access_token TEXT, refresh_token TEXT,
  token_expires_at TEXT, connected_at TEXT NOT NULL, last_synced_at TEXT, UNIQUE(user_id, provider)
);
CREATE TABLE IF NOT EXISTS health_activities (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL, external_id TEXT NOT NULL, sport TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '', distance_km REAL NOT NULL DEFAULT 0, moving_s INTEGER NOT NULL DEFAULT 0,
  elev_m REAL NOT NULL DEFAULT 0, kcal REAL NOT NULL DEFAULT 0, avg_hr INTEGER NOT NULL DEFAULT 0,
  max_hr INTEGER NOT NULL DEFAULT 0, avg_pace_sec_km REAL NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL, raw_json TEXT, created_at TEXT NOT NULL, UNIQUE(user_id, provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_health_activities_user ON health_activities(user_id, started_at);
CREATE TABLE IF NOT EXISTS daily_metrics (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, day TEXT NOT NULL,
  steps INTEGER NOT NULL DEFAULT 0, sleep_min INTEGER NOT NULL DEFAULT 0, resting_hr INTEGER NOT NULL DEFAULT 0,
  weight_kg REAL NOT NULL DEFAULT 0, hydration_ml INTEGER NOT NULL DEFAULT 0,
  blood_pressure INTEGER NOT NULL DEFAULT 0, blood_sugar INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  updated_at TEXT NOT NULL, PRIMARY KEY(user_id, day)
);
CREATE TABLE IF NOT EXISTS business_products (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price TEXT NOT NULL DEFAULT '',
  image TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_photos (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  path TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_hours (
  business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE, dow INTEGER NOT NULL,
  open_time TEXT NOT NULL DEFAULT '', close_time TEXT NOT NULL DEFAULT '', PRIMARY KEY(business_id, dow)
);
CREATE TABLE IF NOT EXISTS business_follows (
  business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, PRIMARY KEY(business_id, user_id)
);
CREATE TABLE IF NOT EXISTS business_posts (
  id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, created_at TEXT NOT NULL, UNIQUE(business_id, post_id)
);
CREATE TABLE IF NOT EXISTS notification_prefs (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, category TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, sound INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, category)
);
CREATE INDEX IF NOT EXISTS idx_biz_products ON business_products(business_id, position);
CREATE INDEX IF NOT EXISTS idx_biz_follows_user ON business_follows(user_id);
CREATE INDEX IF NOT EXISTS idx_biz_posts ON business_posts(business_id);
"""


def initialize_database() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        # FITVERSE 4.0 additive columns (idempotent)
        for col, typ in [("owner_id", "INTEGER"), ("tagline", "TEXT"), ("website", "TEXT"), ("phone", "TEXT"), ("address", "TEXT"), ("lat", "REAL"), ("lng", "REAL"), ("cover", "TEXT"), ("logo", "TEXT"), ("hours_note", "TEXT"), ("verified", "INTEGER DEFAULT 0")]:
            try: db.execute(f"ALTER TABLE businesses ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        for col, typ in [("media_url", "TEXT"), ("media_type", "TEXT"), ("is_public", "INTEGER DEFAULT 1"), ("biz_channel", "INTEGER"), ("media", "TEXT"), ("photo", "TEXT")]:
            try: db.execute(f"ALTER TABLE posts ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        for col, typ in [("link_url", "TEXT"), ("payload", "TEXT")]:
            try: db.execute(f"ALTER TABLE notifications ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        # Event cover photos: migrated HERE at boot (idempotent) instead of on every
        # GET /api/events request — on the remote DB those five UPDATEs ran per view.
        try: db.execute("ALTER TABLE events ADD COLUMN photo TEXT")
        except sqlite3.OperationalError: pass
        # FITVERSE 6.0 vitals: BP (sys mmHg) + fasting blood sugar (mg/dL) on daily metrics
        for _tbl, _col, _typ in (("daily_metrics", "blood_pressure", "INTEGER NOT NULL DEFAULT 0"),
                                 ("daily_metrics", "blood_sugar", "INTEGER NOT NULL DEFAULT 0"),
                                 ("ai_conversations", "pinned", "INTEGER NOT NULL DEFAULT 0")):
            try: db.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_typ}")
            except sqlite3.OperationalError: pass
        db.executemany("UPDATE events SET photo=? WHERE id=? AND (photo IS NULL OR photo='')", [
            ("cycling.jpg", 4), ("yoga.jpg", 5), ("gym.jpg", 6), ("running.jpg", 7), ("basketball.jpg", 8),
        ])
        for col, typ in [("owner_id", "INTEGER")]:
            try: db.execute(f"ALTER TABLE exercises ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        for col, typ in [("owner_id", "INTEGER")]:
            try: db.execute(f"ALTER TABLE exercises ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        for col, typ in [("owner_id", "INTEGER")]:
            try: db.execute(f"ALTER TABLE exercises ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        for col, typ in [("dna_cache", "TEXT"), ("target_week", "INTEGER")]:
            try: db.execute(f"ALTER TABLE user_settings ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError: pass
        stamp = now()
        db.executemany("INSERT OR IGNORE INTO achievements (id,code,name,description,icon) VALUES (?,?,?,?,?)", [
            (1,"first_activity","First Activity","Complete your first activity.","⚡"),
            (2,"challenge_champion","Challenge Champion","Win a fitness challenge.","🏆"),
            (3,"goal_crusher","Goal Crusher","Complete four activities in a week.","🎯"),
            (4,"seven_day_streak","7 Day Streak","Maintain a seven-day streak.","🔥"),
            (5,"event_participant","Event Participant","Book your first fitness event.","🎟️"),
            (6,"first_pr","First PR","Log a personal record.","🏋️"),
            (7,"mission_master","Mission Master","Complete 3 missions.","🥇"),
            (8,"accountability_partner","Accountability Partner","Add your first friend.","🤝"),
            (9,"consistency_master","Consistency Master","Train 12 times.","⚡"),
            (10,"century","Century Club","Reach 1000 XP.","💯"),
            (11,"hydration_helper","Hydration Hero","Log water on 5 different days.","💧"),
        ])
        # Community Mission Engine seed: college teams for the Fitness War
        stamp2 = now()
        db.executemany("INSERT OR IGNORE INTO teams (id,name,kind,description,created_at) VALUES (?,?,?,?,?)", [
            (1, "CSE", "college", "Computer Science squad — ship code and PRs.", stamp2),
            (2, "AIML", "college", "AI & ML crew — training models and bodies.", stamp2),
            (3, "ECE", "college", "Electronics squad — high voltage on and off court.", stamp2),
            (4, "MECH", "college", "Mechanical gang — torque matters.", stamp2),
        ])
        # every demo user joins a team deterministically so the war has stakes
        for u in db.execute("SELECT id FROM users").fetchall():
            db.execute("INSERT OR IGNORE INTO team_members (team_id,user_id,joined_at) VALUES (?,?,?)", (1 + (u[0] % 4), u[0], stamp2))
        # Re-runnable seed: the guard checks that ALL key pieces exist. A boot
        # that crashed partway (remote-DB first deploy, etc.) leaves a partial
        # database; re-entering this block heals it because every INSERT below
        # is INSERT OR IGNORE — a complete database is completely untouched.
        def _seed_complete(db):
            try:
                if db.execute("SELECT COUNT(*) c FROM users WHERE id<=4").fetchone()["c"] < 4: return False
                if db.execute("SELECT COUNT(*) c FROM communities WHERE id<=4").fetchone()["c"] < 4: return False
                if db.execute("SELECT COUNT(*) c FROM businesses").fetchone()["c"] < 1: return False
                if db.execute("SELECT COUNT(*) c FROM achievements").fetchone()["c"] < 11: return False
                if db.execute("SELECT COUNT(*) c FROM exercises").fetchone()["c"] < 1: return False
                if db.execute("SELECT COUNT(*) c FROM foods").fetchone()["c"] < 1: return False
                return True
            except sqlite3.OperationalError:
                return False
        exists = _seed_complete(db)
        if not exists:
            created = now()
            demo_salt = "fitverse-demo-salt"
            users = [
                (1, "Sai Kumar", "saikumar", "sai@fitverse.demo", "Chennai", "Intermediate", "General fitness", "Basketball", "5–7 PM"),
                (2, "Rahul Menon", "rahulmenon", "rahul@fitverse.demo", "Chennai", "Intermediate", "Sports performance", "Basketball", "5–6 PM"),
                (3, "Ananya Iyer", "ananyaiyer", "ananya@fitverse.demo", "Chennai", "Advanced", "Endurance", "Running", "6–7 AM"),
                (4, "Arjun Raj", "arjunraj", "arjun@fitverse.demo", "Chennai", "Intermediate", "General fitness", "Cycling", "6–8 AM"),
            ]
            for u in users:
                db.execute("""INSERT OR IGNORE INTO users (id,name,username,email,password_salt,password_hash,city,fitness_level,fitness_goal,favorite_activity,preferred_time,created_at)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (u[0], u[1], u[2], u[3], demo_salt, hash_password("demo1234", demo_salt), *u[4:], created))
            db.executemany("INSERT OR IGNORE INTO profiles (user_id,bio,availability,workout_intensity,preferred_location,updated_at) VALUES (?,?,?,?,?,?)", [
                (1,"Building a better relationship with consistency. Basketball after class.","Weekdays","Moderate","Campus",created),
                (2,"Courts, community and a little healthy competition.","Weekdays","Moderate","Campus",created),
                (3,"One more kilometre, one more story.","Mornings","High","Track",created),
                (4,"Chasing sunrise and long roads.","Weekends","Moderate","ECR",created),
            ])
            db.execute("INSERT OR IGNORE INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (1, 1080, 6, 3, 0, 0, "pending", 0, 0, 12, created))
            for user_id, xp, streak, activities in [(2, 1240, 9, 7), (3, 1170, 12, 8), (4, 950, 5, 5)]:
                db.execute("INSERT OR IGNORE INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (user_id, xp, streak, activities, 0, 0, "pending", 0, 0, 12, created))
            db.executemany("""INSERT OR IGNORE INTO activities (id,title,sport,starts_at,location_label,max_participants,fitness_level,intensity,description,host_id,created_at)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?)""", [
                (1, "Sunset basketball", "Basketball", "2026-09-10T17:30:00+05:30", "Campus Sports Ground", 8, "Intermediate", "Moderate", "A friendly post-class game.", 2, created),
                (2, "Campus loop run", "Running", "2026-09-10T18:00:00+05:30", "Campus Track", 12, "Beginner", "Moderate", "An easy social 5K.", 3, created),
                (3, "Weekend cycling crew", "Cycling", "2026-09-13T06:30:00+05:30", "ECR Checkpoint", 15, "Intermediate", "Moderate", "Coastal morning ride.", 4, created),
            ])
            db.executemany("INSERT OR IGNORE INTO activity_participants VALUES (?,?,?)", [(1,2,created),(1,3,created),(1,4,created),(2,2,created),(2,3,created)])
            db.execute("""INSERT OR IGNORE INTO challenges (id,title,challenge_type,target_value,challenger_id,opponent_id,status,winner_id,starts_at,ends_at,created_at)
                          VALUES (1,'Rahul 5K Challenge','running_distance',5,2,1,'pending',NULL,?,?,?)""",
                       ("2026-09-10T00:00:00+05:30", "2026-09-17T23:59:00+05:30", created))
            db.executemany("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id,progress) VALUES (?,?,?)", [(1,1,3.8),(1,2,4.2)])
            db.executemany("INSERT OR IGNORE INTO communities (id,name,description,activity,created_at) VALUES (?,?,?,?,?)", [
                (1,"Basketball Community","Courts, crews and competition.","Basketball",created),
                (2,"Chennai Runners","Run the city together.","Running",created),
                (3,"Gym Beginners","Small wins. Strong habits.","Gym",created),
                (4,"Cycling Club","Sunday miles and chai stops.","Cycling",created),
            ])
            db.execute("INSERT OR IGNORE INTO community_members VALUES (?,?,?,?)", (1,1,"member",created))
            db.executemany("""INSERT OR IGNORE INTO events (id,name,category,starts_at,location_label,price_inr,capacity,organizer,description,created_at)
                              VALUES (?,?,?,?,?,?,?,?,?,?)""", [
                (1,"Chennai Night Run 2026","Running","2026-09-20T19:00:00+05:30","Marina Beach",499,2400,"Chennai Running Collective","6K under city lights, music, medals and your fastest self.",created),
                (2,"Campus 3v3 Tournament","Basketball","2026-09-15T16:00:00+05:30","Campus Sports Ground",199,120,"FITVERSE Campus","A fast, friendly campus tournament.",created),
                (3,"Sunrise Yoga at Besant","Yoga","2026-09-18T06:00:00+05:30","Besant Nagar Beach",0,100,"Yoga Chennai","A gentle community flow by the sea.",created),
            ])
            db.execute("INSERT OR IGNORE INTO posts (id,author_id,body,kind,created_at) VALUES (1,3,?,'activity',?)", ("Finished my first 5K today! The last kilometre was all heart. 🏃", created))
            db.execute("INSERT OR IGNORE INTO conversations (id,kind,title,created_at) VALUES (1,'direct','Rahul Menon',?)", (created,))
            if not db.execute("SELECT 1 FROM messages WHERE conversation_id=1 LIMIT 1").fetchone():
                db.executemany("INSERT OR IGNORE INTO messages (conversation_id,sender_id,body,created_at) VALUES (?,?,?,?)", [(1,2,"Hey Sai! You joining basketball later?",created),(1,1,"Absolutely. Bringing an extra ball!",created)])
            if not db.execute("SELECT 1 FROM notifications WHERE user_id=1 AND title='Rahul invited you' LIMIT 1").fetchone():
                db.executemany("INSERT OR IGNORE INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,?,?)", [(1,"activity","Rahul invited you","Sunset basketball starts in 42 minutes.",0,created),(1,"challenge","Challenge reminder","Your 5K challenge is waiting.",0,created)])
            # businesses has no unique constraint — guard by name instead of OR IGNORE
            for _b in [("Pulse Fitness","Gym","Adyar","Community-first strength training.",4.7),("Courtside Academy","Sports academy","Guindy","Basketball coaching and court time.",4.5)]:
                if not db.execute("SELECT 1 FROM businesses WHERE name=?",(_b[0],)).fetchone():
                    db.execute("INSERT INTO businesses (name,category,location_label,description,rating,created_at) VALUES (?,?,?,?,?,?)",(*_b,created))


        # --- extended demo universe (idempotent, runs on every boot) ---
        # -- a living world: 8 athletes, 8 communities, 8 events, 7 activities --
        extra_users = [
            (5,  "Meera Krishnan",  "meerak",    "meera@fitverse.demo",  "Chennai", "Advanced",     "Endurance",          "Running",    "6–7 AM"),
            (6,  "Karthik Verma",    "karthikv",  "karthik@fitverse.demo","Chennai", "Beginner",     "General fitness",    "Gym",        "7–8 PM"),
            (7,  "Divya Rao",        "divyarao",  "divya@fitverse.demo",  "Chennai", "Intermediate",  "Flexibility",        "Yoga",       "6–7 AM"),
            (8,  "Aditya Menon",     "adityam",   "aditya@fitverse.demo", "Chennai", "Advanced",     "Sports performance", "Cycling",    "5–7 AM"),
        ]
        for u in extra_users:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (u[0],)).fetchone():
                db.execute("""INSERT INTO users (id,name,username,email,password_salt,password_hash,city,fitness_level,fitness_goal,favorite_activity,preferred_time,created_at)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (u[0], u[1], u[2], u[3], "fitverse-demo-salt", hash_password("demo1234", "fitverse-demo-salt"), *u[4:], stamp))
                db.execute("INSERT INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)", (u[0], 300 + u[0] * 137, 2 + u[0] % 7, 1 + u[0] % 5, 0, 0, "pending", 0, 0, 6, stamp))
                db.execute("INSERT OR IGNORE INTO profiles (user_id,bio,updated_at) VALUES (?,?,?)", (u[0], f"{u[7]} enthusiast chasing consistency.", stamp))
        extra_communities = [
            (5, "Sunrise Yogis",        "Breathe, stretch, repeat.",                 "Yoga",      "yoga.jpg"),
            (6, "Iron Addicts Chennai", "Strength is a skill. Practice it.",        "Gym",       "gym.jpg"),
            (7, "Coastal Cyclists",     "Sea breeze and sunrise miles.",            "Cycling",   "cycling.jpg"),
            (8, "Marathon Dreamers",    "42.195 km starts with one step.",          "Running",   "running.jpg"),
        ]
        for cid_, name, desc, act, photo in extra_communities:
            db.execute("INSERT OR IGNORE INTO communities (id,name,description,activity,created_at) VALUES (?,?,?,?,?)", (cid_, name, desc, act, stamp))
            try: db.execute("ALTER TABLE communities ADD COLUMN photo TEXT")
            except sqlite3.OperationalError: pass
            db.execute("UPDATE communities SET photo=? WHERE id=?", (photo, cid_))
        extra_events = [
            (4, "East Coast Ride",        "Cycling",   "2026-09-22T06:00:00+05:30", "East Coast Road",      299, 200,  "Chennai Cycling Club",   "A scenic group ride down the coast with chai stops.", "cycling.jpg"),
            (5, "Beach Yoga Festival",    "Yoga",      "2026-09-19T06:30:00+05:30", "Elliot's Beach",       149, 300,  "Yoga Chennai",            "Sunrise flows, breathwork and a beach breakfast.",    "yoga.jpg"),
            (6, "Iron Cup Strength Meet", "Gym",       "2026-09-26T17:00:00+05:30", "Pulse Fitness, Adyar", 399, 80,   "Pulse Fitness",           "Squat, bench, deadlift — community strength meet.",   "gym.jpg"),
            (7, "Monsoon Trail Half",     "Running",   "2026-10-04T05:45:00+05:30", "Chembarambakkam Trail",799, 500,  "Trail Runners Chennai",   "21.1K of forest trails, mist and single-track fun.", "running.jpg"),
            (8, "Hoops Winter League",    "Basketball","2026-10-11T16:00:00+05:30", "Nehru Stadium Courts", 249, 160,  "TN Basketball Assn",      "Team registrations open for the winter season.",     "basketball.jpg"),
        ]
        for eid, name, cat, when, loc, price, cap, org, desc, photo in extra_events:
            db.execute("INSERT OR IGNORE INTO events (id,name,category,starts_at,location_label,price_inr,capacity,organizer,description,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (eid, name, cat, when, loc, int(price), cap, org, desc, stamp))
        extra_activities = [
            (4, "Dawn patrol run",      "Running",    "2026-09-14T06:00:00+05:30", "Besant Nagar Beach", 10, "Intermediate", "Moderate", "Easy coastal 5K before the city wakes.", 5),
            (5, "Strength fundamentals","Gym",        "2026-09-14T19:00:00+05:30", "Pulse Fitness, Adyar",6, "Beginner",     "Moderate", "Squat and hinge technique session.",     6),
            (6, "Sunrise yoga flow",    "Yoga",       "2026-09-15T06:15:00+05:30", "Elliot's Beach",      20, "All levels",   "Light",    "Breath-led flow to open the day.",        7),
            (7, "ECR weekend ride",     "Cycling",    "2026-09-16T06:30:00+05:30", "East Coast Road",     12, "Intermediate",  "Moderate", "40K coastal spin with a chai stop.",      8),
        ]
        for aid_, title, sport, when, loc, cap, lvl, inten, desc, host in extra_activities:
            db.execute("INSERT OR IGNORE INTO activities (id,title,sport,starts_at,location_label,max_participants,fitness_level,intensity,description,host_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (aid_, title, sport, when, loc, cap, lvl, inten, desc, host, stamp))
            db.execute("INSERT OR IGNORE INTO activity_participants VALUES (?,?,?)", (aid_, host, stamp))
        db.executemany("INSERT OR IGNORE INTO community_members (community_id,user_id,role,joined_at) VALUES (?,?,?,?)", [
            (5,7,"owner",stamp),(5,3,"member",stamp),(6,6,"owner",stamp),(6,2,"member",stamp),
            (7,8,"owner",stamp),(7,4,"member",stamp),(8,5,"owner",stamp),(8,3,"member",stamp),
            (2,6,"member",stamp),(2,7,"member",stamp),(3,5,"member",stamp),(4,8,"member",stamp),
        ])
        # -- Reels: short vertical workout clips as photo posts --
        if not db.execute("SELECT 1 FROM posts WHERE kind='reel' LIMIT 1").fetchone():
            reels = [
                (3, "5AM run. Nobody clapping, still showing up. 🌅", "5K done before the city woke. Negative split!", "reel"),
                (5, "PB day at the platform 💪 100kg x 3", "Squat PR after 8 weeks of tempo blocks.", "reel"),
                (7, "Sunrise flow by the waves 🧘‍♀️", "30 minutes of breathwork changes everything.", "reel"),
                (8, "Coastal century ride 🚴 100km done", "Headwinds taught me patience today.", "reel"),
                (2, "Ankle-breaker crossover — game winner 🏀", "Streetball never misses.", "reel"),
                (4, "Rest day recovery routine 🧊", "Ice bath + mobility = fresh legs.", "reel"),
            ]
            for author, title, body, kind in reels:
                cur = db.execute("INSERT INTO posts (author_id,body,kind,created_at) VALUES (?,?,?,?)", (author, f"{title}\\n\\n{body}", kind, now()))
        db.executemany("INSERT OR IGNORE INTO conversations (id,kind,title,created_at) VALUES (?,?,?,?)", [
            (2, "community", "Basketball Community", stamp),
            (3, "direct", "Ananya Iyer", stamp),
            (4, "group", "Weekend Run Crew", stamp),
        ])
        if not db.execute("SELECT 1 FROM messages WHERE conversation_id=4 LIMIT 1").fetchone():
            # guarded: messages has no unique key, so this seed must not re-run per boot
            db.executemany("INSERT OR IGNORE INTO messages (conversation_id,sender_id,body,created_at) VALUES (?,?,?,?)", [
                (2, 2, "Court 3 is booked for Saturday, 6 PM. Who is in?", stamp),
                (3, 3, "Morning run tomorrow? Easy pace, 5K around the loop.", stamp),
                (4, 4, "Weekend ride plan is up — ECR, Sunday 6:30 AM.", stamp),
            ])
        # FITVERSE 5.0 migration (idempotent): backfill direct-chat membership from real
        # message history so the participant-based inbox shows every thread each user
        # genuinely exchanged messages in. Group/community demo chats stay out of
        # personal inboxes — private conversations belong to their real participants only.
        for r in db.execute("SELECT conversation_id, sender_id FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.kind='direct' GROUP BY conversation_id, sender_id").fetchall():
            db.execute("INSERT OR IGNORE INTO dm_participants (conversation_id,user_id,last_read) VALUES (?,?,0)", (r["conversation_id"], r["sender_id"]))
        for r in db.execute("SELECT conversation_id, group_concat(DISTINCT sender_id) senders FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.kind='direct' GROUP BY conversation_id").fetchall():
            ids = [int(x) for x in (r["senders"] or "").split(",") if x]
            if len(ids) == 2:
                for uid2 in ids:
                    db.execute("INSERT OR IGNORE INTO dm_participants (conversation_id,user_id,last_read) VALUES (?,?,0)", (r["conversation_id"], uid2))
        db.execute("INSERT OR IGNORE INTO events (id,name,category,starts_at,location_label,price_inr,capacity,organizer,description,created_at) "
                   "SELECT 4,'East Coast Ride','Cycling','2026-09-22T06:00:00+05:30','East Coast Road',299,200,'Chennai Cycling Club','A scenic group ride down the coast with chai stops.',? "
                   "WHERE NOT EXISTS (SELECT 1 FROM events WHERE id=4)", (stamp,))
        db.executemany("INSERT OR IGNORE INTO community_members (community_id,user_id,role,joined_at) VALUES (?,?,?,?)", [
            (1,2,"member",stamp),(1,3,"member",stamp),(1,4,"member",stamp),
            (2,2,"member",stamp),(2,3,"member",stamp),(4,1,"member",stamp),(4,4,"owner",stamp),
        ])

        # ===== FITVERSE 2.0: exercise library + food database =====
        db.executemany("INSERT OR IGNORE INTO exercises (id,name,muscle,equipment,difficulty,instructions,mistakes,met) VALUES (?,?,?,?,?,?,?,?)", [
            (1,"Barbell Bench Press","Chest","Barbell","Intermediate","Lie on the bench, grip just outside shoulder width. Lower the bar to mid-chest with control, then press up and slightly back.","Bouncing the bar off the chest; flaring elbows to 90 degrees.",6.0),
            (2,"Incline Dumbbell Press","Chest","Dumbbell","Intermediate","Set the bench to 30 degrees. Press the dumbbells up and slightly together, keeping wrists stacked over elbows.","Setting the angle too steep, turning it into a shoulder press.",5.5),
            (3,"Push-Up","Chest","Bodyweight","Beginner","Hands under shoulders, body in one line. Lower until chest is a fist off the floor, press up.","Sagging hips; half range of motion.",4.5),
            (4,"Cable Fly","Chest","Cable","Beginner","Set pulleys at chest height. With a soft elbow bend, sweep hands together in a wide arc and squeeze.","Turning it into a press by bending elbows during the rep.",4.0),
            (5,"Barbell Squat","Legs","Barbell","Intermediate","Bar on upper traps, brace hard, sit down between your hips until thighs hit parallel, drive up through mid-foot.","Knees caving in; losing bracing at the bottom.",7.0),
            (6,"Romanian Deadlift","Legs","Barbell","Intermediate","Soft knees, push hips back and slide the bar down your thighs until you feel a deep hamstring stretch, then stand tall.","Rounding the lower back; turning it into a squat.",6.5),
            (7,"Walking Lunge","Legs","Bodyweight","Beginner","Step forward and lower until both knees are at 90 degrees, then drive through the front heel into the next step.","Short steps that stress the front knee.",5.0),
            (8,"Leg Press","Legs","Machine","Beginner","Feet shoulder-width on the platform. Lower until knees reach 90 degrees without lifting your hips, then press.","Locking knees hard at the top; hands on knees.",5.5),
            (9,"Pull-Up","Back","Bodyweight","Intermediate","Hang with an overhand grip just outside shoulders. Pull your chest toward the bar, lower with control.","Kipping without purpose; cutting range short at the bottom.",6.0),
            (10,"Barbell Row","Back","Barbell","Intermediate","Hinge to about 45 degrees, row the bar to your lower ribs, squeeze shoulder blades, lower under control.","Jerking with the hips; shrugging instead of rowing.",6.0),
            (11,"Lat Pulldown","Back","Cable","Beginner","Grip wide, lean back 10 degrees, pull the bar to your collarbone while driving elbows down.","Pulling behind the neck; using momentum swings.",5.0),
            (12,"Seated Cable Row","Back","Cable","Beginner","Chest proud, pull the handle to your stomach, pause and squeeze, then let arms extend fully.","Rocking the torso for momentum.",5.0),
            (13,"Overhead Press","Shoulders","Barbell","Intermediate","Bar at collarbone, brace glutes and core, press straight up and finish with biceps by your ears.","Leaning back into a standing incline press.",5.5),
            (14,"Lateral Raise","Shoulders","Dumbbell","Beginner","Lead with elbows, raise out to shoulder height, pause, lower slowly. Lighter than you think.","Going too heavy and swinging.",4.0),
            (15,"Face Pull","Shoulders","Cable","Beginner","Set the rope at eye level, pull toward your forehead and rotate knuckles back.","Too much weight so it becomes a row.",4.0),
            (16,"Barbell Curl","Arms","Barbell","Beginner","Elbows pinned to your sides, curl the bar to shoulder height, lower over two seconds.","Swinging the hips to start the rep.",3.5),
            (17,"Hammer Curl","Arms","Dumbbell","Beginner","Neutral grip, curl both dumbbells keeping wrists locked, control the way down.","Half reps at the top only.",3.5),
            (18,"Triceps Rope Pushdown","Arms","Cable","Beginner","Elbows locked at your sides, push the rope down and split it at the bottom.","Leaning your bodyweight into the stack.",3.5),
            (19,"Plank","Core","Bodyweight","Beginner","Forearms down, one straight line from head to heels, squeeze glutes and brace.","Hips too high or sagging; holding your breath.",3.0),
            (20,"Hanging Knee Raise","Core","Bodyweight","Intermediate","Hang tall, raise knees to hip height without swinging, lower slowly.","Using momentum from a swing.",4.5),
            (21,"Easy Run","Cardio","Bodyweight","Beginner","Conversational pace where you could speak in full sentences.","Starting too fast and fading.",8.0),
            (22,"Interval Sprints","Cardio","Bodyweight","Advanced","After a warm-up: 30 seconds hard, 90 seconds easy. Repeat 6-10 times.","Skipping the warm-up; sprinting at 100% from rep one.",10.0),
            (23,"Cycling Moderate","Cardio","Machine","Beginner","Steady cadence 80-95 rpm at a resistance where breathing is elevated but controlled.","Saddle too low, knees tracking inward.",7.0),
            (24,"Burpee","Full Body","Bodyweight","Intermediate","Squat, kick to a plank, optional push-up, jump feet in and explode up.","Piking the hips on the plank kick-back.",8.5),
            (25,"Kettlebell Swing","Full Body","Dumbbell","Intermediate","Hinge, hike the bell back, snap hips forward and let the bell float to chest height.","Squatting the swing; lifting with the arms.",9.0),
            (26,"Glute Bridge","Glutes","Bodyweight","Beginner","Feet flat, drive hips up until knees-hips-shoulders align, squeeze at the top for a beat.","Overarching the lower back at the top.",3.5),
            (27,"Hip Thrust","Glutes","Barbell","Intermediate","Upper back on a bench, bar over hips, drive to full extension and pause.","Feet too far from the body, turning it into a hamstring move.",5.5),
            (28,"Downward Dog","Full Body","Bodyweight","Beginner","From a plank, lift hips up and back into an inverted V, press heels toward the floor.","Rounding the back to reach the heels down.",3.0),
        ])
        db.executemany("INSERT OR IGNORE INTO foods (id,name,kcal_per_100g,protein_g,carbs_g,fat_g,fiber_g) VALUES (?,?,?,?,?,?,?)", [
            (1,"Chicken Breast (grilled)",165,31,0,3.6,0),
            (2,"White Rice (cooked)",130,2.7,28,0.3,0.4),
            (3,"Brown Rice (cooked)",112,2.6,24,0.9,1.8),
            (4,"Whole Eggs",155,13,1.1,11,0),
            (5,"Oats (dry)",389,17,66,7,10),
            (6,"Banana",89,1.1,23,0.3,2.6),
            (7,"Greek Yogurt",59,10,3.6,0.4,0),
            (8,"Paneer",265,18,1.2,21,0),
            (9,"Dal (cooked)",116,9,20,0.4,8),
            (10,"Chapati",297,11,46,7.5,4.9),
            (11,"Idli",132,4.2,28,0.7,1),
            (12,"Dosa",168,3.9,30,3.7,1.1),
            (13,"Almonds",579,21,22,50,12),
            (14,"Peanut Butter",588,25,20,50,6),
            (15,"Milk (toned)",49,3.2,4.9,1.7,0),
            (16,"Whey Scoop (30g)",120,24,3,1.5,0),
            (17,"Salmon Fillet",208,20,0,13,0),
            (18,"Sweet Potato",86,1.6,20,0.1,3),
            (19,"Broccoli",34,2.8,7,0.4,2.6),
            (20,"Olive Oil",884,0,0,100,0),
            (21,"Chicken Biryani",290,9,40,9,1.5),
            (22,"Masala Dosa",218,4.7,33,7,1.6),
            (23,"Pasta (cooked)",158,5.8,31,0.9,1.8),
            (24,"Curd Rice",98,3.5,15,2.4,0.3),
            (25,"Protein Bar",380,30,35,10,5),
        ])
        db.execute("INSERT OR IGNORE INTO user_settings (user_id,age,sex,height_cm,weight_kg,activity_level,goal,kcal_target,protein_target,onboarded,updated_at) VALUES (1,21,'male',178,72,'moderate','build muscle',2500,150,1,?)", (stamp,))

        if exists:
            db.execute("""INSERT OR IGNORE INTO profiles (user_id,bio,availability,workout_intensity,preferred_location,updated_at)
                          SELECT id,'Fitness is better together.','Weekdays','Moderate','Campus',? FROM users""", (stamp,))
            db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id) VALUES (1,1)")
            db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id) VALUES (1,2)")


def user_state(db: sqlite3.Connection, user_id: int) -> dict:
    row = db.execute("SELECT * FROM user_game_state WHERE user_id=?", (user_id,)).fetchone()
    return dict(row)


def ics_for_event(event: dict) -> str:
    """Build a valid RFC 5545 calendar invite for an event."""
    import re as _re
    def _utc(ts):
        from datetime import datetime as _dt
        try: return _dt.fromisoformat(ts).strftime("%Y%m%dT%H%M%SZ") if "+" in ts else ts.replace("-", "").replace(":", "") + "00"
        except Exception: return "20260920T130000Z"
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//FITVERSE//EN\r\n" +
            f"BEGIN:VEVENT\r\nUID:fitverse-event-{event['id']}@fitverse.demo\r\n" +
            f"DTSTAMP:{_utc(now())}\r\n" +
            f"DTSTART:{_utc(event['starts_at'])}\r\n" +
            f"SUMMARY:{_re.sub(r'[\\,;]', ' ', event['name'])}\r\n" +
            f"LOCATION:{_re.sub(r'[\\,;]', ' ', event['location_label'])}\r\n" +
            f"DESCRIPTION:{_re.sub(r'[\\,;]', ' ', str(event.get('description', '')))}\r\n" +
            "END:VEVENT\r\nEND:VCALENDAR\r\n")


def friend_ids(db: sqlite3.Connection, user_id: int) -> list[int]:
    """Accepted friends + followed users — the social graph used for all friend-context."""
    rows = db.execute("""SELECT CASE WHEN requester_id=? THEN addressee_id ELSE requester_id END id FROM friendships
        WHERE status='accepted' AND (requester_id=? OR addressee_id=?)
        UNION SELECT followee_id FROM follows WHERE follower_id=?""", (user_id, user_id, user_id, user_id)).fetchall()
    return [r["id"] for r in rows]


def read_bootstrap(user_id: int) -> dict:
    with connect() as db:
        if user_id <= 0:
            """Signed-out visitors get a generic public experience: no personal identity,
            no personal data — public community counts and the real leaderboard only."""
            leaderboard = [dict(r) for r in db.execute("""SELECT u.name, g.xp, g.streak, g.activities
              FROM user_game_state g JOIN users u ON u.id=g.user_id ORDER BY g.xp DESC LIMIT 10""")]
            counts = {
                "friends": 0,
                "activities": db.execute("SELECT count(*) FROM activities").fetchone()[0],
                "communities": db.execute("SELECT count(*) FROM communities").fetchone()[0],
                "events": db.execute("SELECT count(*) FROM events").fetchone()[0],
            }
            return {"user": {"id": 0, "name": "", "username": "", "guest": True},
                    "state": {"xp": 0, "streak": 0, "activities": 0, "challenge": "pending"},
                    "leaderboard": leaderboard, "counts": counts, "guest": True}
        user = dict(db.execute("SELECT u.id,u.name,u.username,u.city,u.fitness_level,u.fitness_goal,u.favorite_activity,u.preferred_time,p.bio,p.avatar_url,p.onboarding_completed FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.id=?", (user_id,)).fetchone())
        game = user_state(db, user_id)
        leaderboard = [dict(r) for r in db.execute("""SELECT u.name, g.xp, g.streak, g.activities
          FROM user_game_state g JOIN users u ON u.id=g.user_id ORDER BY g.xp DESC LIMIT 10""")]
        counts = {
            "friends": db.execute("SELECT count(*) FROM friendships WHERE status='accepted' AND (requester_id=? OR addressee_id=?)", (user_id,user_id)).fetchone()[0],
            "activities": db.execute("SELECT count(*) FROM activities").fetchone()[0],
            "communities": db.execute("SELECT count(*) FROM communities").fetchone()[0],
            "events": db.execute("SELECT count(*) FROM events").fetchone()[0],
        }
    return {"user": user, "state": game, "leaderboard": leaderboard, "counts": counts}


def award_xp(db: sqlite3.Connection, user_id: int, amount: int, reason: str, source_type: str, source_id: str) -> bool:
    """Records an immutable award first, then updates the projection used by the UI."""
    try:
        db.execute("INSERT INTO xp_transactions (user_id,amount,reason,source_type,source_id,created_at) VALUES (?,?,?,?,?,?)", (user_id,amount,reason,source_type,source_id,now()))
    except sqlite3.IntegrityError:
        return False
    db.execute("UPDATE user_game_state SET xp=xp+? WHERE user_id=?", (amount,user_id))
    # Community Mission Engine: half of every legitimate XP flows to the user's team
    try:
        team = db.execute("SELECT team_id FROM team_members WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
        if team and amount > 0:
            db.execute("INSERT INTO team_xp (team_id,user_id,amount,reason,source_type,created_at) VALUES (?,?,?,?,?,?)", (team["team_id"],user_id,amount//2,reason,source_type,now()))
    except sqlite3.OperationalError:
        pass
    return True


def check_missions(db: sqlite3.Connection, user_id: int) -> dict | None:
    """Complete the active mission if its live metric hit the target. Awards XP + notifies."""
    try:
        import intelligence
        row = db.execute("SELECT * FROM missions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if not row:
            return None
        m = dict(row)
        progress = intelligence.mission_progress_for(db, user_id, m["metric"], m["created_at"])
        if progress >= m["target"]:
            db.execute("UPDATE missions SET status='completed', completed_at=? WHERE id=?", (now(), m["id"]))
            award_xp(db, user_id, m["reward_xp"], f"Mission complete: {m['title']}", "mission", str(m["id"]))
            db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",
                       (user_id, "mission", f"Mission complete: {m['title']}", f"+{m['reward_xp']} XP earned. A new mission is being prepared.", now()))
            return {"completed": m["title"], "xp": m["reward_xp"]}
    except sqlite3.OperationalError:
        pass
    return None


def check_achievements(db: sqlite3.Connection, user_id: int) -> list[str]:
    game = user_state(db,user_id); unlocked=[]
    prs = db.execute("SELECT COUNT(*) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id WHERE ws.user_id=? AND wl.is_pr=1",(user_id,)).fetchone()[0]
    missions = db.execute("SELECT COUNT(*) FROM missions WHERE user_id=? AND status='completed'",(user_id,)).fetchone()[0]
    friends = db.execute("SELECT COUNT(*) FROM friendships WHERE status='accepted' AND (requester_id=? OR addressee_id=?)",(user_id,user_id)).fetchone()[0]
    water_days = db.execute("SELECT COUNT(DISTINCT logged_on) FROM water_logs WHERE user_id=?",(user_id,)).fetchone()[0]
    thresholds = [
        (1, game["activities"] >= 1),
        (2, db.execute("SELECT 1 FROM challenges WHERE winner_id=? LIMIT 1",(user_id,)).fetchone() is not None),
        (3, game["activities"] >= 4),
        (4, game["streak"] >= 7),
        (5, game["booked_event"] == 1),
        (6, prs >= 1),
        (7, missions >= 3),
        (8, friends >= 1),
        (9, game["activities"] >= 12),
        (10, game["xp"] >= 1000),
        (11, water_days >= 5),
    ]
    for achievement_id, eligible in thresholds:
        if eligible:
            cursor=db.execute("INSERT OR IGNORE INTO user_achievements (user_id,achievement_id,unlocked_at) VALUES (?,?,?)",(user_id,achievement_id,now()))
            if cursor.rowcount:
                name=db.execute("SELECT name FROM achievements WHERE id=?",(achievement_id,)).fetchone()[0]
                unlocked.append(name)
                db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(user_id,"achievement","Achievement unlocked",name,now()))
    return unlocked


def recommendations(user_id: int) -> list[dict]:
    with connect() as db:
        mine=dict(db.execute("SELECT u.*,p.workout_intensity,p.preferred_location FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.id=?",(user_id,)).fetchone())
        others=[dict(r) for r in db.execute("SELECT u.*,p.workout_intensity,p.preferred_location FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.id<>?",(user_id,))]
    results=[]
    for person in others:
        activity=30 if person["favorite_activity"] == mine["favorite_activity"] else 0
        schedule=20 if person["preferred_time"] == mine["preferred_time"] or person["preferred_time"].startswith("5") and mine["preferred_time"].startswith("5") else 0
        level=15 if person["fitness_level"] == mine["fitness_level"] else 7
        goal=9 if person["fitness_goal"] != mine["fitness_goal"] else 15
        location=10 if person["city"] == mine["city"] else 0
        intensity=10 if person["workout_intensity"] == mine["workout_intensity"] else 4
        score=min(100,activity+schedule+level+goal+location+intensity)
        reasons=[]
        if activity: reasons.append("Same preferred activity")
        if level>=15: reasons.append("Similar fitness level")
        if schedule: reasons.append("Matching availability")
        if location: reasons.append("Nearby activity location")
        results.append({"id":person["id"],"name":person["name"],"username":person["username"],"activity":person["favorite_activity"],"fitnessLevel":person["fitness_level"],"preferredTime":person["preferred_time"],"score":score,"reasons":reasons})
    return sorted(results,key=lambda p:p["score"],reverse=True)


def list_feed(user_id: int) -> list[dict]:
    """Signed-in: the real feed. Guests: the same real posts but with author
    names anonymized to display initials — a visitor must never see a specific
    member's identity or any personal user data before signing in."""
    with connect() as db:
        try: db.execute("ALTER TABLE posts ADD COLUMN photo TEXT")
        except sqlite3.OperationalError: pass
        rows=db.execute("""SELECT p.id,p.body,p.kind,p.photo,p.media,p.created_at,u.name,u.username,p.author_id,
          (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id) AS likes,
          EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked,
          EXISTS(SELECT 1 FROM saved_posts s WHERE s.post_id=p.id AND s.user_id=?) AS saved,
          (SELECT count(*) FROM comments c WHERE c.post_id=p.id) AS comments
          FROM posts p JOIN users u ON u.id=p.author_id ORDER BY p.id DESC""",(user_id,user_id)).fetchall()
        # PERF: reactions used to run 2 queries PER POST (N+1). Two grouped queries
        # for the whole feed produce exactly the same shapes.
        reactions: dict[int, list] = {}
        my_reactions: dict[int, list] = {}
        try:
            for r in db.execute("SELECT post_id, reaction, COUNT(*) n FROM post_reactions GROUP BY post_id, reaction"):
                reactions.setdefault(r["post_id"], []).append({"reaction": r["reaction"], "n": r["n"]})
            for r in db.execute("SELECT post_id, reaction FROM post_reactions WHERE user_id=?", (user_id,)):
                my_reactions.setdefault(r["post_id"], []).append(r["reaction"])
        except sqlite3.OperationalError:
            pass  # reactions table not migrated yet — same fallback as before (empty lists)
        out=[]
        for row in rows:
            d=dict(row)
            d["reactions"]=reactions.get(d["id"], [])
            d["my_reactions"]=my_reactions.get(d["id"], [])
            if user_id == 0:  # anonymous visitor: anonymize the author
                d["name"] = "Community athlete"
                d["username"] = "athlete"
            out.append(d)
    return out


def coach_reply(user_id: int, prompt: str) -> dict:
    q=prompt.lower(); data=read_bootstrap(user_id); matches=recommendations(user_id)
    import intelligence, ai_service
    dna=intelligence.fitness_dna(user_id); debt=intelligence.fitness_debt(user_id)
    twin=intelligence.fitness_twin(user_id); patterns=intelligence.detect_patterns(user_id)
    with connect() as db:
        mission=intelligence.ensure_weekly_mission(db,user_id)
        protein=db.execute("SELECT COALESCE(SUM(protein_g),0) FROM nutrition_logs WHERE user_id=? AND logged_on=date('now')",(user_id,)).fetchone()[0]
        kcal=db.execute("SELECT COALESCE(SUM(kcal),0) FROM nutrition_logs WHERE user_id=? AND logged_on=date('now')",(user_id,)).fetchone()[0]
        settings=ai_service.get_settings(db,user_id)
        last_workouts=[dict(r) for r in db.execute("SELECT title,created_at FROM workout_sessions WHERE user_id=? ORDER BY id DESC LIMIT 3",(user_id,))]
    sc=dna["scores"]
    if any(w in q for w in ("mission","operation")):
        text=f"Your active mission is {mission['icon']} {mission['title']}: {mission['description']} Progress: {mission.get('progress',0)}/{mission['target']} · +{mission['reward_xp']} XP on completion."
    elif any(w in q for w in ("dna","personality","strengths")):
        text=f"Your Fitness DNA says you're {dna['personality']}. Top scores: {', '.join(f'{k.capitalize()} {v}' for k,v in sorted(sc.items(),key=lambda kv:-kv[1])[:3])}. Focus area: {dna['focus']}."
    elif any(w in q for w in ("debt","behind","missed")):
        text=f"Fitness debt: {debt['debt']} of {debt['target']} weekly sessions. {debt['advice']}"
    elif any(w in q for w in ("pattern","holding me back","plateau","plateauing","why am i not")):
        p=next((x for x in patterns if x["severity"]!="good"),None)
        text=f"{p['title']}. {p['detail']} {p['fix']}" if p else f"No concerning patterns — your recent training looks balanced. Weakest area right now: {twin['weakest'].capitalize()}. {twin['holding_back']}"
    elif any(w in q for w in ("protein","calorie","calories","eat","food","nutrition")):
        pt=settings.get("protein_target") or 120; kt=settings.get("kcal_target") or 2200
        text=f"Today: {kcal:g}/{kt} kcal and {protein:g}/{pt}g protein. " + ("Protein is behind — a chicken pane, dal, curd or a shake closes the gap." if protein<pt*0.6 else "Protein is on track — keep the meals coming.")
    elif any(w in q for w in ("today","what should i do","next workout","train today","suggestion","recommend")):
        focus=sc["cardio"]<50 and "cardio" or (sc["lower"] if False else ("lower body" if sc.get("strength",0)>55 else "upper body"))
        imbalanced=next((x for x in patterns if x["id"]=="imbalance"),None)
        if imbalanced: focus="lower body"
        elif debt["debt"]>=2: focus="an easy 30-minute full-body session — re-entry before intensity"
        text=f"Given your DNA ({dna['personality']}), I'd do {focus} today. {twin['where_could_go']}"
    elif any(w in q for w in ("workout","routine","session","exercise")):
        recent=" → ".join(w["title"] for w in last_workouts) if last_workouts else "no sessions yet"
        text=f"Recent sessions: {recent}. Based on that and your {sc['intensity']} intensity score, alternate muscle groups and keep RPE around 7-8. Need a plan? Use the AI generator on the Workout page."
    elif any(w in q for w in ("basketball","people","match","compatible","buddy","partner")):
        top=matches[0] if matches else None
        text=f"Your best current match is {top['name']} at {top['score']}%. You both enjoy {top['activity']} and share a weekday training window." if top else "Complete onboarding details to improve your matches."
    elif any(w in q for w in ("event","weekend")):
        text="Chennai Night Run is coming up at Marina Beach. It is a great social 6K option for your current activity level."
    elif any(w in q for w in ("challenge","compete")):
        text=f"You have a challenge system waiting — head to Challenges, pick a friend and stake your claim. Wins award +150 XP and a badge. Current streak to defend: {data['state']['streak']} days."
    elif any(w in q for w in ("motivat","lazy","tired","skip")):
        text=f"{mission['icon']} Small win first: {mission['title'].lower()} needs just {max(0,mission['target']-mission.get('progress',0))} more this week. Even 20 minutes keeps the {data['state']['streak']}-day streak breathing. You don't need motivation — you need a smaller first step."
    else:
        remaining=max(0,4-data["state"]["activities"])
        text=f"You are {remaining} activity{'ies' if remaining != 1 else 'y'} from your weekly goal. Active mission: {mission['title']} ({mission.get('progress',0)}/{mission['target']}). Ask me about your DNA, debt, patterns, protein, or what to train today."
    return {"reply":text,"source":"deterministic profile and FITVERSE activity data"}


def perform_action(user_id: int, action: str, client_state: dict) -> dict:
    """Apply a domain operation transactionally; client state is not trusted for awards."""
    with connect() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            timestamp = now()
            game = user_state(db, user_id)
            if action == "friend":
                db.execute("INSERT OR IGNORE INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)", (user_id,2,"accepted",timestamp))
                db.execute("UPDATE user_game_state SET is_friend_with_rahul=1 WHERE user_id=?", (user_id,))
                db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)", (user_id,"friend","Rahul joined your fitness circle","You can now challenge or message Rahul.",timestamp))
            elif action == "join":
                existing = db.execute("SELECT 1 FROM activity_participants WHERE activity_id=1 AND user_id=?", (user_id,)).fetchone()
                if existing:
                    db.execute("DELETE FROM activity_participants WHERE activity_id=1 AND user_id=?", (user_id,))
                    db.execute("UPDATE user_game_state SET joined_activity=0 WHERE user_id=?", (user_id,))
                else:
                    full = db.execute("SELECT count(*) FROM activity_participants WHERE activity_id=1", ()).fetchone()[0] >= 8
                    if full: raise ValueError("Sunset basketball is full")
                    db.execute("INSERT INTO activity_participants VALUES (?,?,?)", (1,user_id,timestamp))
                    db.execute("UPDATE user_game_state SET joined_activity=1 WHERE user_id=?", (user_id,))
            elif action == "like":
                liked = db.execute("SELECT 1 FROM post_likes WHERE post_id=1 AND user_id=?", (user_id,)).fetchone()
                if liked:
                    db.execute("DELETE FROM post_likes WHERE post_id=1 AND user_id=?", (user_id,))
                    db.execute("UPDATE user_game_state SET liked_featured_post=0 WHERE user_id=?", (user_id,))
                else:
                    db.execute("INSERT INTO post_likes VALUES (?,?,?)", (1,user_id,timestamp))
                    db.execute("UPDATE user_game_state SET liked_featured_post=1 WHERE user_id=?", (user_id,))
            elif action == "comment":
                db.execute("INSERT INTO comments (post_id,author_id,body,created_at) VALUES (?,?,?,?)", (1,user_id,"Cheering you on! 🔥",timestamp))
                db.execute("UPDATE user_game_state SET comments=comments+1 WHERE user_id=?", (user_id,))
            elif action == "accept":
                db.execute("UPDATE challenges SET status='active' WHERE id=1 AND opponent_id=? AND status='pending'", (user_id,))
                db.execute("UPDATE user_game_state SET challenge_status='accepted' WHERE user_id=?", (user_id,))
            elif action == "challenge":
                db.execute("UPDATE challenges SET status='pending', winner_id=NULL WHERE id=1", ())
                db.execute("UPDATE user_game_state SET challenge_status='pending' WHERE user_id=?", (user_id,))
            elif action in ("win", "complete"):
                if action == "win":
                    challenge=db.execute("SELECT status FROM challenges WHERE id=1").fetchone()
                    if not challenge or challenge["status"] == "completed": raise ValueError("This challenge has already been completed")
                    db.execute("UPDATE challenges SET status='completed', winner_id=? WHERE id=1", (user_id,))
                    db.execute("UPDATE user_game_state SET challenge_status='won' WHERE user_id=?", (user_id,))
                    if not award_xp(db,user_id,120,"Won the Rahul 5K Challenge","challenge","1"): raise ValueError("Challenge XP was already awarded")
                    award=120
                else:
                    if not db.execute("SELECT 1 FROM activity_participants WHERE activity_id=1 AND user_id=?",(user_id,)).fetchone(): raise ValueError("Join the activity before completing it")
                    try: db.execute("INSERT INTO activity_completions VALUES (?,?,?)",(1,user_id,timestamp))
                    except sqlite3.IntegrityError: raise ValueError("This activity was already completed")
                    db.execute("UPDATE user_game_state SET activities=activities+1 WHERE user_id=?", (user_id,))
                    award_xp(db,user_id,80,"Completed Sunset basketball","activity","1")
                    award=80
                unlocked=check_achievements(db,user_id)
                suffix=f" Achievement unlocked: {', '.join(unlocked)}." if unlocked else ""
                db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)", (user_id,"xp","XP awarded",f"You earned +{award} XP.{suffix}",timestamp))
            elif action == "community":
                db.execute("INSERT OR IGNORE INTO community_members VALUES (?,?,?,?)", (2,user_id,"member",timestamp))
            elif action == "book":
                already = db.execute("SELECT 1 FROM bookings WHERE user_id=? AND event_id=1 AND status='confirmed'", (user_id,)).fetchone()
                if not already:
                    code = f"FV-2026-{secrets.randbelow(9000)+1000}"
                    db.execute("INSERT INTO bookings (booking_code,user_id,event_id,quantity,status,qr_payload,created_at) VALUES (?,?,?,?,?,?,?)", (code,user_id,1,1,"confirmed",f"fitverse://booking/{code}",timestamp))
                db.execute("UPDATE user_game_state SET booked_event=1 WHERE user_id=?", (user_id,))
                award_xp(db,user_id,75,"Booked Chennai Night Run 2026","event","1")
                check_achievements(db,user_id)
            elif action == "createActivity":
                db.execute("INSERT INTO activities (title,sport,starts_at,location_label,max_participants,fitness_level,intensity,description,host_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", ("New basketball session","Basketball","2026-09-12T17:30:00+05:30","Campus Sports Ground",8,"Intermediate","Moderate","Created from FITVERSE.",user_id,timestamp))
            elif action not in ("sync", "close", "notifications", "create", "edit"):
                raise ValueError("Unsupported action")
            db.execute("UPDATE user_game_state SET updated_at=? WHERE user_id=?", (timestamp,user_id))
            db.commit()
            return {"ok": True, "state": user_state(db,user_id)}
        except Exception:
            db.rollback()
            raise


class FitverseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FITVERSE/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Cookie fallback: if the browser ever loses localStorage, the session
        # token still rides along on every request — no forced re-logins.
        tok = self.headers.get("X-Session", "")
        if tok:
            self.send_header("Set-Cookie", f"fv_session={tok}; Path=/; Max-Age=31536000; SameSite=Lax")  # 365 days — matches session TTL
        self.end_headers()
        self.wfile.write(body)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 40_000_000: raise ValueError("Request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict): raise ValueError("JSON object required")
        return value

    def current_user(self) -> int:
        """0 = anonymous guest. A visitor without a valid session must never be demo
        user 1 — that leaked a real person's name and data to every signed-out visitor."""
        token = self.headers.get("X-Session", "")
        if not token:  # cookie fallback keeps people logged in across localStorage wipes
            from http.cookies import SimpleCookie
            c = SimpleCookie(self.headers.get("Cookie", ""))
            token = c.get("fv_session").value if c.get("fv_session") else ""
        return store.session_user(token)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        if path == "/api/health": return self.send_json(200,{"ok":True,"database":store.storage_mode(),"sessions":"database","time":now()})
        if path == "/api/ai/status":
            try:
                import groq_ai
                return self.send_json(200, groq_ai.status())
            except Exception:
                return self.send_json(200, {"provider": "groq", "configured": False,
                                            "note": "Built-in deterministic AI active — full AI unavailable."})
        # Signed-out visitors may browse PUBLIC content only; personal endpoints need a session.
        _GUEST_OK = ("/api/auth/", "/api/health", "/api/ai/status", "/api/bootstrap", "/api/leaderboard", "/api/users",
                     "/api/feed", "/api/reels", "/api/activities", "/api/events", "/api/communities",
                     "/api/community", "/api/businesses", "/api/challenges", "/api/search",
                     "/api/stream", "/api/friends/activity", "/api/social/context")
        if self.current_user() <= 0 and path.startswith("/api/") and not path.startswith(_GUEST_OK):
            return self.send_json(401, {"error": "Sign in to see that"})
        if path == "/api/bootstrap": return self.send_json(200, read_bootstrap(self.current_user()))
        if path == "/api/leaderboard":
            lb=read_bootstrap(self.current_user())["leaderboard"]
            if self.current_user() == 0:  # guests see initials, not identities
                for r in lb: r["name"]="Athlete "+str(r.get("name","?"))[:1]+"."
            return self.send_json(200,{"items":lb})
        if path == "/api/recommendations":
            recs=recommendations(self.current_user())
            if self.current_user() == 0:
                for r in recs: r["name"]="Athlete"
            return self.send_json(200,{"items":recs,"model":"deterministic compatibility service"})
        if path == "/api/coach":
            from urllib.parse import parse_qs
            return self.send_json(200,coach_reply(self.current_user(),parse_qs(query).get("q",[""])[0]))
        if path == "/api/feed": return self.send_json(200,{"items":list_feed(self.current_user())})
        if path == "/api/friends/activity":
            """Real recent activity from friends + followed users, newest first. Privacy: respects user_settings.is_private for non-friend rows."""
            uid = self.current_user()
            with connect() as db:
                fids = friend_ids(db, uid)
                if not fids:
                    return self.send_json(200, {"items": []})
                marks = ",".join("?" for _ in fids)
                items = []
                for r in db.execute(f"""SELECT ws.user_id, u.name, ws.title detail, ws.created_at at FROM workout_sessions ws
                    JOIN users u ON u.id=ws.user_id WHERE ws.user_id IN ({marks})
                    ORDER BY ws.id DESC LIMIT 12""", fids):
                    items.append({"kind": "workout", "icon": "🏋", "name": r["name"], "user_id": r["user_id"],
                                  "text": f"completed {r['detail']}", "at": r["at"]})
                for r in db.execute(f"""SELECT cp.user_id, u.name, c.title detail, c.id cid, cp.completed_at at FROM challenge_participants cp
                    JOIN challenges c ON c.id=cp.challenge_id JOIN users u ON u.id=cp.user_id
                    WHERE cp.user_id IN ({marks}) ORDER BY cp.rowid DESC LIMIT 8""", fids):
                    items.append({"kind": "challenge", "icon": "⚔️", "name": r["name"], "user_id": r["user_id"],
                                  "text": f"is competing in {r['detail']}", "at": r["at"], "link": "challenges"})
                for r in db.execute(f"""SELECT mp.user_id, u.name, m.title detail, m.reward_xp, m.completed_at at FROM missions mp
                    JOIN users u ON u.id=mp.user_id JOIN missions m ON m.id=mp.id
                    WHERE mp.user_id IN ({marks}) AND mp.status='completed' ORDER BY mp.id DESC LIMIT 6""", fids):
                    items.append({"kind": "mission", "icon": "🎯", "name": r["name"], "user_id": r["user_id"],
                                  "text": f"completed mission {r['detail']} (+{r['reward_xp']} XP)", "at": r["at"]})
                for r in db.execute(f"""SELECT ua.user_id, u.name, a.name detail, a.icon icon, ua.unlocked_at at FROM user_achievements ua
                    JOIN users u ON u.id=ua.user_id JOIN achievements a ON a.id=ua.achievement_id
                    WHERE ua.user_id IN ({marks}) ORDER BY ua.unlocked_at DESC LIMIT 8""", fids):
                    items.append({"kind": "achievement", "icon": r["icon"] or "🏅", "name": r["name"], "user_id": r["user_id"],
                                  "text": f"unlocked {r['detail']}", "at": r["at"]})
                for r in db.execute(f"""SELECT ap.user_id, u.name, a.title detail, a.id aid, ap.joined_at at FROM activity_participants ap
                    JOIN activities a ON a.id=ap.activity_id JOIN users u ON u.id=ap.user_id
                    WHERE ap.user_id IN ({marks}) ORDER BY ap.rowid DESC LIMIT 8""", fids):
                    items.append({"kind": "event", "icon": "📅", "name": r["name"], "user_id": r["user_id"],
                                  "text": f"is joining {r['detail']}", "at": r["at"], "link": "events"})
                for r in db.execute(f"""SELECT cm.user_id, u.name, c.name detail, cm.joined_at at FROM community_members cm
                    JOIN communities c ON c.id=cm.community_id JOIN users u ON u.id=cm.user_id
                    WHERE cm.user_id IN ({marks}) ORDER BY cm.joined_at DESC LIMIT 6""", fids):
                    items.append({"kind": "community", "icon": "◌", "name": r["name"], "user_id": r["user_id"],
                                  "text": f"joined {r['detail']}", "at": r["at"], "link": "communities"})
                for r in db.execute(f"""SELECT user_id, streak, updated_at at FROM user_game_state
                    WHERE user_id IN ({marks}) AND streak >= 7 ORDER BY streak DESC LIMIT 4""", fids):
                    nm = db.execute("SELECT name FROM users WHERE id=?", (r["user_id"],)).fetchone()
                    items.append({"kind": "streak", "icon": "🔥", "name": nm["name"] if nm else "A friend", "user_id": r["user_id"],
                                  "text": f"hit a {r['streak']}-day streak", "at": r["at"]})
                items.sort(key=lambda x: str(x["at"]) or "", reverse=True)
            return self.send_json(200, {"items": items[:14]})
        if path == "/api/social/context":
            """Per-item friend counts for communities/activities/challenges + friend commenters on recent posts."""
            uid = self.current_user()
            with connect() as db:
                fids = friend_ids(db, uid)
                out = {"communities": {}, "activities": {}, "challenges": {}, "posts": {}}
                if fids:
                    marks = ",".join("?" for _ in fids)
                    for r in db.execute(f"""SELECT community_id cid, COUNT(*) n, GROUP_CONCAT(u.name) names FROM community_members cm
                        JOIN users u ON u.id=cm.user_id WHERE cm.user_id IN ({marks}) GROUP BY community_id""", fids):
                        out["communities"][str(r["cid"])] = {"n": r["n"], "names": r["names"].split(",")[:3]}
                    for r in db.execute(f"""SELECT activity_id aid, COUNT(*) n, GROUP_CONCAT(u.name) names FROM activity_participants ap
                        JOIN users u ON u.id=ap.user_id WHERE ap.user_id IN ({marks}) GROUP BY activity_id""", fids):
                        out["activities"][str(r["aid"])] = {"n": r["n"], "names": r["names"].split(",")[:3]}
                    for r in db.execute(f"""SELECT challenge_id cid, COUNT(*) n, GROUP_CONCAT(u.name) names FROM challenge_participants cp
                        JOIN users u ON u.id=cp.user_id WHERE cp.user_id IN ({marks}) GROUP BY challenge_id""", fids):
                        out["challenges"][str(r["cid"])] = {"n": r["n"], "names": r["names"].split(",")[:3]}
                    for r in db.execute(f"""SELECT c.post_id pid, COUNT(DISTINCT c.author_id) n, GROUP_CONCAT(DISTINCT u.name) names
                        FROM comments c JOIN users u ON u.id=c.author_id
                        WHERE c.author_id IN ({marks}) AND c.post_id IN (SELECT id FROM posts ORDER BY id DESC LIMIT 30)
                        GROUP BY c.post_id""", fids):
                        out["posts"][str(r["pid"])] = {"n": r["n"], "names": (r["names"] or "").split(",")[:2]}
            return self.send_json(200, out)
        if path == "/api/feed/tabs":
            uid = self.current_user()
            tab = urlparse(self.path).query.split("tab=")[-1].split("&")[0] or "foryou"
            with connect() as db:
                if tab == "following":
                    rows = db.execute("""SELECT DISTINCT p.id FROM posts p
                        WHERE p.author_id=? OR p.author_id IN (SELECT followee_id FROM follows WHERE follower_id=?)
                        OR p.author_id IN (SELECT CASE WHEN requester_id=? THEN addressee_id ELSE requester_id END FROM friendships
                                           WHERE status='accepted' AND (requester_id=? OR addressee_id=?))
                        ORDER BY p.id DESC LIMIT 30""", (uid, uid, uid, uid, uid)).fetchall()
                elif tab == "trending":
                    rows = db.execute("""SELECT p.id, (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id)
                        + (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id)*2
                        + (SELECT COUNT(*) FROM post_reactions r WHERE r.post_id=p.id)*2 AS heat
                        FROM posts p ORDER BY heat DESC, p.id DESC LIMIT 30""").fetchall()
                else:  # foryou: own + friends + followed first, then everyone by recency
                    rows = db.execute("""SELECT p.id, CASE WHEN p.author_id=? THEN 3
                        WHEN p.author_id IN (SELECT followee_id FROM follows WHERE follower_id=?) THEN 2
                        WHEN p.author_id IN (SELECT CASE WHEN requester_id=? THEN addressee_id ELSE requester_id END FROM friendships
                                            WHERE status='accepted' AND (requester_id=? OR addressee_id=?)) THEN 2
                        ELSE 0 END AS affinity, p.id AS heat
                        FROM posts p ORDER BY affinity DESC, p.id DESC LIMIT 30""", (uid, uid, uid, uid, uid)).fetchall()
                ids = [r[0] for r in rows] or [0]
                marks = ",".join("?" for _ in ids)
                feed = [item for item in list_feed(uid) if item["id"] in set(ids)]
                feed.sort(key=lambda x: ids.index(x["id"]))
            return self.send_json(200, {"tab": tab, "items": feed})
        if path == "/api/profile":
            with connect() as db:
                row=db.execute("""SELECT u.id,u.name,u.username,u.email,u.city,u.fitness_level,u.fitness_goal,u.favorite_activity,u.preferred_time,
                p.bio,p.college_or_company,p.availability,p.workout_intensity,p.preferred_location,p.avatar_url,p.onboarding_completed,g.xp,g.streak,g.activities
                FROM users u JOIN profiles p ON p.user_id=u.id JOIN user_game_state g ON g.user_id=u.id WHERE u.id=?""",(self.current_user(),)).fetchone()
            return self.send_json(200,{"profile":dict(row)})
        if path == "/api/activities":
            with connect() as db:
                rows=db.execute("""SELECT a.*,count(ap.user_id) AS participant_count,
                  EXISTS(SELECT 1 FROM activity_participants mine WHERE mine.activity_id=a.id AND mine.user_id=?) AS joined
                  FROM activities a LEFT JOIN activity_participants ap ON ap.activity_id=a.id GROUP BY a.id ORDER BY a.starts_at""",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/communities":
            with connect() as db:
                rows=db.execute("""SELECT c.*,count(cm.user_id) AS member_count,
                  EXISTS(SELECT 1 FROM community_members mine WHERE mine.community_id=c.id AND mine.user_id=?) AS joined
                  FROM communities c LEFT JOIN community_members cm ON cm.community_id=c.id GROUP BY c.id ORDER BY member_count DESC""",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/events":
            with connect() as db:
                rows=db.execute("""SELECT e.*,COALESCE(sum(b.quantity),0) AS booked_count,
                  EXISTS(SELECT 1 FROM bookings mine WHERE mine.event_id=e.id AND mine.user_id=? AND mine.status='confirmed') AS booked
                  FROM events e LEFT JOIN bookings b ON b.event_id=e.id AND b.status='confirmed' GROUP BY e.id ORDER BY e.starts_at""",(self.current_user(),)).fetchall()
            items=[]
            for r in rows:
                d=dict(r)
                if not d.get("photo"): d["photo"]={"Running":"running.jpg","Basketball":"basketball.jpg","Yoga":"yoga.jpg","Cycling":"cycling.jpg","Gym":"gym.jpg"}.get(d["category"], "workout.jpg")
                items.append(d)
            return self.send_json(200,{"items":items})
        if path.endswith("/calendar.ics"):
            eid=int(path.split("/")[3])
            with connect() as db:
                ev=db.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
                if not ev: return self.send_json(404,{"error":"Event not found"})
                body=ics_for_event(dict(ev)); self.send_response(200)
                self.send_header("Content-Type","text/calendar; charset=utf-8")
                self.send_header("Content-Disposition",f"attachment; filename=fitverse-event-{eid}.ics")
                self.send_header("Content-Length",str(len(body.encode()))); self.end_headers(); self.wfile.write(body.encode()); return
        if path == "/api/notifications":
            with connect() as db: rows=db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/notifications/center":
            import platform_service
            return self.send_json(200, platform_service.list_notifications(self.current_user()))
        if path == "/api/notifications/prefs":
            import platform_service
            with connect() as db:
                prefs = platform_service.get_prefs(db, self.current_user())
            return self.send_json(200, {"prefs": prefs})
        if path == "/api/businesses/mine":
            uid = self.current_user()
            with connect() as db:
                rows = db.execute("SELECT * FROM businesses WHERE owner_id=? ORDER BY id", (uid,)).fetchall()
            return self.send_json(200, {"items": [dict(r) for r in rows]})
        if path == "/api/messages":
            """Legacy endpoint, now privacy-scoped: without ?conversation_id= it serves the
            caller's most recent thread; with one, it enforces membership like every route."""
            uid=self.current_user()
            if uid <= 0: return self.send_json(200,{"items":[]})
            q=urlparse(self.path).query
            try: cid=int(q.split("conversation_id=")[-1].split("&")[0] or 0)
            except ValueError: cid=0
            with connect() as db:
                if not cid:
                    row=db.execute("SELECT conversation_id id FROM dm_participants WHERE user_id=? ORDER BY conversation_id DESC LIMIT 1",(uid,)).fetchone()
                    cid=row["id"] if row else 0
                if not cid: return self.send_json(200,{"items":[]})
                if not db.execute("SELECT 1 FROM dm_participants WHERE conversation_id=? AND user_id=?",(cid,uid)).fetchone():
                    return self.send_json(403,{"error":"This conversation is private"})
                rows=db.execute('SELECT m.*,u.name,p.avatar_url FROM messages m JOIN users u ON u.id=m.sender_id LEFT JOIN profiles p ON p.user_id=m.sender_id WHERE m.conversation_id=? ORDER BY m.id',(cid,)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/reports":
            with connect() as db: rows=db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 50").fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/search":
            qstr='%'+urlparse(self.path).query.split("q=")[-1][:40].replace('+',' ').lower()+'%'
            uid=self.current_user(); results={"users":[],"activities":[],"communities":[],"events":[]}
            with connect() as db:
                results["users"]=[dict(r) for r in db.execute("SELECT u.id,u.name,u.username,u.favorite_activity,u.fitness_level,g.xp FROM users u JOIN user_game_state g ON g.user_id=u.id WHERE lower(u.name) LIKE ? OR lower(u.username) LIKE ? LIMIT 6",(qstr,qstr))]
                results["activities"]=[dict(r) for r in db.execute("SELECT id,title,sport,starts_at,location_label FROM activities WHERE lower(title) LIKE ? OR lower(sport) LIKE ? LIMIT 6",(qstr,qstr))]
                results["communities"]=[dict(r) for r in db.execute("SELECT id,name,description FROM communities WHERE lower(name) LIKE ? OR lower(description) LIKE ? LIMIT 6",(qstr,qstr))]
                results["events"]=[dict(r) for r in db.execute("SELECT id,name,category,starts_at,price_inr FROM events WHERE lower(name) LIKE ? OR lower(category) LIKE ? LIMIT 6",(qstr,qstr))]
            return self.send_json(200,{"items":results})
        if path == "/api/auth/google/url":
            """Start Google sign-in. Honest states: exact free setup steps when unconfigured."""
            import os as _os
            client_id=_os.environ.get("GOOGLE_CLIENT_ID","")
            if not client_id:
                return self.send_json(200,{"configured":False,"setup":"Free setup (~5 min, no billing): console.cloud.google.com → APIs & Services → OAuth consent screen (External) → Credentials → Create OAuth client ID (Web application) → add Authorized redirect URI <your-site-url>/api/auth/google/callback → then set environment variables GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."})
            import secrets as _s
            st=_s.token_urlsafe(16); OAUTH_STATES[st]=time.time()+600
            host=self.headers.get("Host") or "127.0.0.1:4173"
            proto=self.headers.get("X-Forwarded-Proto") or ("https" if ".onrender.com" in host else "http")
            from urllib.parse import quote as _q
            redirect=f"{proto}://{host}/api/auth/google/callback"
            url=("https://accounts.google.com/o/oauth2/v2/auth?response_type=code&scope="+_q("openid email profile")
                 +"&redirect_uri="+_q(redirect)+"&client_id="+_q(client_id)+"&state="+st+"&prompt=select_account")
            return self.send_json(200,{"configured":True,"url":url})
        if path == "/api/auth/google/callback":
            """Official Google OAuth code exchange. Creates or signs into the matching
            FITVERSE account by verified Google email; the secret never leaves the server."""
            import os as _os, base64 as _b64, html as _html
            from urllib.parse import parse_qs as _pqs, quote as _q
            from urllib.request import Request as _Req, urlopen as _open
            qs=_pqs(query); code=(qs.get("code") or [""])[0]; st=(qs.get("state") or [""])[0]
            if not code or not st or OAUTH_STATES.pop(st,0)<time.time():
                return self.send_json(400,{"error":"Invalid or expired sign-in state — please try again"})
            client_id=_os.environ.get("GOOGLE_CLIENT_ID",""); client_secret=_os.environ.get("GOOGLE_CLIENT_SECRET","")
            if not client_id or not client_secret: return self.send_json(500,{"error":"Google sign-in is not configured on this server"})
            host=self.headers.get("Host") or "127.0.0.1:4173"
            proto=self.headers.get("X-Forwarded-Proto") or ("https" if ".onrender.com" in host else "http")
            redirect=f"{proto}://{host}/api/auth/google/callback"
            try:
                req=_Req("https://oauth2.googleapis.com/token",
                    data=json.dumps({"code":code,"client_id":client_id,"client_secret":client_secret,"redirect_uri":redirect,"grant_type":"authorization_code"}).encode(),
                    headers={"Content-Type":"application/json"})
                tok=json.loads(_open(req,timeout=10).read().decode())
                payload=tok.get("id_token","").split(".")[1]; payload+="="*(-len(payload)%4)
                info=json.loads(_b64.urlsafe_b64decode(payload).decode())
                email=str(info.get("email","")).lower(); gname=str(info.get("name") or email.split("@")[0]); pic=str(info.get("picture") or "")
                if not email: raise ValueError("no email in Google profile")
            except Exception as _e:
                return self.send_json(401,{"error":f"Google sign-in failed: {_e}"})
            with connect() as db:
                row=db.execute("SELECT id,name FROM users WHERE email=?",(email,)).fetchone()
                if row:
                    uid=row["id"]; greeting=row["name"]
                else:
                    base="".join(ch for ch in email.split("@")[0].lower() if ch.isalnum() or ch=="_")[:20] or "athlete"
                    username=base; n=1
                    while db.execute("SELECT 1 FROM users WHERE username=?",(username,)).fetchone(): username=f"{base}{n}"; n+=1
                    salt=secrets.token_hex(16)
                    cur=db.execute("INSERT INTO users (name,username,email,password_salt,password_hash,created_at) VALUES (?,?,?,?,?,?)",
                                   (gname,username,email,salt,hash_password(secrets.token_urlsafe(32),salt),now()))
                    uid=cur.lastrowid
                    stamp=now()
                    db.execute("INSERT INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",(uid,0,0,0,0,0,"pending",0,0,0,stamp))
                    db.execute("INSERT INTO profiles (user_id,avatar_url,updated_at,onboarding_completed) VALUES (?,?,?,0)",(uid,pic or None,stamp))
                    greeting=gname
            token=secrets.token_urlsafe(32); store.session_put(token, uid)
            disp=_html.escape(greeting); safe_name=_q(greeting)
            html=("<!doctype html><meta charset='utf-8'><title>Signing in…</title><style>body{font-family:system-ui;display:grid;place-items:center;height:100vh;background:#f6faf7;color:#0b1711}</style>"
                  f"<div style='text-align:center'><div style='font-size:40px'>✅</div><b>Signed in as {disp}</b><p style='color:#647068'>Opening FITVERSE…</p></div>"
                  f"<script>try{{localStorage.setItem('fitverse-session','{token}')}}catch(e){{}};location.replace('/?welcome={safe_name}');</script>")
            body=html.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if path == "/api/stream":
            """Server-Sent Events stream: instant chat + notification push."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            uid = self.current_user(); last_notif = int(urlparse(self.path).query.split("since=")[-1].split("&")[0] or 0)
            try:
                # PERF: one database handle for the whole stream (remote DB keeps its
                # HTTPS connection warm; sqlite keeps its file handle). Same queries
                # run every tick as before — only the per-tick reconnect is gone.
                with connect() as db:
                    snap = _sse_snapshot(db)
                    last_msg = int(snap.get("msg_max") or 0)
                    self.wfile.write(b"retry: 3000\n\n"); self.wfile.flush()
                    while True:
                        # Real DM push: only messages in conversations THIS user participates in.
                        if uid > 0:
                            conv_ids = (snap.get("dm") or {}).get(uid) or []
                            if conv_ids:
                                marks = ",".join("?" for _ in conv_ids)
                                new = db.execute(f"SELECT m.*,u.name,p.avatar_url FROM messages m JOIN users u ON u.id=m.sender_id LEFT JOIN profiles p ON p.user_id=m.sender_id WHERE m.conversation_id IN ({marks}) AND m.id>? ORDER BY m.id", (*conv_ids, last_msg)).fetchall()
                                for m in new:
                                    payload = json.dumps(dict(m), ensure_ascii=False)
                                    self.wfile.write(f"event: message\ndata: {payload}\n\n".encode()); last_msg = m["id"]
                        notes = db.execute("SELECT * FROM notifications WHERE user_id=? AND id>? ORDER BY id", (uid, last_notif)).fetchall()
                        for n in notes:
                            self.wfile.write(f"event: notification\ndata: {json.dumps(dict(n), ensure_ascii=False)}\n\n".encode()); last_notif = n["id"]
                        # Typing indicator (signed-in only): someone OTHER than the viewer typed in the last 2.5s.
                        active_now = [cid for cid, (ts, who) in TYPING.items() if uid > 0 and time.time() - ts < 2.5 and who != uid]
                        if active_now:
                            self.wfile.write(f"event: typing\ndata: {json.dumps({'conversations': active_now})}\n\n".encode())
                        self.wfile.write(b": ping\n\n"); self.wfile.flush()
                        time.sleep(1.2)
                        snap = _sse_snapshot(db)  # refreshes internally every ~30s
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            except Exception as exc:
                import traceback; traceback.print_exc()
                print(f"[stream] error: {exc!r}", flush=True)
                return
        if path == "/api/health/integrations":
            import platform_service
            return self.send_json(200, platform_service.connections_status(self.current_user()))
        if path == "/api/health/overview":
            import platform_service
            return self.send_json(200, platform_service.unified_overview(self.current_user()))
        if path == "/api/health/insights":
            import platform_service
            return self.send_json(200, platform_service.groq_health_insights(self.current_user()))
        if path == "/api/health/cardio":
            import platform_service
            return self.send_json(200, platform_service.cardio_analysis(self.current_user()))
        if path == "/api/health/recommendation":
            import platform_service
            return self.send_json(200, platform_service.recommendation(self.current_user()))
        if path == "/api/health/nutrition":
            import platform_service
            return self.send_json(200, platform_service.nutrition_intelligence(self.current_user()))
        if path == "/api/health/google/callback":
            import platform_service
            from urllib.parse import parse_qs
            qs = parse_qs(query)
            code = (qs.get("code") or [""])[0]
            if not code: return self.send_json(400, {"error": "Missing OAuth code"})
            host = self.headers.get("Host") or "127.0.0.1:4173"
            proto = self.headers.get("X-Forwarded-Proto") or ("https" if ".onrender.com" in host else "http")
            r = platform_service.google_fit_exchange(self.current_user(), code, f"{proto}://{host}")
            ok = "✅ Google Fit connected and synced." if r.get("ok") else "❌ " + r.get("error", "Connection failed")
            html = ("<!doctype html><meta charset='utf-8'><title>FITVERSE</title><style>body{font-family:system-ui;display:grid;place-items:center;height:100vh;background:#f6faf7;color:#0b1711}b{color:#3f6212}</style>"
                    f"<div style='text-align:center'><div style='font-size:40px'>❤️</div><b>{ok}</b><p style='color:#647068'>You can close this tab and return to FITVERSE.</p>"
                    "<script>setTimeout(()=>window.close(),2500)</script></div>")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(html.encode()); return
        if path == "/api/notifications/since":
            since=int(urlparse(self.path).query.split("since=")[-1].split("&")[0] or 0)
            with connect() as db:
                rows=[dict(r) for r in db.execute("SELECT * FROM notifications WHERE user_id=? AND id>? ORDER BY id",(self.current_user(),since))]
                unread=db.execute("SELECT count(*) FROM notifications WHERE user_id=? AND is_read=0",(self.current_user(),)).fetchone()[0]
            return self.send_json(200,{"items":rows,"unread":unread})
        if path.startswith("/api/activities/") and not path.endswith(("/join","/leave","/complete")):
            aid=int(path.split("/")[3])
            with connect() as db:
                row=db.execute("""SELECT a.*,u.name AS host_name,
                  (SELECT count(*) FROM activity_participants ap WHERE ap.activity_id=a.id) AS participant_count,
                  EXISTS(SELECT 1 FROM activity_participants m WHERE m.activity_id=a.id AND m.user_id=?) AS joined,
                  EXISTS(SELECT 1 FROM activity_completions c WHERE c.activity_id=a.id AND c.user_id=?) AS completed
                  FROM activities a JOIN users u ON u.id=a.host_id WHERE a.id=?""",(self.current_user(),self.current_user(),aid)).fetchone()
                people=[dict(r) for r in db.execute("""SELECT u.id,u.name,u.username FROM activity_participants ap JOIN users u ON u.id=ap.user_id WHERE ap.activity_id=? ORDER BY ap.joined_at LIMIT 12""",(aid,))] if row else []
            if not row: return self.send_json(404,{"error":"Activity not found"})
            item=dict(row); item["participants"]=people
            return self.send_json(200,{"item":item})
        if path == "/api/achievements":
            with connect() as db: rows=db.execute("SELECT a.*,ua.unlocked_at FROM achievements a LEFT JOIN user_achievements ua ON ua.achievement_id=a.id AND ua.user_id=? ORDER BY a.id",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/bookings":
            with connect() as db:
                items=[dict(r) for r in db.execute("SELECT b.booking_code,b.status,b.quantity,e.name,e.starts_at,e.location_label FROM bookings b JOIN events e ON e.id=b.event_id WHERE b.user_id=? ORDER BY b.id DESC",(self.current_user(),))]
            return self.send_json(200,{"items":items})
        if path == "/api/users":
            """Real registered users. ?q= does partial, case-insensitive search over
            name and username. ?include_self=1 keeps your own account in the list.
            avatar_url is the user's real uploaded photo when they have one."""
            from urllib.parse import parse_qs as _pqs_u, unquote as _unq_u
            prms=_pqs_u(urlparse(self.path).query)
            qq=(prms.get("q") or [""])[0].strip().lower()
            include_self=(prms.get("include_self") or ["0"])[0]=="1"
            uid=self.current_user()
            with connect() as db:
                rows=db.execute("SELECT u.id,u.name,u.username,u.city,u.fitness_level,u.fitness_goal,u.favorite_activity,u.preferred_time,p.bio,p.avatar_url,g.xp,g.streak FROM users u JOIN user_game_state g ON g.user_id=u.id LEFT JOIN profiles p ON p.user_id=u.id ORDER BY u.name").fetchall()
                friend_ids_set=set()
                if uid:
                    try:
                        friend_ids_set={r[0] for r in db.execute("""SELECT CASE WHEN f.requester_id=? THEN f.addressee_id ELSE f.requester_id END
                          FROM friendships f WHERE f.status='accepted' AND (f.requester_id=? OR f.addressee_id=?)""",(uid,uid,uid)).fetchall()}
                    except Exception:
                        friend_ids_set=set()
            items=[]
            for r in rows:
                d=dict(r)
                if not include_self and uid and d["id"]==uid: continue
                if qq and qq not in str(d["name"]).lower() and qq not in str(d["username"]).lower(): continue
                d["photo"]=f"img/p{1 + (d['id'] % 12)}.jpg"
                d["is_friend"]=d["id"] in friend_ids_set  # Discover shows 'Friends ✓' instead of re-adding
                items.append(d)
            return self.send_json(200,{"items":items})
        if path == "/api/challenges":
            uid=self.current_user()
            with connect() as db:
                rows=db.execute("""SELECT c.*, cu.name AS challenger_name, ou.name AS opponent_name,
                  (SELECT progress FROM challenge_participants cp WHERE cp.challenge_id=c.id AND cp.user_id=c.challenger_id) AS challenger_progress,
                  (SELECT progress FROM challenge_participants cp WHERE cp.challenge_id=c.id AND cp.user_id=c.opponent_id) AS opponent_progress,
                  EXISTS(SELECT 1 FROM challenge_participants cp WHERE cp.challenge_id=c.id AND cp.user_id=?) AS joined,
                  (c.challenger_id=? OR c.opponent_id=?) AS involved
                  FROM challenges c JOIN users cu ON cu.id=c.challenger_id JOIN users ou ON ou.id=c.opponent_id ORDER BY c.id DESC""",(uid,uid,uid)).fetchall()
                friends=[dict(r) for r in db.execute("""SELECT u.id,u.name FROM friendships f
                  JOIN users u ON u.id=CASE WHEN f.requester_id=? THEN f.addressee_id ELSE f.requester_id END
                  WHERE f.status='accepted' AND (f.requester_id=? OR f.addressee_id=?) ORDER BY u.name""",(uid,uid,uid))]
                board=[dict(r) for r in db.execute("""SELECT u.name, COUNT(*) wins FROM challenges c
                  JOIN users u ON u.id=c.winner_id WHERE c.winner_id IS NOT NULL
                  GROUP BY c.winner_id ORDER BY wins DESC LIMIT 5""")]
            return self.send_json(200,{"items":[dict(r) for r in rows],"friends":friends,"leaderboard":board})
        if path == "/api/conversations":
            """Real per-user inbox: direct threads the caller participates in, titled by the
            other real user, with unread counts. Guests get an empty inbox."""
            uid=self.current_user()
            if uid <= 0: return self.send_json(200,{"items":[]})
            with connect() as db:
                rows=db.execute("""SELECT c.id,c.kind,c.created_at,
                  (SELECT body FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message,
                  (SELECT created_at FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_at,
                  (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count,
                  (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id AND m.sender_id<>? AND m.id>COALESCE(rp.last_read,0)) AS unread,
                  (SELECT u2.name FROM dm_participants dp JOIN users u2 ON u2.id=dp.user_id WHERE dp.conversation_id=c.id AND dp.user_id<>?) AS other_name,
                  (SELECT pr.avatar_url FROM dm_participants dp JOIN profiles pr ON pr.user_id=dp.user_id WHERE dp.conversation_id=c.id AND dp.user_id<>?) AS other_avatar,
                  (SELECT dp2.user_id FROM dm_participants dp2 WHERE dp2.conversation_id=c.id AND dp2.user_id<>?) AS other_id
                  FROM conversations c
                  JOIN dm_participants rp ON rp.conversation_id=c.id AND rp.user_id=?
                  ORDER BY COALESCE((SELECT m.created_at FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1), c.created_at) DESC""",(uid,uid,uid,uid,uid)).fetchall()
            items=[]
            for r in rows:
                d=dict(r)
                d["title"]=d["other_name"] or "Direct chat"
                if d.get("other_avatar"): d["other_avatar_url"]=d["other_avatar"]
                d.pop("other_name",None); d.pop("other_avatar",None)
                items.append(d)
            return self.send_json(200,{"items":items})
        if path.startswith("/api/conversations/"):
            """Thread history — members only. Opening the thread marks it read."""
            uid=self.current_user()
            if uid <= 0: return self.send_json(401,{"error":"Sign in to read your conversations"})
            try: cid=int(path.split("/")[3])
            except ValueError: return self.send_json(404,{"error":"Conversation not found"})
            with connect() as db:
                if not db.execute("SELECT 1 FROM dm_participants WHERE conversation_id=? AND user_id=?",(cid,uid)).fetchone():
                    return self.send_json(403,{"error":"This conversation is private"})
                rows=db.execute('SELECT m.*,u.name,p.avatar_url FROM messages m JOIN users u ON u.id=m.sender_id LEFT JOIN profiles p ON p.user_id=m.sender_id WHERE m.conversation_id=? ORDER BY m.id',(cid,)).fetchall()
                db.execute("UPDATE dm_participants SET last_read=(SELECT COALESCE(MAX(id),0) FROM messages WHERE conversation_id=?) WHERE conversation_id=? AND user_id=?",(cid,cid,uid))
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/comments":
            post_id=int(urlparse(self.path).query.split("post_id=")[-1] or 0)
            with connect() as db: rows=db.execute('SELECT c.*,u.name FROM comments c JOIN users u ON u.id=c.author_id WHERE c.post_id=? ORDER BY c.id',(post_id,)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/reels":
            with connect() as db:
                try: db.execute("ALTER TABLE posts ADD COLUMN media TEXT")
                except sqlite3.OperationalError: pass
                rows=db.execute("""SELECT p.*,u.name,u.username,
                  (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id) AS likes,
                  EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked,
                  (SELECT count(*) FROM comments c WHERE c.post_id=p.id) AS comments
                  FROM posts p JOIN users u ON u.id=p.author_id WHERE p.kind IN ('reel','motivation','achievement') ORDER BY p.id DESC""",(self.current_user(),)).fetchall()
                items=[]
                for r in rows:
                    d=dict(r)
                    if not d.get("photo"):
                        bl=d["body"].lower()
                        d["photo"]="running.jpg" if ("run" in bl or "5k" in bl or "km" in bl) else "cycling.jpg" if ("cycl" in bl or "ride" in bl) else "yoga.jpg" if "yoga" in bl else "gym.jpg" if ("gym" in bl or "lift" in bl or "strength" in bl or "ice" in bl) else "basketball.jpg" if ("court" in bl or "hoop" in bl or "basketball" in bl) else "workout.jpg"
                    items.append(d)
            return self.send_json(200,{"items":items})
        if path == "/api/community":
            cid=int(urlparse(self.path).query.split("id=")[-1].split("&")[0] or 1)
            uid=self.current_user()
            with connect() as db:
                c=db.execute("SELECT * FROM communities WHERE id=?",(cid,)).fetchone()
                if not c: return self.send_json(404,{"error":"Community not found"})
                members=[dict(r) for r in db.execute("""SELECT u.id,u.name,u.username FROM community_members cm JOIN users u ON u.id=cm.user_id WHERE cm.community_id=? LIMIT 24""",(cid,))]
                posts=[dict(r) for r in db.execute("""SELECT p.*,u.name,u.username,
                  (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id) AS likes,
                  EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked
                  FROM community_posts cp JOIN posts p ON p.id=cp.post_id JOIN users u ON u.id=p.author_id
                  WHERE cp.community_id=? ORDER BY p.id DESC LIMIT 30""",(uid,cid))]
                events=[dict(r) for r in db.execute("SELECT * FROM events WHERE category=(SELECT activity FROM communities WHERE id=?) ORDER BY starts_at LIMIT 4",(cid,))]
            item=dict(c); item["members"]=members; item["posts"]=posts; item["events"]=events
            return self.send_json(200,{"item":item})
        if path == "/api/businesses":
            with connect() as db:
                try: db.execute("ALTER TABLE businesses ADD COLUMN photo TEXT")
                except sqlite3.OperationalError: pass
                db.executemany("INSERT OR IGNORE INTO businesses (id,name,category,location_label,description,rating,created_at) VALUES (?,?,?,?,?,?,?)", [
                    (3,"Zen Yoga Studio","Yoga studio","Besant Nagar","Heated flows, aerial yoga and teacher training.",4.8,now()),
                    (4,"Coast Cycle Co.","Cycling shop","ECR-Kelambakkam","Rentals, repairs and weekend group rides.",4.6,now()),
                    (5,"Iron Temple Strength","Powerlifting gym","Kodambakkam","Platform lifting, coaching and open meets.",4.9,now()),
                    (6,"The Runner's Fix","Running store","Alwarpet","Gait analysis, shoes and a runners' cafe.",4.7,now()),
                    (7,"Aqua Fit Swim Center","Swim school","T.Nagar","Adult learn-to-swim and masters squads.",4.5,now()),
                    (8,"Summit Climbing Gym","Climbing gym","Velachery","Bouldering, top-rope and yoga combos.",4.8,now()),
                ])
                rows=db.execute("SELECT * FROM businesses ORDER BY rating DESC").fetchall()
            items=[]
            for r in rows:
                d=dict(r)
                if not d.get("photo"): d["photo"]={"Gym":"gym.jpg","Sports academy":"basketball.jpg","Yoga studio":"yoga.jpg","Cycling shop":"cycling.jpg","Powerlifting gym":"gym.jpg","Running store":"running.jpg","Swim school":"workout.jpg","Climbing gym":"gym.jpg"}.get(d["category"], "workout.jpg")
                items.append(d)
            return self.send_json(200,{"items":items})
        if path.startswith("/api/businesses/"):
            bid=int(path.split("/")[3])
            with connect() as db:
                b=db.execute("SELECT * FROM businesses WHERE id=?",(bid,)).fetchone()
                reviews=[dict(r) for r in db.execute("""SELECT r.*,u.name FROM reviews r JOIN users u ON u.id=r.user_id WHERE r.business_id=? ORDER BY r.id DESC LIMIT 20""",(bid,))]
            if not b: return self.send_json(404,{"error":"Business not found"})
            item=dict(b)
            if not item.get("photo"): item["photo"]={"Gym":"gym.jpg","Sports academy":"basketball.jpg","Yoga studio":"yoga.jpg","Cycling shop":"cycling.jpg","Powerlifting gym":"gym.jpg","Running store":"running.jpg","Swim school":"workout.jpg","Climbing gym":"gym.jpg"}.get(item["category"], "workout.jpg")
            item["reviews"]=reviews
            uid = self.current_user()
            with connect() as db:
                item["is_owner"] = bool(item.get("owner_id") and item["owner_id"] == uid)
                item["is_following"] = bool(db.execute("SELECT 1 FROM business_follows WHERE business_id=? AND user_id=?",(bid,uid)).fetchone())
                item["followers"] = db.execute("SELECT count(*) FROM business_follows WHERE business_id=?",(bid,)).fetchone()[0]
                item["products"] = [dict(r) for r in db.execute("SELECT * FROM business_products WHERE business_id=? ORDER BY position,id",(bid,))]
                item["photos"] = [r["path"] for r in db.execute("SELECT path FROM business_photos WHERE business_id=? ORDER BY position,id",(bid,))]
                item["hours"] = {str(r["dow"]): [r["open_time"],r["close_time"]] for r in db.execute("SELECT * FROM business_hours WHERE business_id=?",(bid,))}
                item["channel_posts"] = [dict(r) for r in db.execute("""SELECT p.id,p.body,p.media_url,p.media_type,p.created_at,u.name AS author_name
                    FROM business_posts bp JOIN posts p ON p.id=bp.post_id JOIN users u ON u.id=p.author_id
                    WHERE bp.business_id=? ORDER BY bp.id DESC LIMIT 20""",(bid,))]
            return self.send_json(200,{"item":item})
        if path.startswith("/api/athletes/"):
            aid=int(path.split("/")[3]); uid=self.current_user()
            with connect() as db:
                a=db.execute("""SELECT u.*,p.bio,p.avatar_url,g.xp,g.streak,g.activities FROM users u JOIN profiles p ON p.user_id=u.id JOIN user_game_state g ON g.user_id=u.id WHERE u.id=?""",(aid,)).fetchone()
                if not a: return self.send_json(404,{"error":"Athlete not found"})
                posts=[dict(r) for r in db.execute("""SELECT p.*,
                  (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id) AS likes
                  FROM posts p WHERE p.author_id=? ORDER BY p.id DESC LIMIT 12""",(aid,))]
                acts=[dict(r) for r in db.execute("""SELECT a.*,(SELECT count(*) FROM activity_participants ap WHERE ap.activity_id=a.id) AS participant_count
                  FROM activities a WHERE a.host_id=? ORDER BY a.starts_at LIMIT 8""",(aid,))]
                badges=[dict(r) for r in db.execute("""SELECT an.name,an.icon,ua.unlocked_at FROM user_achievements ua JOIN achievements an ON an.id=ua.achievement_id WHERE ua.user_id=?""",(aid,))]
            item=dict(a); item["posts"]=posts; item["activities"]=acts; item["badges"]=badges
            return self.send_json(200,{"item":item})
        if path == "/api/stats":
            uid=self.current_user()
            with connect() as db:
                stats={
                    "users": db.execute("SELECT count(*) FROM users").fetchone()[0],
                    "activities": db.execute("SELECT count(*) FROM activities").fetchone()[0],
                    "communities": db.execute("SELECT count(*) FROM communities").fetchone()[0],
                    "events": db.execute("SELECT count(*) FROM events").fetchone()[0],
                    "posts": db.execute("SELECT count(*) FROM posts").fetchone()[0],
                    "bookings": db.execute("SELECT count(*) FROM bookings").fetchone()[0],
                    "challenges": db.execute("SELECT count(*) FROM challenges").fetchone()[0],
                    "messages": db.execute("SELECT count(*) FROM messages").fetchone()[0],
                    "reports": db.execute("SELECT count(*) FROM reports WHERE status='open'").fetchone()[0],
                }
            return self.send_json(200,{"items":stats})
        if path == "/api/xp":
            with connect() as db: rows=db.execute("SELECT amount,reason,source_type,created_at FROM xp_transactions WHERE user_id=? ORDER BY id DESC LIMIT 50",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        # ===== FITVERSE 2.0 GET endpoints =====
        if path == "/api/me/settings":
            with connect() as db:
                s=db.execute("SELECT * FROM user_settings WHERE user_id=?",(self.current_user(),)).fetchone()
                import ai_service
                t=ai_service.targets_from_profile(dict(s) if s else {})
                if s:  # user-configured targets win over the auto-estimate
                    if s["kcal_target"]: t["kcal_target"]=s["kcal_target"]
                    if s["protein_target"]: t["protein_target"]=s["protein_target"]
            return self.send_json(200,{"item":{**(dict(s) if s else {}), **t}})
        if path == "/api/exercises":
            """Everyone gets the shared library plus their OWN custom exercises.
            Guests see the shared library only."""
            from urllib.parse import unquote as _unq_e
            q=urlparse(self.path).query.lower(); muscle=[m.split('=')[1] for m in q.split('&') if m.startswith('muscle=')]
            equip=[e.split('=')[1] for e in q.split('&') if e.startswith('equipment=')]
            search=[_unq_e(s.split('=')[1]) for s in q.split('&') if s.startswith('q=')]
            uid=self.current_user()
            with connect() as db:
                conds=["1=1"]; args=[]
                if muscle and muscle[0]: conds.append("muscle=?"); args.append(muscle[0].capitalize())
                if equip and equip[0]: conds.append("equipment=?"); args.append(equip[0].capitalize())
                if search and search[0]: conds.append("lower(name) LIKE ?"); args.append(f"%{search[0]}%")
                if uid: conds.append("(owner_id IS NULL OR owner_id=?)"); args.append(uid)
                else: conds.append("owner_id IS NULL")
                rows=db.execute("SELECT * FROM exercises WHERE "+" AND ".join(conds)+" ORDER BY muscle,name",args).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/workouts":
            uid=self.current_user()
            with connect() as db:
                rows=db.execute("SELECT * FROM workout_sessions WHERE user_id=? ORDER BY id DESC LIMIT 40",(uid,)).fetchall()
                items=[]
                for r in rows:
                    d=dict(r); d["logs"]=[dict(l) for l in db.execute("""SELECT wl.*,e.name,e.muscle FROM workout_logs wl JOIN exercises e ON e.id=wl.exercise_id WHERE wl.session_id=? ORDER BY wl.id""",(d['id'],))]
                    items.append(d)
            return self.send_json(200,{"items":items})
        if path == "/api/workouts/prs":
            """Personal records. FITVERSE 6.1: bodyweight/cardio rows (weight=0) no
            longer read as max_w=0 vol=0 — we surface each exercise's best session
            volume and best sets so the PR card always shows something real."""
            uid=self.current_user()
            with connect() as db:
                rows=db.execute("""SELECT e.name, MAX(wl.weight) max_w, MAX(wl.reps*wl.weight) max_vol,
                  MAX(ws.total_volume) best_session_vol, MAX(wl.sets*wl.reps) best_reps, COUNT(*) n
                  FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id JOIN exercises e ON e.id=wl.exercise_id
                  WHERE ws.user_id=? GROUP BY e.name ORDER BY max_w DESC, best_session_vol DESC LIMIT 12""",(uid,)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/nutrition":
            uid=self.current_user(); import datetime as _dt
            day=_dt.date.today().isoformat()
            with connect() as db:
                logs=[dict(r) for r in db.execute("SELECT * FROM nutrition_logs WHERE user_id=? AND logged_on=? ORDER BY id",(uid,day))]
                week=[dict(r) for r in db.execute("""SELECT logged_on, SUM(kcal) kcal, SUM(protein_g) p FROM nutrition_logs
                  WHERE user_id=? AND logged_on>=date('now','-6 days') GROUP BY logged_on ORDER BY logged_on""",(uid,))]
                s=db.execute("SELECT kcal_target,protein_target,water_target_ml FROM user_settings WHERE user_id=?",(uid,)).fetchone()
                import ai_service
                t=ai_service.targets_from_profile(dict(s) if s else {})
                if s:  # user-configured targets win over the auto-estimate
                    if s["kcal_target"]: t["kcal_target"]=s["kcal_target"]
                    if s["protein_target"]: t["protein_target"]=s["protein_target"]
            import datetime as _dt2
            totals={"kcal":sum(l['kcal'] for l in logs),"protein":round(sum(l['protein_g'] for l in logs)),"carbs":round(sum(l['carbs_g'] for l in logs)),"fat":round(sum(l['fat_g'] for l in logs)),"fiber":round(sum(l['fiber_g'] for l in logs))}
            return self.send_json(200,{"items":logs,"day":day,"totals":totals,"targets":t,"week":week})
        if path == "/api/water":
            uid=self.current_user(); import datetime as _dt
            day=_dt.date.today().isoformat()
            with connect() as db:
                ml=db.execute("SELECT COALESCE(SUM(ml),0) FROM water_logs WHERE user_id=? AND logged_on=?",(uid,day)).fetchone()[0]
                week=[dict(r) for r in db.execute("SELECT logged_on, SUM(ml) ml FROM water_logs WHERE user_id=? AND logged_on>=date('now','-6 days') GROUP BY logged_on",(uid,))]
                target=db.execute("SELECT water_target_ml FROM user_settings WHERE user_id=?",(uid,)).fetchone()
            return self.send_json(200,{"today_ml":ml,"target_ml":target['water_target_ml'] if target else 2500,"week":week})
        if path == "/api/progress":
            uid=self.current_user()
            with connect() as db:
                entries=[dict(r) for r in db.execute("SELECT * FROM progress_entries WHERE user_id=? ORDER BY entry_date DESC LIMIT 50",(uid,))]
            return self.send_json(200,{"items":entries})
        if path == "/api/ai/coach":
            """FITVERSE 6.0: conversation-aware. ?conversation_id= loads one thread;
            without it, the newest (pinned first). Every thread belongs to one user."""
            uid=self.current_user()
            q=urlparse(self.path).query
            try: cid_req=int(q.split("conversation_id=")[-1].split("&")[0] or 0)
            except ValueError: cid_req=0
            with connect() as db:
                convs=[dict(r) for r in db.execute("SELECT id,title,pinned,created_at FROM ai_conversations WHERE user_id=? ORDER BY pinned DESC,id DESC LIMIT 40",(uid,))]
                if cid_req:
                    conv=db.execute("SELECT id FROM ai_conversations WHERE id=? AND user_id=?",(cid_req,uid)).fetchone()
                    cid=conv["id"] if conv else 0
                if not cid_req or not cid:
                    conv=db.execute("SELECT id FROM ai_conversations WHERE user_id=? ORDER BY pinned DESC,id DESC LIMIT 1",(uid,)).fetchone()
                    if not conv:
                        cur=db.execute("INSERT INTO ai_conversations (user_id,title,created_at) VALUES (?,?,?)",(uid,'Coach chat',now())); cid=cur.lastrowid
                        convs=[{"id":cid,"title":"Coach chat","pinned":0,"created_at":now()}]
                    else: cid=conv["id"]
                msgs=[dict(r) for r in db.execute("SELECT role,content,created_at FROM ai_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 40",(cid,))]
                cur_conv=next((c for c in convs if c["id"]==cid),None)
                if cur_conv is None:
                    row=db.execute("SELECT id,title,pinned,created_at FROM ai_conversations WHERE id=?",(cid,)).fetchone()
                    cur_conv=dict(row) if row else {"id":cid,"title":"Coach chat","pinned":0,"created_at":""}
                convs=[cur_conv]+[c for c in convs if c["id"]!=cid]
            return self.send_json(200,{"conversationId":cid,"items":list(reversed(msgs)),"conversations":convs})
        if path == "/api/ai/review":
            import ai_service
            return self.send_json(200,{"item":ai_service.weekly_review(self.current_user())})
        if path == "/api/ai/buddy":
            import ai_service
            return self.send_json(200,{"items":[{"note":n} for n in ai_service.buddy_notes(self.current_user())]})
        if path == "/api/fitmatch":
            import ai_service
            fm=ai_service.fit_match(self.current_user(),8)
            if self.current_user() == 0:
                for r in fm: r["name"]="Athlete"
            return self.send_json(200,{"items":fm})
        if path == "/api/leaderboards":
            uid=self.current_user()
            with connect() as db:
                weekly=[dict(r) for r in db.execute("""SELECT u.name,u.username,COALESCE(SUM(x.amount),0) xp FROM xp_transactions x JOIN users u ON u.id=x.user_id
                  WHERE x.created_at>=date('now','-7 days') GROUP BY x.user_id ORDER BY xp DESC LIMIT 10""")]
                strength=[dict(r) for r in db.execute("""SELECT u.name,u.username,MAX(wl.weight) top FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
                  JOIN users u ON u.id=ws.user_id WHERE wl.weight>0 GROUP BY ws.user_id ORDER BY top DESC LIMIT 10""")]
                streaks=[dict(r) for r in db.execute("SELECT u.name,u.username,g.streak FROM user_game_state g JOIN users u ON u.id=g.user_id ORDER BY g.streak DESC LIMIT 10")]
                consistency=[dict(r) for r in db.execute("""SELECT u.name,u.username,COUNT(*) n FROM workout_sessions ws JOIN users u ON u.id=ws.user_id
                  WHERE ws.created_at>=date('now','-28 days') GROUP BY ws.user_id ORDER BY n DESC LIMIT 10""")]
            return self.send_json(200,{"weekly":weekly,"strength":strength,"streaks":streaks,"consistency":consistency})
        if path == "/api/friends":
            uid=self.current_user()
            with connect() as db:
                friends=[dict(r) for r in db.execute("""SELECT u.id,u.name,u.username,u.city,u.fitness_level,u.favorite_activity,g.streak,g.xp,p.bio,p.avatar_url
                  FROM friendships f JOIN users u ON u.id=CASE WHEN f.requester_id=? THEN f.addressee_id ELSE f.requester_id END
                  JOIN user_game_state g ON g.user_id=u.id LEFT JOIN profiles p ON p.user_id=u.id
                  WHERE f.status='accepted' AND (f.requester_id=? OR f.addressee_id=?) ORDER BY u.name""",(uid,uid,uid))]
                incoming=[dict(r) for r in db.execute("""SELECT f.id req_id,u.id,u.name,u.username,p.avatar_url FROM friendships f JOIN users u ON u.id=f.requester_id
                  LEFT JOIN profiles p ON p.user_id=u.id
                  WHERE f.addressee_id=? AND f.status='pending'""",(uid,))]
                for f_ in friends: f_["photo"]=f"img/p{1 + (f_['id'] % 12)}.jpg"
            return self.send_json(200,{"items":friends,"incoming":incoming})
        if path.startswith("/api/posts/") and path.endswith("/comments") and path.count('/')==3:
            # already handled earlier; guard for GET comments by post id
            pass
        if path.startswith("/api/users/"):
            aid=int(path.split("/")[3]); uid=self.current_user()
            with connect() as db:
                a=db.execute("""SELECT u.id,u.name,u.username,u.city,u.fitness_level,u.fitness_goal,u.favorite_activity,u.preferred_time,p.bio,p.avatar_url,g.xp,g.streak,g.activities
                  FROM users u JOIN profiles p ON p.user_id=u.id JOIN user_game_state g ON g.user_id=u.id WHERE u.id=?""",(aid,)).fetchone()
                if not a: return self.send_json(404,{"error":"Athlete not found"})
                posts=[dict(r) for r in db.execute("SELECT * FROM posts WHERE author_id=? ORDER BY id DESC LIMIT 12",(aid,))]
                badges=[dict(r) for r in db.execute("SELECT an.name,an.icon,ua.unlocked_at FROM user_achievements ua JOIN achievements an ON an.id=ua.achievement_id WHERE ua.user_id=?",(aid,))]
                followers=db.execute("SELECT count(*) FROM follows WHERE followee_id=?",(aid,)).fetchone()[0]
                following=db.execute("SELECT count(*) FROM follows WHERE follower_id=?",(aid,)).fetchone()[0]
                is_following=db.execute("SELECT 1 FROM follows WHERE follower_id=? AND followee_id=?",(uid,aid)).fetchone()
                sessions=db.execute("SELECT count(*) FROM workout_sessions WHERE user_id=?",(aid,)).fetchone()[0]
            item=dict(a); item.update({"posts":posts,"badges":badges,"followers":followers,"following":following,"is_following":bool(is_following),"sessions":sessions})
            return self.send_json(200,{"item":item})
        # ===== FITVERSE 3.0: intelligence ecosystem =====
        if path == "/api/intelligence":
            import intelligence
            uid = self.current_user()
            return self.send_json(200, {
                "dna": intelligence.fitness_dna(uid),
                "twin": intelligence.fitness_twin(uid),
                "patterns": intelligence.detect_patterns(uid),
                "debt": intelligence.fitness_debt(uid),
            })
        if path == "/api/moments":
            uid = self.current_user()
            with connect() as db:
                prs = [dict(r) for r in db.execute("""SELECT e.name, wl.weight, wl.reps, ws.created_at FROM workout_logs wl
                    JOIN workout_sessions ws ON ws.id=wl.session_id JOIN exercises e ON e.id=wl.exercise_id
                    WHERE ws.user_id=? AND wl.is_pr=1 AND wl.weight>0 ORDER BY ws.id DESC LIMIT 4""", (uid,))]
                streak = db.execute("SELECT streak FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
                missions = [dict(r) for r in db.execute(
                    "SELECT title, reward_xp, completed_at FROM missions WHERE user_id=? AND status='completed' ORDER BY id DESC LIMIT 3", (uid,))]
                wins = [dict(r) for r in db.execute(
                    "SELECT title, ends_at as at FROM challenges WHERE winner_id=? LIMIT 3", (uid,))]
            items = []
            for p in prs:
                items.append({"kind": "pr", "icon": "🏆", "title": f"New personal best — {p['name']}",
                              "detail": f"{p['weight']:g} kg × {p['reps']} reps", "date": p["created_at"],
                              "card": {"headline": "NEW PERSONAL BEST", "main": p["name"], "big": f"{p['weight']:g} KG × {p['reps']}"}})
            if streak and streak["streak"] >= 7:
                items.append({"kind": "streak", "icon": "🔥", "title": f"{streak['streak']}-day streak",
                              "detail": "Consistency is compounding — keep the chain alive.", "date": now(),
                              "card": {"headline": "STREAK MILESTONE", "main": "Day streak", "big": str(streak["streak"])}})
            for m in missions:
                items.append({"kind": "mission", "icon": "🎯", "title": f"Mission complete — {m['title']}",
                              "detail": f"+{m['reward_xp']} XP earned", "date": m["completed_at"],
                              "card": {"headline": "MISSION COMPLETE", "main": m["title"], "big": f"+{m['reward_xp']} XP"}})
            for w in wins:
                items.append({"kind": "challenge", "icon": "⚔️", "title": f"Challenge won — {w['title']}",
                              "detail": "Victory is earned, not given.", "date": w["at"],
                              "card": {"headline": "CHALLENGE WON", "main": w["title"], "big": "WINNER"}})
            items.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
            return self.send_json(200, {"items": items[:8]})
        if path == "/api/intelligence/trajectory":
            import intelligence
            q = urlparse(self.path).query
            params = dict(p.split('=', 1) for p in q.split('&') if '=' in p)
            sid = params.get('scenario', 'current')
            horizon = int(params.get('days', '90') or 90)
            return self.send_json(200, {"item": intelligence.trajectory(self.current_user(), sid, horizon)})
        if path == "/api/missions":
            import intelligence
            uid = self.current_user()
            with connect() as db:
                intelligence.ensure_weekly_mission(db, uid)
                check_missions(db, uid)  # a freshly forged mission may already be earned
                m = db.execute("SELECT * FROM missions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
                m = dict(m) if m else None
                if m: m["progress"] = intelligence.mission_progress_for(db, uid, m["metric"], m["created_at"])
                history = [dict(r) for r in db.execute(
                    "SELECT id,title,icon,reward_xp,status,completed_at FROM missions WHERE user_id=? AND status!='active' ORDER BY id DESC LIMIT 6", (uid,))]
            return self.send_json(200, {"item": m, "history": history})
        if path == "/api/teams":
            uid = self.current_user()
            with connect() as db:
                teams = []
                for t in db.execute("SELECT * FROM teams ORDER BY id").fetchall():
                    d = dict(t)
                    d["team_xp"] = db.execute("SELECT COALESCE(SUM(amount),0) FROM team_xp WHERE team_id=?", (d['id'],)).fetchone()[0]
                    d["members"] = db.execute("SELECT COUNT(*) FROM team_members WHERE team_id=?", (d['id'],)).fetchone()[0]
                    d["is_mine"] = db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?", (d['id'], uid)).fetchone() is not None
                    top = db.execute("""SELECT u.name, SUM(tx.amount) xp FROM team_xp tx JOIN users u ON u.id=tx.user_id
                        WHERE tx.team_id=? GROUP BY tx.user_id ORDER BY xp DESC LIMIT 3""", (d['id'],)).fetchall()
                    d["top"] = [dict(r) for r in top]
                    teams.append(d)
                teams.sort(key=lambda t: -t["team_xp"])
                my = next((t for t in teams if t["is_mine"]), None)
                individual = [dict(r) for r in db.execute("""SELECT u.name, u.username, SUM(tx.amount) xp FROM team_xp tx
                    JOIN users u ON u.id=tx.user_id GROUP BY tx.user_id ORDER BY xp DESC LIMIT 10""")]
            return self.send_json(200, {"items": teams, "mine": my, "individual": individual})
        if path == "/api/posts":
            uid = self.current_user()
            with connect() as db:
                rows = db.execute("SELECT p.*, u.name author_name, u.username FROM posts p JOIN users u ON u.id=p.author_id ORDER BY p.id DESC LIMIT 30").fetchall()
                items = []
                for r in rows:
                    d = dict(r)
                    d["reactions"] = [dict(x) for x in db.execute(
                        "SELECT reaction, COUNT(*) n FROM post_reactions WHERE post_id=? GROUP BY reaction", (d['id'],))]
                    d["my_reactions"] = [x[0] for x in db.execute(
                        "SELECT reaction FROM post_reactions WHERE post_id=? AND user_id=?", (d['id'], uid))]
                    items.append(d)
            return self.send_json(200, {"items": items})
        if path.startswith("/api/"): return self.send_json(404, {"error": "Unknown API route"})
        self.serve_static(path)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path; data = self.body()
            # Every write needs a real account; guests get a clear sign-in prompt.
            if self.current_user() <= 0 and not path.startswith("/api/auth/"):
                return self.send_json(401,{"error":"Sign in to do that"})
            # Any write may change the numbers the intelligence layer memoizes —
            # drop that user's cached DNA/debt/patterns immediately.
            try:
                import intelligence
                intelligence.invalidate_user_cache(self.current_user())
            except Exception:
                pass
            if path == "/api/auth/logout":
                """Revoke the caller's session token (real logout, not just forgetting it client-side)."""
                tok = self.headers.get("X-Session", "")
                if tok: store.session_drop(tok)
                return self.send_json(200,{"ok":True})
            if path == "/api/auth/login":
                username=str(data.get("username","")).strip().lower(); password=str(data.get("password",""))
                with connect() as db: user=db.execute("SELECT * FROM users WHERE username=? OR email=?",(username,username)).fetchone()
                if not user or hash_password(password,user["password_salt"]) != user["password_hash"]: return self.send_json(401,{"error":"Invalid username or password"})
                token=secrets.token_urlsafe(32); store.session_put(token, user["id"]); return self.send_json(200,{"token":token,"user":{"id":user["id"],"name":user["name"]}})
            if path == "/api/auth/register":
                required=["name","username","email","password"]
                if any(not str(data.get(k,"")).strip() for k in required): return self.send_json(400,{"error":"Name, username, email and password are required"})
                salt=secrets.token_hex(16); stamp=now()
                try:
                    with connect() as db:
                        cur=db.execute("INSERT INTO users (name,username,email,password_salt,password_hash,created_at) VALUES (?,?,?,?,?,?)",(data["name"].strip(),data["username"].strip().lower(),data["email"].strip().lower(),salt,hash_password(data["password"],salt),stamp))
                        db.execute("INSERT INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",(cur.lastrowid,0,0,0,0,0,"pending",0,0,0,stamp)); db.execute("INSERT INTO profiles (user_id,updated_at,onboarding_completed) VALUES (?,?,0)",(cur.lastrowid,stamp)); user_id=cur.lastrowid
                    token=secrets.token_urlsafe(32); store.session_put(token, user_id); return self.send_json(201,{"token":token,"userId":user_id})
                except sqlite3.IntegrityError: return self.send_json(409,{"error":"That username or email is already in use"})
            if path == "/api/profile":
                allowed_user={"name","city","fitness_level","fitness_goal","favorite_activity","preferred_time"}
                allowed_profile={"bio","college_or_company","availability","workout_intensity","preferred_location","avatar_url","onboarding_completed"}
                if not any(key in data for key in (*allowed_user,*allowed_profile)): return self.send_json(400,{"error":"No editable profile fields supplied"})
                with connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for key in allowed_user:
                        if key in data: db.execute(f"UPDATE users SET {key}=? WHERE id=?",(str(data[key]).strip()[:120],self.current_user()))
                    for key in allowed_profile:
                        if key in data: db.execute(f"UPDATE profiles SET {key}=?,updated_at=? WHERE user_id=?",(str(data[key]).strip()[:500],now(),self.current_user()))
                    db.commit()
                return self.send_json(200,{"ok":True})
            if path == "/api/friendships/respond":
                """Accept/decline a pending friend request. Only the addressee decides.
                Accepting makes the friendship mutual for BOTH users and notifies the sender."""
                rid=int(data.get("request_id",0)); decision=str(data.get("decision",""))
                uid=self.current_user()
                with connect() as db:
                    fr=db.execute("SELECT * FROM friendships WHERE id=?",(rid,)).fetchone()
                    if not fr or fr["addressee_id"]!=uid: return self.send_json(404,{"error":"Request not found"})
                    if fr["status"]!="pending": return self.send_json(409,{"error":"This request was already handled"})
                    if decision=="accept":
                        db.execute("UPDATE friendships SET status='accepted' WHERE id=?",(rid,))
                        myname=db.execute("SELECT name FROM users WHERE id=?",(uid,)).fetchone()[0]
                        db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(fr["requester_id"],"friend_request","Friend request accepted",f"🎉 {myname} accepted your friend request — you're in each other's circle now.",now()))
                    elif decision=="decline":
                        db.execute("DELETE FROM friendships WHERE id=?",(rid,))
                    else:
                        return self.send_json(400,{"error":"Decision must be accept or decline"})
                return self.send_json(200,{"ok":True,"status":decision})
            if path == "/api/activities":
                required=("title","sport","starts_at","location_label")
                if any(not str(data.get(k,"")).strip() for k in required): return self.send_json(400,{"error":"Activity title, sport, time and location are required"})
                maximum=max(2,min(100,int(data.get("max_participants",8))))
                with connect() as db:
                    cur=db.execute("""INSERT INTO activities (title,sport,starts_at,location_label,max_participants,fitness_level,intensity,description,host_id,created_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?)""",(str(data["title"]).strip()[:100],str(data["sport"]).strip()[:50],str(data["starts_at"]),str(data["location_label"]).strip()[:120],maximum,str(data.get("fitness_level","Open"))[:30],str(data.get("intensity","Moderate"))[:30],str(data.get("description","")).strip()[:1000],self.current_user(),now()))
                    db.execute("INSERT INTO activity_participants VALUES (?,?,?)",(cur.lastrowid,self.current_user(),now()))
                return self.send_json(201,{"ok":True,"activityId":cur.lastrowid})
            if path.startswith("/api/communities/") and path.endswith("/join"):
                """Join a community — persisted membership so 'Your crews' lists it forever."""
                cid=int(path.split("/")[3]); uid=self.current_user()
                with connect() as db:
                    if not db.execute("SELECT 1 FROM communities WHERE id=?",(cid,)).fetchone():
                        return self.send_json(404,{"error":"Community not found"})
                    db.execute("INSERT OR IGNORE INTO community_members VALUES (?,?,?,?)",(cid,uid,"member",now()))
                return self.send_json(200,{"ok":True,"joined":True})
            if path.startswith("/api/communities/") and path.endswith("/leave"):
                cid=int(path.split("/")[3]); uid=self.current_user()
                with connect() as db:
                    db.execute("DELETE FROM community_members WHERE community_id=? AND user_id=? AND role='member'",(cid,uid))
                return self.send_json(200,{"ok":True,"joined":False})
            if path == "/api/communities":
                name=str(data.get("name","")).strip(); description=str(data.get("description","")).strip()
                if not name or not description:return self.send_json(400,{"error":"Community name and description are required"})
                try:
                    with connect() as db:
                        cur=db.execute("INSERT INTO communities (name,description,activity,created_at) VALUES (?,?,?,?)",(name[:100],description[:800],str(data.get("activity","Fitness"))[:50],now()))
                        db.execute("INSERT INTO community_members VALUES (?,?,?,?)",(cur.lastrowid,self.current_user(),"owner",now()))
                    return self.send_json(201,{"ok":True,"communityId":cur.lastrowid})
                except sqlite3.IntegrityError:return self.send_json(409,{"error":"A community with that name already exists"})
            if path == "/api/events":
                required=("name","category","starts_at","location_label","organizer")
                if any(not str(data.get(k,"")).strip() for k in required): return self.send_json(400,{"error":"Event name, category, time, location and organizer are required"})
                with connect() as db:
                    cur=db.execute("INSERT INTO events (name,category,starts_at,location_label,price_inr,capacity,organizer,description,created_at) VALUES (?,?,?,?,?,?,?,?,?)",(str(data["name"]).strip()[:100],str(data["category"]).strip()[:50],str(data["starts_at"]),str(data["location_label"]).strip()[:120],max(0,int(data.get("price_inr",0))),max(1,int(data.get("capacity",20))),str(data["organizer"]).strip()[:100],str(data.get("description","")).strip()[:1500],now()))
                return self.send_json(201,{"ok":True,"eventId":cur.lastrowid})
            if path == "/api/notifications/read":
                with connect() as db: db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?" if not data.get("id") else "UPDATE notifications SET is_read=1 WHERE user_id=? AND id=?",(self.current_user(),) if not data.get("id") else (self.current_user(),int(data["id"])))
                return self.send_json(200,{"ok":True})
            if path == "/api/friends/request":
                recipient=int(data.get("user_id",0))
                if recipient == self.current_user(): return self.send_json(400,{"error":"You cannot add yourself"})
                with connect() as db:
                    exists=db.execute("SELECT status FROM friendships WHERE (requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?)",(self.current_user(),recipient,recipient,self.current_user())).fetchone()
                    if exists:return self.send_json(409,{"error":"A friend relationship already exists"})
                    db.execute("INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)",(self.current_user(),recipient,"pending",now()))
                    reqname=db.execute("SELECT name FROM users WHERE id=?",(self.current_user(),)).fetchone()[0]
                    db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(recipient,"friend_request","New friend request",f"👥 {reqname} sent you a friend request. Open Friends to accept or decline.",now()))
                return self.send_json(201,{"ok":True,"status":"pending"})
            if path.startswith("/api/posts/"):
                parts=path.split("/"); post_id=int(parts[3]); operation=parts[4] if len(parts)>4 else ""
                with connect() as db:
                    if operation == "like":
                        exists=db.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?",(post_id,self.current_user())).fetchone()
                        if exists: db.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?",(post_id,self.current_user())); liked=False
                        else: db.execute("INSERT INTO post_likes VALUES (?,?,?)",(post_id,self.current_user(),now())); liked=True
                        return self.send_json(200,{"ok":True,"liked":liked})
                    if operation == "save":
                        exists=db.execute("SELECT 1 FROM saved_posts WHERE post_id=? AND user_id=?",(post_id,self.current_user())).fetchone()
                        if exists: db.execute("DELETE FROM saved_posts WHERE post_id=? AND user_id=?",(post_id,self.current_user())); saved=False
                        else: db.execute("INSERT INTO saved_posts VALUES (?,?,?)",(post_id,self.current_user(),now())); saved=True
                        return self.send_json(200,{"ok":True,"saved":saved})
                    if operation == "comments":
                        comment=str(data.get("body","")).strip()
                        if not comment:return self.send_json(400,{"error":"Comment cannot be empty"})
                        cur=db.execute("INSERT INTO comments (post_id,author_id,body,created_at) VALUES (?,?,?,?)",(post_id,self.current_user(),comment[:1000],now()))
                        return self.send_json(201,{"ok":True,"commentId":cur.lastrowid})
            if path.startswith("/api/activities/"):
                parts=path.split("/"); activity_id=int(parts[3]); operation=parts[4] if len(parts)>4 else ""
                with connect() as db:
                    if operation == "join":
                        activity=db.execute("SELECT max_participants FROM activities WHERE id=?",(activity_id,)).fetchone()
                        if not activity:return self.send_json(404,{"error":"Activity not found"})
                        if db.execute("SELECT count(*) FROM activity_participants WHERE activity_id=?",(activity_id,)).fetchone()[0]>=activity["max_participants"]: return self.send_json(409,{"error":"This activity is full"})
                        try: db.execute("INSERT INTO activity_participants VALUES (?,?,?)",(activity_id,self.current_user(),now()))
                        except sqlite3.IntegrityError:return self.send_json(409,{"error":"You have already joined this activity"})
                        return self.send_json(200,{"ok":True})
                    if operation == "leave":
                        db.execute("DELETE FROM activity_participants WHERE activity_id=? AND user_id=?",(activity_id,self.current_user()))
                        return self.send_json(200,{"ok":True})
                    if operation == "complete":
                        try: db.execute("INSERT INTO activity_completions VALUES (?,?,?)",(activity_id,self.current_user(),now()))
                        except sqlite3.IntegrityError: return self.send_json(409,{"error":"You already completed this activity"})
                        db.execute("UPDATE user_game_state SET activities=activities+1 WHERE user_id=?",(self.current_user(),))
                        award_xp(db,self.current_user(),80,"Completed an activity","activity",str(activity_id))
                        mission_done=check_missions(db,self.current_user())
                        unlocked=check_achievements(db,self.current_user())
                        msg=f"+80 XP earned!" + (f" Mission: {mission_done['completed']} +{mission_done['xp']} XP." if mission_done else "") + (f" Achievement: {', '.join(unlocked)}." if unlocked else "")
                        db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(self.current_user(),"xp","Activity complete",msg,now()))
                        g=user_state(db,self.current_user()); return self.send_json(200,{"ok":True,"state":g,"message":msg})
            if path.startswith("/api/communities/"):
                parts=path.split("/"); community_id=int(parts[3]); operation=parts[4] if len(parts)>4 else ""
                with connect() as db:
                    if operation == "join":
                        try: db.execute("INSERT INTO community_members VALUES (?,?,?,?)",(community_id,self.current_user(),"member",now()))
                        except sqlite3.IntegrityError:return self.send_json(409,{"error":"You are already a member"})
                        return self.send_json(200,{"ok":True})
                    if operation == "leave":
                        db.execute("DELETE FROM community_members WHERE community_id=? AND user_id=? AND role<>'owner'",(community_id,self.current_user()))
                        return self.send_json(200,{"ok":True})
            if path.startswith("/api/events/") and path.endswith("/book"):
                event_id=int(path.split("/")[3]); quantity=max(1,min(10,int(data.get("quantity",1))))
                with connect() as db:
                    event=db.execute("SELECT capacity FROM events WHERE id=?",(event_id,)).fetchone()
                    if not event:return self.send_json(404,{"error":"Event not found"})
                    booked=db.execute("SELECT COALESCE(sum(quantity),0) FROM bookings WHERE event_id=? AND status='confirmed'",(event_id,)).fetchone()[0]
                    if booked+quantity>event["capacity"]:return self.send_json(409,{"error":"Not enough tickets remaining"})
                    code=f"FV-2026-{secrets.randbelow(9000)+1000}"; db.execute("INSERT INTO bookings (booking_code,user_id,event_id,quantity,status,qr_payload,created_at) VALUES (?,?,?,?,?,?,?)",(code,self.current_user(),event_id,quantity,"confirmed",f"fitverse://booking/{code}",now()))
                return self.send_json(201,{"ok":True,"bookingCode":code,"message":"Demo payment successful"})
            if path == "/api/actions":
                action=str(data.get("action","sync")); return self.send_json(200,perform_action(self.current_user(),action,data.get("state",{})))
            if path == "/api/messages":
                """Real user-to-user direct message. Body: {to_user_id} starts/continues a
                private thread with that real registered user; {conversation_id} continues one."""
                uid = self.current_user()
                if uid <= 0: return self.send_json(401,{"error":"Sign in to send messages"})
                body=str(data.get("body","")).strip()
                if not body or len(body)>1000: return self.send_json(400,{"error":"Message must be 1–1000 characters"})
                with connect() as db:
                    to_uid=int(data.get("to_user_id",0) or 0)
                    cid=int(data.get("conversation_id",0) or 0)
                    if to_uid==uid: return self.send_json(400,{"error":"You cannot message yourself"})
                    if cid:
                        if not db.execute("SELECT 1 FROM dm_participants WHERE conversation_id=? AND user_id=?",(cid,uid)).fetchone():
                            return self.send_json(403,{"error":"This conversation is private"})
                        other=db.execute("SELECT user_id FROM dm_participants WHERE conversation_id=? AND user_id<>?",(cid,uid)).fetchone()
                        if not other: return self.send_json(400,{"error":"This conversation has no other participant"})
                        other_id=other["user_id"]
                    elif to_uid:
                        if not db.execute("SELECT 1 FROM users WHERE id=?",(to_uid,)).fetchone(): return self.send_json(404,{"error":"Athlete not found"})
                        row=db.execute("""SELECT dp.conversation_id id FROM dm_participants dp JOIN conversations c ON c.id=dp.conversation_id
                          WHERE c.kind='direct' AND dp.user_id IN (?,?) GROUP BY dp.conversation_id HAVING count(*)=2""",(uid,to_uid)).fetchone()
                        if row: cid=row["id"]
                        else:
                            stamp=now()
                            cid=db.execute("INSERT INTO conversations (kind,title,created_at) VALUES ('direct',?,?)",("",stamp)).lastrowid
                            db.executemany("INSERT INTO dm_participants (conversation_id,user_id,last_read) VALUES (?,?,0)",[(cid,uid),(cid,to_uid)])
                        other_id=to_uid  # fresh thread: the recipient IS the other participant
                    else:
                        return self.send_json(400,{"error":"Recipient is required"})
                    # Notify only when the recipient isn't already caught up in this thread.
                    prev_max=db.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE conversation_id=?",(cid,)).fetchone()[0]
                    lr=db.execute("SELECT last_read FROM dm_participants WHERE conversation_id=? AND user_id=?",(cid,other_id)).fetchone()
                    caught_up=bool(lr and lr["last_read"]>=prev_max)
                    db.execute("INSERT INTO messages (conversation_id,sender_id,body,created_at) VALUES (?,?,?,?)",(cid,uid,body,now()))
                    if not caught_up:
                        sender=db.execute("SELECT name FROM users WHERE id=?",(uid,)).fetchone()
                        import platform_service
                        platform_service.notify(db, other_id, "message", f"💬 {sender['name']}", body[:120], link=f"conversation:{cid}")
                return self.send_json(201,{"ok":True,"conversation_id":cid})
            if path == "/api/dm/start":
                """Open (or reuse) a private thread with another registered user."""
                uid=self.current_user()
                if uid<=0: return self.send_json(401,{"error":"Sign in to message athletes"})
                to_uid=int(data.get("to_user_id",0) or 0)
                if not to_uid or to_uid==uid: return self.send_json(400,{"error":"Pick another athlete to message"})
                with connect() as db:
                    if not db.execute("SELECT 1 FROM users WHERE id=?",(to_uid,)).fetchone(): return self.send_json(404,{"error":"Athlete not found"})
                    row=db.execute("""SELECT dp.conversation_id id FROM dm_participants dp JOIN conversations c ON c.id=dp.conversation_id
                      WHERE c.kind='direct' AND dp.user_id IN (?,?) GROUP BY dp.conversation_id HAVING count(*)=2""",(uid,to_uid)).fetchone()
                    if row: cid=row["id"]
                    else:
                        stamp=now()
                        cid=db.execute("INSERT INTO conversations (kind,title,created_at) VALUES ('direct',?,?)",("",stamp)).lastrowid
                        db.executemany("INSERT INTO dm_participants (conversation_id,user_id,last_read) VALUES (?,?,0)",[(cid,uid),(cid,to_uid)])
                return self.send_json(200,{"conversation_id":cid})
            if path == "/api/typing":
                TYPING[int(data.get("conversation_id",1))] = (time.time(), self.current_user())
                return self.send_json(200,{"ok":True})
            if path == "/api/reviews":
                bid=int(data.get("business_id",0)); rating=max(1,min(5,int(data.get("rating",5)))); body=str(data.get("body","Great place!")).strip()[:600]
                if not bid: return self.send_json(400,{"error":"Business is required"})
                with connect() as db:
                    db.execute("INSERT INTO reviews (user_id,business_id,rating,body,created_at) VALUES (?,?,?,?,?)",(self.current_user(),bid,rating,body,now()))
                    avg=db.execute("SELECT AVG(rating) FROM reviews WHERE business_id=?",(bid,)).fetchone()[0]
                    db.execute("UPDATE businesses SET rating=? WHERE id=?",(round(avg,2),bid))
                return self.send_json(201,{"ok":True,"message":"Review posted"})
            if path == "/api/community/posts":
                cid=int(data.get("community_id",0)); body=str(data.get("body","")).strip()
                if not cid or not body: return self.send_json(400,{"error":"Community and content are required"})
                with connect() as db:
                    cur=db.execute("INSERT INTO posts (author_id,body,kind,created_at) VALUES (?,?,?,?)",(self.current_user(),body[:2000],"community",now()))
                    db.execute("INSERT OR IGNORE INTO community_posts (community_id,post_id,created_at) VALUES (?,?,?)",(cid,cur.lastrowid,now()))
                return self.send_json(201,{"ok":True,"postId":cur.lastrowid})
            if path == "/api/reports":
                target_type=str(data.get("target_type","post"))[:30]; target_id=int(data.get("target_id",0)); reason=str(data.get("reason","Inappropriate content")).strip()[:500]
                if not target_id: return self.send_json(400,{"error":"Report target is required"})
                with connect() as db: db.execute("INSERT INTO reports (reporter_id,target_type,target_id,reason,status,created_at) VALUES (?,?,?,?, 'open',?)",(self.current_user(),target_type,target_id,reason,now()))
                return self.send_json(201,{"ok":True,"message":"Report submitted — our moderators will review it."})
            if path.startswith("/api/reports/") and path.endswith("/resolve"):
                rid=int(path.split("/")[3])
                with connect() as db: db.execute("UPDATE reports SET status='resolved' WHERE id=?",(rid,))
                return self.send_json(200,{"ok":True})
            if path == "/api/challenges":
                title=str(data.get("title","Fitness challenge")).strip()[:100]; ctype=str(data.get("challenge_type","running_distance"))[:40]
                opponent=int(data.get("opponent_id",0)); target=float(data.get("target_value",5))
                uid=self.current_user()
                if opponent==uid: return self.send_json(400,{"error":"Pick someone else to challenge"})
                if opponent<=0: return self.send_json(400,{"error":"Choose a friend to challenge"})
                with connect() as db:
                    fr=db.execute("SELECT 1 FROM friendships WHERE status='accepted' AND ((requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?))",(uid,opponent,opponent,uid)).fetchone()
                    if not fr: return self.send_json(403,{"error":"You can only challenge your friends — send them a friend request first"})
                    cur=db.execute("INSERT INTO challenges (title,challenge_type,target_value,challenger_id,opponent_id,status,winner_id,starts_at,ends_at,created_at) VALUES (?,?,?,?,?,'active',NULL,?,?,?)",(title,ctype,target,uid,opponent,now()[:10],now()[:10],now()))
                    db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id,progress) VALUES (?,?,0)",(cur.lastrowid,uid))
                    db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id,progress) VALUES (?,?,0)",(cur.lastrowid,opponent))
                    myname=db.execute("SELECT name FROM users WHERE id=?",(uid,)).fetchone()[0]
                    db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(opponent,"challenge","New challenge",f"⚔️ {myname} challenged you: {title}. Open Challenges to accept.",now()))
                return self.send_json(201,{"ok":True,"challengeId":cur.lastrowid})
            if path.startswith("/api/challenges/"):
                parts=path.split("/"); cid=int(parts[3]); op=parts[4] if len(parts)>4 else ""
                uid=self.current_user()
                with connect() as db:
                    ch=db.execute("SELECT * FROM challenges WHERE id=?",(cid,)).fetchone()
                    if not ch: return self.send_json(404,{"error":"Challenge not found"})
                    ch=dict(ch)
                    if op=="accept":
                        if ch["opponent_id"]!=uid: return self.send_json(403,{"error":"Only the challenged user can accept"})
                        db.execute("UPDATE challenges SET status='active' WHERE id=?",(cid,))
                        db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(ch["challenger_id"],"challenge","Challenge accepted",f"Game on: {ch['title']}",now()))
                        return self.send_json(200,{"ok":True,"status":"active"})
                    if op=="decline":
                        if ch["opponent_id"]!=uid: return self.send_json(403,{"error":"Only the challenged user can decline"})
                        db.execute("UPDATE challenges SET status='declined' WHERE id=?",(cid,))
                        return self.send_json(200,{"ok":True,"status":"declined"})
                    if op=="invite":
                        fid=int(data.get("friend_id",0) or 0)
                        if not fid: return self.send_json(400,{"error":"Pick a friend to invite"})
                        db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id,progress) VALUES (?,?,0)",(cid,fid))
                        fname=db.execute("SELECT name FROM users WHERE id=?",(fid,)).fetchone()
                        db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(fid,"challenge","You are invited",f"Join the challenge: {ch['title']}",now()))
                        return self.send_json(200,{"ok":True,"invited":fname["name"] if fname else None})
                    if op=="progress":
                        amount=float(data.get("amount",0) or 0)
                        if amount<=0: return self.send_json(400,{"error":"Enter your progress amount"})
                        row=db.execute("SELECT progress FROM challenge_participants WHERE challenge_id=? AND user_id=?",(cid,uid)).fetchone()
                        if not row: return self.send_json(403,{"error":"Join the challenge first"})
                        newp=row["progress"]+amount
                        db.execute("UPDATE challenge_participants SET progress=? WHERE challenge_id=? AND user_id=?",(newp,cid,uid))
                        done=None
                        if newp>=ch["target_value"] and ch["status"]=="active":
                            db.execute("UPDATE challenges SET status='completed', winner_id=? WHERE id=?",(uid,cid))
                            award_xp(db,uid,150,f"Challenge won: {ch['title']}","challenge",str(cid))
                            check_achievements(db,uid)
                            db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(uid,"challenge","Challenge complete!",f"You crushed: {ch['title']} · +150 XP",now()))
                            done={"won":True,"xp":150}
                        return self.send_json(200,{"ok":True,"progress":newp,"completed":done})
            # ===== FITVERSE 2.0 POST endpoints =====
            if path == "/api/settings":
                uid=self.current_user()
                allowed={"age","sex","height_cm","weight_kg","activity_level","goal","diet_pref","days_per_week","session_minutes","equipment","kcal_target","protein_target","water_target_ml","is_private","discoverable","onboarded"}
                vals={k:v for k,v in data.items() if k in allowed}
                for _z in ("kcal_target","protein_target"):
                    if _z in vals and (vals[_z] in (0,"0") or str(vals[_z]) in ("0","0.0")):
                        vals[_z]=None  # 0 = clear back to the automatic estimate
                if not vals or all(v is None for v in vals.values()):
                    if not vals: return self.send_json(400,{"error":"Nothing to update"})
                with connect() as db:
                    db.execute("INSERT OR IGNORE INTO user_settings (user_id,updated_at) VALUES (?,?)",(uid,now()))
                    cols=",".join(f"{k}=?" for k in vals)
                    db.execute(f"UPDATE user_settings SET {cols},updated_at=? WHERE user_id=?",(*vals.values(),now(),uid))
                    if db.execute("SELECT 1 FROM user_settings WHERE user_id=?",(uid,)).fetchone() is None:
                        db.execute("INSERT INTO user_settings (user_id,updated_at) VALUES (?,?)",(uid,now()))
                return self.send_json(200,{"ok":True})
            if path == "/api/onboarding":
                uid=self.current_user()
                with connect() as db:
                    vals={k:data.get(k) for k in ("age","sex","height_cm","weight_kg","activity_level","goal","diet_pref","days_per_week","session_minutes","equipment") if k in data}
                    vals["onboarded"]=1
                    import ai_service
                    t=ai_service.targets_from_profile(vals)
                    vals["kcal_target"]=t["kcal_target"]; vals["protein_target"]=t["protein_target"]
                    # FITVERSE 6.0: 30+ onboarding collects BP / fasting sugar as day-1 vitals.
                    try:
                        bp_v=int(data.get("blood_pressure") or 0); sg_v=int(data.get("blood_sugar") or 0)
                    except (TypeError, ValueError):
                        bp_v=sg_v=0
                    if bp_v>0 or sg_v>0:
                        db.execute("INSERT INTO daily_metrics (user_id,day,steps,sleep_min,resting_hr,weight_kg,hydration_ml,blood_pressure,blood_sugar,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET blood_pressure=MAX(COALESCE(blood_pressure,0),excluded.blood_pressure),blood_sugar=MAX(COALESCE(blood_sugar,0),excluded.blood_sugar),updated_at=excluded.updated_at",
                                   (uid, now()[:10], 0,0,0, float(vals.get("weight_kg") or 0), 0, max(0,min(260,bp_v)), max(0,min(600,sg_v)), "onboarding", now()))
                    cols=",".join(f"{k}=?" for k in vals)
                    # Row must exist BEFORE the UPDATE: a fresh user has no user_settings row,
                    # and a 0-row UPDATE silently dropped the whole plan (the flash-then-vanish bug).
                    db.execute("INSERT OR IGNORE INTO user_settings (user_id,updated_at) VALUES (?,?)",(uid,now()))
                    db.execute(f"UPDATE user_settings SET {cols},updated_at=? WHERE user_id=?",(*vals.values(),now(),uid))
                    db.execute("UPDATE users SET fitness_level=?,fitness_goal=? WHERE id=?",(data.get("experience","Intermediate"),data.get("goal","General fitness"),uid))
                return self.send_json(200,{"ok":True,"targets":t})
            if path == "/api/posts":
                body=str(data.get("body","")).strip()
                if not body or len(body)>2000:return self.send_json(400,{"error":"Post content must be 1–2000 characters"})
                kind=str(data.get("kind","fitness_update"))[:40]
                photo=str(data.get("photo",""))[:200] if data.get("photo") else None
                media='video' if data.get("meta")=="video" or data.get("media")=="video" else None
                with connect() as db:
                    try: db.execute("ALTER TABLE posts ADD COLUMN photo TEXT")
                    except sqlite3.OperationalError: pass
                    try: db.execute("ALTER TABLE posts ADD COLUMN media TEXT")
                    except sqlite3.OperationalError: pass
                    cur=db.execute("INSERT INTO posts (author_id,body,kind,photo,media,created_at) VALUES (?,?,?,?,?,?)",(self.current_user(),body,kind,photo,media,now()))
                    db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) SELECT f.follower_id,'feed','New post',? || ' shared an update',0,? FROM follows f WHERE f.followee_id=?",((db.execute("SELECT name FROM users WHERE id=?",(self.current_user(),)).fetchone()[0]),now(),self.current_user()))
                return self.send_json(201,{"ok":True,"postId":cur.lastrowid})
            if path == "/api/reactions":
                pid=int(data.get("post_id",0) or 0); reaction=str(data.get("reaction",""))[:20]
                allowed={"beast","respect","keepgoing","support"}
                if not pid or reaction not in allowed: return self.send_json(400,{"error":"Invalid reaction"})
                uid=self.current_user()
                with connect() as db:
                    if not db.execute("SELECT 1 FROM posts WHERE id=?",(pid,)).fetchone(): return self.send_json(404,{"error":"Post not found"})
                    existing=db.execute("SELECT id FROM post_reactions WHERE post_id=? AND user_id=? AND reaction=?",(pid,uid,reaction)).fetchone()
                    if existing:
                        db.execute("DELETE FROM post_reactions WHERE id=?",(existing["id"],)); actioned="removed"
                    else:
                        db.execute("INSERT INTO post_reactions (post_id,user_id,reaction,created_at) VALUES (?,?,?,?)",(pid,uid,reaction,now()))
                        actioned="added"
                        owner=db.execute("SELECT author_id FROM posts WHERE id=?",(pid,)).fetchone()
                        if owner and owner["author_id"]!=uid:
                            reactor=db.execute("SELECT name FROM users WHERE id=?",(uid,)).fetchone()
                            icons={"beast":"🔥","respect":"💪","keepgoing":"🫡","support":"❤️"}
                            db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",
                                (owner["author_id"],"reaction",reactor["name"]+" reacted to your post",icons.get(reaction,"")+" "+reaction,now()))
                            award_xp(db, owner["author_id"], 2, "Post reaction received", "reaction", str(pid))
                    counts=[dict(x) for x in db.execute("SELECT reaction, COUNT(*) n FROM post_reactions WHERE post_id=? GROUP BY reaction",(pid,))]
                    mine=[x[0] for x in db.execute("SELECT reaction FROM post_reactions WHERE post_id=? AND user_id=?",(pid,uid))]
                return self.send_json(200,{"ok":True,"actioned":actioned,"reactions":counts,"mine":mine})
            if path == "/api/missions/join":
                import intelligence
                uid=self.current_user()
                fid=int(data.get("friend_id",0) or 0) or None
                with connect() as db:
                    m=intelligence.ensure_weekly_mission(db,uid)
                    if not m: return self.send_json(500,{"error":"Mission engine unavailable"})
                    if fid: db.execute("UPDATE missions SET invited_friend_id=? WHERE id=?",(fid,m["id"]))
                return self.send_json(200,{"ok":True,"mission":m,"invited":bool(fid)})
            if path == "/api/missions/abandon":
                uid=self.current_user()
                with connect() as db:
                    row=db.execute("SELECT id FROM missions WHERE user_id=? AND status='active'",(uid,)).fetchone()
                    if not row: return self.send_json(404,{"error":"No active mission"})
                    db.execute("UPDATE missions SET status='abandoned' WHERE id=?",(row["id"],))
                return self.send_json(200,{"ok":True})
            if path == "/api/teams/join":
                tid=int(data.get("team_id",0) or 0); uid=self.current_user()
                with connect() as db:
                    if not db.execute("SELECT 1 FROM teams WHERE id=?",(tid,)).fetchone(): return self.send_json(404,{"error":"Team not found"})
                    db.execute("DELETE FROM team_members WHERE user_id=?",(uid,))
                    db.execute("INSERT OR IGNORE INTO team_members (team_id,user_id,joined_at) VALUES (?,?,?)",(tid,uid,now()))
                return self.send_json(200,{"ok":True})
            if path == "/api/upload":
                import base64
                b64=str(data.get("data","")); ext=str(data.get("ext","jpg")).lower().replace("jpeg","jpg")[:5]
                kind=str(data.get("kind","image"))[:10]
                if "," in b64: b64=b64.split(",",1)[1]
                try: raw=base64.b64decode(b64)
                except Exception: return self.send_json(400,{"error":"Invalid upload data"})
                limit=3_000_000 if kind=="image" else 25_000_000
                if len(raw)>limit:
                    size_mb=3 if kind=="image" else 25
                    return self.send_json(413,{"error":f"File too large (max {size_mb}MB)"})
                allowed={"jpg","png","gif","webp","mp4","webm","mov"}
                if ext not in allowed: ext="jpg" if kind=="image" else "mp4"
                fname=f"up_{secrets.token_hex(8)}.{ext}"
                (ROOT/"uploads").mkdir(exist_ok=True)
                (ROOT/"uploads"/fname).write_bytes(raw)
                return self.send_json(201,{"ok":True,"path":f"uploads/{fname}","media":"video" if ext in ("mp4","webm","mov") else "image"})
            if path == "/api/follow":
                uid=self.current_user(); fid=int(data.get("user_id",0))
                if fid==uid: return self.send_json(400,{"error":"You cannot follow yourself"})
                with connect() as db:
                    existing=db.execute("SELECT 1 FROM follows WHERE follower_id=? AND followee_id=?",(uid,fid)).fetchone()
                    if existing:
                        db.execute("DELETE FROM follows WHERE follower_id=? AND followee_id=?",(uid,fid))
                        return self.send_json(200,{"ok":True,"following":False})
                    db.execute("INSERT OR IGNORE INTO follows (follower_id,followee_id,created_at) VALUES (?,?,?)",(uid,fid,now()))
                    db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(fid,'social','New follower',f"{db.execute('SELECT name FROM users WHERE id=?',(uid,)).fetchone()[0]} started following you",now()))
                return self.send_json(200,{"ok":True,"following":True})
            if path == "/api/exercises":
                """Create a personal custom exercise. It appears only in YOUR library,
                your workout logging, and your logs — never another user's."""
                name=str(data.get("name","")).strip()[:80]
                muscle=str(data.get("muscle","Other")).strip().capitalize()[:20]
                if not name: return self.send_json(400,{"error":"Exercise name is required"})
                uid=self.current_user()
                with connect() as db:
                    try:
                        cur=db.execute("INSERT INTO exercises (name,muscle,equipment,difficulty,instructions,mistakes,met,owner_id) VALUES (?,?,?,?,?,?,?,?)",
                            (name,muscle,str(data.get("equipment","Bodyweight")).strip().capitalize()[:30] or "Bodyweight",str(data.get("difficulty","Intermediate")).strip().capitalize()[:20],str(data.get("description","")).strip()[:500],"",5.0,uid))
                    except sqlite3.IntegrityError:
                        return self.send_json(409,{"error":"An exercise with that name already exists"})
                return self.send_json(201,{"ok":True,"exerciseId":cur.lastrowid})
            if path == "/api/workouts":
                uid=self.current_user()
                title=str(data.get("title","Workout"))[:80]; notes=str(data.get("notes",""))[:500]
                logs=data.get("logs") or []
                if not logs: return self.send_json(400,{"error":"Add at least one exercise"})
                import ai_service as _ai
                with connect() as db:
                    started=data.get("started_at") or now()
                    duration=int(data.get("duration_min") or 40)
                    volume=0.0; kcal_est=0; prs=0
                    cur=db.execute("INSERT INTO workout_sessions (user_id,title,notes,started_at,ended_at,duration_min,total_volume,est_kcal,pr_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(uid,title,notes,started,now(),duration,0,0,0,now()))
                    sid=cur.lastrowid
                    for lg in logs:
                        eid=int(lg.get("exercise_id",0)); sets=int(lg.get("sets",3)); reps=int(lg.get("reps",10)); weight=float(lg.get("weight",0)); rpe=lg.get("rpe")
                        if not eid: continue
                        ex=db.execute("SELECT * FROM exercises WHERE id=?",(eid,)).fetchone()
                        is_pr=0
                        # FITVERSE 6.1: bodyweight & cardio count too — weight=0 is a REAL
                        # log (bw volume / minutes), not a zero. Yoga poses, planks, runs
                        # were previously invisible to PRs and volume.
                        prev=db.execute("SELECT MAX(wl.weight) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id WHERE ws.user_id=? AND wl.exercise_id=? AND ws.id<>?",(uid,eid,sid)).fetchone()[0]
                        if prev is None or weight>prev: is_pr=1; prs+=1
                        vol=weight*reps*sets; volume+=vol
                        db.execute("INSERT INTO workout_logs (session_id,exercise_id,sets,reps,weight,rpe,is_pr,created_at) VALUES (?,?,?,?,?,?,?,?)",(sid,eid,sets,reps,weight,rpe,is_pr,now()))
                    kcal_est=max(120, min(900, round(duration*6.5*(1+prs*0.1) + volume/1000)))
                    db.execute("UPDATE workout_sessions SET total_volume=?,est_kcal=?,pr_count=? WHERE id=?",(round(volume),kcal_est,prs,sid))
                    award_xp(db,uid,60+prs*25,"Workout logged","workout",str(sid))
                    mission_done=check_missions(db,uid)
                    if prs:
                        db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(uid,'pr','New personal record',f"{prs} new PR{'s' if prs>1 else ''} in {title}!",now()))
                return self.send_json(201,{"ok":True,"sessionId":sid,"pr_count":prs,"total_volume":round(volume),"est_kcal":kcal_est,"mission_completed":mission_done})
            if path == "/api/nutrition":
                uid=self.current_user()
                import datetime as _dt
                day=data.get("day") or _dt.date.today().isoformat()
                name=str(data.get("name","")).strip()[:100]
                if not name: return self.send_json(400,{"error":"Food name is required"})
                with connect() as db:
                    cur=db.execute("INSERT INTO nutrition_logs (user_id,meal,name,kcal,protein_g,carbs_g,fat_g,fiber_g,qty,logged_on,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(uid,str(data.get("meal","breakfast"))[:20],name,int(data.get("kcal",0)),float(data.get("protein_g",0)),float(data.get("carbs_g",0)),float(data.get("fat_g",0)),float(data.get("fiber_g",0)),float(data.get("qty",1)),day,now()))
                    award_xp(db,uid,5,"Meal logged","meal",str(cur.lastrowid))
                    # Echo back the freshly-updated day totals so the UI updates instantly,
                    # with no stale-cache or disappearing-rows glitch.
                    fresh=[dict(r) for r in db.execute("SELECT * FROM nutrition_logs WHERE user_id=? AND logged_on=? ORDER BY id",(uid,day))]
                    tot={"kcal":sum(int(x["kcal"] or 0) for x in fresh),"protein":round(sum(float(x["protein_g"] or 0) for x in fresh)),"carbs":round(sum(float(x["carbs_g"] or 0) for x in fresh)),"fat":round(sum(float(x["fat_g"] or 0) for x in fresh))}
                return self.send_json(201,{"ok":True,"logId":cur.lastrowid,"totals":tot,"items":fresh,"day":day})
            if path.startswith("/api/nutrition/"):
                uid=self.current_user(); lid=int(path.split("/")[3])
                with connect() as db:
                    row=db.execute("SELECT user_id FROM nutrition_logs WHERE id=?",(lid,)).fetchone()
                    if not row or row["user_id"]!=uid: return self.send_json(404,{"error":"Log not found"})
                    db.execute("DELETE FROM nutrition_logs WHERE id=?",(lid,))
                return self.send_json(200,{"ok":True})
            if path == "/api/water":
                uid=self.current_user()
                import datetime as _dt
                day=_dt.date.today().isoformat()
                ml=int(data.get("ml",250))
                with connect() as db:
                    db.execute("INSERT INTO water_logs (user_id,ml,logged_on,created_at) VALUES (?,?,?,?)",(uid,ml,day,now()))
                    tot=db.execute("SELECT COALESCE(SUM(ml),0) FROM water_logs WHERE user_id=? AND logged_on=?",(uid,day)).fetchone()[0]
                    tgt=db.execute("SELECT water_target_ml FROM user_settings WHERE user_id=?",(uid,)).fetchone()
                return self.send_json(200,{"ok":True,"today_ml":tot,"target_ml":(tgt[0] if tgt and tgt[0] else 2500)})
            if path == "/api/progress":
                uid=self.current_user()
                import datetime as _dt
                with connect() as db:
                    cur=db.execute("INSERT INTO progress_entries (user_id,weight_kg,body_fat,chest_cm,waist_cm,hips_cm,arm_cm,photo_path,note,entry_date,created_at,is_public) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(uid,data.get("weight_kg"),data.get("body_fat"),data.get("chest_cm"),data.get("waist_cm"),data.get("hips_cm"),data.get("arm_cm"),data.get("photo_path"),str(data.get("note",""))[:300],data.get("entry_date") or _dt.date.today().isoformat(),now(),1 if data.get("is_public") else 0))
                return self.send_json(201,{"ok":True,"entryId":cur.lastrowid})
            if path == "/api/ai/coach":
                uid=self.current_user(); msg=str(data.get("message","")).strip()[:500]
                if not msg: return self.send_json(400,{"error":"Ask me something!"})
                import ai_service
                r=ai_service.ai_coach(uid,msg)
                cid=int(data.get("conversationId",0) or 0)
                with connect() as db:
                    conv=db.execute("SELECT id FROM ai_conversations WHERE id=? AND user_id=?",(cid,uid)).fetchone() if cid else None
                    if conv: useid=conv["id"]
                    else:
                        cur=db.execute("INSERT INTO ai_conversations (user_id,title,created_at) VALUES (?,?,?)",(uid,msg[:60] if msg else 'Coach chat',now())); useid=cur.lastrowid
                    db.execute("INSERT INTO ai_messages (conversation_id,role,content,created_at) VALUES (?,?,?,?)",(useid,'user',msg,now()))
                    db.execute("INSERT INTO ai_messages (conversation_id,role,content,created_at) VALUES (?,?,?,?)",(useid,'coach',r['reply'],now()))
                return self.send_json(200,{"ok":True,"reply":r['reply'],"kind":r.get('kind','brief'),"conversationId":useid})
            if path.startswith("/api/ai/coach/") and path.split("/")[-1].isdigit():
                """Rename / pin / delete an AI conversation (owner-only).
                NOTE: writes happen inside the with-block; responses are returned
                AFTER it — returning from inside would roll the write back."""
                uid=self.current_user(); conv_id=int(path.split("/")[-1]); op=str(data.get("op","") or ("delete" if data.get("delete") else ""))
                resp=None
                with connect() as db:
                    conv=db.execute("SELECT id FROM ai_conversations WHERE id=? AND user_id=?",(conv_id,uid)).fetchone()
                    if not conv:
                        return self.send_json(404,{"error":"Conversation not found"})
                    if op=="delete":
                        db.execute("DELETE FROM ai_messages WHERE conversation_id=?",(conv_id,)); db.execute("DELETE FROM ai_conversations WHERE id=?",(conv_id,))
                        resp={"ok":True,"deleted":conv_id}
                    elif op=="rename":
                        title=str(data.get("title","")).strip()[:80]
                        if not title: return self.send_json(400,{"error":"Title required"})
                        db.execute("UPDATE ai_conversations SET title=? WHERE id=?",(title,conv_id))
                        resp={"ok":True,"title":title}
                    elif op=="pin":
                        db.execute("UPDATE ai_conversations SET pinned=CASE WHEN pinned=1 THEN 0 ELSE 1 END WHERE id=?",(conv_id,))
                        row=db.execute("SELECT pinned FROM ai_conversations WHERE id=?",(conv_id,)).fetchone()
                        resp={"ok":True,"pinned":row["pinned"]}
                if resp is None: return self.send_json(400,{"error":"Unknown op"})
                return self.send_json(200,resp)
            if path == "/api/health/suggest":
                """AI training suggestion built from the user's imported health data."""
                import platform_service
                return self.send_json(200, platform_service.training_suggestion(self.current_user()))
            if path.startswith("/api/workouts/") and path.split("/")[3].isdigit():
                """DELETE a workout session (and its logs) — removes it from every panel."""
                sid = int(path.split("/")[3]); uid = self.current_user()
                with connect() as db:
                    row = db.execute("SELECT user_id FROM workout_sessions WHERE id=?", (sid,)).fetchone()
                    if not row or row["user_id"] != uid:
                        return self.send_json(404, {"error": "Session not found"})
                    db.execute("DELETE FROM workout_logs WHERE session_id=?", (sid,))
                    db.execute("DELETE FROM workout_sessions WHERE id=?", (sid,))
                return self.send_json(200, {"ok": True, "deleted": sid})
            if path == "/api/ai/workout":
                import ai_service
                plan=ai_service.generate_workout(self.current_user(),data)
                return self.send_json(200,{"item":plan})
            if path == "/api/ai/meal":
                import ai_service
                r=ai_service.analyze_meal(str(data.get("desc","")),float(data.get("grams",250)))
                return self.send_json(200,{"item":r})
            if path == "/api/ai/indian-diet":
                """FITVERSE 6.0: Indian diet plan built from targets + BP/sugar vitals."""
                import ai_service
                return self.send_json(200,{"item":ai_service.indian_diet_plan(self.current_user())})
            if path == "/api/ai/goal":
                import ai_service
                return self.send_json(200,{"item":ai_service.goal_plan(self.current_user(),str(data.get("goal","")))})
            if path == "/api/block":
                uid=self.current_user(); bid=int(data.get("user_id",0)); kind=str(data.get("kind","block"))[:10]
                with connect() as db:
                    if kind=="unblock": db.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?",(uid,bid))
                    else: db.execute("INSERT OR REPLACE INTO blocks (blocker_id,blocked_id,kind,created_at) VALUES (?,?,?,?)",(uid,bid,kind,now()))
                return self.send_json(200,{"ok":True})
            # ===== FITVERSE 4.0 routes =====
            if path == "/api/notifications/prefs":
                import platform_service
                cat = str(data.get("category","")).strip()
                if cat not in [c for c, _ in platform_service.DEFAULT_CATEGORIES]:
                    return self.send_json(400,{"error":"Unknown notification category"})
                field = "sound" if data.get("field")=="sound" else "enabled"
                val = 1 if data.get("enabled", True) else 0
                with connect() as db:
                    platform_service.ensure_prefs(db, self.current_user())
                    db.execute(f"UPDATE notification_prefs SET {field}=? WHERE user_id=? AND category=?",(val,self.current_user(),cat))
                return self.send_json(200,{"ok":True})
            if path == "/api/businesses":
                uid=self.current_user()
                name=str(data.get("name","")).strip()[:100]; category=str(data.get("category","Gym")).strip()[:40]
                if not name: return self.send_json(400,{"error":"Business name is required"})
                with connect() as db:
                    cur=db.execute("""INSERT INTO businesses (name,category,location_label,description,rating,owner_id,tagline,website,phone,address,lat,lng,cover,logo,hours_note,created_at)
                                     VALUES (?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?)""",
                        (name,category,str(data.get("location_label","Chennai")).strip()[:80],str(data.get("description","")).strip()[:1200],uid,
                         str(data.get("tagline","")).strip()[:120] or None,str(data.get("website","")).strip()[:200] or None,
                         str(data.get("phone","")).strip()[:30] or None,str(data.get("address","")).strip()[:200] or None,
                         float(data["lat"]) if data.get("lat") not in (None,"") else None,
                         float(data["lng"]) if data.get("lng") not in (None,"") else None,
                         str(data.get("cover","")).strip()[:300] or None,str(data.get("logo","")).strip()[:300] or None,
                         str(data.get("hours_note","")).strip()[:140] or None,now()))
                    bid=cur.lastrowid
                return self.send_json(201,{"ok":True,"id":bid})
            if path.startswith("/api/businesses/") and path.endswith("/edit"):
                uid=self.current_user(); bid=int(path.split("/")[3])
                with connect() as db:
                    b=db.execute("SELECT owner_id FROM businesses WHERE id=?",(bid,)).fetchone()
                    if not b or b["owner_id"]!=uid: return self.send_json(403,{"error":"Only the business owner can edit"})
                    fields=[]; vals=[]
                    for k in ("name","category","location_label","description","tagline","website","phone","address","hours_note"):
                        if k in data: fields.append(f"{k}=?"); vals.append(str(data[k]).strip()[:1200] or None)
                    for k in ("lat","lng"):
                        if k in data: fields.append(f"{k}=?"); vals.append(float(data[k]) if data[k] not in (None,"") else None)
                    for k in ("cover","logo"):
                        if k in data: fields.append(f"{k}=?"); vals.append(str(data[k]).strip()[:300] or None)
                    if fields: db.execute(f"UPDATE businesses SET {', '.join(fields)} WHERE id=?",(*vals,bid))
                return self.send_json(200,{"ok":True})
            if path.startswith("/api/businesses/") and path.endswith("/products"):
                uid=self.current_user(); bid=int(path.split("/")[3])
                name=str(data.get("name","")).strip()[:120]
                if not name: return self.send_json(400,{"error":"Product name is required"})
                with connect() as db:
                    b=db.execute("SELECT owner_id FROM businesses WHERE id=?",(bid,)).fetchone()
                    if not b or b["owner_id"]!=uid: return self.send_json(403,{"error":"Only the business owner can add products"})
                    db.execute("INSERT INTO business_products (business_id,name,description,price,image,link,position,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (bid,name,str(data.get("description","")).strip()[:600],str(data.get("price","")).strip()[:40],str(data.get("image","")).strip()[:300],str(data.get("link","")).strip()[:300],int(data.get("position",0)),now()))
                return self.send_json(201,{"ok":True})
            if path.startswith("/api/businesses/") and path.endswith("/products/delete"):
                uid=self.current_user(); bid=int(path.split("/")[3]); pid=int(data.get("product_id",0))
                with connect() as db:
                    b=db.execute("SELECT owner_id FROM businesses WHERE id=?",(bid,)).fetchone()
                    if not b or b["owner_id"]!=uid: return self.send_json(403,{"error":"Only the business owner can remove products"})
                    db.execute("DELETE FROM business_products WHERE id=? AND business_id=?",(pid,bid))
                return self.send_json(200,{"ok":True})
            if path.startswith("/api/businesses/") and path.endswith("/photos"):
                uid=self.current_user(); bid=int(path.split("/")[3]); p=str(data.get("path","")).strip()[:300]
                if not p: return self.send_json(400,{"error":"Photo path is required"})
                with connect() as db:
                    b=db.execute("SELECT owner_id FROM businesses WHERE id=?",(bid,)).fetchone()
                    if not b or b["owner_id"]!=uid: return self.send_json(403,{"error":"Only the business owner can add photos"})
                    db.execute("INSERT INTO business_photos (business_id,path,position,created_at) VALUES (?,?,?,?)",(bid,p,0,now()))
                return self.send_json(201,{"ok":True})
            if path.startswith("/api/businesses/") and path.endswith("/hours"):
                uid=self.current_user(); bid=int(path.split("/")[3]); hours=data.get("hours",{})
                with connect() as db:
                    b=db.execute("SELECT owner_id FROM businesses WHERE id=?",(bid,)).fetchone()
                    if not b or b["owner_id"]!=uid: return self.send_json(403,{"error":"Only the business owner can set hours"})
                    db.execute("DELETE FROM business_hours WHERE business_id=?",(bid,))
                    for d,v in (hours.items() if isinstance(hours,dict) else []):
                        try: dow=int(d)
                        except Exception: continue
                        if isinstance(v,(list,tuple)) and len(v)>=2:
                            db.execute("INSERT OR REPLACE INTO business_hours (business_id,dow,open_time,close_time) VALUES (?,?,?,?)",(bid,dow,str(v[0])[:8],str(v[1])[:8]))
                return self.send_json(200,{"ok":True})
            if path.startswith("/api/businesses/") and path.endswith("/follow"):
                uid=self.current_user(); bid=int(path.split("/")[3])
                with connect() as db:
                    if db.execute("SELECT 1 FROM business_follows WHERE business_id=? AND user_id=?",(bid,uid)).fetchone():
                        db.execute("DELETE FROM business_follows WHERE business_id=? AND user_id=?",(bid,uid))
                        followed=False
                    else:
                        db.execute("INSERT INTO business_follows (business_id,user_id,created_at) VALUES (?,?,?)",(bid,uid,now()))
                        followed=True
                return self.send_json(200,{"ok":True,"following":followed})
            if path.startswith("/api/businesses/") and path.endswith("/post"):
                import platform_service
                uid=self.current_user(); bid=int(path.split("/")[3]); body=str(data.get("body","")).strip()[:2000]
                if not body: return self.send_json(400,{"error":"Post content is required"})
                with connect() as db:
                    b=db.execute("SELECT owner_id FROM businesses WHERE id=?",(bid,)).fetchone()
                    if not b or b["owner_id"]!=uid: return self.send_json(403,{"error":"Only the business owner can post"})
                    cur=db.execute("INSERT INTO posts (author_id,body,kind,media_url,media_type,created_at) VALUES (?,?,?,?,?,?)",
                        (uid,body[:2000],"business",str(data.get("media_url","")).strip()[:300] or None,"image" if data.get("media_url") else None,now()))
                    db.execute("INSERT INTO business_posts (business_id,post_id,created_at) VALUES (?,?,?)",(bid,cur.lastrowid,now()))
                    for (fid,) in db.execute("SELECT user_id FROM business_follows WHERE business_id=?",(bid,)).fetchall():
                        if fid!=uid: platform_service.notify(db,fid,"business","📣 " + (db.execute("SELECT name FROM businesses WHERE id=?",(bid,)).fetchone()["name"]), body[:120], f"business/{bid}")
                return self.send_json(201,{"ok":True})
            if path == "/api/health/google/connect":
                import platform_service
                host = self.headers.get("Host") or "127.0.0.1:4173"
                proto = self.headers.get("X-Forwarded-Proto") or ("https" if ".onrender.com" in host else "http")
                st = platform_service.google_fit_status(self.current_user(), f"{proto}://{host}")
                if not st["configured"]:
                    return self.send_json(501, {"error": "Google Fit sign-in is not configured on this server yet.", "missing": st["missing"],
                                                "how": "Zero-setup option: use 'Import from Google Takeout' on the Health page (works right now). Full auto-sync (free): console.cloud.google.com -> enable Fitness API -> OAuth web client with redirect /api/health/google/callback -> set GOOGLE_FIT_CLIENT_ID and GOOGLE_FIT_CLIENT_SECRET."})
                return self.send_json(200, {"ok": True, "authorize_url": st["authorize_url"]})
            if path == "/api/health/google/sync":
                import platform_service
                return self.send_json(200, platform_service.google_fit_sync(self.current_user()))
            if path == "/api/health/import/takeout":
                import platform_service
                days = data.get("days")
                if not isinstance(days, list) or not days:
                    return self.send_json(400, {"error": "No days to import"})
                return self.send_json(200, platform_service.import_takeout_days(self.current_user(), days))
            if path == "/api/health/import/file":
                """Real file import: Health Connect export / Google Takeout Fit JSON.
                Accepts either {records:[...]} or a raw pasted/exported JSON payload."""
                import platform_service
                records = data.get("records")
                if records is None and isinstance(data.get("json"), str):
                    try:
                        parsed = json.loads(data["json"])
                        if isinstance(parsed, list):
                            records = parsed
                        elif isinstance(parsed, dict):
                            records = (parsed.get("records") or parsed.get("days") or parsed.get("data")
                                       or parsed.get("metrics") or parsed.get("sessions") or [parsed])
                    except Exception:
                        records = None
                if not isinstance(records, list) or not records:
                    return self.send_json(400, {"error": "No parsable records found. Export from Health Connect (Settings → Export data) or Google Takeout (Fit) as JSON, then import it here."})
                return self.send_json(200, platform_service.import_health_connect_records(self.current_user(), records))
            if path == "/api/health/disconnect":
                import platform_service
                return self.send_json(200, platform_service.health_disconnect(self.current_user(), str(data.get("provider","google_fit"))[:20]))
            if path == "/api/health/metrics":
                uid=self.current_user()
                day=str(data.get("day",now()[:10]))[:10]
                try:
                    vals=(int(data["steps"]) if data.get("steps") not in (None,"") else 0,
                          int(data["sleep_min"]) if data.get("sleep_min") not in (None,"") else 0,
                          int(data["resting_hr"]) if data.get("resting_hr") not in (None,"") else 0,
                          float(data["weight_kg"]) if data.get("weight_kg") not in (None,"") else 0,
                          int(data["hydration_ml"]) if data.get("hydration_ml") not in (None,"") else 0,
                          int(data["blood_pressure"]) if data.get("blood_pressure") not in (None,"") else 0,
                          int(data["blood_sugar"]) if data.get("blood_sugar") not in (None,"") else 0)
                except Exception: return self.send_json(400,{"error":"Invalid metric values"})
                with connect() as db:
                    db.execute("""INSERT INTO daily_metrics (user_id,day,steps,sleep_min,resting_hr,weight_kg,hydration_ml,blood_pressure,blood_sugar,source,updated_at)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?)
                                  ON CONFLICT(user_id,day) DO UPDATE SET steps=excluded.steps,sleep_min=excluded.sleep_min,
                                    resting_hr=excluded.resting_hr,weight_kg=excluded.weight_kg,hydration_ml=excluded.hydration_ml,
                                    blood_pressure=excluded.blood_pressure,blood_sugar=excluded.blood_sugar,updated_at=excluded.updated_at""",
                               (uid,day,*vals,"manual",now()))
                return self.send_json(200,{"ok":True})
            if path == "/api/ai/companion":
                import platform_service
                r = platform_service.chat_reply(self.current_user(), str(data.get("message","")), data.get("conversationId"))
                return self.send_json(200, r)
            if path == "/api/ai/daily":
                import platform_service
                return self.send_json(200, platform_service.daily_companion(self.current_user()))
            if path == "/api/ai/compose":
                import platform_service
                return self.send_json(200, platform_service.compose_assist(self.current_user(), str(data.get("text", ""))))
            if path == "/api/ai/status":
                try:
                    import groq_ai
                    return self.send_json(200, groq_ai.status())
                except Exception:
                    return self.send_json(200, {"provider": "groq", "configured": False,
                                                "note": "Built-in deterministic AI active — full AI unavailable."})
            return self.send_json(404,{"error":"Unknown API route"})
        except ValueError as error: self.send_json(400,{"error":str(error)})
        except Exception as error:
            import traceback; traceback.print_exc()
            print("API error:",repr(error)); self.send_json(500,{"error":"Something went wrong. Please try again."})

    def serve_static(self, url_path: str) -> None:
        requested = "index.html" if url_path in ("", "/") else url_path.lstrip("/")
        target = (ROOT / requested).resolve()
        if ROOT not in target.parents and target != ROOT: return self.send_error(HTTPStatus.FORBIDDEN)
        if not target.is_file(): return self.send_error(HTTPStatus.NOT_FOUND)
        content = target.read_bytes(); content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type",content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type in ("application/javascript",) else "")); self.send_header("Content-Length",str(len(content))); self.end_headers(); self.wfile.write(content)


if __name__ == "__main__":
    initialize_database()
    store.purge_expired_sessions()
    host = os.environ.get("HOST", "0.0.0.0")   # 0.0.0.0 so cloud hosts like Render can reach it
    try: port = int(os.environ.get("PORT", "4173"))
    except (TypeError, ValueError): port = 0
    if port <= 0: port = 4173                  # some shells export PORT=0; fall back to the default
    server = ThreadingHTTPServer((host, port), FitverseHandler)
    _rep = store.storage_report()
    print("FITVERSE is live at http://127.0.0.1:" + str(port) if host in ("127.0.0.1", "localhost") else f"FITVERSE is live on port {port}", flush=True)
    print(f"[storage] {_rep['mode']}", flush=True)
    if _rep["warning"]:
        print(f"[storage] WARNING: {_rep['warning']}", flush=True)
    print("[ai] brain: " + (("Groq (" + (os.environ.get("GROK_API_KEY") or os.environ.get("GROQ_API_KEY") or "")[:6] + "… set)") if ((os.environ.get("GROQ_API_KEY") or "").strip() or (os.environ.get("GROK_API_KEY") or "").strip()) else "built-in demo engine (set GROQ_API_KEY for full AI)"), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
