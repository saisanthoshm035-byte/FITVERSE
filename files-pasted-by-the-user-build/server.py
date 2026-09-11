"""FITVERSE MVP backend — stdlib-only HTTP API + SQLite persistence.

Run: python server.py
Then open: http://127.0.0.1:4173
"""
from __future__ import annotations

import hashlib
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
SESSIONS: dict[str, int] = {}
DEMO_USER_ID = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


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
"""


def initialize_database() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        stamp = now()
        db.executemany("INSERT OR IGNORE INTO achievements (id,code,name,description,icon) VALUES (?,?,?,?,?)", [
            (1,"first_activity","First Activity","Complete your first activity.","⚡"),
            (2,"challenge_champion","Challenge Champion","Win a fitness challenge.","🏆"),
            (3,"goal_crusher","Goal Crusher","Complete four activities in a week.","🎯"),
            (4,"seven_day_streak","7 Day Streak","Maintain a seven-day streak.","🔥"),
            (5,"event_participant","Event Participant","Book your first fitness event.","🎟️"),
        ])
        exists = db.execute("SELECT 1 FROM users WHERE id = ?", (DEMO_USER_ID,)).fetchone()
        if exists:
            db.execute("""INSERT OR IGNORE INTO profiles (user_id,bio,availability,workout_intensity,preferred_location,updated_at)
                          SELECT id,'Fitness is better together.','Weekdays','Moderate','Campus',? FROM users""", (stamp,))
            db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id) VALUES (1,1)")
            db.execute("INSERT OR IGNORE INTO challenge_participants (challenge_id,user_id) VALUES (1,2)")
            return
        created = now()
        demo_salt = "fitverse-demo-salt"
        users = [
            (1, "Sai Kumar", "saikumar", "sai@fitverse.demo", "Chennai", "Intermediate", "General fitness", "Basketball", "5–7 PM"),
            (2, "Rahul Menon", "rahulmenon", "rahul@fitverse.demo", "Chennai", "Intermediate", "Sports performance", "Basketball", "5–6 PM"),
            (3, "Ananya Iyer", "ananyaiyer", "ananya@fitverse.demo", "Chennai", "Advanced", "Endurance", "Running", "6–7 AM"),
            (4, "Arjun Raj", "arjunraj", "arjun@fitverse.demo", "Chennai", "Intermediate", "General fitness", "Cycling", "6–8 AM"),
        ]
        for u in users:
            db.execute("""INSERT INTO users (id,name,username,email,password_salt,password_hash,city,fitness_level,fitness_goal,favorite_activity,preferred_time,created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (u[0], u[1], u[2], u[3], demo_salt, hash_password("demo1234", demo_salt), *u[4:], created))
        db.executemany("INSERT INTO profiles (user_id,bio,availability,workout_intensity,preferred_location,updated_at) VALUES (?,?,?,?,?,?)", [
            (1,"Building a better relationship with consistency. Basketball after class.","Weekdays","Moderate","Campus",created),
            (2,"Courts, community and a little healthy competition.","Weekdays","Moderate","Campus",created),
            (3,"One more kilometre, one more story.","Mornings","High","Track",created),
            (4,"Chasing sunrise and long roads.","Weekends","Moderate","ECR",created),
        ])
        db.execute("INSERT INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (1, 1080, 6, 3, 0, 0, "pending", 0, 0, 12, created))
        for user_id, xp, streak, activities in [(2, 1240, 9, 7), (3, 1170, 12, 8), (4, 950, 5, 5)]:
            db.execute("INSERT INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (user_id, xp, streak, activities, 0, 0, "pending", 0, 0, 12, created))
        db.executemany("""INSERT INTO activities (id,title,sport,starts_at,location_label,max_participants,fitness_level,intensity,description,host_id,created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)""", [
            (1, "Sunset basketball", "Basketball", "2026-09-10T17:30:00+05:30", "Campus Sports Ground", 8, "Intermediate", "Moderate", "A friendly post-class game.", 2, created),
            (2, "Campus loop run", "Running", "2026-09-10T18:00:00+05:30", "Campus Track", 12, "Beginner", "Moderate", "An easy social 5K.", 3, created),
            (3, "Weekend cycling crew", "Cycling", "2026-09-13T06:30:00+05:30", "ECR Checkpoint", 15, "Intermediate", "Moderate", "Coastal morning ride.", 4, created),
        ])
        db.executemany("INSERT INTO activity_participants VALUES (?,?,?)", [(1,2,created),(1,3,created),(1,4,created),(2,2,created),(2,3,created)])
        db.execute("""INSERT INTO challenges (id,title,challenge_type,target_value,challenger_id,opponent_id,status,winner_id,starts_at,ends_at,created_at)
                      VALUES (1,'Rahul 5K Challenge','running_distance',5,2,1,'pending',NULL,?,?,?)""",
                   ("2026-09-10T00:00:00+05:30", "2026-09-17T23:59:00+05:30", created))
        db.executemany("INSERT INTO challenge_participants (challenge_id,user_id,progress) VALUES (?,?,?)", [(1,1,3.8),(1,2,4.2)])
        db.executemany("INSERT INTO communities (id,name,description,activity,created_at) VALUES (?,?,?,?,?)", [
            (1,"Basketball Community","Courts, crews and competition.","Basketball",created),
            (2,"Chennai Runners","Run the city together.","Running",created),
            (3,"Gym Beginners","Small wins. Strong habits.","Gym",created),
            (4,"Cycling Club","Sunday miles and chai stops.","Cycling",created),
        ])
        db.execute("INSERT INTO community_members VALUES (?,?,?,?)", (1,1,"member",created))
        db.executemany("""INSERT INTO events (id,name,category,starts_at,location_label,price_inr,capacity,organizer,description,created_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?)""", [
            (1,"Chennai Night Run 2026","Running","2026-09-20T19:00:00+05:30","Marina Beach",499,2400,"Chennai Running Collective","6K under city lights, music, medals and your fastest self.",created),
            (2,"Campus 3v3 Tournament","Basketball","2026-09-15T16:00:00+05:30","Campus Sports Ground",199,120,"FITVERSE Campus","A fast, friendly campus tournament.",created),
            (3,"Sunrise Yoga at Besant","Yoga","2026-09-18T06:00:00+05:30","Besant Nagar Beach",0,100,"Yoga Chennai","A gentle community flow by the sea.",created),
        ])
        db.execute("INSERT INTO posts (id,author_id,body,kind,created_at) VALUES (1,3,?,'activity',?)", ("Finished my first 5K today! The last kilometre was all heart. 🏃", created))
        db.execute("INSERT INTO conversations (id,kind,title,created_at) VALUES (1,'direct','Rahul Menon',?)", (created,))
        db.executemany("INSERT INTO messages (conversation_id,sender_id,body,created_at) VALUES (?,?,?,?)", [(1,2,"Hey Sai! You joining basketball later?",created),(1,1,"Absolutely. Bringing an extra ball!",created)])
        db.executemany("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,?,?)", [(1,"activity","Rahul invited you","Sunset basketball starts in 42 minutes.",0,created),(1,"challenge","Challenge reminder","Your 5K challenge is waiting.",0,created)])
        db.executemany("INSERT INTO businesses (name,category,location_label,description,rating,created_at) VALUES (?,?,?,?,?,?)", [("Pulse Fitness","Gym","Adyar","Community-first strength training.",4.7,created),("Courtside Academy","Sports academy","Guindy","Basketball coaching and court time.",4.5,created)])


def user_state(db: sqlite3.Connection, user_id: int) -> dict:
    row = db.execute("SELECT * FROM user_game_state WHERE user_id=?", (user_id,)).fetchone()
    return dict(row)


def read_bootstrap(user_id: int) -> dict:
    with connect() as db:
        user = dict(db.execute("SELECT id,name,username,city,fitness_level,fitness_goal,favorite_activity,preferred_time FROM users WHERE id=?", (user_id,)).fetchone())
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
    return True


def check_achievements(db: sqlite3.Connection, user_id: int) -> list[str]:
    game = user_state(db,user_id); unlocked=[]
    thresholds = [
        (1, game["activities"] >= 1),
        (2, db.execute("SELECT 1 FROM challenges WHERE winner_id=? LIMIT 1",(user_id,)).fetchone() is not None),
        (3, game["activities"] >= 4),
        (4, game["streak"] >= 7),
        (5, game["booked_event"] == 1),
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
    with connect() as db:
        rows=db.execute("""SELECT p.id,p.body,p.kind,p.created_at,u.name,u.username,
          (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id) AS likes,
          EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked,
          EXISTS(SELECT 1 FROM saved_posts s WHERE s.post_id=p.id AND s.user_id=?) AS saved,
          (SELECT count(*) FROM comments c WHERE c.post_id=p.id) AS comments
          FROM posts p JOIN users u ON u.id=p.author_id ORDER BY p.id DESC""",(user_id,user_id)).fetchall()
    return [dict(row) for row in rows]


def coach_reply(user_id: int, prompt: str) -> dict:
    q=prompt.lower(); data=read_bootstrap(user_id); matches=recommendations(user_id)
    if any(word in q for word in ("basketball","people","match","compatible")):
        top=matches[0] if matches else None
        text=f"Your best current match is {top['name']} at {top['score']}%. You both enjoy {top['activity']} and share a weekday training window." if top else "Complete onboarding details to improve your matches."
    elif any(word in q for word in ("event","weekend")):
        text="Chennai Night Run is coming up at Marina Beach. It is a great social 6K option for your current activity level."
    elif any(word in q for word in ("challenge","compete")):
        text="Try a 5K distance challenge with Rahul. It is active, measurable, and awards XP only when the result is recorded."
    else:
        remaining=max(0,4-data["state"]["activities"])
        text=f"You are {remaining} activity{'ies' if remaining != 1 else 'y'} from your weekly goal. Join Sunset basketball or log a completed activity to keep your streak moving."
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
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000: raise ValueError("Request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict): raise ValueError("JSON object required")
        return value

    def current_user(self) -> int:
        token = self.headers.get("X-Session", "")
        return SESSIONS.get(token, DEMO_USER_ID)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        query = urlparse(self.path).query
        if path == "/api/health": return self.send_json(200,{"ok":True,"database":"sqlite","time":now()})
        if path == "/api/bootstrap": return self.send_json(200, read_bootstrap(self.current_user()))
        if path == "/api/leaderboard": return self.send_json(200,{"items":read_bootstrap(self.current_user())["leaderboard"]})
        if path == "/api/recommendations": return self.send_json(200,{"items":recommendations(self.current_user()),"model":"deterministic compatibility service"})
        if path == "/api/coach":
            from urllib.parse import parse_qs
            return self.send_json(200,coach_reply(self.current_user(),parse_qs(query).get("q",[""])[0]))
        if path == "/api/feed": return self.send_json(200,{"items":list_feed(self.current_user())})
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
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/businesses":
            with connect() as db: rows=db.execute("SELECT * FROM businesses ORDER BY rating DESC").fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/notifications":
            with connect() as db: rows=db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/messages":
            with connect() as db: rows=db.execute("SELECT m.*,u.name FROM messages m JOIN users u ON u.id=m.sender_id WHERE m.conversation_id=1 ORDER BY m.id",()).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/achievements":
            with connect() as db: rows=db.execute("SELECT a.*,ua.unlocked_at FROM achievements a LEFT JOIN user_achievements ua ON ua.achievement_id=a.id AND ua.user_id=? ORDER BY a.id",(self.current_user(),)).fetchall()
            return self.send_json(200,{"items":[dict(r) for r in rows]})
        if path == "/api/bookings":
            with connect() as db:
                items=[dict(r) for r in db.execute("SELECT b.booking_code,b.status,b.quantity,e.name,e.starts_at,e.location_label FROM bookings b JOIN events e ON e.id=b.event_id WHERE b.user_id=? ORDER BY b.id DESC",(self.current_user(),))]
            return self.send_json(200,{"items":items})
        if path.startswith("/api/"): return self.send_json(404,{"error":"Unknown API route"})
        self.serve_static(path)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path; data = self.body()
            if path == "/api/auth/login":
                username=str(data.get("username","")).strip().lower(); password=str(data.get("password",""))
                with connect() as db: user=db.execute("SELECT * FROM users WHERE username=? OR email=?",(username,username)).fetchone()
                if not user or hash_password(password,user["password_salt"]) != user["password_hash"]: return self.send_json(401,{"error":"Invalid username or password"})
                token=secrets.token_urlsafe(32); SESSIONS[token]=user["id"]; return self.send_json(200,{"token":token,"user":{"id":user["id"],"name":user["name"]}})
            if path == "/api/auth/register":
                required=["name","username","email","password"]
                if any(not str(data.get(k,"")).strip() for k in required): return self.send_json(400,{"error":"Name, username, email and password are required"})
                salt=secrets.token_hex(16); stamp=now()
                try:
                    with connect() as db:
                        cur=db.execute("INSERT INTO users (name,username,email,password_salt,password_hash,created_at) VALUES (?,?,?,?,?,?)",(data["name"].strip(),data["username"].strip().lower(),data["email"].strip().lower(),salt,hash_password(data["password"],salt),stamp))
                        db.execute("INSERT INTO user_game_state VALUES (?,?,?,?,?,?,?,?,?,?,?)",(cur.lastrowid,0,0,0,0,0,"pending",0,0,0,stamp)); db.execute("INSERT INTO profiles (user_id,updated_at,onboarding_completed) VALUES (?,?,0)",(cur.lastrowid,stamp)); user_id=cur.lastrowid
                    token=secrets.token_urlsafe(32); SESSIONS[token]=user_id; return self.send_json(201,{"token":token,"userId":user_id})
                except sqlite3.IntegrityError: return self.send_json(409,{"error":"That username or email is already in use"})
            if path == "/api/profile":
                allowed_user={"name","city","fitness_level","fitness_goal","favorite_activity","preferred_time"}
                allowed_profile={"bio","college_or_company","availability","workout_intensity","preferred_location","avatar_url"}
                if not any(key in data for key in (*allowed_user,*allowed_profile)): return self.send_json(400,{"error":"No editable profile fields supplied"})
                with connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for key in allowed_user:
                        if key in data: db.execute(f"UPDATE users SET {key}=? WHERE id=?",(str(data[key]).strip()[:120],self.current_user()))
                    for key in allowed_profile:
                        if key in data: db.execute(f"UPDATE profiles SET {key}=?,updated_at=? WHERE user_id=?",(str(data[key]).strip()[:500],now(),self.current_user()))
                    db.commit()
                return self.send_json(200,{"ok":True})
            if path == "/api/posts":
                body=str(data.get("body","")).strip()
                if not body or len(body)>2000:return self.send_json(400,{"error":"Post content must be 1–2000 characters"})
                with connect() as db:
                    cur=db.execute("INSERT INTO posts (author_id,body,kind,created_at) VALUES (?,?,?,?)",(self.current_user(),body,str(data.get("kind","fitness_update"))[:40],now()))
                return self.send_json(201,{"ok":True,"postId":cur.lastrowid})
            if path == "/api/activities":
                required=("title","sport","starts_at","location_label")
                if any(not str(data.get(k,"")).strip() for k in required): return self.send_json(400,{"error":"Activity title, sport, time and location are required"})
                maximum=max(2,min(100,int(data.get("max_participants",8))))
                with connect() as db:
                    cur=db.execute("""INSERT INTO activities (title,sport,starts_at,location_label,max_participants,fitness_level,intensity,description,host_id,created_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?)""",(str(data["title"]).strip()[:100],str(data["sport"]).strip()[:50],str(data["starts_at"]),str(data["location_label"]).strip()[:120],maximum,str(data.get("fitness_level","Open"))[:30],str(data.get("intensity","Moderate"))[:30],str(data.get("description","")).strip()[:1000],self.current_user(),now()))
                    db.execute("INSERT INTO activity_participants VALUES (?,?,?)",(cur.lastrowid,self.current_user(),now()))
                return self.send_json(201,{"ok":True,"activityId":cur.lastrowid})
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
                    db.execute("INSERT INTO notifications (user_id,type,title,body,is_read,created_at) VALUES (?,?,?,?,0,?)",(recipient,"friend_request","New friend request","Someone wants to connect through FITVERSE.",now()))
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
                body=str(data.get("body","")).strip()
                if not body or len(body)>1000:return self.send_json(400,{"error":"Message must be 1–1000 characters"})
                with connect() as db: db.execute("INSERT INTO messages (conversation_id,sender_id,body,created_at) VALUES (1,?,?,?)",(self.current_user(),body,now()))
                return self.send_json(201,{"ok":True})
            return self.send_json(404,{"error":"Unknown API route"})
        except ValueError as error: self.send_json(400,{"error":str(error)})
        except Exception as error:
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
    server = ThreadingHTTPServer(("127.0.0.1", 4173), FitverseHandler)
    print("FITVERSE is live at http://127.0.0.1:4173")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
