# FITVERSE MVP

This build uses a self-contained Python standard-library API server with a SQLite database. No package installation is required.

## Run the full application

1. Double-click `start-fitverse.cmd` (or run `python server.py` from this folder).
2. Open `http://127.0.0.1:4173` in a browser.

The database is created and seeded automatically as `fitverse.db` on first run. The demo user is **Sai Kumar**. API authentication is available at `/api/auth/login` with `saikumar` / `demo1234`; the UI defaults to the demo session so the presentation flow starts immediately.

## Persistence implemented

- User/profile and game-state data
- Friendships
- Activities and participants
- Challenges and XP awards
- Communities and memberships
- Events, bookings, and QR-ticket payloads
- Posts, likes, comments, conversations, and messages
- Notifications, businesses, and moderation reports
