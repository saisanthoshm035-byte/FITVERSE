"""FITVERSE AI engine v5 — composes answers instead of replaying canned text.

Design (all deterministic, zero external services, zero new dependencies):
- Topic scoring: weights question words across 12 fitness topics instead of an
  if-chain, so any phrasing lands on the right specialist.
- Sub-intent detection: extracts constraints the user actually stated (days/week,
  minutes/session, equipment, muscle, goal, experience) and threads them into
  the answer — plus remembers them for later follow-ups in the conversation.
- Fact layer: every answer is assembled from the user's REAL data (sessions,
  PRs, muscle coverage, nutrition, hydration, streak, DNA, mission) so two
  users never get the same reply and one user's reply changes as their data
  changes.
- Variation: rotating phrasings and topic-relevant optional lines so repeated
  questions read fresh instead of identical.
- Generic responder: for questions with no fitness topic, it still answers from
  context (personal brief, capability intro, or conversational bridging) —
  never a fixed "I can only answer fitness questions" wall.
- Optional LLM seam (FITVERSE_LLM_API/KEY) still wins when configured.

Safety: emergency/injury gates stay in platform_service.chat_reply, which runs
BEFORE this engine. Nothing here diagnoses, prescribes, or invents user data.
"""
from __future__ import annotations

import re
import random
import sqlite3
from datetime import datetime, timedelta

from server import connect

try:
    import intelligence
except Exception:  # pragma: no cover
    intelligence = None

try:
    import ai_service
except Exception:  # pragma: no cover
    ai_service = None


# ---------------------------------------------------------------- settings/targets

def _settings(db, uid):
    if ai_service:
        return ai_service.get_settings(db, uid)
    row = db.execute("SELECT * FROM user_settings WHERE user_id=?", (uid,)).fetchone()
    return dict(row) if row else {}


def _targets(s):
    if ai_service:
        return ai_service.targets_from_profile(s)
    return {"kcal_target": 2200, "protein_target": 130, "tdee": 2400}


# ---------------------------------------------------------------- fact layer

