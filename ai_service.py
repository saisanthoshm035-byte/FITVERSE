"""FITVERSE AI service layer.

A clean seam for real AI models: every function returns data the UI can render.
Groq (GROQ_API_KEY) powers the heavy lifting wherever an LLM genuinely helps —
coach chat, workout design, meal parsing, weekly narrative — while personalized
deterministic rules over the user's real data remain the permanent fallback, so
nothing ever breaks when the API is unreachable or unconfigured.

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
    note = "Estimates from the Mifflin-St Jeor formula — adjust to how your body responds."
    diet = (s.get("diet_pref") or "").lower()
    if "indian" in diet:
        note += " Indian-style plates: roti/rice + dal + sabzi + curd — the split below already fits that pattern."
    if "vegetarian" in diet:
        note += " Vegetarian: paneer, dal, curd and soy cover your protein."
    return {
        "bmr": round(bmr), "tdee": round(tdee), "kcal_target": kcal,
        "protein_target": protein, "carbs_target": round(kcal * 0.45 / 4),
        "fat_target": round(kcal * 0.25 / 9),
        "estimate_note": note,
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


# ---------------------------------------------------------------- vitals + Indian diet

def _vitals(db, uid):
    """7-day averaged BP (systolic) + fasting sugar from daily_metrics (0/None if absent)."""
    row = db.execute(
        "SELECT AVG(blood_pressure) bp, AVG(blood_sugar) sg FROM daily_metrics "
        "WHERE user_id=? AND updated_at>=date('now','-7 days') AND (blood_pressure>0 OR blood_sugar>0)", (uid,)).fetchone()
    bp = round(row["bp"]) if row and row["bp"] else None
    sg = round(row["sg"]) if row and row["sg"] else None
    return bp, sg


def _ensure_exercises(db, specs: list[dict]) -> dict:
    """Make sure generic library items (yoga poses, cardio machines, home moves)
    exist in the shared exercises table so generated plans can be LOGGED —
    FITVERSE 6.1: yoga plans used to fail because poses weren't in the pool.
    Returns {name: id}. Idempotent (INSERT OR IGNORE)."""
    ids = {}
    for sp in specs:
        row = db.execute("SELECT id FROM exercises WHERE name=?", (sp["name"],)).fetchone()
        if row:
            ids[sp["name"]] = row["id"]
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO exercises (name,muscle,equipment,difficulty,instructions,mistakes,met) VALUES (?,?,?,?,?,?,?)",
            (sp["name"], sp.get("muscle", "Full Body"), sp.get("equipment", "Mat / bodyweight"),
             "Beginner", sp.get("instructions", ""), "", sp.get("met", 4.0)))
        if cur.lastrowid:
            ids[sp["name"]] = cur.lastrowid
        else:
            row2 = db.execute("SELECT id FROM exercises WHERE name=?", (sp["name"],)).fetchone()
            if row2: ids[sp["name"]] = row2["id"]
    return ids


def indian_diet_plan(uid: int, meal: str = "") -> dict:
    """Deterministic full-day Indian diet plan built from the user's REAL data:
    kcal/protein targets, diet preference (veg/non-veg), and — the FITVERSE 6.0
    part — blood pressure & fasting sugar averages. High BP → low-sodium swaps;
    high sugar → low-GI swaps and post-meal walks. Groq polishes when available."""
    with connect() as db:
        s = get_settings(db, uid)
        t = targets_from_profile(s)
        bp, sugar = _vitals(db, uid)
    kcal = t["kcal_target"]
    protein = t["protein_target"]
    diet = (s.get("diet_pref") or "balanced").lower()
    veg = "veg" in diet or "indian" in diet
    age = int(s.get("age") or 25)
    bp_high = bp is not None and bp >= 140
    sugar_high = sugar is not None and sugar >= 126
    split = {"Breakfast": 0.25, "Lunch": 0.35, "Snacks": 0.12, "Dinner": 0.28}
    items = []
    for m, share in split.items():
        mk = round(kcal * share / 10) * 10
        mp = round(protein * share)
        if m == "Breakfast":
            food = ("2 moong dal chillas + curd + 1 fruit" if veg else "2 egg-white omelette + 1 moong chilla + curd")
            if sugar_high: food += " · skip juice, whole fruit only (fiber slows glucose)"
        elif m == "Lunch":
            food = "2 roti + 1 katori dal + sabzi + big salad + curd" if veg else "2 roti + grilled fish/chicken + dal + sabzi + salad"
            if bp_high: food += " · low-salt dal & sabzi, no papad/pickle"
            if sugar_high: food += " · 1 roti instead of 2, extra salad"
        elif m == "Snacks":
            food = "roasted chana + buttermilk" if veg else "boiled eggs + buttermilk"
            if sugar_high: food += " · nuts instead of any sweet"
        else:
            food = "1-2 roti + paneer bhurji + sauteed veggies" if veg else "grilled chicken/fish + veggies + small roti"
            if bp_high: food += " · no added salt at dinner"
        items.append({"meal": m, "food": food, "kcal": mk, "protein_g": mp})
    flags = []
    if bp_high: flags.append("LOW-SODIUM")
    if sugar_high: flags.append("LOW-GI")
    if veg: flags.append("VEGETARIAN")
    flags.append("INDIAN")
    title = "Indian plate plan"
    if bp_high and sugar_high: title = "BP + sugar-friendly Indian plan"
    elif bp_high: title = "BP-friendly Indian plan"
    elif sugar_high: title = "Sugar-friendly Indian plan"
    elif veg: title = "Vegetarian Indian plan"
    note = (f"Built from YOUR numbers: ~{kcal} kcal / {protein}g protein target"
            + (f", 7-day BP {bp} systolic" if bp else "") + (f", fasting sugar {sugar} mg/dL" if sugar else "")
            + ". Estimates — adjust portions to hunger and keep your doctor's advice first.")
    plan = {"title": title, "flags": flags, "items": items, "note": note,
            "targets": {"kcal": kcal, "protein": protein}, "vitals": {"bp": bp, "sugar": sugar, "age": age or None}}
    # Groq refinement: same deterministic skeleton, natural Indian-food coaching.
    try:
        import groq_ai
        if groq_ai.configured():
            line = f"kcal={kcal} protein={protein} diet={'veg' if veg else 'nonveg'} bp={bp or 'na'} sugar={sugar or 'na'} age={age}"
            sys = ("You are an Indian sports-nutrition coach. From the given REAL targets and vitals, "
                   "return a compact one-day Indian meal plan: 4 meals with roti/dal/sabzi/paneer/curd "
                   "style foods, gram-level protein, low-salt if BP high, low-GI if sugar high. "
                   "Plain text: one line per meal 'Meal: food — kcal kcal'. Under 90 words. No diagnosis.")
            g = groq_ai._chat([{"role": "system", "content": sys}, {"role": "user", "content": line}], max_tokens=400, temperature=0.5, timeout=12)
            if g: plan["ai"] = g
    except Exception:
        pass
    return plan


# ---------------------------------------------------------------- coach

SAFETY = ("I'm not able to diagnose injuries or medical conditions. General guidance: stop the movement that "
          "causes pain, keep the area mobile within a pain-free range, and please check with a qualified "
          "healthcare professional before loading it again. 💚")


def ai_coach(user_id: int, message: str) -> dict:
    """Personalized coach reply. Groq first (facts from real data), deterministic fallback."""
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

    # --- FITVERSE 6.0: vitals (BP / fasting sugar) shape every answer ---
    bp_avg = sugar_avg = None
    try:
        with connect() as db:
            _v = db.execute("SELECT AVG(blood_pressure) bp, AVG(blood_sugar) sg FROM daily_metrics WHERE user_id=? AND updated_at>=date('now','-7 days') AND (blood_pressure>0 OR blood_sugar>0)", (user_id,)).fetchone()
        if _v:
            bp_avg = round(_v["bp"]) if _v["bp"] else None
            sugar_avg = round(_v["sg"]) if _v["sg"] else None
    except Exception:
        bp_avg = sugar_avg = None
    if any(k in q for k in ("blood pressure", " bp", "hypertension", "sugar", "diabetes", "bp")):
        bits = []
        if bp_avg:
            bits.append(f"🩺 Your week's averaged BP: **{bp_avg} systolic** — {'above the 140 line, keep your doctor in the loop' if bp_avg >= 140 else 'in a workable zone'}. Easy cardio 30 min most days, less added salt/pickles, and 4-7-8 breathing are the levers.")
        if sugar_avg:
            bits.append(f"🩸 Fasting sugar is averaging **{sugar_avg} mg/dL** — {'at or above the 126 line, please review it with your doctor' if sugar_avg >= 126 else 'reasonable'}. Post-meal walks and light resistance training pull glucose down best.")
        if not bits:
            bits.append("🩺 Log your BP and fasting sugar in Health Data (Daily metrics) — I'll track the trend and adapt your training and meals around it.")
        return {"reply": parts(*bits), "kind": "vitals"}
    if any(k in q for k in ("indian diet", "indian meal", "desi diet", "indian food plan")):
        plan = indian_diet_plan(user_id)
        lines = [f"🍛 **{plan['title']}**"]
        for it in plan["items"]:
            lines.append(f"• **{it['meal']}:** {it['food']} — {it['kcal']} kcal")
        lines.append(plan["note"])
        return {"reply": parts(*lines), "kind": "nutrition"}

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
            f"🍽️ You've logged **{round(today['kcal'])}/{t['kcal_target']} kcal** today (protein {round(today['p'])}g).",
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

    # --- Groq: natural, personalized answer over the deterministic draft ---
    # The deterministic branches above already answered topical questions with
    # real data; anything reaching here gets the LLM treatment when available.
    try:
        import groq_ai
        if groq_ai.configured():
            _draft = parts(
                f"👋 {streak}-day streak, {len(sessions)} sessions this week, {round(today['p'])}g protein so far.",
                f"Your week looks {'strong' if len(sessions)>=3 else 'light so far'} — **{weakest} has the least attention in the last 7 days**.",
                "Ask me for a workout, a meal idea, your protein, or say 'plan my week'.")
            _ctx = f"streak {streak}d | {len(sessions)} sessions this week | today {round(today['kcal'])} kcal, {round(today['p'])}g protein | goal {s.get('goal') or 'general fitness'} | {prs} PRs in 30d"
            if bp_avg: _ctx += f" | avg_bp_systolic={bp_avg}"
            if sugar_avg: _ctx += f" | avg_fasting_sugar={sugar_avg}"
            _reply = groq_ai.coach_reply(_ctx, [], q, draft=_draft)
            if _reply:
                return {"reply": _reply, "kind": "ai"}
    except Exception:
        pass
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
        s = get_settings(db, user_id)
        bp, sugar = _vitals(db, user_id)
        age = int(s.get("age") or 0)

    # --- FITVERSE 6.0 easy modes: cardio / home / yoga (low-impact, senior-safe) ---
    # Any of these styles, or a vitals flag, converts the plan to gentle work:
    # higher reps, short rests, no barbell maxing, Beginner candidates first.
    easy_mode = style in ("cardio", "home", "yoga") or params.get("easy")
    vitals_gentle = (bp is not None and bp >= 140) or (sugar is not None and sugar >= 126) or (age and age >= 60)
    if style == "yoga":
        names = ["Sun Salutation Flow", "Downward Dog Hold", "Warrior II Pose", "Seated Forward Bend",
                 "Cat-Cow Stretch", "Child's Pose Hold", "Bridge Pose", "Legs Up the Wall"]
        have = {e["name"]: e for e in pool}
        with connect() as db:
            ids = _ensure_exercises(db, [{"name": n, "muscle": "Full Body", "equipment": "Mat / bodyweight", "met": 3.0,
                                          "instructions": "Move slowly with the breath; never stretch into pain."} for n in names])
        items = []
        for i, n in enumerate(names[: max(4, min(8, minutes // 7))]):
            e = have.get(n)
            items.append({"exercise": n, "muscle": "Full Body" if "Flow" in n or "Pose" in n else "Core",
                          "equipment": "Mat / bodyweight", "sets": 2 if i % 2 else 3, "reps": "5 breaths" if i % 2 else "45-60s",
                          "rest_s": 30, "tempo": "slow flow", "difficulty": "Beginner",
                          "tips": "Breathe through the nose; never stretch into pain.", "mistakes": "Locking joints or holding the breath.",
                          "alt": "—", "id": e["id"] if e else ids.get(n)})
        est = round(minutes * 3.5)
        return {"title": f"Gentle yoga flow · {minutes} min", "params": params, "items": [i for i in items if i["id"]] or items,
                "est_kcal": est, "engine": "deterministic",
                "note": "Low-impact flow — great for BP, joint health and recovery. Move within a pain-free range."}
    if easy_mode:
        if style == "cardio":
            focus_m = ["Cardio"]
            n_main = max(3, min(6, minutes // 8))
            cands = [e for e in pool if e["muscle"] == "Cardio" and e["id"] not in {}]
            cands.sort(key=lambda e: ("Beginner" not in e["difficulty"], e["met"] or 0))
            # If the library has almost no cardio, add the universal starters.
            if len(cands) < 3:
                with connect() as db:
                    extra_ids = _ensure_exercises(db, [
                        {"name": "Brisk Walk", "muscle": "Cardio", "equipment": "Bodyweight", "met": 4.3,
                         "instructions": "Steady, conversational pace. Great for BP and blood sugar."},
                        {"name": "Stationary Bike — Easy Spin", "muscle": "Cardio", "equipment": "Machine", "met": 5.0,
                         "instructions": "Light resistance, high cadence, nasal breathing."},
                        {"name": "March in Place", "muscle": "Cardio", "equipment": "Bodyweight", "met": 3.8,
                         "instructions": "Home-friendly low-impact cardio."}])
                have2 = {e["name"]: e for e in pool}
                for n, eid in extra_ids.items():
                    if n not in {c["name"] for c in cands}:
                        cands.append({**have2.get(n, {}), "name": n, "muscle": "Cardio", "equipment": "Bodyweight",
                                      "difficulty": "Beginner", "met": 4.0, "instructions": "", "mistakes": "", "id": eid})
            cands.sort(key=lambda e: ("Beginner" not in e.get("difficulty", "Beginner"), e.get("met") or 0))
            items = []
            for e in cands:
                items.append({"exercise": e["name"], "muscle": "Cardio", "equipment": e["equipment"], "sets": 1,
                              "reps": f"{max(8, minutes // max(1, len(cands[:n_main])))} min", "rest_s": 60,
                              "tempo": "conversational pace", "difficulty": e["difficulty"],
                              "tips": (e.get("instructions") or "")[:120], "mistakes": e.get("mistakes", ""), "alt": "—", "id": e["id"]})
                if len(items) >= n_main: break
            est = round(minutes * 6.0)
            return {"title": f"Easy cardio · {minutes} min", "params": params, "items": items, "est_kcal": est,
                    "engine": "deterministic",
                    "note": ("Heart-friendly steady state — you should be able to talk while moving."
                             + (" BP-aware: keep intensity easy and breathe nasally." if bp is not None and bp >= 140 else ""))}
        # home: bodyweight strength
        muscles = muscles or ["Chest", "Legs", "Core", "Cardio"]
        equipment = "bodyweight"
        reps = (12, 15)
        rest = 60
    else:
        if sugar is not None and sugar >= 110 and not muscles:
            muscles = ["Cardio", "Legs", "Core"]  # light resistance + cardio help glucose control

    # --- Groq: let the model design the session from the REAL exercise pool ---
    try:
        import groq_ai
        if groq_ai.configured() and not params.get("fast"):
            gp = {"goal": goal, "days_per_week": days, "duration": minutes, "equipment": equipment,
                  "muscles": muscles, "style": style, "experience": experience,
                  "harder": bool(harder), "easier": bool(easier)}
            g = groq_ai.workout_plan(pool, gp)
            if g and g.get("items"):
                est = round(minutes * (6.5 if "cardio" in str(g["items"]).lower() else 5.5) * (1.1 if harder else 1.0))
                g.update({"params": params, "est_kcal": est,
                          "note": (g.get("note") or "") + " — AI-designed from your equipment and goal."})
                return g
    except Exception:
        pass

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
    if easy_mode or vitals_gentle:
        reps, rest = (12, 15), 75  # gentle defaults: BP/sugar-aware or senior users

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
            "note": "Generated from your equipment and goal — replace any exercise you like.",
            "engine": "deterministic"}


# ---------------------------------------------------------------- meal analysis

def analyze_meal(desc: str, grams: float = 250) -> dict:
    """Estimate nutrition from a text description. Groq parses free text first;
    the foods-DB matcher remains the offline fallback. Labeled estimates."""
    try:
        import groq_ai
        if groq_ai.configured():
            g = groq_ai.meal_parse(desc, grams)
            if g:
                return g
    except Exception:
        pass
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
    # --- Groq: short personalized narrative over the real numbers ---
    ai_narrative = None
    try:
        import groq_ai
        if groq_ai.configured():
            ai_narrative = groq_ai.week_review({
                "workouts": len(sessions), "minutes": mins, "calories_burned": kcal,
                "avg_protein": avg_prot, "new_prs": prs, "days_meals_logged": days_logged,
                "consistency": min(100, consistency), "streak": game["streak"] if game else 0,
                "goal": s.get("goal"), "best_exercise": best["name"] if best else None})
    except Exception:
        ai_narrative = None
    review = {
        "week": f"Week of {date.today().strftime('%b %d')}",
        "workouts": len(sessions), "minutes": mins, "calories_burned": kcal,
        "avg_protein": avg_prot, "best_exercise": best["name"] if best else "—",
        "new_prs": prs, "days_meals_logged": days_logged,
        "consistency": min(100, consistency), "streak": game["streak"] if game else 0,
        "ai_summary": ai_narrative,  # Groq narrative; UI falls back to the suggestion list
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
    """Compatibility from goal overlap, schedule, sport, activity level and onboarding prefs."""
    with connect() as db:
        me = db.execute("""SELECT u.*,p.availability,s.goal AS ob_goal,s.equipment AS ob_equipment,s.diet_pref AS ob_diet,s.activity_level AS ob_activity,s.days_per_week AS ob_days FROM users u LEFT JOIN profiles p ON p.user_id=u.id LEFT JOIN user_settings s ON s.user_id=u.id WHERE u.id=?""", (user_id,)).fetchone()
        if not me:
            return []
        others = db.execute("""SELECT u.id,u.name,u.username,u.city,u.fitness_level,u.fitness_goal,u.favorite_activity,u.preferred_time,
            g.xp,g.streak, p.bio, s.goal AS ob_goal, s.equipment AS ob_equipment, s.diet_pref AS ob_diet, s.activity_level AS ob_activity, s.days_per_week AS ob_days
            FROM users u JOIN user_game_state g ON g.user_id=u.id
            LEFT JOIN profiles p ON p.user_id=u.id LEFT JOIN user_settings s ON s.user_id=u.id WHERE u.id<>? ORDER BY g.xp DESC""", (user_id,)).fetchall()
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
            # Onboarding-pref compatibility (user_settings) — tuned by the setup wizard
            def _same(a, b):
                return bool(a and b and str(a).strip().lower() == str(b).strip().lower())
            if _same(me["ob_goal"], o["ob_goal"]):
                score += 7; reasons.append(f"Same onboarding goal · {o['ob_goal']}")
            try:
                my_days = int(me["ob_days"] or 0); ot_days = int(o["ob_days"] or 0)
            except (TypeError, ValueError):
                my_days = ot_days = 0
            if my_days and ot_days and abs(my_days - ot_days) <= 1:
                score += 6; reasons.append(f"Both train ~{min(my_days, ot_days)}x a week")
            if _same(me["ob_equipment"], o["ob_equipment"]):
                score += 5; reasons.append(f"Both train with {str(o['ob_equipment']).lower()}")
            if _same(me["ob_diet"], o["ob_diet"]):
                score += 3; reasons.append("Matching diet style")
            lv = {"low": 0, "moderate": 1, "high": 2}
            if me["ob_activity"] in lv and o["ob_activity"] in lv and me["ob_activity"] != o["ob_activity"] and abs(lv[me["ob_activity"]] - lv[o["ob_activity"]]) == 1:
                score += 2; reasons.append("Similar daily activity")
            score = min(97, score)
            items.append({"id": o["id"], "name": o["name"], "username": o["username"], "photo": f"img/p{1 + (o['id'] % 12)}.jpg",
                          "score": score, "activity": o["favorite_activity"], "fitnessLevel": o["fitness_level"],
                          "preferredTime": o["preferred_time"], "streak": o["streak"], "xp": o["xp"],
                          "reasons": reasons or ["Active in your city"]})
        return sorted(items, key=lambda x: -x["score"])[:limit]
