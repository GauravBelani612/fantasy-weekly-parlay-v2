"""ESPN scoreboard client (unofficial, no API key).

Used for two things: the kickoff time that anchors each submission deadline, and whether a
week has actually finished. Sleeper reports points continuously, so without a finality
signal we would happily crown a "loser" halfway through Sunday afternoon.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from dateutil import parser as date_parser

from app.config import settings
from app.integrations.http import get_json

log = logging.getLogger(__name__)

REGULAR_SEASON = 2
MAX_REGULAR_WEEK = 18


@dataclass(frozen=True)
class NflEvent:
    event_id: str
    name: str
    kickoff_at: datetime
    status: str

    @property
    def is_final(self) -> bool:
        return self.status == "STATUS_FINAL"


@dataclass(frozen=True)
class WeekSchedule:
    season: str
    week: int
    events: list[NflEvent]

    @property
    def first_kickoff_at(self) -> datetime | None:
        return min((e.kickoff_at for e in self.events), default=None)

    @property
    def last_kickoff_at(self) -> datetime | None:
        return max((e.kickoff_at for e in self.events), default=None)

    @property
    def all_final(self) -> bool:
        return bool(self.events) and all(e.is_final for e in self.events)


def _parse_dt(value: str) -> datetime:
    dt = date_parser.isoparse(value)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


async def get_week_schedule(season: str, week: int) -> WeekSchedule:
    data = await get_json(
        f"{settings.espn_base_url}/scoreboard",
        params={"dates": season, "seasontype": REGULAR_SEASON, "week": week},
    )
    events: list[NflEvent] = []
    for raw in (data or {}).get("events", []):
        try:
            events.append(
                NflEvent(
                    event_id=str(raw["id"]),
                    name=raw.get("shortName") or raw.get("name") or "",
                    kickoff_at=_parse_dt(raw["date"]),
                    status=raw.get("status", {}).get("type", {}).get("name", "STATUS_SCHEDULED"),
                )
            )
        except (KeyError, ValueError) as exc:
            log.warning("Skipping malformed ESPN event in %s wk%s: %s", season, week, exc)

    return WeekSchedule(season=season, week=week, events=events)
