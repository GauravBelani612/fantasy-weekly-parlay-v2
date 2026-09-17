# Weekly Parlay

Your fantasy league's low scorer funds a parlay for next week's NFL games, and everyone
contributes one leg. This replaces the Google Form + spreadsheet: it works out who lost
from the Sleeper API, collects exactly one leg per person, and shows the whole board
before kickoff.

Multi-tenant — any league can sign in and use it, and you can belong to several.

## How a week works

```
Mon night   Week N finishes (ESPN reports every game FINAL)
Tue         Round opens. Lowest scorer in week N is on the hook.
            Everyone submits one leg for week N+1.
Wed         Reminder to anyone who hasn't submitted (inside 24h of the deadline)
Thu ~7pm    Legs lock, 60 min before the first week N+1 kickoff (configurable)
            The payer gets the final list by email
Thu 8:15pm  TNF kicks off
```

## Stack

| Piece | Choice |
|---|---|
| API | FastAPI + SQLAlchemy 2.0 async + Alembic |
| Web | React 19 + TypeScript + Vite + TanStack Query + Tailwind 4 |
| DB | SQLite locally, Neon Postgres in production |
| Auth | Google Identity Services → our own JWT session cookie |
| Data | Sleeper API (scores/rosters), ESPN (kickoff times, finality, box scores) |
| Legs | Claude reads free-text legs; graded against ESPN box scores |
| Notify | Resend email + Discord/Slack webhook |
| Cron | GitHub Actions → `POST /internal/tick` |

## Local setup

**Backend** (no Docker or Postgres needed — defaults to SQLite):

```bash
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # macOS/Linux
cp .env.example .env
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.local     # then set VITE_GOOGLE_CLIENT_ID
npm run dev                     # http://localhost:5173
```

**Google sign-in:** Google Cloud Console → APIs & Services → Credentials → *Create OAuth
client ID* → Web application. Add `http://localhost:5173` to **Authorized JavaScript
origins**. Put the client ID in both `backend/.env` (`GOOGLE_CLIENT_ID`) and
`frontend/.env.local` (`VITE_GOOGLE_CLIENT_ID`) — they must match or token verification fails.

## Verify the loser calculation against your real league

This is the most important correctness check in the project. The 2026 season has no scores
yet, so point it at last season and confirm the app would have picked the same person you
actually made pay:

```bash
cd backend
./.venv/Scripts/python.exe scripts/verify_league.py --username <your_sleeper_username> --season 2025
./.venv/Scripts/python.exe scripts/verify_league.py --league-id <id> --season 2025 --week 5
```

It prints every roster's score for the week, sorted, with the computed payer marked — no
database involved.

## Test a full round before the season starts

In the preseason `state/nfl` reports `week: 0`, so no week is final and the app correctly
opens nothing. To exercise the real flow, seed a round from a completed week — actual
Sleeper scores, actual payer, actual kickoff times:

```bash
cd backend

# open a round from last season's week 5, with other managers' legs filled in
./.venv/Scripts/python.exe scripts/seed_round.py \
    --sleeper-league-id <last_seasons_league_id> --week 5 --demo-legs

# same round, but already past the deadline
./.venv/Scripts/python.exe scripts/seed_round.py \
    --sleeper-league-id <id> --week 5 --lock-in -5

# remove every round and placeholder account it created
./.venv/Scripts/python.exe scripts/seed_round.py --clear
```

Find last season's league id from the `previous_league_id` field on your current league:
`curl https://api.sleeper.app/v1/league/<current_league_id>`.

`--demo-legs` gives unclaimed rosters placeholder accounts so they count as eligible, then
fills in most of their legs — two are left blank so the "still waiting on" list renders.
Your own roster is never pre-filled. Placeholder accounts all use the `@demo.invalid`
domain, which is how `--clear` finds them; they can never collide with a real sign-in.

## Troubleshooting

**"Failed to fetch" when you open a league.** The API isn't running. The page itself keeps
working for a while because React Query serves cached data, so the league *list* looks fine
and only the click-through fails — which reads like a frontend bug but never is. Check the
API first:

```bash
curl http://localhost:8000/health          # expect {"status":"ok"}
```

**`origin_mismatch` on the Google button.** The browser is on an origin that isn't
registered. Almost always the port: if 5173 was busy, Vite silently starts on 5174, and
Google treats that as a different app. Check Vite's startup banner for the real port, and
kill stray dev servers rather than registering more ports.

**Sign-in works but data never loads.** On Windows `localhost` can resolve to IPv6 `::1`
while uvicorn listens on IPv4 only. Set `VITE_API_BASE_URL=http://127.0.0.1:8000` to
sidestep it.

