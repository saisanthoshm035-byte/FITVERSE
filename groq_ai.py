"""FITVERSE × Groq — real LLM power for every AI surface.

WHY THIS MODULE EXISTS
----------------------
Groq (https://groq.com) serves open models like Llama 3.3 70B on LPUs with
sub-second responses and a free tier. Its API is OpenAI-compatible
(POST /openai/v1/chat/completions), so one tiny stdlib-only client powers:

- the AI coach chat (platform_service.chat_reply / ai_service.ai_coach)
- workout generation (ai_service.generate_workout — ordering + coaching notes)
- meal analysis (ai_service.analyze_meal — free-text → macro estimates)
- weekly review narrative (Progress page)
- daily tip (Home page morning brief)
- post composer assist (fit-post flow: hashtags, emoji, polish)

DESIGN RULES (unchanged from FITVERSE's honesty policy)
- The key NEVER enters the repo: it lives in .env (gitignored) / Render env vars.
- Every function returns None (or the caller's fallback) on ANY failure —
  the deterministic engines still answer, so the app never breaks.
- Timeouts are short (default 10s) so pages stay fast; one retry max.
- Safety: the model is instructed it is not a doctor, never prescribes
  extreme deficits (<1200 kcal), never invents user data.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

API_BASE = "https://api.groq.com/openai/v1"

# Groq rotates model lineups (llama-3.3 was retired), so we don't hardcode one.
# At boot/first use we ask /models which ids THIS key can use, then pick the
# best available from these preference lists. Env overrides always win.
MODEL_PREFERENCE = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
FAST_MODEL_PREFERENCE = ["openai/gpt-oss-20b", "llama-3.1-8b-instant", "openai/gpt-oss-120b"]
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_DEFAULT_FAST = "openai/gpt-oss-20b"

SAFETY_RULES = (
    "You are FITVERSE's AI fitness companion. You are NOT a doctor: never diagnose, "
    "never handle medical emergencies (defer to professionals). Never recommend extreme "
    "dieting (below 1200 kcal/day), dehydration, steroids or unsafe training. Use only "
    "the user data provided — never invent numbers about the user. Be warm, practical, concise."
)


# ---------------------------------------------------------------- status

_KEY_ALIASES = ("GROQ_API_KEY", "GROK_API_KEY", "GROQCLOUD_API_KEY", "GROQ_AI_KEY")


def _clean(val: str) -> str:
    """Trim whitespace and accidental wrapping quotes from a pasted key."""
    return (val or "").strip().strip('"').strip("'").strip()


def _api_key() -> str:
    """First non-empty value among GROQ_API_KEY and common misspellings (GROK_API_KEY, ...)."""
    for name in _KEY_ALIASES:
        val = _clean(os.environ.get(name))
        if val:
            return val
    return ""


def _key_source() -> str:
    """Name of the env var actually holding the key ('' when none) — for diagnostics only."""
    for name in _KEY_ALIASES:
        if _clean(os.environ.get(name)):
            return name
    return ""


def configured() -> bool:
    return bool(_api_key())


_model_cache: dict = {"ids": None, "at": 0.0}
_MODEL_TTL = 600.0  # re-check available models every 10 minutes at most


def available_models() -> list[str]:
    """Model ids this API key can actually use (cached). [] on any failure."""
    key = _api_key()
    if not key:
        return []
    if _model_cache["ids"] is not None and time.time() - _model_cache["at"] < _MODEL_TTL:
        return _model_cache["ids"]
    try:
        req = urllib.request.Request(f"{API_BASE}/models", headers={"Authorization": f"Bearer {key}", "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = sorted(m.get("id", "") for m in data.get("data", []))
        _model_cache["ids"] = ids
        _model_cache["at"] = time.time()
        return ids
    except Exception:
        return []  # keep any stale cache, else callers use static defaults


def _pick_available(prefs: list[str], fallback: str) -> str:
    ids = available_models()
    if not ids:
        return fallback
    for p in prefs:
        if p in ids:
            return p
    chat = [i for i in ids if "guard" not in i and "whisper" not in i and "orpheus" not in i and "safeguard" not in i]
    return chat[0] if chat else fallback


def model_name(fast: bool = False) -> str:
    override = (os.environ.get("GROQ_MODEL_FAST" if fast else "GROQ_MODEL") or "").strip()
    if override:
        return override
    return _pick_available(FAST_MODEL_PREFERENCE if fast else MODEL_PREFERENCE,
                           _DEFAULT_FAST if fast else _DEFAULT_MODEL)


def status() -> dict:
    """Honest capability report for /api/ai/status and the UI badge."""
    return {
        "provider": "groq",
        "configured": configured(),
        "env_var": _key_source() or None,
        "model": model_name(),
        "fast_model": model_name(fast=True),
        "surfaces": ["coach chat", "workout generator", "meal analyzer", "weekly review", "daily tip", "post assistant"],
        "note": "When Groq is unreachable, FITVERSE answers from its built-in deterministic engine — the app never breaks.",
    }


# ---------------------------------------------------------------- core client

_UA = "FITVERSE/5.0 (fitness-web-app)"  # Cloudflare rejects default Python-urllib UA


def _chat(messages: list[dict], max_tokens: int = 500, temperature: float = 0.6,
          fast: bool = False, json_mode: bool = False, timeout: int = 10) -> str | None:
    """One Groq chat completion. Returns None on any failure — never raises."""
    key = _api_key()
    if not (key and messages):
        return None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": _UA}
    body = {
        "model": model_name(fast),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if body["model"].startswith("openai/gpt-oss"):
        # gpt-oss are reasoning models: reasoning tokens come out of the budget.
        # Keep effort low and the budget practical, or answers come back empty.
        body["reasoning_effort"] = "low"
        body["max_tokens"] = max(max_tokens, 512)
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(2):  # one retry for transient 429/5xx/network
        req = urllib.request.Request(f"{API_BASE}/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            content = (content or "").strip()
            return content or None
        except urllib.error.HTTPError as e:
            if e.code == 404:  # model retired mid-flight — re-detect and retry once
                _model_cache["ids"], _model_cache["at"] = None, 0.0
                body["model"] = model_name(fast)
            elif e.code < 500 and e.code != 429:
                return None  # real API error (auth/bad request) — don't retry
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.4)
    return None


def _extract_json(text: str | None):
    """Parse JSON from a model reply, tolerating ```json fences and prose."""
    if not text:
        return None
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        s = m.group(1)
    else:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            s = s[start:end + 1]
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------- surfaces
# Each helper returns None when Groq is unavailable — callers fall back to the
# deterministic engine, so features keep working with zero configuration.

def coach_reply(context_line: str, history: list[dict], question: str,
                draft: str | None = None) -> str | None:
    """Chat reply for the AI coach. `draft` is the deterministic engine's answer —
    the model keeps its facts and makes it natural. Falls back to None."""
    sys = (SAFETY_RULES +
           f"\n\nThe user's real FITVERSE data right now: {context_line}"
           + ("\nA draft answer computed from their real data is provided — keep its facts "
              "and numbers exactly, rewrite for flow and add coaching detail. Under 180 words."
              if draft else "\nAnswer in under 180 words."))
    msgs = [{"role": "system", "content": sys}]
    for h in (history or [])[-8:]:
        role = "assistant" if h.get("role") == "coach" else "user"
        msgs.append({"role": role, "content": str(h.get("content", ""))[:800]})
    msgs.append({"role": "user", "content": question[:800]})
    return _chat(msgs, max_tokens=700, temperature=0.65)


def post_polish(text: str) -> dict | None:
    """Composer assistant: tidy a draft + relevant hashtags + emoji. JSON result."""
    obj = _extract_json(_chat([
        {"role": "system", "content":
            "You polish fitness-community posts. Return ONLY JSON: "
            '{"text": "<improved post, same meaning and language, <160 words, 0-2 tasteful emoji>", '
            '"hashtags": ["<3-6 lowercase relevant hashtags without #>"]}. '
            "Never invent achievements or numbers not in the draft."},
        {"role": "user", "content": f"Polish this post:\n{(text or '')[:1000]}"},
    ], max_tokens=300, temperature=0.5, fast=True, timeout=12))
    if not obj or not isinstance(obj.get("text"), str) or not obj["text"].strip():
        return None
    tags = [re.sub(r"[^a-z0-9]", "", str(t).lower().lstrip("#")) for t in (obj.get("hashtags") or [])]
    return {"text": obj["text"].strip()[:600], "hashtags": [t for t in tags if t][:6]}


def meal_parse(desc: str, grams: float) -> dict | None:
    """Free-text meal → per-item macro estimates (JSON). Labeled estimates by callers."""
    obj = _extract_json(_chat([
        {"role": "system", "content":
            "You estimate nutrition from meal descriptions. Return ONLY JSON: "
            '{"title": "<short meal name>", "items": [{"food": "<name>", "grams": <number>, '
            '"kcal": <int>, "protein_g": <number>, "carbs_g": <number>, "fat_g": <number>}], '
            '"note": "<one short caveat>"}. '
            f"The description is for about {round(grams)} g total unless it clearly states otherwise. "
            "Split the total across the detected items. Keep 1-5 items. Use round practical numbers."},
        {"role": "user", "content": (desc or "")[:400]},
    ], max_tokens=450, temperature=0.2))
    if not obj or not isinstance(obj.get("items"), list) or not obj["items"]:
        return None
    items = []
    for it in obj["items"][:5]:
        try:
            items.append({
                "food": str(it.get("food", "item"))[:60],
                "grams": round(float(it.get("grams") or grams / max(1, len(obj["items"])))),
                "kcal": round(float(it.get("kcal") or 0)),
                "protein_g": round(float(it.get("protein_g") or 0), 1),
                "carbs_g": round(float(it.get("carbs_g") or 0), 1),
                "fat_g": round(float(it.get("fat_g") or 0), 1),
            })
        except Exception:
            continue
    if not items:
        return None
    tot = {k: round(sum(i[k] for i in items), 1) for k in ("kcal", "protein_g", "carbs_g", "fat_g")}
    return {
        "title": str(obj.get("title") or desc[:60])[:80],
        "grams": round(grams), "items": items, "matched": True,
        "totals": {**tot, "fiber_g": 0},
        "note": str(obj.get("note") or "")[:140] or "AI estimates — tap Edit to fix any item before adding.",
        "engine": "groq",
    }


def workout_plan(pool: list[dict], params: dict) -> dict | None:
    """Pick + order exercises from the REAL exercise pool for the user's params.
    The pool comes from the database — the model chooses, it never invents."""
    slim = [{"id": e["id"], "name": e["name"], "muscle": e["muscle"], "equipment": e["equipment"],
             "difficulty": e["difficulty"], "tip": (e.get("instructions") or "")[:110]} for e in pool[:120]]
    obj = _extract_json(_chat([
        {"role": "system", "content":
            "You are an expert strength coach. From the given exercise pool ONLY (never invent exercises), "
            "build one workout. Return ONLY JSON: "
            '{"title": "<short title>", "note": "<1-2 sentence coaching note>", '
            '"items": [{"id": <pool id>, "sets": <int 2-5>, "reps": "<e.g. 8-12>", "rest_s": <int 45-180>}]}. '
            "Order: main compound first, isolation last. Respect the requested muscles, equipment, minutes "
            f"(~{max(3, int(params.get('duration') or 45) // 12)} main exercises), goal and experience. "
            "Do not exceed the pool."},
        {"role": "user", "content": json.dumps({"params": params, "pool": slim}, ensure_ascii=False)[:12000]},
    ], max_tokens=1000, temperature=0.4, timeout=14))
    if not obj or not isinstance(obj.get("items"), list) or not obj["items"]:
        return None
    by_id = {e["id"]: e for e in pool}
    items = []
    for it in obj["items"][:10]:
        try:
            e = by_id.get(int(it.get("id")))
        except Exception:
            e = None
        if not e:
            continue
        items.append({"exercise": e["name"], "muscle": e["muscle"], "equipment": e["equipment"],
                      "sets": max(2, min(5, int(it.get("sets") or 3))),
                      "reps": str(it.get("reps") or "8-12")[:12],
                      "rest_s": max(30, min(240, int(it.get("rest_s") or 90))),
                      "tempo": "2-0-2", "difficulty": e["difficulty"],
                      "tips": (e.get("instructions") or "")[:120] + ("…" if len(e.get("instructions") or "") > 120 else ""),
                      "mistakes": e.get("mistakes", ""),
                      "alt": ""})
    if not items:
        return None
    return {"title": str(obj.get("title") or "AI workout")[:80],
            "note": str(obj.get("note") or "")[:200] or "AI-designed from your real exercise library.",
            "items": items, "engine": "groq"}


def week_review(review: dict) -> str | None:
    """Progress page: turn the deterministic weekly review into a short narrative."""
    return _chat([
        {"role": "system", "content":
            "You write a warm 3-4 sentence weekly fitness review for a fitness app. "
            "Use ONLY the numbers provided (never invent data). Encourage, never shame; "
            "end with one concrete suggestion for next week. Plain text, max 80 words."},
        {"role": "user", "content": json.dumps(review, ensure_ascii=False, default=str)[:2500]},
    ], max_tokens=300, temperature=0.6, fast=True)


def daily_tip(context_line: str) -> str | None:
    """Home page: one personal tip from the user's real context."""
    return _chat([
        {"role": "system", "content":
            "You give ONE short daily fitness tip (1-2 sentences, max 40 words), personalized to the "
            "user data provided. Never invent data. General fitness advice only, not medical. "
            "Plain text — no greeting, no sign-off, at most one emoji."},
        {"role": "user", "content": context_line[:800]},
    ], max_tokens=160, temperature=0.8, fast=True)
