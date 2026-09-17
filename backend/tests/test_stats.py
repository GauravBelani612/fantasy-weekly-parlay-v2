"""Stats: the numbers a league brags and argues about, so each rule gets pinned down."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Leg, ParlayRound
from app.services.stats import (
    LegRecord,
    MemberRecord,
    RoundRecord,
    bet_type,
    compute,
    streaks,
)


def member(name: str, *, account: bool = True, you: bool = False) -> MemberRecord:
    return MemberRecord(uuid.uuid4(), name, None, account, you)


def week(n: int, outcome: str = "pending", loser=None, locked: bool = True) -> RoundRecord:
    return RoundRecord(uuid.uuid4(), n, outcome, loser.id if loser else None, locked)


def leg(who: MemberRecord, rnd: RoundRecord, result: str, market: str = "touchdowns") -> LegRecord:
    return LegRecord(who.id, rnd.id, rnd.bet_week, result, market)


def stats_for(result, who: MemberRecord):
    return next(s for s in result.members if s.member_id == who.id)


# ------------------------------------------------------------------ streaks


@pytest.mark.parametrize(
    ("results", "current", "longest"),
    [
        ([], None, 0),
        (["hit", "hit", "hit"], ("hit", 3), 3),
        (["hit", "hit", "miss"], ("miss", 1), 2),
        (["miss", "hit", "hit", "hit", "miss", "hit"], ("hit", 1), 3),
        # A void is a player who sat out: it neither extends nor breaks a streak.
        (["hit", "void", "hit"], ("hit", 2), 2),
        (["void", "void"], None, 0),
        (["hit", "pending"], ("hit", 1), 1),
    ],
)
def test_streaks(results, current, longest):
    got_current, got_longest = streaks(results)
    assert (got_current and (got_current.result, got_current.length)) == (current or None)
    assert got_longest == longest


# ------------------------------------------------------------------ personal


def test_hit_rate_counts_hits_and_misses_only():
    ann = member("Ann")
    w1, w2, w3, w4 = week(1), week(2), week(3), week(4)
    result = compute("2026", [w1, w2, w3, w4],
                     [leg(ann, w1, "hit"), leg(ann, w2, "miss"),
                      leg(ann, w3, "void"), leg(ann, w4, "pending")], [ann])
    s = stats_for(result, ann)
    assert (s.hits, s.misses, s.voids) == (1, 1, 1)
    assert s.hit_rate == 0.5


def test_parlays_won_means_you_had_a_leg_in_one_that_cashed():
    ann, bob = member("Ann"), member("Bob")
    won, lost = week(1, "won"), week(2, "lost")
    result = compute("2026", [won, lost],
                     [leg(ann, won, "hit"), leg(bob, won, "hit"), leg(ann, lost, "miss")],
                     [ann, bob])
    assert (stats_for(result, ann).parlays_played, stats_for(result, ann).parlays_won) == (2, 1)
    assert (stats_for(result, bob).parlays_played, stats_for(result, bob).parlays_won) == (1, 1)


def test_times_funded():
    ann, bob = member("Ann"), member("Bob")
    rounds = [week(1, loser=ann), week(2, loser=ann), week(3, loser=bob)]
    result = compute("2026", rounds, [], [ann, bob])
    assert stats_for(result, ann).times_funded == 2
    assert stats_for(result, bob).times_funded == 1


def test_only_miss_needs_a_finished_week_and_a_single_miss():
    ann, bob, cam = member("Ann"), member("Bob"), member("Cam")
    alone = week(1, "lost")  # Ann's miss is the only one
    shared = week(2, "lost")  # two misses: nobody sank it alone
    unfinished = week(3, "lost")  # Bob's miss is alone *so far*, but a leg is still open
    legs = [
        leg(ann, alone, "miss"), leg(bob, alone, "hit"), leg(cam, alone, "hit"),
        leg(ann, shared, "miss"), leg(bob, shared, "miss"), leg(cam, shared, "hit"),
        leg(ann, unfinished, "hit"), leg(bob, unfinished, "miss"), leg(cam, unfinished, "pending"),
    ]
    result = compute("2026", [alone, shared, unfinished], legs, [ann, bob, cam])
    assert stats_for(result, ann).only_miss == 1
    assert stats_for(result, bob).only_miss == 0


def test_best_bet_type_needs_more_than_one_lucky_leg():
    ann = member("Ann")
    weeks = [week(n) for n in range(1, 5)]
    legs = [
        leg(ann, weeks[0], "hit", "moneyline"),  # 1-for-1: too few to count
        leg(ann, weeks[1], "hit", "rushing_yards"),
        leg(ann, weeks[2], "hit", "receiving_yards"),
        leg(ann, weeks[3], "miss", "touchdowns"),
    ]
    best = stats_for(compute("2026", weeks, legs, [ann]), ann).best_bet_type
    assert best.label == "Yards"
    assert (best.hits, best.misses) == (2, 0)


def test_unclaimed_rosters_appear_only_if_they_did_something():
    ann = member("Ann")
    ghost = member("Ghost", account=False)
    payer = member("Carol", account=False)  # never signed up, but funded a week
    result = compute("2026", [week(1, loser=payer)], [], [ann, ghost, payer])
    names = {s.display_name for s in result.members}
    assert names == {"Ann", "Carol"}


def test_leaderboard_orders_by_hits_then_rate():
    ann, bob, cam = member("Ann"), member("Bob"), member("Cam")
    weeks = [week(n) for n in range(1, 4)]
    legs = [
        leg(ann, weeks[0], "hit"), leg(ann, weeks[1], "hit"), leg(ann, weeks[2], "miss"),
        leg(bob, weeks[0], "hit"), leg(bob, weeks[1], "hit"),  # same hits, better rate
        leg(cam, weeks[0], "hit"),
    ]
    order = [s.display_name for s in compute("2026", weeks, legs, [ann, bob, cam]).members]
    assert order == ["Bob", "Ann", "Cam"]


# ------------------------------------------------------------------ league


def test_weekly_averages_use_finished_weeks_only():
    ann, bob = member("Ann"), member("Bob")
    done = week(1)
    in_progress = week(2)  # locked, but a leg is still pending
    open_week = week(3, locked=False)  # nothing has kicked off
    legs = [
        leg(ann, done, "hit"), leg(bob, done, "miss"),
        leg(ann, in_progress, "miss"), leg(bob, in_progress, "pending"),
        leg(ann, open_week, "pending"),
    ]
    totals = compute("2026", [done, in_progress, open_week], legs, [ann, bob]).league
    assert totals.weeks_complete == 1
    assert totals.avg_hits_per_week == 1.0
    assert totals.avg_legs_per_week == 2.0
    # Counts of settled legs still include every week.
    assert (totals.legs_hit, totals.legs_missed) == (1, 2)


def test_best_week_takes_the_earliest_on_a_tie():
    ann, bob = member("Ann"), member("Bob")
    w1, w2, w3 = week(1), week(2), week(3)
    legs = [
        leg(ann, w1, "hit"), leg(bob, w1, "miss"),
        leg(ann, w2, "hit"), leg(bob, w2, "hit"),
        leg(ann, w3, "hit"), leg(bob, w3, "hit"),
    ]
    best = compute("2026", [w3, w1, w2], legs, [ann, bob]).league.best_week
    assert (best.bet_week, best.hits, best.legs) == (2, 2, 2)


def test_most_often_paying_names_everyone_tied():
    ann, bob, cam = member("Ann"), member("Bob"), member("Cam")
    rounds = [week(1, loser=bob), week(2, loser=ann), week(3, loser=bob),
              week(4, loser=ann), week(5, loser=cam)]
    payers = compute("2026", rounds, [], [ann, bob, cam]).league.top_payers
    assert [(p.display_name, p.times) for p in payers] == [("Ann", 2), ("Bob", 2)]


def test_most_often_paying_includes_someone_who_never_signed_up():
    carol = member("Carol", account=False)
    payers = compute("2026", [week(1, loser=carol)], [], [carol]).league.top_payers
    assert [p.display_name for p in payers] == ["Carol"]
    assert compute("2026", [], [], [carol]).league.top_payers == []


def test_cash_rate_ignores_voided_parlays():
    rounds = [week(1, "won"), week(2, "lost"), week(3, "lost"), week(4, "void"), week(5)]
    totals = compute("2026", rounds, [], []).league
    assert (totals.parlays_won, totals.parlays_lost) == (1, 2)
    assert totals.cash_rate == round(1 / 3, 4)


def test_one_leg_away():
    ann, bob, cam = member("Ann"), member("Bob"), member("Cam")
    heartbreak = week(1, "lost")
    blowout = week(2, "lost")
    legs = [
        leg(ann, heartbreak, "hit"), leg(bob, heartbreak, "hit"), leg(cam, heartbreak, "miss"),
        leg(ann, blowout, "miss"), leg(bob, blowout, "miss"), leg(cam, blowout, "hit"),
    ]
    assert compute("2026", [heartbreak, blowout], legs, [ann, bob, cam]).league.one_leg_away == 1


def test_hit_rate_by_bet_type():
    ann = member("Ann")
    weeks = [week(n) for n in range(1, 6)]
    legs = [
        leg(ann, weeks[0], "hit", "touchdowns"),
        leg(ann, weeks[1], "miss", "rushing_touchdowns"),
        leg(ann, weeks[2], "miss", "touchdowns"),
        leg(ann, weeks[3], "hit", "moneyline"),
        leg(ann, weeks[4], "void", "passing_yards"),  # a void doesn't create a row
    ]
    rows = compute("2026", weeks, legs, [ann]).league.by_bet_type
    assert [(r.label, r.hits, r.misses) for r in rows] == [
        ("Touchdowns", 1, 2),  # most-bet first
        ("Moneyline", 1, 0),
    ]


def test_an_empty_season_is_all_zeros_not_an_error():
    ann = member("Ann")
    result = compute("2026", [], [], [ann])
    assert result.league.weeks_complete == 0
    assert result.league.hit_rate is None
    assert result.league.best_week is None
    assert stats_for(result, ann).current_streak is None


def test_unparsed_legs_group_as_other():
    assert bet_type(None) == "Other"
    assert bet_type("receptions") == "Receptions"


# ------------------------------------------------------------------ endpoint


async def test_stats_endpoint(client, login, session, user_factory, league_factory,
                              member_factory):
    league = await league_factory(season="2026")
    ann = await user_factory("ann", sleeper_user_id="S1")
    stranger = await user_factory("stranger", sleeper_user_id="S9")
    ann_m = await member_factory(league, 1, "Ann", user=ann, role="commissioner")

    now = datetime.now(UTC)
    rnd = ParlayRound(league_id=league.id, season="2026", scored_week=1, bet_week=2,
                      loser_member_id=ann_m.id, outcome="won",
                      opens_at=now - timedelta(days=3), locks_at=now - timedelta(days=2))
    session.add(rnd)
    await session.flush()
    session.add(Leg(round_id=rnd.id, member_id=ann_m.id, raw_text="Saquon TD", result="hit",
                    parsed={"understood": True, "market": "touchdowns"}))
    await session.commit()

    login(ann)
    r = await client.get(f"/leagues/{league.id}/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["league"]["parlays_won"] == 1
    assert body["league"]["by_bet_type"][0]["label"] == "Touchdowns"
    me = body["members"][0]
    assert me["is_you"] is True
    assert (me["hits"], me["parlays_won"], me["times_funded"]) == (1, 1, 1)
    assert me["current_streak"] == {"result": "hit", "length": 1}

    login(stranger)
    assert (await client.get(f"/leagues/{league.id}/stats")).status_code == 404