## Tests

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q     # 114 tests
cd frontend && npm run build                              # type-check + build
```

## Design notes

**Round state is derived, never stored as a flag.** `open` / `locked` is computed from
`now()` against `opens_at` / `locks_at` on every read. The cron job exists *only* to push
notifications. If it never fires — free-tier API asleep, scheduler flaky — the app is still
correct, you just don't get an email.

**A week is only scorable once ESPN says every game is FINAL.** Sleeper reports points
continuously, so without that gate the app would crown a "loser" halfway through Sunday.

**Ties are never broken automatically.** A tie for lowest is surfaced and the commissioner
decides who pays.

**`raw_text` is the permanent source of truth.** Legs are stored exactly as typed. Claude
reads each one into a separate `parsed` column (player or team, market, direction, line), so
a bad reading can never destroy what someone meant to bet. The board shows how every leg was
read, so a misreading gets noticed before kickoff rather than after grading.

**Legs grade themselves as games finish, the way a sportsbook settles -- minus pushes.**
League rule: every leg is a hit or a miss. "3+" is inclusive, but over and under are strict,
so "over 70" landing on exactly 70 is a miss, as is a spread covered by exactly the number or
a tied moneyline. Anytime TDs count rushing, receiving and return scores but never a
quarterback's passing TDs. One miss busts the parlay immediately. A player is only voided when ESPN ruled them out -- one merely
missing from a box score is left for a person, since that also describes a misread name.
Void is the only way a leg drops out of the parlay without busting it.

**A leg with no line can't be graded by any API.** "Jordan Love over passing yards" never
said over what, and ESPN has no player-prop lines to fall back on. The line gets set when the
payer places the bet, so the payer either records it (and it grades itself) or just marks the
leg hit or miss. Hand-set results are never touched by the grader.

**The grader never overturns a settled parlay; a person correcting a leg can.** Otherwise one
misgraded leg on Thursday would leave the parlay stuck at "busted" after every leg cashed.

**Sleeper linking is trust-based.** Sleeper has no OAuth for third-party apps, so ownership
cannot be proven. A `UNIQUE` on `sleeper_user_id` enforces first-claim-wins, and the claim
endpoint is rate limited. Note that an unknown username returns **HTTP 200 with a `null`
body**, not a 404 — handled explicitly in `app/integrations/sleeper.py`.

**Members who haven't signed up still count.** Every Sleeper roster gets a `league_members`
row so the lowest-score calculation sees the whole league; only rows with a linked account
can submit a leg. If the payer hasn't signed up, the round still works and says so.

## Deploying (free tier)

1. **Neon** — create a Postgres project. Use the connection string as
   `postgresql+asyncpg://...` and replace `?sslmode=require` with `?ssl=require`.
   Both halves matter: asyncpg rejects `sslmode` outright as an unknown kwarg, but with
   *no* ssl argument at all it negotiates `prefer`, falls back to plaintext, and Neon
   closes the connection with "connection is insecure". Only `ssl` is translated by the
   SQLAlchemy asyncpg dialect. Drop `channel_binding` entirely.
2. **Render** — `render.yaml` is a blueprint. Set `DATABASE_URL`, `GOOGLE_CLIENT_ID`,
   `FRONTEND_ORIGIN`, `APP_URL`, and `ANTHROPIC_API_KEY`. Migrations run in the build
   command. Without the Anthropic key legs are never read, so nothing grades automatically
   -- the payer can still mark every leg by hand. Check how legs will be read first with
   `scripts/check_parse.py`.
3. **Vercel** — deploy `frontend/`. Set `VITE_API_BASE_URL` to the Render URL and
   `VITE_GOOGLE_CLIENT_ID`. Add the Vercel domain to the Google client's authorized origins.
4. **GitHub Actions** — add repo secrets `API_BASE_URL` and `INTERNAL_TICK_SECRET` (must
   match Render's). The workflow runs every 30 minutes.

Because the API and web app sit on different hosts, the session cookie is cross-site:
`COOKIE_SECURE=true` and `COOKIE_SAMESITE=none` are both required or the browser drops it.

## Roadmap

Built: Google auth, Sleeper linking, league import, loser detection, leg submission and
live board, email + Discord notifications, round history with result recording, leg reading
with Claude, automatic hit/miss grading against ESPN box scores, and parlay settlement with
a busted/cashed announcement.

Next: player and team icons (Sleeper CDN), per-leg odds via The Odds API, and combined
parlay odds.
