# FITVERSE — Fitness is more fun together

A social fitness platform: train, eat better, compete with friends, share
reels, and get AI coaching — all in one app.

## Run it (no terminal needed)

Double-click **`start-fitverse.cmd`**

- It opens your browser at `http://127.0.0.1:4173` automatically
- If the server crashes, press any key in the window and it restarts
- If it says "already running", your app is open — just use it

Requirements: [Python 3.10+](https://www.python.org/downloads/) (tick
*"Add Python to PATH"* during install). Everything else is built-in —
no packages to install.

**Demo login:** username `saikumar` · password `demo1234`
(or create your own account from the app)

## What's inside

| Area | What you get |
|---|---|
| **Feed** | Posts & Reels with 8 post types, photo/video uploads, likes, comments, follows |
| **Workout** | 28-exercise library, session logging, volume + calorie estimates, PR celebrations |
| **Nutrition** | Food diary, macro targets, AI meal estimates, water tracker |
| **AI Coach** | Personalized chat, workout generator, weekly recap with shareable card |
| **Social** | FIT MATCH partner matching, friend requests, communities, 1v1 challenges |
| **Progress** | Private measurements, weight trend chart, achievements, streaks |
| **Live** | Real-time chat over SSE with typing indicators |

## Tech

Python 3 standard library only (no pip installs) + SQLite + vanilla JS.
Database seeds itself on first run with a demo world of athletes,
communities, events and chats.

## Project layout

```
server.py            HTTP API + SSE + static server + DB schema/seeds
ai_service.py        FITVERSE AI (coach, generator, meal analysis, recap)
app.js / styles.css  The whole frontend (SPA)
fitverse.db          SQLite database (auto-created if missing)
uploads/             User photos/videos (gitignored, auto-created)
```
