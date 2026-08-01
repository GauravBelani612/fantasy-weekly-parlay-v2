"""Sleeper API client.

Sleeper is public and read-only -- no API key, no OAuth -- with a documented limit of
roughly 1000 calls/minute.
"""

import logging
import time
from dataclasses import dataclass

from app.config import settings
from app.integrations.http import get_json

log = logging.getLogger(__name__)

# NFL state changes a handful of times a week; every page load asking for it is wasteful.
_STATE_TTL_SECONDS = 300
_state_cache: tuple[float, dict] | None = None


@dataclass(frozen=True)
class SleeperUser:
    user_id: str
    username: str
    display_name: str
    avatar: str | None


def avatar_url(avatar_id: str | None, thumb: bool = True) -> str | None:
    if not avatar_id:
        return None
    kind = "thumbs" if thumb else "full"
    return f"https://sleepercdn.com/avatars/{kind}/{avatar_id}"


async def get_nfl_state(use_cache: bool = True) -> dict:
    """Current season/week. `week` is 0 during the preseason."""
    global _state_cache
    if use_cache and _state_cache is not None:
        cached_at, value = _state_cache
        if time.monotonic() - cached_at < _STATE_TTL_SECONDS:
            return value

    state = await get_json(f"{settings.sleeper_base_url}/state/nfl") or {}
    _state_cache = (time.monotonic(), state)
    return state


def clear_state_cache() -> None:
    global _state_cache
    _state_cache = None


async def get_user(username_or_id: str) -> SleeperUser | None:
    """Look up a Sleeper account.

    Sleeper answers an unknown username with HTTP 200 and a literal `null` body rather
    than a 404, so the None check here is load-bearing -- without it the claim flow would
    happily link an account that does not exist.
    """
    data = await get_json(f"{settings.sleeper_base_url}/user/{username_or_id}")
    if not data or not data.get("user_id"):
        return None
    return SleeperUser(
        user_id=str(data["user_id"]),
        username=data.get("username") or "",
        display_name=data.get("display_name") or data.get("username") or "",
        avatar=data.get("avatar"),
    )


async def get_user_leagues(sleeper_user_id: str, season: str) -> list[dict]:
    url = f"{settings.sleeper_base_url}/user/{sleeper_user_id}/leagues/nfl/{season}"
    return await get_json(url) or []


async def get_league(league_id: str) -> dict | None:
    return await get_json(f"{settings.sleeper_base_url}/league/{league_id}")


async def get_league_rosters(league_id: str) -> list[dict]:
    return await get_json(f"{settings.sleeper_base_url}/league/{league_id}/rosters") or []


async def get_league_users(league_id: str) -> list[dict]:
    return await get_json(f"{settings.sleeper_base_url}/league/{league_id}/users") or []


async def get_matchups(league_id: str, week: int) -> list[dict]:
    """Per-roster scoring for one week: {roster_id, matchup_id, points, starters}."""
    url = f"{settings.sleeper_base_url}/league/{league_id}/matchups/{week}"
    return await get_json(url) or []
