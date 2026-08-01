"""Check the loser calculation against a real Sleeper league, with no database involved.

The 2026 season has no scores yet, so point this at last season to confirm the app would
have picked the same person you actually made pay.

    python scripts/verify_league.py --username <your_sleeper_username> --season 2025
    python scripts/verify_league.py --league-id <id> --season 2025 --week 5
"""

import argparse
import asyncio
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.integrations import espn, sleeper  # noqa: E402
from app.integrations.http import close_client  # noqa: E402
from app.services.rounds import compute_loser  # noqa: E402


async def pick_league(username: str, season: str) -> str | None:
    account = await sleeper.get_user(username)
    if account is None:
        print(f"No Sleeper account found for '{username}'.")
        return None
    print(f"Sleeper user: {account.display_name} (id {account.user_id})\n")

    leagues = await sleeper.get_user_leagues(account.user_id, season)
    if not leagues:
        print(f"No {season} leagues for that account.")
        return None

    print(f"{season} leagues:")
    for i, lg in enumerate(leagues, 1):
        print(f"  [{i}] {lg['name']}  ({lg['total_rosters']} teams)  id={lg['league_id']}")
    if len(leagues) == 1:
        return str(leagues[0]["league_id"])

    choice = input("\nPick a league number: ").strip()
    try:
        return str(leagues[int(choice) - 1]["league_id"])
    except (ValueError, IndexError):
        print("Invalid choice.")
        return None


async def report_week(league_id: str, season: str, week: int) -> None:
    rosters = await sleeper.get_league_rosters(league_id)
    users = await sleeper.get_league_users(league_id)
    users_by_id = {str(u["user_id"]): u for u in users if u.get("user_id")}
    name_by_roster = {
        r["roster_id"]: (
            users_by_id.get(str(r.get("owner_id")), {}).get("display_name")
            or f"Roster {r['roster_id']}"
        )
        for r in rosters
        if r.get("roster_id") is not None
    }

    matchups = await sleeper.get_matchups(league_id, week)
    scores = {
        int(m["roster_id"]): float(m["points"])
        for m in matchups
        if m.get("roster_id") is not None and m.get("points") is not None
    }
    if not scores:
        print(f"Week {week}: no scores reported.")
        return

    schedule = await espn.get_week_schedule(season, week)
    finality = "FINAL" if schedule.all_final else "IN PROGRESS / SCHEDULED"

    result = compute_loser(scores)
    print(f"\n--- Week {week} ({finality}, {len(schedule.events)} NFL games) ---")
    for roster_id, points in sorted(scores.items(), key=lambda kv: kv[1]):
        marker = ""
        if roster_id == result.roster_id:
            marker = "   <-- PAYS FOR THE PARLAY"
        elif roster_id in result.tie_roster_ids:
            marker = "   <-- TIED FOR LOWEST"
        print(f"  {points:8.2f}  {name_by_roster.get(roster_id, roster_id):<24}{marker}")

    if result.is_tie:
        print("\n  TIE -- the app will not pick automatically; the commissioner decides.")

    next_week = await espn.get_week_schedule(season, week + 1)
    if next_week.first_kickoff_at:
        print(f"\n  Legs would be for week {week + 1}.")
        print(f"  First kickoff: {next_week.first_kickoff_at:%a %Y-%m-%d %H:%M} UTC")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", help="Sleeper username, to list your leagues")
    parser.add_argument("--league-id", help="Sleeper league id (skips the lookup)")
    parser.add_argument("--season", default="2025")
    parser.add_argument("--week", type=int, help="Single week; omit to sweep weeks 1-17")
    args = parser.parse_args()

    try:
        league_id = args.league_id
        if not league_id:
            if not args.username:
                parser.error("pass --username or --league-id")
            league_id = await pick_league(args.username, args.season)
            if not league_id:
                return

        league = await sleeper.get_league(league_id)
        if not league:
            print("League not found.")
            return
        print(f"\nLeague: {league['name']}  season {league['season']}")

        weeks = [args.week] if args.week else range(1, 18)
        for week in weeks:
            await report_week(league_id, args.season, week)
    finally:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
