# AGENTS.md

This repository is a full-stack fantasy football app with a FastAPI backend and a React/Vite frontend. Keep changes scoped to the correct side of the app and follow the project’s local-first setup conventions.

## Repository layout

- Backend application code: `backend/app/`
- Backend tests: `backend/tests/`
- Database schema and migrations: `backend/alembic/`
- Frontend app: `frontend/src/`
- Project overview and setup notes: [README.md](README.md)
- Python dependency and lint/test configuration: [backend/pyproject.toml](backend/pyproject.toml)
- Frontend scripts and dependencies: [frontend/package.json](frontend/package.json)

## Working conventions

- Prefer the existing architecture: API routes in `backend/app/routers/`, services in `backend/app/services/`, integrations in `backend/app/integrations/`, and schema/domain types in `backend/app/models.py` and `backend/app/schemas.py`.
- Keep business logic in service layers rather than spreading it across routers.
- This app uses async SQLAlchemy; match that style when editing backend code.
- For local development, the backend defaults to SQLite and the frontend uses Vite on localhost.
- Do not assume the app is running; verify with the relevant health or test commands before debugging frontend issues.

## Commands

Run commands from the repo root unless the task is specifically backend- or frontend-only.

### Backend

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

If you need a single targeted check, prefer the narrowest pytest selection possible instead of broad suite runs.

### Frontend

```bash
cd frontend
npm install
npm run build
npm run dev
```

## Project-specific rules

- Round state is derived from timestamps (`opens_at` / `locks_at`), not stored as a separate flag. Respect that model when fixing logic or adding tests.
- A week is not scorable until ESPN marks all games as FINAL. Do not bypass that gate in a bug fix unless the issue explicitly requires it.
- The app uses Google Identity Services plus a custom JWT/session-cookie flow. If sign-in or auth fails, verify the matching Google client ID and allowed origins, especially the local port mismatch issue (`5173` vs `5174`).
- The session cookie is cross-site in production, so secure cookie settings and same-site behavior matter. Do not “simplify” them without checking the deployment constraints described in [README.md](README.md).
- Sleeper linking is trust-based and uses a first-claim-wins pattern; keep behavior aligned with that design when touching league and member logic.
- Raw leg text is preserved as the canonical source of truth; do not overwrite or discard it while normalizing or parsing.

## Tests and validation

- Backend: run `pytest` in `backend/` after any API or business-logic change.
- Frontend: run `npm run build` after UI/API contract changes.
- For correctness-critical logic, prefer the project’s existing verification scripts in `backend/scripts/` before changing the payout or league-scoring behavior.

## Safe change guidance

- Before changing a migration, model, or API contract, inspect the matching router and schema files to keep SQLAlchemy models, response schemas, and database migrations consistent.
- If you add or change environment-sensitive behavior, verify the config in `backend/app/config.py` and update relevant docs when needed.
- Keep security-sensitive changes minimal and explicit. This repo handles session cookies, OAuth verification, and external API calls that are easy to break with overly broad changes.
- If a task is ambiguous, prefer the smallest change that matches the existing project patterns rather than introducing a new framework or abstraction.

## Agent behavior

- Follow repo conventions before inventing patterns.
- Match the app’s existing naming and folder structure.
- Use commands when needed to validate changes, but keep execution focused and relevant.
- Do not edit unrelated files just to “clean up” a task; stay surgical.
- When there is a mismatch between docs and code, defer to the live code and the existing tests.

This file is intentionally terse and repo-specific so agents can start productively without re-reading the whole project from scratch.
