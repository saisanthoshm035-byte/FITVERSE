# FITVERSE — Persistent Storage & Deployment Guide

## What was the problem?

Render's free tier has an **ephemeral disk**: every redeploy or spin-down wipes
`fitverse.db` (the SQLite file), and the old code kept logins in an in-memory
Python dictionary, which died with every restart. Result: users were logged out
and their data vanished.

## What is fixed (already done, live in the code)

1. **Logins now survive restarts.** Sessions are stored in a real `sessions`
   database table (30-day expiry, random server-side tokens, real logout that
   revokes the token server-side). A server restart, redeploy or Render
   spin-down no longer signs anyone out.
2. **Onboarding saves for real.** The "Generate My Plan" step guarantees
   the user's settings row exists before saving, so calorie/protein targets
   persist for brand-new accounts.
3. **All data still goes through one database layer.** Same APIs, same UI,
   same features.

## REVERT (2026-09-28): SQLite is the default again — speed first

The Turso remote database made every query an HTTP round-trip, and the app
became noticeably slow. **FITVERSE now uses plain local SQLite everywhere,
even on Render**, unless remote mode is explicitly re-enabled.

### What you'll notice

- `https://fitverse-omdx.onrender.com/api/health` now reports
  `"database": "sqlite"` and the app is fast again (queries are in-process).
- **Render free-tier caveat (accepted "for now"):** the SQLite file lives on
  Render's ephemeral disk, so posts/accounts made on the live site are wiped
  on each redeploy or spin-down. Local data on your PC is unaffected.
- Everyone simply signs up / logs in again after a redeploy until we switch
  to a permanent database.

### How to re-enable Turso later (when you want persistence back)

The Turso code is untouched. Two steps on Render:

1. Keep/set `FITVERSE_DB_URL` (libsql://…) and `FITVERSE_DB_TOKEN`.
2. Add one variable: `FITVERSE_DB_MODE` = `remote`, then save.

Without that `remote` flag the URL/token are ignored and SQLite is used —
so leaving the old variables in place is harmless.

### Verifying it's working

- `GET /api/health` → `"database": "sqlite"` = fast local mode;
  `"libsql-remote"` = Turso active.

## Security notes

- Passwords are hashed (PBKDF2, 120k iterations) — never stored in plain text.
- Session tokens are random, 32-byte, stored server-side, expire in 30 days.
- Secrets live in `.env` (gitignored) / Render env vars — never in the repo.
- `.env.example` in the repo documents every supported variable.
