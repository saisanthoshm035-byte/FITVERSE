"""FITVERSE AI service layer.

A clean seam for real AI models: every function returns data the UI can render.
Currently powered by deterministic, personalized rules over the user's real data
(goals, history, nutrition, recovery) so responses are genuinely useful without
any external API. To plug in a real model later, replace the internals of each
function with a provider call — the signatures and response shapes stay the same.

Medical safety: injury/pain questions always return general safety guidance and
a recommendation to consult a qualified healthcare professional. The coach never
diagnoses, never prescribes extreme deficits (<1200 kcal), and frames all
numbers as estimates.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta

from server import connect, now  # shared connection + timestamp helpers


# ---------------------------------------------------------------- helpers

def get_settings(db: sqlite3.Connection, user_id: int) -> dict:
    row = db.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else {"kcal_target": 2200, "protein_target": 120, "weight_kg": 70, "goal": "maintain", "age": None, "sex": None, "height_cm": None, "activity_level": "moderate", "days_per_week": 4, "session_minutes": 45, "equipment": "Full gym", "water_target_ml": 2500, "onboarded": 0}


def targets_from_profile(s: dict) -> dict:
    """Mifflin-St Jeor estimate with goal adjustment. Clearly an estimate."""
    try:
        age = int(s.get("age") or 25)
        sex = (s.get("sex") or "male").lower()
        h = float(s.get("height_cm") or 175)
        w = float(s.get("weight_kg") or 70)
        bmr = 10 * w + 6.25 * h - 5 * age + (5 if sex.startswith("m") else -161)
    except (TypeError, ValueError):
        bmr = 1600
    mult = {"low": 1.3, "moderate": 1.5, "high": 1.7, "athlete": 1.85}.get((s.get("activity_level") or "moderate").lower(), 1.5)
    tdee = bmr * mult
    goal = (s.get("goal") or "maintain").lower()
    if "lose" in goal:
        kcal = tdee - 400          # gentle deficit, never aggressive
    elif "gain" in goal or "muscle" in goal:
        kcal = tdee + 300
    else:
        kcal = tdee
    kcal = max(1300, round(kcal / 10) * 10)
    protein = round((1.6 if "muscle" in goal or "gain" in goal else 1.5) * (s.get("weight_kg") or 70))
    return {
        "bmr": round(bmr), "tdee": round(tdee), "kcal_target": kcal,
        "protein_target": protein, "carbs_target": round(kcal * 0.45 / 4),
        "fat_target": round(kcal * 0.25 / 9),
        "estimate_note": "Estimates from the Mifflin-St Jeor formula — adjust to how your body responds.",
    }


def _recent_sessions(db, uid, days=28):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    return [dict(r) for r in db.execute(
        "SELECT * FROM workout_sessions WHERE user_id=? AND created_at>=? ORDER BY created_at DESC", (uid, since))]


def _muscle_coverage(db, uid, days=7):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = db.execute("""SELECT e.muscle, count(*) n FROM workout_logs wl
        JOIN workout_sessions ws ON ws.id=wl.session_id JOIN exercises e ON e.id=wl.exercise_id
        WHERE ws.user_id=? AND ws.created_at>=? GROUP BY e.muscle""", (uid, since)).fetchall()
    return {r["muscle"]: r["n"] for r in rows}


def _macro_day(db, uid, day=None):
    day = day or date.today().isoformat()
    row = db.execute("""SELECT COALESCE(SUM(kcal),0) kcal, COALESCE(SUM(protein_g),0) p,
        COALESCE(SUM(carbs_g),0) c, COALESCE(SUM(fat_g),0) f FROM nutrition_logs WHERE user_id=? AND logged_on=?""", (uid, day)).fetchone()
    return dict(row)


def _water_day(db, uid, day=None):
    day = day or date.today().isoformat()
    return db.execute("SELECT COALESCE(SUM(ml),0) FROM water_logs WHERE user_id=? AND logged_on=?", (uid, day)).fetchone()[0]


# ---------------------------------------------------------------- coach

SAFETY = ("I'm not able to diagnose injuries or medical conditions. General guidance: stop the movement that "
          "causes pain, keep the area mobile within a pain-free range, and please check with a qualified "
          "healthcare professional before loading it again. 💚")


def ai_coach(user_id: int, message: str) -> dict:
    """Personalized coach reply. Deterministic today, model-backed later — same shape."""
    q = (message or "").lower().strip()
    with connect() as db:
        s = get_settings(db, user_id)
        t = targets_from_profile(s)
        cov = _muscle_coverage(db, user_id)
        sessions = _recent_sessions(db, user_id, 7)
        today = _macro_day(db, user_id)
        game = db.execute("SELECT xp,streak FROM user_game_state WHERE user_id=?", (user_id,)).fetchone()
        streak = game["streak"] if game else 0
        week_kcal = sum(s2["est_kcal"] for s2 in sessions)
        prs = db.execute("""SELECT count(*) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
            WHERE ws.user_id=? AND wl.is_pr=1 AND ws.created_at>=date('now','-30 days')""", (user_id,)).fetchone()[0]

    def parts(*xs):
        return " ".join(x for x in xs if x)

    # --- FITVERSE 3.0 context: missions, DNA, debt, patterns ---
    try:
        import intelligence
        dna = intelligence.fitness_dna(user_id)
        debt = intelligence.fitness_debt(user_id)
        sc = dna["scores"]
        with connect() as db:
            mission = intelligence.ensure_weekly_mission(db, user_id)
        if any(k in q for k in ("mission", "operation")):
            return {"reply": parts(
                f"🎯 Your active mission is {mission['title']}: {mission['description']}",
                f"Progress: {mission.get('progress', 0)}/{mission['target']} · +{mission['reward_xp']} XP when you finish. Log a workout and I'll track it automatically."), "kind": "mission"}
        if "fitness dna" in q or "my dna" in q or "personality" in q:
            top3 = ", ".join(f"{k.capitalize()} {v}" for k, v in sorted(sc.items(), key=lambda kv: -kv[1])[:3])
            return {"reply": parts(
                f"🧬 Your Fitness DNA says you're {dna['personality']}.",
                f"Top scores: {top3}.",
                f"Focus: {dna['focus']}."), "kind": "dna"}
        if "debt" in q or "behind" in q or "missed" in q or "catch up" in q:
            return {"reply": parts(
                f"⚡ Fitness debt: {debt['debt']} of {debt['target']} weekly sessions.",
                debt["advice"]), "kind": "debt"}
        if any(k in q for k in ("lazy", "motivat", "skip", "don't feel", "cant be bothered", "can't be bothered")):
            left = max(0, mission["target"] - mission.get("progress", 0))
            return {"reply": parts(
                f"🔥 Small win first: {mission['title']} needs just {left} more this week.",
                f"Even 20 minutes keeps your {streak}-day streak breathing.",
                "You don't need motivation — you need a smaller first step."), "kind": "motivation"}
    except Exception:
        pass  # intelligence layer unavailable — fall through to the classic branches

    # --- injury / pain: safety first ---
    if any(k in q for k in ("knee", "hurts", "pain", "injur", "sharp", "swollen")):
        return {"reply": parts("🩺", SAFETY,
                f"While it settles, swap loaded squats for split squats within a comfortable range or hip thrusts, and keep training pain-free areas." if "knee" in q else "While it settles, train around it — pain-free movements only."), "kind": "safety"}

    # --- nutrition questions ---
    if "calorie" in q or "how much should i eat" in q:
        return {"reply": parts(
            f"🎯 Your estimated maintenance is **{t['tdee']} kcal/day** (Mifflin-St Jeor).",
            f"For your goal ({s.get('goal','maintain')}) aim for about **{t['kcal_target']} kcal**.",
            f"Protein target: **{t['protein_target']}g** — the anchor for recovery.",
            "These are estimates; weigh in weekly and adjust by ±150 kcal if the trend isn't moving." if s.get("weight_kg") else "These are estimates; tune them as you learn your rhythm."), "kind": "nutrition"}
    if "protein" in q:
        return {"reply": parts(
            f"🥩 Today you're at **{round(today['p'])}g of {t['protein_target']}g protein**.",
            f"Easy wins to close the gap: {round(max(0, t['protein_target']-today['p']))}g left ≈ a whey scoop + 100g paneer, or 150g chicken breast.",
            "Spread it across 3-4 meals for better recovery."), "kind": "nutrition"}
    if any(k in q for k in ("eat", "meal", "diet", "food")):
        return {"reply": parts(
            f"🍽️ You've logged **{round(today['kcal'])}/{t['kcal']} kcal** today (protein {round(today['p'])}g).",
            "Build plates around a palm of protein, a fist of carbs, thumbs of fats — and log right after eating, not at midnight. Your diary makes the coach smarter."), "kind": "nutrition"}

    # --- programming questions ---
    if "routine" in q or "split" in q or ("plan" in q and "day" in q) or "5-day" in q or "3-day" in q:
        num = 5 if "5" in q else 3 if "3" in q else (s.get("days_per_week") or 4)
        splits = {3: "Full Body A / B / C", 4: "Upper / Lower / Upper / Lower", 5: "Push / Pull / Legs / Upper / Lower"}
        return {"reply": parts(
            f"🗓️ A {num}-day week fits you well. Try: **{splits.get(num, splits[4])}**.",
            "Rule of thumb: every muscle 2× weekly, 10-20 hard sets per muscle per week, and one full rest day.",
            "Ask me: 'generate a 5 day gym routine' and I'll build it exercise by exercise."), "kind": "programming"}
    if "dumbbell" in q or "home" in q or "equipment" in q or "travelling" in q or "travel" in q:
        return {"reply": parts(
            "🏋️ No problem — say **generate a home dumbbell workout** and I'll build one.",
            "Dumbbell + bodyweight covers everything: presses, rows, goblet squats, RDLs, lunges, planks. Progress by adding reps first, then load."), "kind": "programming"}
    if "beginner" in q:
        return {"reply": parts(
            "🌱 Beginner blueprint: 3 days/week full body — squat pattern, push, pull, hinge, carry. 2-3 sets of 8-12, leave 2 reps in the tank.",
            "Consistency beats intensity for the first 8 weeks. Ask for a generated plan any time."), "kind": "programming"}
    if "not progressing" in q or "plateau" in q or "stuck" in q:
        return {"reply": parts(
            f"📈 Looking at your last 30 days: **{len(_recent_sessions(db, user_id, 30))} sessions, {prs} PRs**.",
            "The usual suspects: (1) same weights for weeks — add 2.5kg or 1 rep, (2) sleep under 7h, (3) protein below target.",
            "Pick ONE lever this week and log everything; plateaus break under measurement."), "kind": "analysis"}
    if "workout today" in q or "what should i do today" in q or "train today" in q:
        return {"reply": daily_session_idea(user_id), "kind": "programming"}

    # --- default: personalized brief ---
    weakest = min(["Chest", "Back", "Shoulders", "Arms", "Legs", "Glutes", "Core"], key=lambda m: cov.get(m, 0))
    return {"reply": parts(
        f"👋 {streak}-day streak, {len(sessions)} sessions this week, {round(today['p'])}g protein so far.",
        f"Your week looks {'strong' if len(sessions)>=3 else 'light so far'} — **{weakest} has the least attention in the last 7 days**.",
        "Ask me for a workout, a meal idea, your protein, or say 'plan my week'."),
        "kind": "brief"}


def daily_session_idea(user_id: int) -> str:
    with connect() as db:
        cov = _muscle_coverage(db, user_id)
        s = get_settings(db, user_id)
    all_m = ["Chest", "Back", "Shoulders", "Arms", "Legs", "Glutes", "Core"]
    nxt = min(all_m, key=lambda m: cov.get(m, 0))
    idea = {"Chest": "a pressing day — bench or push-ups, 4 sets, then flys and triceps",
            "Back": "a pulling day — rows and pulldowns, 4 sets each, finish with biceps",
            "Legs": "a squat + hinge day — 4 hard sets each, walking lunges to finish",
            "Shoulders": "overhead press + lateral raises, easy on the ego, high on the pump",
            "Arms": "superset curls and pushdowns, 3 rounds, 60-90s rest",
            "Glutes": "hip thrusts + RDLs + glute bridges, 3 sets each",
            "Core": "planks, hanging knee raises and a walk — recovery-style day"}.get(nxt)
    rest = " You're also due a rest day soon if yesterday was heavy." if s.get("days_per_week", 4) >= 5 else ""
    return f"💡 Based on your week, **{idea}** fits best today.{rest} Log it and I'll track your volume."


# ---------------------------------------------------------------- workout generator

def generate_workout(user_id: int, params: dict) -> dict:
    goal = (params.get("goal") or "build muscle").lower()
    days = int(params.get("days_per_week") or 4)
    minutes = int(params.get("duration") or 45)
    equipment = (params.get("equipment") or "Full gym").lower()
    muscles = params.get("muscles") or []
    style = (params.get("style") or "strength").lower()
    experience = (params.get("experience") or "Intermediate").lower()
    harder = params.get("harder", False)
    easier = params.get("easier", False)

    with connect() as db:
        pool = [dict(r) for r in db.execute("SELECT * FROM exercises")]
    equip_ok = lambda e: (equipment in ("full gym", "gym") or e.lower() in ("bodyweight", equipment) or
                          (equipment == "home dumbbells" and e.lower() in ("dumbbell", "bodyweight")))

    focus = muscles or (["Chest", "Shoulders", "Arms"] if "push" in style else
                        ["Back", "Arms"] if "pull" in style else
                        ["Legs", "Glutes"] if "legs" in style else
                        ["Chest", "Back", "Legs", "Core"])
    n_main = max(2, min(6, minutes // 12))
    reps = (12, 15) if "endurance" in goal else (8, 12) if "muscle" in goal else (5, 8)
    rest = 60 if "fat" in goal else 90 if "muscle" in goal else 150
    if easier:
        reps, rest = (12, 15), 75
    if harder:
        reps, rest = (5, 8), 180

    plan, used = [], set()
    for m in focus:
        cands = [e for e in pool if e["muscle"] == m and equip_ok(e["equipment"]) and e["id"] not in used]
        cands.sort(key=lambda e: ("beginner" in experience and "Beginner" not in e["difficulty"], -e["met"]))
        for e in cands[:1 if len(focus) > 3 else 2]:
            used.add(e["id"])
            sets = 3 if len(focus) > 3 else 4
            plan.append({"exercise": e["name"], "muscle": m, "equipment": e["equipment"],
                         "sets": sets, "reps": f"{reps[0]}-{reps[1]}", "rest_s": rest,
                         "tempo": "2-0-2" if "endurance" in goal else "3-0-1",
                         "difficulty": e["difficulty"],
                         "tips": e["instructions"][:120] + ("…" if len(e["instructions"]) > 120 else ""),
                         "mistakes": e["mistakes"],
                         "alt": next((c["name"] for c in pool if c["muscle"] == m and c["id"] != e["id"] and equip_ok(c["equipment"])), "—")})
            if len(plan) >= n_main:
                break
        if len(plan) >= n_main:
            break
    est = round(minutes * (6.5 if "cardio" in str(plan).lower() else 5.5) * (1.1 if harder else 1.0))
    return {"title": f"{'Home ' if equipment=='home dumbbells' else ''}{'Easier ' if easier else 'Harder ' if harder else ''}{focus[0]} focus · {minutes} min",
            "params": params, "items": plan, "est_kcal": est,
            "note": "Generated from your equipment and goal — replace any exercise you like."}


# ---------------------------------------------------------------- meal analysis

def analyze_meal(desc: str, grams: float = 250) -> dict:
    """Estimate nutrition from a text description using the foods DB. Labeled estimates."""
    d = (desc or "").lower()
    with connect() as db:
        foods = [dict(r) for r in db.execute("SELECT * FROM foods")]
    hits = []
    seen = set()
    for f in foods:
        key = f["name"].split(" (")[0].lower()
        if key and key in d and key not in seen:
            hits.append(f); seen.add(key)
    if not hits:  # token match: "chicken rice bowl" -> chicken, rice
        for f in foods:
            for word in f["name"].split(" (")[0].lower().split():
                if len(word) > 3 and word in d and f["id"] not in seen:
                    hits.append(f); seen.add(f["id"])
                    break
        hits = hits[:3]
    if not hits:
        return {"title": None, "items": [], "totals": {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0},
                "note": "Could not match that to the food database — describe it differently (e.g. 'grilled chicken with rice') or add it manually.",
                "matched": False}
    matched = [f["name"] for f in hits]
    per = grams / 100.0 / len(hits)
    items = [{"food": f["name"], "grams": round(grams / len(hits)),
              "kcal": round(f["kcal_per_100g"] * per),
              "protein_g": round(f["protein_g"] * per),
              "carbs_g": round(f["carbs_g"] * per),
              "fat_g": round(f["fat_g"] * per)} for f in hits]
    tot = {k: sum(i[k] for i in items) for k in ("kcal", "protein_g", "carbs_g", "fat_g")}
    return {"title": " + ".join(matched), "grams": grams, "items": items, "matched": True,
            "totals": {**tot, "fiber_g": round(sum(f["fiber_g"] * per for f in hits))},
            "note": "Rough estimates — tap Edit to fix the detected food or portion before adding to your diary."}


# ---------------------------------------------------------------- weekly review + buddy

def weekly_review(user_id: int) -> dict:
    with connect() as db:
        s = get_settings(db, user_id)
        sessions = _recent_sessions(db, user_id, 7)
        mins = sum(x["duration_min"] or 30 for x in sessions)
        kcal = sum(x["est_kcal"] for x in sessions)
        prs = db.execute("""SELECT count(*) c FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id
            WHERE ws.user_id=? AND wl.is_pr=1 AND ws.created_at>=date('now','-7 days')""", (user_id,)).fetchone()["c"]
        best = db.execute("""SELECT e.name, count(*) n FROM workout_logs wl
            JOIN workout_sessions ws ON ws.id=wl.session_id JOIN exercises e ON e.id=wl.exercise_id
            WHERE ws.user_id=? AND ws.created_at>=date('now','-7 days') GROUP BY e.name ORDER BY n DESC LIMIT 1""", (user_id,)).fetchone()
        days_logged = db.execute("SELECT count(DISTINCT logged_on) FROM nutrition_logs WHERE user_id=? AND logged_on>=date('now','-7 days')", (user_id,)).fetchone()[0]
        prot = [dict(r)["p"] for r in db.execute("SELECT SUM(protein_g) p FROM nutrition_logs WHERE user_id=? GROUP BY logged_on", (user_id,))]
        game = db.execute("SELECT streak FROM user_game_state WHERE user_id=?", (user_id,)).fetchone()
    consistency = round(len(sessions) / max(1, s.get("days_per_week") or 4) * 100)
    avg_prot = round(sum(prot) / len(prot)) if prot else 0
    review = {
        "week": f"Week of {date.today().strftime('%b %d')}",
        "workouts": len(sessions), "minutes": mins, "calories_burned": kcal,
        "avg_protein": avg_prot, "best_exercise": best["name"] if best else "—",
        "new_prs": prs, "days_meals_logged": days_logged,
        "consistency": min(100, consistency), "streak": game["streak"] if game else 0,
        "suggestions": [
            f"{'Great rhythm — add one mobility day to lock it in.' if len(sessions) >= 3 else 'Two more sessions this week hits your goal — schedule them now.'}",
            f"{'Protein averaged ' + str(avg_prot) + 'g — prep 2 protein-forward meals ahead on busy days.' if avg_prot and avg_prot < (s.get('protein_target') or 130) else 'Hydration is the easiest win — keep the bottle on your desk.'}",
            "Log one sentence after each session; your weekly review gets sharper every week.",
        ],
    }
    return review


def buddy_notes(user_id: int) -> list[str]:
    """Short motivational nudges from real data — encouraging, never judgmental."""
    with connect() as db:
        s = get_settings(db, user_id)
        sessions = _recent_sessions(db, user_id, 7)
        cov = _muscle_coverage(db, user_id)
        today = _macro_day(db, user_id)
        water = _water_day(db, user_id)
        game = db.execute("SELECT streak FROM user_game_state WHERE user_id=?", (user_id,)).fetchone()
    notes = []
    streak = game["streak"] if game else 0
    if streak:
        notes.append(f"🔥 {streak}-day streak. Momentum is a real thing — protect it with one more session this week.")
    target = s.get("days_per_week") or 4
    left = target - len(sessions)
    if left > 0:
        notes.append(f"You're **{left} workout{'s' if left > 1 else ''}** away from your weekly goal. Book them like meetings.")
    elif left <= 0:
        notes.append("Weekly goal complete — recovery is part of training now. Stretch, walk, sleep. 💚")
    legs = cov.get("Legs", 0) + cov.get("Glutes", 0)
    if len(sessions) >= 2 and legs == 0:
        notes.append("You haven't trained legs this week. Two words: leg. day. 🦵")
    pt = s.get("protein_target") or 140
    if today["p"] < pt * 0.5:
        notes.append(f"Protein is at {round(today['p'])}g of {pt}g — a shake or paneer bowl closes the gap tonight.")
    if water < (s.get("water_target_ml") or 2500) * 0.5:
        notes.append(f"💧 {round(water/1000, 1)}L of water so far. Another bottle before evening puts you on target.")
    if not notes:
        notes.append("Everything is on track. Ask me for a workout and let's keep the streak alive. ⚡")
    return notes[:4]


# ---------------------------------------------------------------- goals + fit match

def goal_plan(user_id: int, goal_text: str) -> dict:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*kg", (goal_text or "").lower())
    amount = float(m.group(1)) if m else None
    with connect() as db:
        s = get_settings(db, user_id)
    qt = (goal_text or "").lower()
    lose = "lose" in qt or "weight" in qt and "gain" not in qt or (amount or 0) < 0 and "gain" not in qt
    if "gain" in qt or "muscle" in qt:
        lose = False
    amount = abs(amount) if amount else (4 if lose else 2)
    if lose:
        weeks = max(4, round(amount / 0.5))          # 0.5 kg/week — safe, sustainable
        rate = "0.5 kg per week"
        kcal = (targets_from_profile(s)["kcal_target"] - 400)
        training = "3-4 strength sessions (keep the muscle) + 2 easy cardio days + 8k steps daily"
    else:
        weeks = max(6, round(amount / 0.25))
        rate = "0.25-0.5 kg per week (lean gain)"
        kcal = (targets_from_profile(s)["kcal_target"] + 250)
        training = "4 progressive strength days, add 2.5kg or 1 rep per week on your main lifts"
    milestones = [f"Week {w}: {'-' if lose else '+'}round({amount * w / weeks}, 1) kg · check waist/progress photo" for w in range(2, weeks + 1, max(2, weeks // 4))]
    return {"goal": goal_text or ("Lose weight" if lose else "Gain muscle"),
            "weeks": weeks, "rate": rate, "kcal_target": kcal,
            "protein_target": round(1.8 * (s.get("weight_kg") or 70)),
            "training": training,
            "recovery": "7-9h sleep, one full rest day, and a deload week every 6-8 weeks.",
            "milestones": milestones,
            "note": "Estimates for guidance — never below 1200 kcal/day, and adjust to how you feel and perform."}


def fit_match(user_id: int, limit: int = 6) -> list[dict]:
    """Compatibility from goal overlap, schedule, sport and activity level."""
    with connect() as db:
        me = db.execute("""SELECT u.*,p.availability FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=?""", (user_id,)).fetchone()
        if not me:
            return []
        others = db.execute("""SELECT u.id,u.name,u.username,u.city,u.fitness_level,u.fitness_goal,u.favorite_activity,u.preferred_time,
            g.xp,g.streak, p.bio FROM users u JOIN user_game_state g ON g.user_id=u.id
            LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id<>? ORDER BY g.xp DESC""", (user_id,)).fetchall()
        blocked = {r["blocked_id"] for r in db.execute("SELECT blocked_id FROM blocks WHERE blocker_id=?", (user_id,))}
        items = []
        for o in others:
            if o["id"] in blocked:
                continue
            score = 62
            reasons = []
            if o["fitness_goal"] == me["fitness_goal"]:
                score += 14; reasons.append(f"Both chasing {o['fitness_goal'].lower()}")
            if o["favorite_activity"] == me["favorite_activity"]:
                score += 12; reasons.append(f"You both love {o['favorite_activity']}")
            if o["preferred_time"] == me["preferred_time"]:
                score += 8; reasons.append("Same training window")
            if o["city"] == me["city"]:
                score += 4; reasons.append("Nearby")
            if o["fitness_level"] == me["fitness_level"]:
                score += 5; reasons.append("Similar experience")
            score = min(97, score)
            items.append({"id": o["id"], "name": o["name"], "username": o["username"], "photo": f"img/p{1 + (o['id'] % 12)}.jpg",
                          "score": score, "activity": o["favorite_activity"], "fitnessLevel": o["fitness_level"],
                          "preferredTime": o["preferred_time"], "streak": o["streak"], "xp": o["xp"],
                          "reasons": reasons or ["Active in your city"]})
        return sorted(items, key=lambda x: -x["score"])[:limit]
