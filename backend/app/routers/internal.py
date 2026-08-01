import hmac

from fastapi import APIRouter, Header, HTTPException, status

from app.auth.session import DbSession
from app.config import settings
from app.jobs.tick import run_tick

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


def _authorize(provided: str | None) -> None:
    if not settings.internal_tick_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Tick secret is not configured")
    # Constant-time compare so the secret cannot be recovered by timing.
    if not provided or not hmac.compare_digest(provided, settings.internal_tick_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad tick secret")


@router.post("/tick")
async def tick(session: DbSession, x_tick_secret: str | None = Header(default=None)):
    """Advance every league's round and send any notifications that are due.

    Safe to call repeatedly: notifications_log makes each message send at most once.
    """
    _authorize(x_tick_secret)
    report = await run_tick(session)
    return {
        "leagues_checked": report.leagues_checked,
        "rounds_active": report.rounds_active,
        "notifications_sent": report.notifications_sent,
        "errors": report.errors,
    }
