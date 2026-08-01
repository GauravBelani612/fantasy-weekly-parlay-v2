"""The scheduled sweep.

Only notifications need this to run. Round open/lock state is derived from timestamps on
every read, so a missed tick costs you an email, never correctness.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import League
from app.services import notify
from app.services.rounds import ensure_current_round

log = logging.getLogger(__name__)


@dataclass
class TickReport:
    leagues_checked: int = 0
    rounds_active: int = 0
    notifications_sent: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def run_tick(session: AsyncSession) -> TickReport:
    report = TickReport()
    leagues = (await session.scalars(select(League))).all()
    app_url = settings.public_app_url

    for league in leagues:
        report.leagues_checked += 1
        try:
            rnd = await ensure_current_round(session, league)
            if rnd is None:
                continue
            report.rounds_active += 1
            sent = await notify.notify_round(session, league, rnd, app_url)
            report.notifications_sent.extend(f"{league.name}:{kind}" for kind in sent)
        except Exception as exc:  # one bad league must not stop the rest
            log.exception("Tick failed for league %s", league.id)
            report.errors.append(f"{league.name}: {exc}")
            await session.rollback()

    return report
