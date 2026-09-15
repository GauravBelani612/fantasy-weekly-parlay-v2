from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth.session import CurrentUser, DbSession
from app.integrations import sleeper
from app.integrations.sleeper import avatar_url
from app.models import League, SleeperLink
from app.ratelimit import enforce
from app.schemas import ClaimSleeperIn, MeOut, SleeperLeagueOut, SleeperLinkOut, UserOut
from app.services.leagues import attach_user_to_leagues

router = APIRouter(prefix="/me", tags=["me"])


def _link_out(link: SleeperLink) -> SleeperLinkOut:
    return SleeperLinkOut(
        sleeper_user_id=link.sleeper_user_id,
        sleeper_username=link.sleeper_username,
        sleeper_display_name=link.sleeper_display_name,
        avatar_url=avatar_url(link.sleeper_avatar),
    )


@router.get("", response_model=MeOut)
async def get_me(user: CurrentUser, session: DbSession):
    link = await session.get(SleeperLink, user.id)
    return MeOut(user=UserOut.model_validate(user), sleeper=_link_out(link) if link else None)


@router.post("/sleeper", response_model=SleeperLinkOut)
async def claim_sleeper_account(payload: ClaimSleeperIn, user: CurrentUser, session: DbSession):
    """Claim a Sleeper account by username.

    Sleeper offers no OAuth, so ownership cannot be proven -- this is trust-based and
    first-claim-wins. Rate limited because it is otherwise a free identity-guessing loop.
    """
    enforce(
        f"claim:{user.id}",
        limit=10,
        window_seconds=300,
        message="Too many link attempts. Wait a few minutes and try again.",
    )

    username = payload.username.strip().lstrip("@")
    account = await sleeper.get_user(username)
    if account is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No Sleeper account found for '{username}'. Check the spelling of your username.",
        )

    taken_by = await session.scalar(
        select(SleeperLink).where(SleeperLink.sleeper_user_id == account.user_id)
    )
    if taken_by is not None and taken_by.user_id != user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That Sleeper account is already linked to another login.",
        )

    link = taken_by or await session.get(SleeperLink, user.id) or SleeperLink(user_id=user.id)
    link.sleeper_user_id = account.user_id
    link.sleeper_username = account.username or username
    link.sleeper_display_name = account.display_name
    link.sleeper_avatar = account.avatar
    session.add(link)
    await session.flush()

    # Anyone who imported this league earlier left an unclaimed roster row for this
    # person; wire it up so they can submit immediately.
    await attach_user_to_leagues(session, user, account.user_id)
    await session.commit()
    return _link_out(link)


@router.delete("/sleeper", status_code=204)
async def unlink_sleeper_account(user: CurrentUser, session: DbSession) -> None:
    link = await session.get(SleeperLink, user.id)
    if link is not None:
        await session.delete(link)
        await session.commit()


def _is_unconfigured(item: dict) -> bool:
    """True for a Sleeper league nobody finished setting up.

    An abandoned league stays in the owner's list indefinitely, still reporting
    status "in_season" with a full set of drafted rosters, so neither of those
    separates it from the real thing. Not having a playoff week does: every league
    that was actually configured has one, and importing an abandoned twin means the
    league gets two parlays, two payers and two sets of email every week.
    """
    settings = item.get("settings") or {}
    try:
        return int(settings.get("playoff_week_start") or 0) <= 0
    except (TypeError, ValueError):
        return False


@router.get("/sleeper/leagues", response_model=list[SleeperLeagueOut])
async def list_importable_leagues(
    user: CurrentUser,
    session: DbSession,
    season: str | None = Query(default=None, max_length=8),
):
    link = await session.get(SleeperLink, user.id)
    if link is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Link your Sleeper account before importing leagues."
        )

    if not season:
        state = await sleeper.get_nfl_state()
        season = str(state.get("season") or "")

    raw = await sleeper.get_user_leagues(link.sleeper_user_id, season)
    if not raw and season:
        # Sleeper rolls league IDs each season; during the preseason the new season can be
        # empty while last season's league is the one people actually want.
        previous = str(int(season) - 1)
        raw = await sleeper.get_user_leagues(link.sleeper_user_id, previous)
        season = previous if raw else season

    imported = {
        row
        for row in (
            await session.scalars(
                select(League.sleeper_league_id).where(
                    League.sleeper_league_id.in_([str(x.get("league_id")) for x in raw] or [""])
                )
            )
        ).all()
    }

    return [
        SleeperLeagueOut(
            sleeper_league_id=str(item.get("league_id")),
            name=item.get("name") or "Untitled League",
            season=str(item.get("season") or season),
            total_rosters=int(item.get("total_rosters") or 0),
            avatar_url=avatar_url(item.get("avatar")),
            already_imported=str(item.get("league_id")) in imported,
            unconfigured=_is_unconfigured(item),
        )
        for item in raw
    ]
