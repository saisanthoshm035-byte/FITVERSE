"""FITVERSE intelligence layer.

Computes the signature ecosystem features from the user's real activity:
  - FITNESS DNA        seven behavioral scores + training personality + focus
  - PATTERN DETECTOR   behavioral patterns (imbalance, gaps, cardio avoidance...)
  - FITNESS DEBT       missed weekly commitments, safe recovery framing
  - FITNESS TWIN       where am I / what holds me back / where could I go
  - TRAJECTORIES       clearly-labeled what-if estimates (never guarantees)

Everything is deterministic and derived from permitted FITVERSE activity only.
No medical claims: outputs are behavioral/educational estimates.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

from server import connect, now


# ---------------------------------------------------------------- helpers

def _settings(db, uid):
    row = db.execute("SELECT * FROM user_settings WHERE user_id=?", (uid,)).fetchone()
    return dict(row) if row else {}


def _clamp(n, lo=0, hi=100):
    return int(max(lo, min(hi, round(n))))


def _days_since(iso):
    if not iso:
        return 999
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))[:10] if False else datetime.fromisoformat(str(iso)[:19]).date()
    except ValueError:
        try:
            d = date.fromisoformat(str(iso)[:10])
        except ValueError:
            return 999
    return (date.today() - d).days


def _weekly_sessions(db, uid, weeks=1):
    row = db.execute(
        "SELECT COUNT(*) FROM workout_sessions WHERE user_id=? AND created_at>=date('now',?)",
        (uid, f"-{weeks * 7} days")).fetchone()
    return row[0] if row else 0


def _muscle_split(db, uid, days=28):
    """Upper vs lower vs cardio session counts from exercise muscles."""
    rows = db.execute(
        """SELECT COALESCE(e.muscle,'unknown') m, COUNT(DISTINCT ws.id) n
             FROM workout_sessions ws
             JOIN workout_logs wl ON wl.session_id=ws.id
             JOIN exercises e ON e.id=wl.exercise_id
            WHERE ws.user_id=? AND ws.created_at>=date('now',?)
            GROUP BY m""", (uid, f"-{days} days")).fetchall()
    upper = {"Chest", "Back", "Shoulders", "Arms"}
    counts = {"upper": 0, "lower": 0, "cardio": 0, "core": 0}
    for r in rows:
        m = r["m"] or ""
        if m == "Cardio":
            counts["cardio"] += r["n"]
        elif m in upper:
            counts["upper"] += r["n"]
        elif m in ("Legs", "Glutes"):
            counts["lower"] += r["n"]
        elif m == "Core":
            counts["core"] += r["n"]
        else:
            counts["upper"] += r["n"] // 2
    return counts


# ---------------------------------------------------------------- FITNESS DNA

def fitness_dna(uid: int) -> dict:
    """Seven behavioral scores (0-100) computed from real activity."""
    with connect() as db:
        s = _settings(db, uid)
        game = db.execute("SELECT xp,streak,activities FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
        game = dict(game) if game else {"xp": 0, "streak": 0, "activities": 0}
        weeks = max(1, _weekly_sessions(db, uid))
        sessions_28 = _weekly_sessions(db, uid, weeks=4)
        split = _muscle_split(db, uid)
        cardio_min = db.execute(
            """SELECT COALESCE(SUM(wl.duration_min),0) FROM workout_logs wl
               JOIN workout_sessions ws ON ws.id=wl.session_id JOIN exercises e ON e.id=wl.exercise_id
               WHERE ws.user_id=? AND e.muscle='Cardio' AND ws.created_at>=date('now','-28 days')""",
            (uid,)).fetchone()[0]
        rpe = db.execute(
            """SELECT AVG(wl.rpe) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
               WHERE ws.user_id=? AND wl.rpe IS NOT NULL AND ws.created_at>=date('now','-28 days')""",
            (uid,)).fetchone()[0]
        volume = db.execute(
            """SELECT COALESCE(SUM(total_volume),0) FROM workout_sessions
               WHERE user_id=? AND created_at>=date('now','-28 days')""", (uid,)).fetchone()[0]
        challenge_rows = db.execute(
            "SELECT COUNT(*) FROM challenge_participants WHERE user_id=?", (uid,)).fetchone()[0]
        social = db.execute(
            """SELECT (SELECT COUNT(*) FROM friendships WHERE status='accepted' AND (requester_id=? OR addressee_id=?))
                    + (SELECT COUNT(*) FROM posts WHERE author_id=?)
                    + (SELECT COUNT(*) FROM comments WHERE author_id=?)
                    + (SELECT COUNT(*) FROM community_members WHERE user_id=?)""",
            (uid, uid, uid, uid, uid)).fetchone()[0]
        days_trained = db.execute(
            """SELECT COUNT(DISTINCT date(created_at)) FROM workout_sessions
               WHERE user_id=? AND created_at>=date('now','-28 days')""", (uid,)).fetchone()[0]
        days_logged_meals = db.execute(
            "SELECT COUNT(DISTINCT logged_on) FROM nutrition_logs WHERE user_id=? AND logged_on>=date('now','-28 days')",
            (uid,)).fetchone()[0]
        days_logged_water = db.execute(
            "SELECT COUNT(DISTINCT logged_on) FROM water_logs WHERE user_id=? AND logged_on>=date('now','-28 days')",
            (uid,)).fetchone()[0]
        mission_done = db.execute(
            "SELECT COUNT(*) FROM missions WHERE user_id=? AND status='completed' AND completed_at>=date('now','-28 days')",
            (uid,)).fetchone()[0] if _table_exists(db, "missions") else 0

    target_days = max(2, int(s.get("days_per_week") or 4) * 4 * 0.9)  # 28d target, slight grace
    consistency = 100.0 * days_trained / target_days

    pr_count = _recent_prs(uid)
    strength = _clamp(40 + min(30, volume / 500) + min(18, pr_count * 6))
    cardio = _clamp(min(100, 18 + cardio_min * 1.1 + (15 if split["cardio"] else 0)))
    social_score = _clamp(20 + social * 5)
    discipline = _clamp(consistency * 0.55 + min(30, days_logged_meals * 4) + min(15, days_logged_water * 3))
    intensity = _clamp(35 + (rpe or 5) * 8 + (10 if sessions_28 >= 8 else 0))
    nutrition = _clamp(min(100, days_logged_meals * 11 + days_logged_water * 4))
    consistency = _clamp(consistency + min(15, game["streak"] * 2) + min(10, mission_done * 5))
    # challenge participation nudges discipline & social
    if challenge_rows:
        discipline = _clamp(discipline + 4)
        social_score = _clamp(social_score + 4)

    scores = {
        "strength": strength,
        "consistency": consistency,
        "cardio": cardio,
        "social": social_score,
        "discipline": discipline,
        "nutrition": nutrition,
        "intensity": intensity,
    }
    personality, focus = _personality(scores, split, s)
    strengths = [k.capitalize() for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:2] if v >= 40]
    improve = [k.capitalize() for k, v in sorted(scores.items(), key=lambda kv: kv[1])[:2] if v < 70]
    mission = _recommended_mission(uid, scores, split)
    return {
        "scores": scores,
        "personality": personality,
        "focus": focus,
        "strengths": strengths or ["Showing up — the strongest habit"],
        "improve": improve or ["Pushing intensity once recovered"],
        "top": max(scores, key=scores.get),
        "mission": mission,
        "sessions_28d": sessions_28,
    }


def _recent_prs(uid, days=28):
    with connect() as db:
        if not _table_exists(db, "workout_logs"):
            return 0
        return db.execute(
            """SELECT COUNT(*) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
               WHERE ws.user_id=? AND wl.is_pr=1 AND ws.created_at>=date('now',?)""",
            (uid, f"-{days} days")).fetchone()[0]


def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _personality(scores, split, s):
    goal = (s.get("goal") or "maintain").lower()
    if scores["consistency"] >= 75 and scores["strength"] >= 65:
        p, f = "The Consistent Builder", "Add intensity to an already-solid routine"
    elif scores["cardio"] >= 70 and scores["consistency"] >= 55:
        p, f = "The Endurance Engine", "Layer in strength work twice a week"
    elif scores["strength"] >= 75:
        p, f = "The Power Builder", "Balance your week with cardio + mobility"
    elif scores["consistency"] >= 60:
        p, f = "The Habit Forger", "Lock in your weekly rhythm before adding volume"
    elif scores["social"] >= 60:
        p, f = "The Team Player", "Channel squad energy into a personal mission"
    else:
        p, f = "The Explorer", "Build one anchor habit: 3 sessions a week"
    return p, f


# ---------------------------------------------------------------- MISSION ENGINE

MISSION_CATALOG = [
    {"id": "legs", "icon": "🎯", "title": "Operation Leg Day", "metric": "lower_workouts",
     "base": 3, "xp": 500, "desc": "Complete {target} lower-body workouts this week. Squats, lunges, deadlifts — all count."},
    {"id": "cardio", "icon": "🔥", "title": "Cardio Awakening", "metric": "cardio_sessions",
     "base": 2, "xp": 350, "desc": "Finish {target} cardio sessions this week — walk, run, cycle, swim, court sport: every movement counts."},
    {"id": "sprint", "icon": "⚡", "title": "Consistency Sprint", "metric": "workouts",
     "base": 4, "xp": 400, "desc": "Complete {target} workouts this week. Keep every session honest, none extreme."},
    {"id": "fuel", "icon": "🥗", "title": "Fuel Week", "metric": "meal_days",
     "base": 5, "xp": 300, "desc": "Log your meals on {target} different days this week. Awareness first, optimization later."},
    {"id": "squad", "icon": "🤝", "title": "Squad Accountability", "metric": "workouts",
     "base": 3, "xp": 450, "desc": "Complete {target} workouts this week and invite a friend to at least one."},
]


def _recommended_mission(uid: int, scores: dict, split: dict) -> dict:
    """Pick the highest-leverage mission from DNA + patterns + debt, with adaptive difficulty."""
    with connect() as db:
        debt = fitness_debt(uid)
        # priority: imbalance > debt > weakest DNA area
        imbalance = split["upper"] >= 2 and split["lower"] <= split["upper"] * 0.34
        if imbalance:
            chosen = MISSION_CATALOG[0]
        elif debt["debt"] >= 2 or scores["consistency"] < 55:
            chosen = MISSION_CATALOG[2]
        elif scores["cardio"] < 55:
            chosen = MISSION_CATALOG[1]
        elif scores["nutrition"] < 50:
            chosen = MISSION_CATALOG[3]
        elif scores["social"] < 55:
            chosen = MISSION_CATALOG[4]
        else:
            chosen = MISSION_CATALOG[1]  # even strong users get the cardio touch
        target = chosen["base"]
        # ---- adaptive difficulty from recent mission history
        recent = db.execute(
            "SELECT status FROM missions WHERE user_id=? AND status IN ('completed','expired') ORDER BY id DESC LIMIT 3",
            (uid,)).fetchall()
        done = sum(1 for r in recent if r["status"] == "completed")
        if len(recent) >= 2 and done == len(recent):
            target += 1  # crushing it → level up
        elif len(recent) >= 2 and done == 0:
            target = max(2, target - 1)  # struggling → reduce pressure
        xp = chosen["xp"] + (100 if target > chosen["base"] else -75 if target < chosen["base"] else 0)
    return {"key": chosen["id"], "icon": chosen["icon"], "title": chosen["title"],
            "metric": chosen["metric"], "target": target, "reward_xp": xp,
            "description": chosen["desc"].format(target=target)}


def mission_progress_for(db, uid: int, metric: str, since: str | None = None) -> int:
    """Live counter for a mission metric. Counts only activity since the mission was
    created (falls back to this ISO week when `since` is None) so missions can never
    be instantly completed by activity that predates them."""
    since = since or "date('now','weekday 0','-6 days')"  # Monday of this week
    if metric == "workouts":
        return db.execute("SELECT COUNT(*) FROM workout_sessions WHERE user_id=? AND created_at>=?", (uid, since)).fetchone()[0]
    if metric == "lower_workouts":
        return db.execute("""SELECT COUNT(DISTINCT ws.id) FROM workout_sessions ws
            JOIN workout_logs wl ON wl.session_id=ws.id JOIN exercises e ON e.id=wl.exercise_id
            WHERE ws.user_id=? AND ws.created_at>=? AND e.muscle IN ('Legs','Glutes')""", (uid, since)).fetchone()[0]
    if metric == "cardio_sessions":
        return db.execute("""SELECT COUNT(DISTINCT ws.id) FROM workout_sessions ws
            JOIN workout_logs wl ON wl.session_id=ws.id JOIN exercises e ON e.id=wl.exercise_id
            WHERE ws.user_id=? AND ws.created_at>=? AND e.muscle='Cardio'""", (uid, since)).fetchone()[0]
    if metric == "meal_days":
        return db.execute("SELECT COUNT(DISTINCT logged_on) FROM nutrition_logs WHERE user_id=? AND logged_on>=?", (uid, since[:10])).fetchone()[0]
    return 0


def ensure_weekly_mission(db, uid: int) -> dict | None:
    """Return the user's active mission, generating one from the engine if none exists."""
    if not _table_exists(db, "missions"):
        return None
    row = db.execute("SELECT * FROM missions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    if row:
        m = dict(row)
    else:
        rec = _recommended_mission(uid, fitness_dna(uid)["scores"], _muscle_split(db, uid))
        cur = db.execute("INSERT INTO missions (user_id,mission_key,title,icon,description,metric,target,reward_xp,status,created_at) VALUES (?,?,?,?,?,?,?,?,'active',?)",
                         (uid, rec["key"], rec["title"], rec["icon"], rec["description"], rec["metric"], rec["target"], rec["reward_xp"], now()))
        m = dict(db.execute("SELECT * FROM missions WHERE id=?", (cur.lastrowid,)).fetchone())
    m["progress"] = mission_progress_for(db, uid, m["metric"], m["created_at"])
    return m


# ---------------------------------------------------------------- PATTERNS

def detect_patterns(uid: int) -> list[dict]:
    """Behavioral patterns. Never medical, never shaming."""
    with connect() as db:
        split = _muscle_split(db, uid)
        gap = None
        row = db.execute("SELECT MAX(created_at) FROM workout_sessions WHERE user_id=?", (uid,)).fetchone()
        if row and row[0]:
            gap = _days_since(row[0])
        cardio_sessions = _muscle_cardio_sessions(db, uid)
        recent = db.execute(
            "SELECT date(created_at) d FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-28 days') ORDER BY d",
            (uid,)).fetchall()
        s = _settings(db, uid)
        target_wk = int(s.get("days_per_week") or 4)
    out = []
    total = split["upper"] + split["lower"]
    if total >= 3 and split["lower"] <= split["upper"] * 0.34:
        out.append({
            "id": "imbalance", "severity": "warning", "icon": "⚠️",
            "title": "Upper-body outweighs lower-body",
            "detail": f"In the last 28 days you logged {split['upper']} upper-body vs {split['lower']} lower-body sessions.",
            "why": "Balanced training builds a stronger foundation and keeps joints happy.",
            "fix": "Add one lower-body session this week — even 20 minutes counts.",
        })
    if cardio_sessions <= 1:
        out.append({
            "id": "cardio", "severity": "info", "icon": "ℹ️",
            "title": "Cardio is quiet lately",
            "detail": "You've done at most one cardio-focused session in the last 28 days.",
            "why": "A little cardio supports recovery and heart health — it doesn't have to mean running.",
            "fix": "Try one 20-minute walk, cycle, or swim this week. It counts.",
        })
    if gap is not None and gap >= 5:
        out.append({
            "id": "gap", "severity": "warning", "icon": "⏳",
            "title": f"{gap} days since your last session",
            "detail": "Long gaps make restarting feel heavier than it is.",
            "why": "Momentum returns fastest with a small, easy session — not a monster one.",
            "fix": "Book a 20-minute re-entry session today. Lower the bar, keep the streak alive.",
        })
    if len(recent) < target_wk * 3:
        out.append({
            "id": "consistency", "severity": "info", "icon": "📉",
            "title": "Below your weekly target",
            "detail": f"You averaged {round(len(recent) / 4, 1)} sessions/week vs your {target_wk}/week plan.",
            "why": "Consistency beats intensity — a slightly easier target you hit every week wins.",
            "fix": "Consider temporarily setting your plan to " + str(max(2, target_wk - 1)) + " days/week and rebuilding.",
        })
    if not out:
        out.append({
            "id": "healthy", "severity": "good", "icon": "✅",
            "title": "No concerning patterns",
            "detail": "Your recent training looks balanced and consistent. Keep going!",
            "why": "Balanced programs build resilient athletes.",
            "fix": "Hold the course, and consider a fresh challenge to stay sharp.",
        })
    return out


def _muscle_cardio_sessions(db, uid):
    return db.execute(
        """SELECT COUNT(DISTINCT ws.id) FROM workout_sessions ws
           JOIN workout_logs wl ON wl.session_id=ws.id JOIN exercises e ON e.id=wl.exercise_id
           WHERE ws.user_id=? AND e.muscle='Cardio' AND ws.created_at>=date('now','-28 days')""",
        (uid,)).fetchone()[0]


# ---------------------------------------------------------------- FITNESS DEBT

def fitness_debt(uid: int) -> dict:
    """Missed sessions vs weekly plan, framed for safe recovery."""
    with connect() as db:
        s = _settings(db, uid)
        done = _weekly_sessions(db, uid)
        last_week = db.execute(
            "SELECT COUNT(*) FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-14 days') AND created_at<date('now','-7 days')",
            (uid,)).fetchone()[0]
    target = int(s.get("days_per_week") or 4)
    debt = max(0, target - done)
    prev_debt = max(0, target - last_week)
    if debt == 0:
        advice = "Weekly target cleared. Whatever you do from here is a bonus — recovery counts too."
        level = "clear"
    elif debt <= 1:
        advice = "One session left in the plan. A focused 30 minutes closes the gap — no heroics needed."
        level = "low"
    elif debt == 2:
        advice = "Don't compensate with extreme training. Space two normal sessions across the rest of the week."
        level = "moderate"
    else:
        advice = "The week got away — that happens. Ease back with 2-3 short sessions and reset the target next week."
        level = "high"
    return {
        "target": target, "completed": done, "debt": debt, "previous_debt": prev_debt,
        "reduction": max(0, prev_debt - debt), "level": level, "advice": advice,
        "week_progress": _clamp(100 * done / target if target else 0),
    }


# ---------------------------------------------------------------- FITNESS TWIN

def fitness_twin(uid: int) -> dict:
    """Behavior model: where am I / what holds me back / where could I go / next."""
    dna = fitness_dna(uid)
    debt = fitness_debt(uid)
    patterns = detect_patterns(uid)
    with connect() as db:
        s = _settings(db, uid)
        game = db.execute("SELECT xp,streak FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
        game = dict(game) if game else {"xp": 0, "streak": 0}
        wk4 = _weekly_sessions(db, uid, weeks=4)
        wk_last = db.execute(
            "SELECT COUNT(*) FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-14 days') AND created_at<date('now','-7 days')",
            (uid,)).fetchone()[0]
        first_pr = db.execute(
            """SELECT e.name, MAX(wl.weight) w FROM workout_logs wl
               JOIN workout_sessions ws ON ws.id=wl.session_id JOIN exercises e ON e.id=wl.exercise_id
               WHERE ws.user_id=? AND wl.weight>0 GROUP BY e.name ORDER BY w DESC LIMIT 1""", (uid,)).fetchone()
    trend = "up" if wk4 / 4 >= max(1, wk_last) else "steady"
    weakest = min(dna["scores"], key=dna["scores"].get)
    holding = {
        "consistency": "Your weekly rhythm dips below plan — the habit anchor, not effort, is the bottleneck.",
        "cardio": "Cardio is the missing pillar, capping your engine and recovery.",
        "nutrition": "Fuel logging is sparse, so progress is harder to see and steer.",
        "strength": "Volume is still light — progressive overload hasn't fully kicked in.",
        "social": "Training solo: accountability is your biggest untapped lever.",
        "discipline": "Streaks break before they compound — protect the small days.",
        "intensity": "Sessions are comfortable; a touch more challenge would unlock gains.",
    }.get(weakest, "Focus is still forming — one clear priority will sharpen everything.")
    next_action = dna["mission"]["title"] if dna.get("mission") else "Log your next session"
    return {
        "where_now": {
            "sessions_28d": dna["sessions_28d"],
            "weekly_avg": round(dna["sessions_28d"] / 4, 1),
            "target_weekly": int(s.get("days_per_week") or 4),
            "trend": trend,
            "streak": game["streak"],
            "top_lif": dict(first_pr) if first_pr else None,
            "debt": debt["debt"],
        },
        "holding_back": holding,
        "weakest": weakest,
        "patterns": len([p for p in patterns if p["severity"] != "good"]),
        "where_could_go": "Two consistent weeks at your target would move " + weakest.capitalize() + " noticeably — your recent trend is " + trend + ".",
        "next": next_action,
        "disclaimer": "Your Fitness Twin models behavior from your FITVERSE activity. It guides training habits — it is not a medical assessment.",
    }


# ---------------------------------------------------------------- TRAJECTORIES

SCENARIOS = {
    "current": {"label": "Current routine", "days": None},
    "3days": {"label": "Train 3 days/week", "days": 3},
    "4days": {"label": "Train 4 days/week", "days": 4},
    "5days": {"label": "Train 5 days/week", "days": 5},
    "consistency": {"label": "Improve consistency", "days": None, "consistency_boost": 12},
    "cardio": {"label": "Increase cardio", "days": None, "cardio_boost": True},
    "strength": {"label": "Focus on strength", "days": None, "strength_boost": True},
}


def trajectory(uid: int, scenario_id: str = "current", horizon_days: int = 90) -> dict:
    """Estimated what-if scenario. Clearly labeled as an estimate, not a promise."""
    sc = SCENARIOS.get(scenario_id, SCENARIOS["current"])
    dna = fitness_dna(uid)
    debt = fitness_debt(uid)
    s_cur = dna["scores"]["consistency"]
    base_weekly = max(1.0, dna["sessions_28d"] / 4)
    target = sc["days"] or int((dna["sessions_28d"] / 4) or 3)
    weeks = horizon_days // 7

    with connect() as db:
        s = _settings(db, uid)
    plan = int(s.get("days_per_week") or 4)
    adherence = min(1.0, base_weekly / plan) if plan else 0.7

    proj_consistency = _clamp(min(97, s_cur * (0.75 + 0.25 * adherence) + (sc.get("consistency_boost") or 0) + (4 if sc["days"] and sc["days"] <= plan else -2 if sc["days"] and sc["days"] > plan + 1 else 0)))
    volume_delta = round((target - base_weekly) / max(1, base_weekly) * 100)
    volume_delta = max(-30, min(60, volume_delta))
    if sc.get("strength_boost"):
        volume_delta += 12
    est_sessions = int(round(target * weeks))
    cardio_note = "Cardio share of your week roughly doubles." if sc.get("cardio_boost") else None
    direction = "positive" if proj_consistency >= s_cur and volume_delta >= 0 else "mixed" if volume_delta >= -10 else "recovery"
    return {
        "scenario": scenario_id, "label": sc["label"], "horizon_days": horizon_days,
        "current_consistency": s_cur,
        "projected_consistency": proj_consistency,
        "weekly_sessions": {"now": round(base_weekly, 1), "projected": target},
        "volume_delta_pct": volume_delta,
        "estimated_sessions": est_sessions,
        "cardio_note": cardio_note,
        "debt_clearance": "Clears your current debt within 2 weeks" if debt["debt"] and target >= debt["target"] else None,
        "direction": direction,
        "disclaimer": "Estimate based on your previous activity and selected assumptions. Not a guaranteed prediction — no medical or body-composition promises.",
    }
