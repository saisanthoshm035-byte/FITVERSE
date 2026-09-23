# FITVERSE — Persistent Storage & Deployment Guide

## What was the problem?

Render's free tier has an **ephemeral disk**: every redeploy or spin-down wipes
`fitverse.db` (the SQLite file), and the old code kept logins in an in-memory
Python dictionary, which died with every restart. Result: users were logged out
and their data vanished.

## What is fixed (already done, live in the code)

1. **Logins now survive restarts.** Sessions are stored in a real `sessions`
   database table (30-day expiry, hashed-free random tokens, real logout that
   revokes the token server-side). A server restart, redeploy or Render
   spin-down no longer signs anyone out.
2. **Onboarding saves for real.** The "Generate My Plan" step now guarantees
   the user's settings row exists before saving, so calorie/protein targets
   persist for brand-new accounts (previously the plan flashed and vanished).
3. **All data still goes through one database layer.** Nothing else changed —
   same APIs, same UI, same features.

## The one thing you should do: give Render a real database

If you do nothing, the app still works, **but on Render the SQLite file is
wiped on every redeploy** (that is a Render free-tier limitation, not a bug).
Local data on your PC is safe. To make data permanent on Render, connect the
free Turso database (~5 minutes, no credit card):

1. Go to **https://turso.tech** → sign up free.
2. Create a database (any name, e.g. `fitverse`), location closest to you.
3. In the database page open **Connect** and copy:
   - the **URL** — looks like `libsql://fitverse-yourorg.turso.io`
   - create a **token** and copy it.
4. On **Render**: your `fitverse` service → **Environment** → add:
   - `FITVERSE_DB_URL` = the libsql:// URL
   - `FITVERSE_DB_TOKEN` = the token
5. Save → wait for the redeploy to go **Live**.

That's it. FITVERSE automatically detects the remote database and stores
everything there (users, sessions, posts, messages, workouts, nutrition…).
No other configuration is needed, and the app runs unchanged with zero
new dependencies.

**First deploy on a fresh Turso database:** the schema is created
automatically at boot. Your existing demo data on your PC does **not** transfer
(it stays in your local `fitverse.db`); users simply sign up fresh on the live
site, and from then on everything they do is permanent.

## Verifying it's working

- Open `https://your-render-url/api/health` — it reports
  `"database": "libsql-remote"` when the remote DB is active
  (`"sqlite"` = local file mode, e.g. on your PC).
- Log in, note your name/targets, wait for Render to redeploy or spin down,
  log back in — your account and data are still there.
- Log out → your token is revoked server-side (the old token cannot be reused).

## Security notes

- Passwords are hashed (PBKDF2, 120k iterations) — never stored in plain text.
- Session tokens are random, 32-byte, stored server-side, expire in 30 days.
- Secrets live in `.env` (gitignored) / Render env vars — never in the repo.
- `.env.example` in the repo documents every supported variable.
