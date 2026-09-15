"""A double-firing cron must not spam the league."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.models import Leg, ParlayRound
from app.services import email_templates as tpl
from app.services import notify


@pytest.fixture
def outbox(monkeypatch):
    sent: list[tuple[str, str]] = []
    hooks: list[str] = []

    async def fake_email(to: str, subject: str, html: str) -> bool:
        sent.append((to, subject))
        return True

    async def fake_webhook(url: str, content: str) -> bool:
        hooks.append(content)
        return True

    monkeypatch.setattr(notify, "send_email", fake_email)
    monkeypatch.setattr(notify, "send_webhook", fake_webhook)
    return {"email": sent, "webhook": hooks}


@pytest_asyncio.fixture
async def open_round(session, user_factory, league_factory, member_factory):
    league = await league_factory()
    league.discord_webhook_url = "https://discord.com/api/webhooks/fake"
    session.add(league)

    alice = await user_factory("alice", sleeper_user_id="S1")
    bob = await user_factory("bob", sleeper_user_id="S2")
    alice_m = await member_factory(league, 1, "Alice", user=alice, role="commissioner")
    bob_m = await member_factory(league, 2, "Bob", user=bob)

    now = datetime.now(UTC)
    rnd = ParlayRound(
        league_id=league.id,
        season=league.season,
        scored_week=5,
        bet_week=6,
        loser_member_id=alice_m.id,
        loser_points=71.2,
        opens_at=now - timedelta(days=1),
        # Outside the 24h reminder window, so reminders stay out of this test.
        locks_at=now + timedelta(days=3),
    )
    session.add(rnd)
    await session.flush()
    await session.commit()
    return {"league": league, "round": rnd, "alice_m": alice_m, "bob_m": bob_m}


async def test_round_opened_sends_once_per_person(session, outbox, open_round):
    league, rnd = open_round["league"], open_round["round"]

    first = await notify.notify_round(session, league, rnd, "https://app.example")
    assert first.count(notify.KIND_ROUND_OPENED) == 3  # 2 emails + 1 discord
    assert len(outbox["email"]) == 2
    assert len(outbox["webhook"]) == 1

    # The cron fires again five minutes later.
    second = await notify.notify_round(session, league, rnd, "https://app.example")
    assert second == []
    assert len(outbox["email"]) == 2, "no duplicate emails"
    assert len(outbox["webhook"]) == 1, "no duplicate webhook posts"


async def test_whole_league_gets_the_parlay_when_every_leg_is_in(session, outbox, open_round):
    """Everyone contributed a leg, so everyone sees what it became."""
    league, rnd = open_round["league"], open_round["round"]

    await notify.notify_round(session, league, rnd, "https://app.example")
    outbox["email"].clear()

    session.add(Leg(round_id=rnd.id, member_id=open_round["alice_m"].id, raw_text="Chase o89.5"))
    session.add(Leg(round_id=rnd.id, member_id=open_round["bob_m"].id, raw_text="KC ML"))
    await session.commit()

    sent = await notify.notify_round(session, league, rnd, "https://app.example")
    assert notify.KIND_ALL_LEGS_IN in sent

    by_to = dict(outbox["email"])
    assert set(by_to) == {"alice@example.com", "bob@example.com"}

    # Alice is the payer and is told to go and place it; Bob is only shown the result.
    assert "time to place it" in by_to["alice@example.com"]
    assert "parlay is set" in by_to["bob@example.com"]

    await notify.notify_round(session, league, rnd, "https://app.example")
    assert len(outbox["email"]) == 2, "each person is told exactly once"


async def test_reminder_only_inside_the_final_day(session, outbox, open_round):
    league, rnd = open_round["league"], open_round["round"]
    await notify.notify_round(session, league, rnd, "https://app.example")
    outbox["email"].clear()

    # Still 3 days out -- nobody should be nagged yet.
    assert notify.KIND_REMINDER not in await notify.notify_round(
        session, league, rnd, "https://app.example"
    )
    assert outbox["email"] == []

    # Move the deadline inside the window; only the non-submitter hears about it.
    session.add(Leg(round_id=rnd.id, member_id=open_round["alice_m"].id, raw_text="Chase o89.5"))
    rnd.locks_at = datetime.now(UTC) + timedelta(hours=6)
    session.add(rnd)
    await session.commit()

    sent = await notify.notify_round(session, league, rnd, "https://app.example")
    assert notify.KIND_REMINDER in sent
    assert [to for to, _ in outbox["email"]] == ["bob@example.com"]


async def test_locked_round_emails_the_final_list_to_everyone(session, outbox, open_round):
    league, rnd = open_round["league"], open_round["round"]
    session.add(Leg(round_id=rnd.id, member_id=open_round["bob_m"].id, raw_text="Bills -3.5"))
    rnd.locks_at = datetime.now(UTC) - timedelta(minutes=5)
    session.add(rnd)
    await session.commit()

    sent = await notify.notify_round(session, league, rnd, "https://app.example")
    assert sent == [notify.KIND_LOCKED, notify.KIND_LOCKED]
    assert {to for to, _ in outbox["email"]} == {"alice@example.com", "bob@example.com"}
    assert all("locked" in subject for _, subject in outbox["email"])

    await notify.notify_round(session, league, rnd, "https://app.example")
    assert len(outbox["email"]) == 2


async def test_locked_does_not_repeat_the_list_people_already_got(session, outbox, open_round):
    """A league that submits on time must not receive the same parlay twice.

    The early send and the lock send carry an identical list, so the lock pass skips
    anyone the all-legs-in pass already reached.
    """
    league, rnd = open_round["league"], open_round["round"]
    session.add(Leg(round_id=rnd.id, member_id=open_round["alice_m"].id, raw_text="Chase o89.5"))
    session.add(Leg(round_id=rnd.id, member_id=open_round["bob_m"].id, raw_text="KC ML"))
    await session.commit()

    await notify.notify_round(session, league, rnd, "https://app.example")
    early = {to for to, _ in outbox["email"]}
    assert early == {"alice@example.com", "bob@example.com"}
    outbox["email"].clear()

    rnd.locks_at = datetime.now(UTC) - timedelta(minutes=5)
    session.add(rnd)
    await session.commit()

    sent = await notify.notify_round(session, league, rnd, "https://app.example")
    assert notify.KIND_LOCKED not in sent
    assert outbox["email"] == []


async def test_deadline_text_is_portable_and_localized(open_round):
    """%-d / %-I are glibc-only and would raise on Windows."""
    league, rnd = open_round["league"], open_round["round"]
    text = notify._deadline_text(rnd, league)
    assert "EDT" in text or "EST" in text

    league.timezone = "Not/AZone"
    assert "UTC" in notify._deadline_text(rnd, league)


async def test_leg_text_is_escaped_into_email_html(open_round):
    """Leg text is whatever someone typed, and it lands in an HTML email."""
    html = tpl.legs_ready(
        league_name="Bob & Co League",
        loser_name="Bob & Co",
        bet_week=2,
        deadline="Thu Sep 17, 7:15 PM EDT",
        legs=[("<script>alert(1)</script>", "Bob & Co")],
        url="https://app.example",
        locked=False,
        missing_names=[],
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "Bob &amp; Co" in html


async def test_scoreboard_marks_only_the_low_scorer(open_round):
    html = tpl.scoreboard([("Ann", 70.5), ("Bob", 99.25)], loser_name="Ann")
    assert "70.50" in html and "99.25" in html
    # The marker must land on the low scorer's row, not simply appear somewhere.
    assert html.index("PAYS") < html.index("99.25")


async def test_locked_email_names_who_never_submitted(open_round):
    html = tpl.legs_ready(
        league_name="L",
        loser_name="Ann",
        bet_week=2,
        deadline="Thu Sep 17, 7:15 PM EDT",
        legs=[("Bills -3.5", "Bob")],
        url="https://app.example",
        locked=True,
        missing_names=["Carol", "Dave"],
    )
    assert "locked" in html.lower()
    assert "Carol" in html and "Dave" in html
