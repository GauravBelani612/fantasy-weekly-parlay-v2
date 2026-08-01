"""Create a real parlay round from a completed week, for testing before the season starts.

The 2026 season has no scores until September, so there is nothing for the app to open on
its own. This pulls a finished week's actual Sleeper scores, works out who really lost, and
opens a round you can drive through the UI.

    # import last season's league and open a round from week 5
    python scripts/seed_round.py --sleeper-league-id 1242530523637624832 --week 5

    # populate the board with other managers' legs so it looks like a live week
    python scripts/seed_round.py --sleeper-league-id 1242530523637624832 --week 5 --demo-legs

    # test the locked state instead
    python scripts/seed_round.py --sleeper-league-id 1242530523637624832 --week 5 --lock-in -5

    # remove everything this script created
    python scripts/seed_round.py --clear
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.integrations import espn  # noqa: E402
from app.integrations.http import close_client  # noqa: E402
from app.models import (  # noqa: E402
    League,
    LeagueMember,
    Leg,
    NotificationLog,
    ParlayRound,
    SleeperLink,
    User,
    WeekScore,
)
from app.services.leagues import import_league, sync_members  # noqa: E402
from app.services.rounds import compute_loser, sync_week_scores  # noqa: E402

# Marks every account this script invents, so --clear can find them again.
DEMO_EMAIL_DOMAIN = "demo.invalid"

DEMO_LEGS = [
    "Ja'Marr Chase over 89.5 receiving yards",
    "Bills -3.5",
    "Jalen Hurts anytime TD",
    "Chiefs/Lions over 47.5",
    "Bijan Robinson over 74.5 rush yards",
    "Lamar Jackson over 1.5 passing TDs",
    "49ers moneyline",
    "Travis Kelce over 5.5 receptions",
    "Puka Nacua over 6.5 receptions",
    "Cowboys +6.5",
    "Saquon Barkley anytime TD",
    "Tyreek Hill over 79.5 receiving yards",
]


async def real_users(db) -> list[User]:
    """Everyone who actually signed in, excluding placeholders this script created."""
    return list(
        (
            await db.scalars(
                select(User)
                .where(~User.email.like(f"%@{DEMO_EMAIL_DOMAIN}"))
                .order_by(User.created_at)
            )
        ).all()
    )


async def resolve_owner(db, email: str | None) -> User:
    """Who the import is attributed to, and who becomes commissioner."""
    users = await real_users(db)
    if not users:
        raise SystemExit("No user found. Sign in through the web app first.")

    if email:
        match = next((u for u in users if u.email.lower() == email.lower()), None)
        if match is None:
            known = ", ".join(u.email for u in users)
            raise SystemExit(f"No user with email {email}. Known accounts: {known}")
        return match

    # Prefer someone who has actually linked a Sleeper account -- an owner without one
    # cannot be matched to a roster, which silently produces a league you can't play in.
    linked = [u for u in users if await db.get(SleeperLink, u.id) is not None]
    pool = linked or users
    if len(pool) > 1:
        known = ", ".join(u.email for u in pool)
        raise SystemExit(f"Several accounts exist; pick one with --as. Options: {known}")
    return pool[0]


async def clear(db) -> None:
    demo_users = (
        await db.scalars(select(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")))
    ).all()
    demo_ids = [u.id for u in demo_users]

    if demo_ids:
        # Unhook the placeholder accounts before deleting them so real rosters survive.
        for member in (
            await db.scalars(select(LeagueMember).where(LeagueMember.user_id.in_(demo_ids)))
        ).all():
            member.user_id = None
            db.add(member)
        await db.flush()

    rounds = (await db.scalars(select(ParlayRound))).all()
    for rnd in rounds:
        await db.execute(delete(Leg).where(Leg.round_id == rnd.id))
        await db.execute(delete(NotificationLog).where(NotificationLog.round_id == rnd.id))
    await db.execute(delete(ParlayRound))
    await db.execute(delete(WeekScore))
    for user in demo_users:
        await db.delete(user)
    await db.commit()
    print(f"Cleared {len(rounds)} round(s) and {len(demo_users)} demo account(s).")


async def attach_demo_accounts(db, league: League, skip_member_ids: set) -> int:
    """Give unclaimed rosters placeholder accounts so they count as able to submit.

    Without this the board reads '1 of 1 in' and the interesting parts of the UI -- the
    waiting list, the full leg board -- never render.
    """
    members = (
        await db.scalars(
            select(LeagueMember).where(
                LeagueMember.league_id == league.id, LeagueMember.user_id.is_(None)
            )
        )
    ).all()

    created = 0
    for member in members:
        if member.id in skip_member_ids:
            continue
        handle = (member.sleeper_user_id or str(member.sleeper_roster_id)).lower()
        email = f"demo-{handle}@{DEMO_EMAIL_DOMAIN}"
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                google_sub=f"demo-{uuid.uuid4().hex}",
                email=email,
                display_name=member.display_name,
            )
            db.add(user)
            await db.flush()
        member.user_id = user.id
        db.add(member)
        created += 1

    await db.flush()
    return created


async def seed(args) -> None:
    async with SessionLocal() as db:
        if args.clear:
            await clear(db)
            return

        owner = await resolve_owner(db, args.as_email)
        print(f"Acting as {owner.email}\n")

        league = await db.scalar(
            select(League).where(League.sleeper_league_id == args.sleeper_league_id)
        )
        if league is None:
            print(f"Importing Sleeper league {args.sleeper_league_id}...")
            league = await import_league(db, owner, args.sleeper_league_id)
        else:
            await sync_members(db, league)
            await db.commit()
        print(f"League: {league.name}  (season {league.season}, {league.total_rosters} teams)")

        # Real scores from the week that actually happened.
        scores = await sync_week_scores(db, league, args.week)
        if not scores:
            raise SystemExit(
                f"Sleeper has no scores for week {args.week} of season {league.season}."
            )
        result = compute_loser(scores)

        members = {
            m.sleeper_roster_id: m
            for m in (
                await db.scalars(select(LeagueMember).where(LeagueMember.league_id == league.id))
            ).all()
        }
        loser = members.get(result.roster_id) if result.roster_id else None

        bet_week = args.week + 1
        schedule = await espn.get_week_schedule(league.season, bet_week)
        now = datetime.now(UTC)
        locks_at = now + timedelta(minutes=args.lock_in)

        existing = await db.scalar(
            select(ParlayRound).where(
                ParlayRound.league_id == league.id,
                ParlayRound.season == league.season,
                ParlayRound.bet_week == bet_week,
            )
        )
        if existing is not None:
            await db.execute(delete(Leg).where(Leg.round_id == existing.id))
            await db.execute(delete(NotificationLog).where(NotificationLog.round_id == existing.id))
            await db.delete(existing)
            await db.flush()

        rnd = ParlayRound(
            league_id=league.id,
            season=league.season,
            scored_week=args.week,
            bet_week=bet_week,
            loser_member_id=loser.id if loser else None,
            loser_points=result.points,
            tie_roster_ids=result.tie_roster_ids or None,
            opens_at=now - timedelta(hours=1),
            locks_at=locks_at,
        )
        db.add(rnd)
        await db.flush()

        # Any roster held by a genuinely signed-in account is yours to fill in by hand.
        # Matching on `owner` alone would pre-fill your own leg whenever the import was
        # attributed to a different account than the one holding the roster.
        human_ids = {u.id for u in await real_users(db)}
        human_members = {m.id for m in members.values() if m.user_id in human_ids}
        your_member = next(
            (m for m in members.values() if m.user_id == owner.id),
            next((m for m in members.values() if m.id in human_members), None),
        )

        demo_count = 0
        leg_count = 0
        if args.demo_legs:
            demo_count = await attach_demo_accounts(db, league, skip_member_ids=human_members)

            # Leave two managers empty so the "still waiting on" list has something in it.
            fillable = [m for m in members.values() if m.id not in human_members]
            fillable.sort(key=lambda m: m.sleeper_roster_id)
            for i, member in enumerate(fillable[:-2]):
                db.add(
                    Leg(
                        round_id=rnd.id,
                        member_id=member.id,
                        raw_text=DEMO_LEGS[i % len(DEMO_LEGS)],
                    )
                )
                leg_count += 1

        await db.commit()

        who = loser.display_name if loser else "TIE / unresolved"
        pts = f"{result.points:.2f} pts" if result.points is not None else "no score"
        print(f"\nWeek {args.week} low scorer: {who}  ({pts})")
        if result.is_tie:
            print(f"  TIE between rosters {result.tie_roster_ids} -- resolve it in the UI.")
        print(f"Round opened for week {bet_week} bets.")
        if schedule.first_kickoff_at:
            kickoff = f"{schedule.first_kickoff_at:%a %Y-%m-%d %H:%M}"
            print(f"  Real week {bet_week} kickoff was {kickoff} UTC")
        state = "LOCKED" if args.lock_in <= 0 else f"locks in {args.lock_in} min"
        print(f"  Submission window: {state}")
        if args.demo_legs:
            print(f"  Gave {demo_count} roster(s) placeholder accounts,"
                  f" added {leg_count} leg(s).")
        if your_member:
            print(f"\nYou are '{your_member.display_name}'"
                  f" (roster {your_member.sleeper_roster_id}).")
        else:
            print("\nWARNING: your Sleeper account does not own a roster in this league,"
                  " so you will not be able to submit a leg.")
        print("\nOpen http://localhost:5173 and pick this league.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sleeper-league-id", help="Sleeper league id of a completed season")
    parser.add_argument("--week", type=int, default=5, help="Completed week that decides the payer")
    parser.add_argument(
        "--lock-in",
        type=int,
        default=120,
        help="Minutes until submissions lock. Zero or negative opens the round already locked.",
    )
    parser.add_argument(
        "--demo-legs",
        action="store_true",
        help="Give other rosters placeholder accounts and fill in most of their legs.",
    )
    parser.add_argument(
        "--as",
        dest="as_email",
        help="Email of the account to import as. Required if several accounts exist.",
    )
    parser.add_argument("--clear", action="store_true", help="Delete all rounds and demo accounts")
    args = parser.parse_args()

    if not args.clear and not args.sleeper_league_id:
        parser.error("--sleeper-league-id is required unless you pass --clear")

    try:
        await seed(args)
    finally:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