def collect_facts(uid: int) -> dict:
    """One pass over the DB for every fact any answer might need."""
    with connect() as db:
        s = _settings(db, uid)
        t = _targets(s)
        week = db.execute(
            "SELECT count(*) c, COALESCE(sum(duration_min),0) m, COALESCE(sum(est_kcal),0) k "
            "FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-7 days')", (uid,)).fetchone()
        month = db.execute(
            "SELECT count(*) c FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-30 days')", (uid,)).fetchone()
        last = db.execute(
            "SELECT title, created_at, est_kcal FROM workout_sessions WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        yesterday = db.execute(
            "SELECT title FROM workout_sessions WHERE user_id=? AND created_at>=date('now','-2 days') ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        prs30 = db.execute(
            "SELECT count(*) FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id "
            "WHERE ws.user_id=? AND wl.is_pr=1 AND ws.created_at>=date('now','-30 days')", (uid,)).fetchone()[0]
        cov_rows = db.execute(
            "SELECT e.muscle, count(*) n FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id "
            "JOIN exercises e ON e.id=wl.exercise_id WHERE ws.user_id=? AND ws.created_at>=date('now','-7 days') "
            "GROUP BY e.muscle", (uid,)).fetchall()
        cov = {r["muscle"]: r["n"] for r in cov_rows}
        fav = db.execute(
            "SELECT e.name, count(*) n FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id "
            "JOIN exercises e ON e.id=wl.exercise_id WHERE ws.user_id=? GROUP BY e.name ORDER BY n DESC LIMIT 1", (uid,)).fetchone()
        today = db.execute(
            "SELECT COALESCE(sum(kcal),0) k, COALESCE(sum(protein_g),0) p, COALESCE(sum(carbs_g),0) c, COALESCE(sum(fat_g),0) f "
            "FROM nutrition_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()
        days_logged = db.execute(
            "SELECT count(DISTINCT logged_on) FROM nutrition_logs WHERE user_id=? AND logged_on>=date('now','-7 days')", (uid,)).fetchone()[0]
        water = db.execute(
            "SELECT COALESCE(sum(ml),0) FROM water_logs WHERE user_id=? AND logged_on=date('now')", (uid,)).fetchone()[0]
        game = db.execute("SELECT xp, streak FROM user_game_state WHERE user_id=?", (uid,)).fetchone()
        challenges = db.execute(
            "SELECT c.title FROM challenges c JOIN challenge_participants cp ON cp.challenge_id=c.id "
            "WHERE cp.user_id=? AND c.status='active' LIMIT 3", (uid,)).fetchall()
        heaviest = db.execute(
            "SELECT e.name, MAX(wl.weight) w FROM workout_logs wl JOIN workout_sessions ws ON ws.id=wl.session_id "
            "JOIN exercises e ON e.id=wl.exercise_id WHERE ws.user_id=? AND wl.weight>0 GROUP BY e.name ORDER BY w DESC LIMIT 3", (uid,)).fetchall()
        missions = []
        if intelligence:
            try:
                with_intelligence = intelligence.ensure_weekly_mission(db, uid)
                missions = [dict(with_intelligence)] if with_intelligence else []
            except Exception:
                missions = []
    dna = None
    if intelligence:
        try:
            dna = intelligence.fitness_dna(uid)
        except Exception:
            dna = None

    return {
        "settings": s, "targets": t,
        "week_sessions": week["c"], "week_minutes": week["m"], "week_kcal": week["k"],
        "month_sessions": month["c"],
        "last_workout": dict(last) if last else None,
        "yesterday_workout": yesterday["title"] if yesterday else None,
        "prs30": prs30,
        "coverage": cov,
        "favorite_exercise": {"name": fav["name"], "n": fav["n"]} if fav else None,
        "today_kcal": today["k"], "today_protein": today["p"], "today_carbs": today["c"], "today_fat": today["f"],
        "days_logged": days_logged,
        "water_ml": water,
        "streak": game["streak"] if game else 0, "xp": game["xp"] if game else 0,
        "active_challenges": [c["title"] for c in challenges],
        "heaviest": [{"name": r["name"], "w": r["w"]} for r in heaviest],
        "mission": missions[0] if missions else None,
        "dna": dna,
        "goal": (s.get("goal") or "general fitness") if isinstance(s, dict) else "general fitness",
        "days_per_week": (s.get("days_per_week") or 4) if isinstance(s, dict) else 4,
    }


# ---------------------------------------------------------------- constraint extraction

_NUM = r"(\d+)"

def extract_constraints(q: str) -> dict:
    """Pull concrete constraints out of the question so answers adapt to THEM."""
    ql = q.lower()
    c: dict = {}
    m = re.search(_NUM + r"\s*(?:x|times|days|sessions?)\s*(?:a|per)?\s*week", ql)
    if m:
        c["days"] = int(m.group(1))
    elif re.search(r"(?:only|just|max)\s+(\d+)\s*(?:day|time)", ql):
        c["days"] = int(re.search(r"(?:only|just|max)\s+(\d+)\s*(?:day|time)", ql).group(1))
    m = re.search(_NUM + r"\s*(?:minutes|min|mins|hrs?|hours?)\b", ql)
    if m:
        n = int(m.group(1))
        c["minutes"] = n * 60 if ("hr" in ql[m.start():m.end()]) else n
    if re.search(r"no gym|without (?:a )?gym|no equipment|home workout|bodyweight only|dumbbell", ql):
        c["equipment"] = "dumbbell" if "dumbbell" in ql else "bodyweight"
    if re.search(r"travell?ing|hotel|on the road", ql):
        c["equipment"] = "bodyweight"
        c["travel"] = True
    muscles = {"chest": "Chest", "back": "Back", "leg": "Legs", "legs": "Legs", "shoulder": "Shoulders",
               "shoulders": "Shoulders", "arm": "Arms", "bicep": "Arms", "tricep": "Arms", "glute": "Glutes",
               "core": "Core", "abs": "Core", "calve": "Legs", "calf": "Legs"}
    for k, v in muscles.items():
        if re.search(r"\b" + k, ql):
            c["muscle"] = v
            break
    if re.search(r"lose (?:weight|fat)|cut(?:ting)?\b|get lean|slim", ql):
        c["goal"] = "fat loss"
    elif re.search(r"(?:build|gain|put on) (?:muscle|mass|size)|bulk|get bigger|bigger arms|bigger chest", ql):
        c["goal"] = "muscle gain"
    elif re.search(r"endurance|stamina|5k|10k|half marathon|marathon|run faster", ql):
        c["goal"] = "endurance"
    if re.search(r"beginner|new to|just started|first time", ql):
        c["experience"] = "beginner"
    elif re.search(r"advanced|years of training|experienced", ql):
        c["experience"] = "advanced"
    return c


# ---------------------------------------------------------------- variation helpers

_rng = random.Random()


def _pick(seq, salt=0):
    seq = list(seq)
    return seq[(salt + _rng.randrange(len(seq))) % len(seq)]


def _weakest(f: dict) -> str:
    all_m = ["Chest", "Back", "Shoulders", "Arms", "Legs", "Glutes", "Core"]
    return min(all_m, key=lambda m: f["coverage"].get(m, 0))


def _strongest(f: dict) -> str:
    all_m = ["Chest", "Back", "Shoulders", "Arms", "Legs", "Glutes", "Core"]
    return max(all_m, key=lambda m: f["coverage"].get(m, 0))


def _ctx_openers(f: dict) -> list[str]:
    """Real-data openers, varied by what's actually true."""
    out = []
    if f["streak"]:
        out.append(f"🔥 {f['streak']}-day streak going")
    if f["week_sessions"]:
        out.append(f"{f['week_sessions']} session{'s' if f['week_sessions'] != 1 else ''} logged this week")
    if f["prs30"]:
        out.append(f"{f['prs30']} PR{'s' if f['prs30'] != 1 else ''} in the last month")
    if f["days_logged"]:
        out.append(f"food logged on {f['days_logged']} of the last 7 days")
    return out


def _maybe_extra(qtopic_salt: int) -> list[str]:
    """Small rotating topic-relevant extras so repeated asks don't read identical."""
    return _pick([
        ["Want it as a saved plan? The Workout generator builds it exercise by exercise."],
        ["Log it after and I'll watch your volume week over week."],
        ["Ask me to adjust anything — days, equipment, or intensity — and I'll rework it."],
        ["Small consistent beats perfect sporadic — that's the whole trick."],
        [],
    ], qtopic_salt)


# ---------------------------------------------------------------- topic specialists

def _t_plan(f: dict, c: dict, salt: int) -> tuple[str, str]:
    days = c.get("days") or f["days_per_week"] or 4
    goal = c.get("goal") or f["goal"]
    if days <= 2:
        split = "two full-body days — squat pattern, push, pull, hinge, core in each"
    elif days == 3:
        split = "full body Mon/Wed/Fri, or push/pull/legs if you prefer rotating focus"
    elif days == 4:
        split = "upper/lower ×2 — the sweet spot for most people"
    elif days == 5:
        split = "push/pull/legs/upper/lower"
    else:
        split = "push/pull/legs ×2 with one day deliberately easy"
    goal_line = {"fat loss": "Keep 2–3 strength days in — muscle is what keeps the fat off.",
                 "muscle gain": "10–20 hard sets per muscle per week, and eat ~200–300 kcal above maintenance.",
                 "endurance": "Keep hard running days away from heavy leg days, easy runs genuinely easy.",
                 "general fitness": "Each session: a push, a pull, a squat/hinge, and core — that covers everything."}.get(
        goal, "Each session: a push, a pull, a squat/hinge, and core.")
    if c.get("equipment") == "dumbbell":
        goal_line += " Dumbbells only? DB presses, rows, goblet squats and RDLs cover every slot in that split."
    elif c.get("equipment") == "bodyweight":
        goal_line += " No equipment? Push-ups, split squats, pike presses and table rows cover every slot — progress via reps and tempo."
    ops = _ctx_openers(f)
    open_line = f"Okay — {', '.join(ops[:2])}. " if ops else ""
    return (f"{open_line}For **{days} days a week** chasing {goal}, I'd run: **{split}**.\n\n"
            f"{goal_line}\n\n"
            "Two rules that make any split work: hit every muscle ~2× weekly, and leave 1–2 reps in the tank on most sets — "
            "the plan you repeat is the plan that works.", "plan")


def _t_workout(f: dict, c: dict, salt: int) -> tuple[str, str]:
    muscle = c.get("muscle") or _weakest(f)
    equip = c.get("equipment") or ""
    mins = c.get("minutes") or 45
    main = {
        "Chest": ("pressing day", "Bench or push-ups 4×6–10, incline press 3×8–12, flys 2×12–15, triceps pushdowns 3×10–12"),
        "Back": ("pulling day", "Rows 4×6–10, lat pulldowns 3×8–12, face pulls 3×15, curls 3×10–12"),
        "Legs": ("squat + hinge day", "Squats 4×5–8, RDLs 3×8–10, lunges 2×10/leg, calf raises 3×12–15"),
        "Shoulders": ("overhead day", "Overhead press 4×6–10, lateral raises 3×12–15, rear-delt flys 3×15, rope pushdowns 3×12"),
        "Arms": ("arm day", "Curls 3×8–12 superset with rope pushdowns 3×10–12, hammer curls 3×10–12, 60–90s rests"),
        "Glutes": ("glute day", "Hip thrusts 4×8–12, RDLs 3×8–10, glute bridges 2×15, abduction 3×15"),
        "Core": ("core day", "Planks 3×45s, hanging knee raises 3×10–12, dead bugs 3×10/side, pallof press 3×12/side"),
    }.get(muscle)
    label, detail = main or ("full-body day", "Squats 3×8, bench/push-ups 3×8–10, rows 3×10, plank 3×45s")
    if equip == "bodyweight":
        detail = {"Chest": "Push-ups 4×10–15 (feet elevated when easy), pike push-ups 3×8–12, dips on chairs 3×10",
                  "Back": "Doorframe rows or towel rows 4×10, superman pulls 3×12, backpack rows 3×12/arm",
                  "Legs": "Squats 4×15, split squats 3×10/leg, glute bridges 3×15, wall sit 3×40s",
                  }.get(muscle, "Squats 4×15, push-ups 3×12, split squats 3×10/leg, plank 3×45s — 3 rounds, minimal rest")
        label = f"bodyweight {label}"
    if equip == "dumbbell":
        detail = {"Chest": "DB bench 4×8–12, DB flys 3×12, push-ups to failure",
                  "Back": "DB rows 4×10/arm, DB pullover 3×12, reverse flys 3×15",
                  "Legs": "Goblet squats 4×10–12, DB RDLs 3×10, lunges 3×10/leg",
                  }.get(muscle, "Goblet squats 4×10, DB bench 3×10, DB rows 3×10/arm, plank 3×45s")
        label = f"dumbbell {label}"
    ops = _ctx_openers(f)
    if ops:
        opener = _pick(["Alright", "Got you", "Here you go"], salt)
        open_line = opener + " — " + ops[0] + ". "
    else:
        open_line = ""
    weakest_note = " (it's also your least-trained area this week — good pick)" if muscle == _weakest(f) else ""
    if mins < 45:
        time_line = "Trim it to the first two lifts if " + str(mins) + " minutes is all you've got."
    else:
        time_line = "Cap it at " + str(mins) + " minutes and keep the first lift heavy."
    return (open_line + "Today: **a " + label + "**" + weakest_note + ".\n\n" + detail + ". "
            "Rest 60–90s between sets, warm up 5 minutes first. "
            + time_line,
            "workout")


def _t_progressive_overload(f: dict, c: dict, salt: int) -> tuple[str, str]:
    lifts = ", ".join(f"{h['name']} at {h['w']}kg" for h in f["heaviest"][:2]) if f["heaviest"] else None
    return ("📈 Progressive overload = asking a little more of your body most weeks. It counts if you: add 1 rep at the same "
            "weight, add 2.5kg when you hit the top of the rep range, add a set, slow the negative, or cut rest at the same output.\n\n"
            + (f"Your current bests to beat: {lifts}. " if lifts else "Log your lifts so I can track your bests. ")
            + "Beat ONE number per session, not every session — most weeks is what matters.", "concept")


def _t_sets_reps(f: dict, c: dict, salt: int) -> tuple[str, str]:
    goal = c.get("goal") or f["goal"]
    if "loss" in goal:
        return ("🔢 For fat loss: 3–4 sets of 8–15 reps, resting 60–75s — keep the weights honest so you keep muscle. "
                "Finish with 10 minutes of intervals or a brisk walk. Total weekly volume matters more than any single magic number.", "concept")
    if "muscle" in goal or "gain" in goal:
        return ("🔢 For muscle: 3–4 sets of 6–12 reps per exercise, 1–2 reps from failure, 90s rests. "
                "10–20 hard sets per muscle per week, spread over 2+ sessions. Compounds first, isolation after.", "concept")
    return ("🔢 By goal — **Strength:** 3–6 sets of 3–6, long rests. **Muscle:** 3–4 sets of 6–12, 1–2 reps shy of failure. "
            "**Endurance:** 2–3 sets of 12–20+, short rests. Most people live happily in the 6–12 range.", "concept")


def _t_form(f: dict, c: dict, salt: int) -> tuple[str, str]:
    muscle = c.get("muscle") or ""
    specifics = {
        "Chest": "**Bench/press:** shoulder blades pinched and tucked, bar to lower chest, wrists stacked over elbows, feet planted. Film from the side — it's the fastest coach.",
        "Back": "**Rows/pulls:** lead with the elbow, squeeze the shoulder blade at the end, no torso swing. If you feel it mostly in your arms, the weight's too heavy.",
        "Legs": "**Squat:** brace like you're about to be tapped on the stomach, knees tracking over toes, sit between your hips, drive through mid-foot. Depth to parallel or your best pain-free range.",
        "Shoulders": "**Overhead press:** squeeze glutes, ribs down, press slightly back so the bar ends over your ears, not in front.",
        "Glutes": "**Hip thrust:** chin tucked, full lockout squeeze for a beat; drive through heels.",
    }.get(muscle)
    return ("🏋 Universal form rules: brace hard, control the negative (2–3s), stop the set when technique breaks — not breath. "
            + (specifics + " " if specifics else "")
            + "One light technique set before each working set pays for itself within a week.", "concept")


def _t_nutrition(f: dict, c: dict, salt: int) -> tuple[str, str]:
    t = f["targets"]
    tp = f["today_protein"]
    tk = f["today_kcal"]
    pt = t.get("protein_target") or 130
    kt = t.get("kcal_target") or 2200
    if c.get("goal") == "muscle gain" or "muscle" in str(f["goal"]):
        lead = (_pick(["💪 To build muscle you need a small surplus (~200–300 kcal over maintenance) and protein you actually hit daily. ",
                       "💪 Muscle is built in the kitchen too: a small surplus plus daily protein you actually hit. "], salt)
                + f"Today you're at **{round(tk)} of {kt} kcal** and **{round(tp)} of {pt}g protein**. ")
        food = _pick(["Close gaps easily: a whey scoop (+24g protein), 100g paneer (+18g), or rice + dal at dinner. "
                      "Put protein in every meal and the totals take care of themselves.",
                      "Easy closes: 150g chicken breast (~46g), 2 eggs + milk at breakfast, or a whey shake when the day ran away from you."], salt)
    elif c.get("goal") == "fat loss":
        lead = (f"🔥 For fat loss, today you're at **{round(tk)} of {kt} kcal**. A deficit of 300–500 kcal is the sweet spot — "
                "enough to move, not enough to wreck training. ")
        food = ("Plate formula: a palm of protein, a fist of veg, a cupped hand of carbs, a thumb of fats. "
                "Protein high = hunger managed = deficit survivable.")
    else:
        lead = (f"🍽 Today: **{round(tk)} of {kt} kcal**, protein **{round(tp)} of {pt}g**, water {round(f['water_ml']/1000,1)}L. "
                "For general fitness you don't need a perfect diet — a consistent one. ")
        food = ("Anchor every meal: protein palm, carb fist, fat thumb, veg freely. Log right after eating — "
                "your diary is what lets me give you real numbers instead of generic advice.")
    extra = _maybe_extra(salt)
    return (lead + "\n\n" + food + ((" " + extra[0]) if extra else ""), "nutrition")


def _t_protein(f: dict, c: dict, salt: int) -> tuple[str, str]:
    t = f["targets"]
    tp, pt = f["today_protein"], t.get("protein_target") or 130
    left = max(0, pt - tp)
    grams_left = f"**{round(left)}g left** ≈ " if left else "Target hit — nice. "
    ideas = "a whey scoop + 100g paneer, or 150g chicken breast" if left else "keep tomorrow identical"
    return (f"🥩 Protein: aim for roughly 1.6–2g per kg bodyweight — your working target is **{pt}g/day**. "
            f"Today: **{round(tp)}g**, {grams_left}{ideas}.\n\n"
            "Spread it over 3–4 meals; 30–40g per meal is the practical sweet spot for recovery.", "nutrition")


def _t_weight_loss(f: dict, c: dict, salt: int) -> tuple[str, str]:
    return ("🔥 Sustainable fat loss: 300–500 kcal daily deficit, protein high (keeps muscle, kills hunger), "
            "2–3 strength sessions weekly, and 8–10k steps a day — steps quietly do half the work.\n\n"
            "Rate check: 0.25–0.5 kg/week. Faster than that usually rebounds. "
            f"You've logged food on {f['days_logged']}/7 days — logging is the #1 predictor of success here, and you're {'on it' if f['days_logged'] >= 5 else 'close — keep going'}.",
            "nutrition")


def _t_cardio_endurance(f: dict, c: dict, salt: int) -> tuple[str, str]:
    return ("🏃 The 80/20 rule: ~80% of cardio at a genuinely easy, conversational pace, ~20% hard (intervals or tempo). "
            "Add ≤10% distance per week, and keep one long session weekly.\n\n"
            "Easy means easy — most people run their easy days too hard and their hard days too easy. "
            "Once you've logged a few distance sessions, your Cardio Analysis page shows real pace trends.", "concept")


def _t_recovery(f: dict, c: dict, salt: int) -> tuple[str, str]:
    y = f.get("yesterday_workout")
    return ("😴 Recovery is where adaptation actually happens: 7–9h sleep, protein spread through the day, "
            "easy movement on rest days (walks beat couch), and don't fear the rest day — it's part of the program.\n\n"
            + (f"You trained **{y}** recently" + (" — a lighter session today is the smart call." if f["week_sessions"] >= 4 else ".") if y else "No sessions in the last couple of days — recovery isn't the issue; booking the next session is.")
            + " Soreness past 3 days or performance dropping several sessions in a row = dial back.", "recovery")


def _t_motivation(f: dict, c: dict, salt: int) -> tuple[str, str]:
    m = f.get("mission")
    left = (m["target"] - m.get("progress", 0)) if m else None
    lines = [
        f"Small win first: commit to **5 minutes**. Starting is the only hard part — you'll usually finish.",
        f"Shrink the task, not the goal: today's minimum is a 10-minute walk or one main lift. Streaks ({f['streak']} 🔥) reward showing up, not perfection.",
    ]
    if left is not None and left > 0:
        lines.insert(0, f"🎯 Your mission **{m['title']}** needs just {left} more this week — that's a concrete, finishable thing.")
    return ("💯 " + " ".join(lines[:2]) + "\n\nYou don't need motivation, you need a smaller first step. Text a friend to train with you — "
            "social stakes double follow-through (FITVERSE challenges exist for exactly this).", "motivation")


def _t_challenges(f: dict, c: dict, salt: int) -> tuple[str, str]:
    if f["active_challenges"]:
        names = ", ".join(f["active_challenges"])
        return (f"🏆 You're already in: **{names}**. Log your progress after each session and I'll track it — "
                "challenges with a friend have roughly double the completion rate, so drag someone in. "
                "The Challenges page has accept/decline, progress bars and the Hall of Wins.", "social")
    return ("🏆 Challenges are the best consistency hack — social stakes beat willpower. "
            "Open the **Challenges page**, pick one ~20% beyond your current level, invite a friend, and log progress after each session. "
            f"Your streak is {f['streak']} 🔥 — a 7-day steps challenge would compound it.", "social")


def _t_beginner(f: dict, c: dict, salt: int) -> tuple[str, str]:
    return ("🌱 Beginner blueprint: 3 days a week, full body — squat pattern, push, pull, hinge, core. 2–3 sets of 8–12, "
            "always 2 reps in the tank. Walk daily, sleep 7–9h, protein at each meal.\n\n"
            "The beginner superpower: everything works at first. Do the boring simple version for 8 weeks before optimizing "
            "anything — consistency is the entire game, and your FITVERSE streak exists exactly for this.", "concept")


def _t_muscle_gain(f: dict, c: dict, salt: int) -> tuple[str, str]:
    ops = _ctx_openers(f)
    open_line = ("💪 " + (ops[0] + " — good base. " if ops else ""))
    return (open_line + "Muscle = progressive overload (reps or weight up most weeks) × enough volume (10–20 hard sets/muscle/week) × "
            "a small surplus with 1.6–2.2g/kg protein.\n\n"
            "Split: push/pull/legs or upper/lower, 3–5 days. 6–12 reps for most lifts. "
            + ({"dumbbell": "Dumbbells are plenty — DB presses, rows, goblet squats and RDLs cover every compound. ",
                "bodyweight": "No equipment is no blocker — push-ups, pike presses, split squats and table rows progress for months. "}.get(c.get("equipment"), "")
               if isinstance(c, dict) else "")
            + (f"You're at {f['week_sessions']} sessions this week — lock 3+ consistently and progress compounds." if f["week_sessions"] < 3
               else f"{f['week_sessions']} sessions this week — volume's there; make sure protein and sleep keep pace."), "concept")


def _t_sleep(f: dict, c: dict, salt: int) -> tuple[str, str]:
    return ("🛌 Sleep is the strongest legal performance enhancer: 7–9 hours. Same bed/wake time daily beats total hours; "
            "dark + cool room; caffeine before ~2pm; screens dimmed in the last hour.\n\n"
            "Training hard on repeated 5-hour nights is where injuries live — if sleep is compromised, cut volume, not form.", "recovery")


def _t_water(f: dict, c: dict, salt: int) -> tuple[str, str]:
    t = f["targets"]
    wt = t.get("water_target_ml") or 2500
    return (f"💧 Hydration: ~{round(wt/1000,1)}L/day, more on sweaty days. You're at **{round(f['water_ml']/1000,1)}L** today. "
            "Practical checks: pale-yellow urine, 500ml in the hour before training, sip during sessions over 45 minutes. "
            "Every glass you log in Nutrition shows up here — easy win.", "nutrition")


def _t_mission(f: dict, c: dict, salt: int) -> tuple[str, str]:
    m = f.get("mission")
    if not m:
        return ("🎯 Weekly missions spawn every Monday from your Fitness DNA — open the Home page and your current one is at the top. "
                "Complete it for XP that feeds your team in the Fitness War.", "mission")
    left = max(0, m["target"] - m.get("progress", 0))
    return (f"🎯 Your active mission: **{m['title']}** — {m.get('description','')}. "
            f"Progress: {m.get('progress', 0)}/{m['target']} ({left} to go), +{m['reward_xp']} XP when you finish. "
            "Log a workout and I track it automatically.", "mission")


def _t_dna(f: dict, c: dict, salt: int) -> tuple[str, str]:
    d = f.get("dna")
    if not d:
        return ("🧬 Your Fitness DNA page computes your personality, scores and focus from your real logs — open it from the sidebar. "
                "The more you log, the sharper it gets.", "dna")
    top3 = ", ".join(f"{k.capitalize()} {v}" for k, v in sorted(d["scores"].items(), key=lambda kv: -kv[1])[:3])
    return (f"🧬 Your Fitness DNA: **{d['personality']}**. Top scores: {top3}. Current focus: {d['focus']}.\n\n"
            "It recomputes from every logged workout — consistency literally reshapes your DNA.", "dna")


def _t_plateau(f: dict, c: dict, salt: int) -> tuple[str, str]:
    w = _weakest(f)
    return (f"📈 Last 30 days: **{f['month_sessions']} sessions, {f['prs30']} PRs**. "
            "Plateau suspects, in order of likelihood: (1) same weights for weeks — add 2.5kg or 1 rep when you hit the top of the range, "
            "(2) sleep under 7h, (3) protein under target, (4) too much sudden volume.\n\n"
            f"Pick ONE lever this week and log everything — plateaus break under measurement. "
            f"Also: your {w} has the least attention recently; that's often where the easy wins hide.", "analysis")


def _t_today(f: dict, c: dict, salt: int) -> tuple[str, str]:
    return _t_workout(f, c, salt)


TOPICS = {
    "muscle_gain": (r"(?:build|gain|put on).{0,12}(?:muscle|mass|size)|\bbulk|hypertrophy|get (?:bigger|swole)|more muscle", 3.2, _t_muscle_gain),
    "weight_loss": (r"lose (?:weight|fat)|fat loss|weight loss|\bcut(?:ting)?\b|get lean|shred|slim down|burn fat", 3.2, _t_weight_loss),
    "protein": (r"\bprotein\b|protein (?:shake|intake|source)", 2.6, _t_protein),
    "water": (r"hydrat|\bwater\b|drink more|\bglasses\b", 2.4, _t_water),
    "nutrition": (r"\beat\b|\bmeal\b|\bdiet\b|\bfood\b|nutrition|calorie|kcal|carb|\bfat\b(?! loss)|\bsugar\b|breakfast|lunch|dinner|supper|supplement|\bcreatine\b|\bwhey\b", 2.0, _t_nutrition),
    "sets_reps": (r"\bsets?\b|\breps?\b|how many (?:reps|sets)|rep range|volume", 2.4, _t_sets_reps),
    "progressive_overload": (r"progressive overload|how (?:do i|to) get stronger|get stronger|add weight|lift heavier", 2.6, _t_progressive_overload),
    "plateau": (r"plateau|stuck|not (?:improving|progressing)|no progress|stalled|why am i not", 2.8, _t_plateau),
    "form": (r"\bform\b|technique|how (?:do i|to) (?:do|perform)|posture|\bsquat\b|\bdeadlift\b|\bbench\b|overhead press|properly", 2.2, _t_form),
    "plan": (r"\bplan\b|\bsplit\b|routine|program(?:me)?|schedule|weekly|per week|days a week|workout plan", 2.4, _t_plan),
    "challenges": (r"challenge|compete|leaderboard|bet|versus|\bvs\b|compete with", 2.4, _t_challenges),
    "mission": (r"\bmission\b|operation|weekly goal\b|quest", 2.6, _t_mission),
    "dna": (r"fitness dna|\bdna\b|personality|what (?:kind|type) of (?:athlete|trainer)", 2.6, _t_dna),
    "cardio": (r"\bcardio\b|endurance|stamina|run faster|\b5k\b|\b10k\b|marathon|jogging|cycling for (?:fitness|cardio)|interval", 2.4, _t_cardio_endurance),
    "recovery": (r"recovery|rest day|\bsore\b|soreness|\bdoms\b|\btired\b|fatigue|overtrain|burnout|deload", 2.6, _t_recovery),
    "sleep": (r"\bsleep\b|insomnia|bedtime|sleep quality", 2.8, _t_sleep),
    "motivation": (r"motivat|\blazy\b|don'?t feel like|can'?t be bothered|unmotivated|give up|procrastinat|discipline|willpower|consistency|how do i stay", 2.4, _t_motivation),
    "beginner": (r"beginner|just started|new to (?:fitness|gym|working out)|where do i (?:start|begin)|first time (?:at|in) (?:the )?gym|start working out", 2.8, _t_beginner),
    "workout": (r"workout|exercise(?:s)? for|\btrain\b|training|what should i do|session|gym (?:today|session)|home workout|bodyweight|dumbbell|abs|\bcore\b|\barm\b|\bchest\b|\bback\b|\bleg\b|glute|shoulder", 1.8, _t_workout),
}

_COMPILED = [(name, re.compile(rx), w, fn) for name, (rx, w, fn) in TOPICS.items()]


def pick_topics(q: str) -> list[tuple[str, float]]:
    ql = q.lower()
    scored = []
    for name, rx, weight, fn in _COMPILED:
        m = rx.search(ql)
        if m:
            scored.append((name, weight + min(len(m.group(0)), 12) / 48.0))
    # eating about a goal ("what should I eat to build muscle") -> nutrition specialist,
    # which is goal-aware via constraints
    if any(n == "nutrition" for n, _ in scored) and re.search(r"\b(?:eat|meal|food|diet)\b", ql):
        scored = [(n, w + (1.6 if n == "nutrition" else 0)) for n, w in scored]
    scored.sort(key=lambda x: -x[1])
    return scored


# ---------------------------------------------------------------- generic responder

_GREET_RX = re.compile(r"^\s*(hi|hello|hey|yo|sup|hii+)\b")
_THANKS_RX = re.compile(r"\b(thanks|thank you|thx|ty\b|appreciate)")
_WHO_RX = re.compile(r"who are you|what are you|your name|what can you do|help me|what do you do")
_FEELING_RX = re.compile(r"how are you|what'?s up|\bwassup\b|good (?:morning|evening|afternoon)")
_META_NEG = re.compile(r"you (?:don'?t|do not) (?:understand|get it)|that'?s (?:wrong|not right)|useless|bad answer|not helpful")
_YES_RX = re.compile(r"^\s*(yes|yeah|yep|sure|ok(?:ay)?|do it|please do|go ahead)\b")


def _generic_reply(q: str, f: dict, salt: int, history: list, last_topic: str | None,
                   c: dict | None = None) -> tuple[str, str] | None:
    """Answers for questions that carry no fitness topic — still personal, never canned."""
    ql = q.lower().strip()
    ops = _ctx_openers(f)
    c = c or {}

    if _GREET_RX.match(ql) and len(ql.split()) <= 4:
        greet = _pick(["Hey!", "Hello!", "Hey hey 👋"], salt)
        personal = f" {f['streak']}-day streak looking good." if f["streak"] else ""
        return (f"{greet}{personal} What are we working on — training, food, or a plan?", "smalltalk")

    if _THANKS_RX.search(ql) and len(ql.split()) <= 5:
        return (_pick(["Anytime 💪", "That's what I'm here for.", "Go get it 💚"], salt), "smalltalk")

    if _WHO_RX.search(ql):
        return ("I'm FITVERSE's AI coach — I answer from **your** real data: workouts, nutrition, hydration, streaks, "
                "challenges and your Fitness DNA. Training plans, exercise form, meal guidance, recovery, motivation, "
                "challenges — ask me anything fitness, and ask follow-ups; I remember what you've told me in this chat.", "smalltalk")

    if _FEELING_RX.search(ql) and len(ql.split()) <= 5:
        line = f"{ops[0].capitalize()} if you're curious" if ops else "Ready when you are."
        return (_pick(["All good and ready to coach 💪", "Running on clean data and good vibes 😄"], salt)
                + f" {line} What's on the agenda?", "smalltalk")

    if _META_NEG.search(ql):
        return ("Fair — let me try harder. Tell me the goal and the constraint in one line "
                "(e.g. \"gain muscle, 3 days a week, dumbbells only\") and I'll give you a specific, no-fluff answer.", "smalltalk")

    # Short follow-ups ("yes", "ok do it", "and tomorrow?") after a real topic
    if last_topic and len(ql.split()) <= 5 and (_YES_RX.match(ql) or "tomorrow" in ql or "and after" in ql):
        fn = next((f2 for name, w, f2 in [(n, w, fn) for n, rx, w, fn in _COMPILED] if name == last_topic), None)
        if fn:
            extra_salt = salt + 7
            text, kind = fn(f, {}, extra_salt)
            return (f"Then here's the next step on that:\n\n{text}", kind)

    # Nothing matched at all: a personal brief IS the answer
    ack = ""
    if c.get("minutes"):
        ack = f"Noted — **{c['minutes']} minutes a day**. I'll factor that into everything from here. "
    elif c.get("days"):
        ack = f"Noted — **{c['days']} days a week**. I'll factor that into everything from here. "
    elif c.get("equipment"):
        ack = f"Noted — training {_pick(['with dumbbells', 'bodyweight only'], salt)}. I'll factor that in. "
    weakest = _weakest(f)
    brief_ops = ", ".join(ops[:2]) if ops else "no sessions logged yet this week"
    return (ack + f"Here's where you stand: {brief_ops}. Goal on file: **{f['goal']}**.\n\n"
            f"Your {_strongest(f)} is the most trained area recently; **{weakest}** could use attention. "
            "Ask me anything specific — a workout, what to eat, why you're stuck, a weekly plan — and I'll answer from your data, "
            "or just tell me your goal in one line and I'll take it from there.", "brief")


# ---------------------------------------------------------------- entry point

def composed_reply(uid: int, message: str, history: list | None = None,
                   remembered: dict | None = None) -> tuple[str, str, dict]:
    """Return (reply_text, kind, newly_stated_constraints) for conversation memory."""
    q = (message or "").strip()
    f = collect_facts(uid)
    if remembered:
        f.update({k: v for k, v in remembered.items() if k in ("days", "minutes", "equipment", "muscle", "goal", "experience")})
    c = extract_constraints(q)
    # thread conversation constraints: explicit now > remembered > defaults
    for k in ("days", "minutes", "equipment", "muscle", "goal", "experience"):
        if k not in c and remembered and k in remembered:
            c[k] = remembered[k]
    c_new = dict(c)
    for k in list(c_new):
        if k not in extract_constraints(q):
            del c_new[k]

    topics = pick_topics(q)
    last_topic = None
    if history:
        for h in reversed(history):
            if h.get("role") == "coach" and h.get("kind"):
                last_topic = h["kind"]
                break

    if not topics:
        r = _generic_reply(q, f, 0, history or [], last_topic, c_new)
        if r:
            mem = {k: v for k, v in c.items() if k in ("days", "minutes", "equipment", "muscle", "goal", "experience")}
            return r[0], r[1], mem
        topics = [("workout", 1.0)]

    name = topics[0][0]
    fn = next(fn for n, rx, w, fn in _COMPILED if n == name)
    text, kind = fn(f, c, len(q))  # salt varies with the question so phrasing rotates
    new_mem = {k: v for k, v in c.items() if k in ("days", "minutes", "equipment", "muscle", "goal", "experience")}
    return text, kind, new_mem
