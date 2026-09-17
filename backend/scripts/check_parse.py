"""See how Claude reads legs, before the grader relies on it.

Reads each leg with the real parser and the real week's matchups, then shows how the
board will display it and whether it needs a line. Nothing is written anywhere -- it only
calls the Anthropic API and ESPN.

    # PowerShell
    $env:ANTHROPIC_API_KEY = 'sk-ant-...'
    ./.venv/Scripts/python.exe scripts/check_parse.py --week 2 "Bijan 2 TDS" "Giants money line"

With no legs given, it reads the eight this league submitted for week 2.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.integrations import espn  # noqa: E402
from app.integrations.http import close_client  # noqa: E402
from app.services import grading, leg_parser  # noqa: E402

LEAGUE_WEEK_2 = [
    "Chase Brown TD",
    "Giants money line",
    "Bijan 2 TDS",
    "Saquon TD",
    "Jordan love over passing yards",
    "Malik Nabers Anytime TD",
    "trey mcbride 3+ receptions",
    "Chubba hubbard over rushing yards",
]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("legs", nargs="*", help="leg text to read (default: this league's week 2)")
    ap.add_argument("--season", default="2026")
    ap.add_argument("--week", type=int, default=2)
    args = ap.parse_args()

    key = os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
    if not key:
        print("ANTHROPIC_API_KEY is not set.\n")
        print(__doc__)
        return 2
    settings.anthropic_api_key = key
    print(f"model: {settings.leg_parse_model}")

    schedule = await espn.get_week_schedule(args.season, args.week)
    matchups = [e.name for e in schedule.events]
    print(f"week {args.week}: {len(matchups)} games\n")

    legs = args.legs or LEAGUE_WEEK_2
    readings = await asyncio.gather(
        *(leg_parser.parse_leg(text, matchups, args.week) for text in legs)
    )

    failures = 0
    for text, parsed in zip(legs, readings, strict=True):
        print(f"  {text!r}")
        if parsed is None:
            failures += 1
            print("     !! no reading -- the call failed; see the log line above\n")
            continue
        shown = grading.read_as(parsed) or "?"
        flag = "  [needs a line]" if grading.needs_line(parsed, None) else ""
        print(f"     -> {shown}{flag}")
        print(f"        {parsed['note']}\n")

    await close_client()
    if failures:
        print(f"{failures} leg(s) could not be read.")
        return 1
    print("Read every leg. Check each line above against what the person meant.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
