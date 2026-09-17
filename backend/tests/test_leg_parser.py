"""The parser is best-effort: it must never raise, and never block a submission.

These run against a fake client. They pin down the request actually sent -- model,
refusal fallback, structured schema, effort -- and that every way the call can fail
leaves the leg unread for the next tick rather than propagating.
"""

import anthropic
import httpx2
import pytest

from app.services import leg_parser
from app.services.leg_parser import ParsedLeg

CHASE = ParsedLeg(
    understood=True,
    market="touchdowns",
    subject="Chase Brown",
    team="CIN",
    direction="at_least",
    line=1,
    note="Anytime TD for Chase Brown.",
)


class FakeResponse:
    def __init__(self, parsed=CHASE, stop_reason="end_turn"):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.stop_details = None


class FakeClient:
    """Stands in for AsyncAnthropic: .with_options(...).beta.messages.parse(...)."""

    def __init__(self, result=None, error: Exception | None = None):
        self.calls: list[dict] = []
        self.options: dict = {}
        self._result = result or FakeResponse()
        self._error = error
        self.beta = self
        self.messages = self

    def with_options(self, **options):
        self.options = options
        return self

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result


@pytest.fixture
def client(monkeypatch):
    def install(**kwargs) -> FakeClient:
        fake = FakeClient(**kwargs)
        monkeypatch.setattr(leg_parser, "_get_client", lambda: fake)
        monkeypatch.setattr(leg_parser.settings, "anthropic_api_key", "sk-ant-test")
        return fake

    return install


def _status_error(cls, code: int):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("nope", response=httpx2.Response(code, request=request), body=None)


async def test_returns_the_structured_reading(client):
    fake = client()
    result = await leg_parser.parse_leg("Chase Brown TD", ["CIN @ JAX"], week=2)
    assert result["subject"] == "Chase Brown"
    assert result["team"] == "CIN"
    assert result["market"] == "touchdowns"
    assert len(fake.calls) == 1


async def test_sends_the_request_it_should(client):
    fake = client()
    await leg_parser.parse_leg("Giants money line", ["NYG @ DAL"], week=2)
    sent = fake.calls[0]

    assert sent["model"] == "claude-opus-5"
    assert sent["fallbacks"] == "default"
    assert leg_parser.FALLBACK_BETA in sent["betas"]
    assert sent["output_format"] is ParsedLeg
    assert sent["output_config"] == {"effort": "low"}
    content = sent["messages"][0]["content"]
    # The typed text is fenced as data, and this week's games give it context.
    assert "<leg>\nGiants money line\n</leg>" in content
    assert "NYG @ DAL" in content


async def test_blank_text_never_calls_the_api(client):
    fake = client()
    assert await leg_parser.parse_leg("   ") is None
    assert fake.calls == []


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_an_incomplete_response_is_left_for_later(client, stop_reason):
    client(result=FakeResponse(stop_reason=stop_reason))
    assert await leg_parser.parse_leg("Saquon TD") is None


async def test_no_structured_output_is_left_for_later(client):
    client(result=FakeResponse(parsed=None))
    assert await leg_parser.parse_leg("Saquon TD") is None


@pytest.mark.parametrize(
    "error",
    [
        _status_error(anthropic.AuthenticationError, 401),
        _status_error(anthropic.RateLimitError, 429),
        _status_error(anthropic.InternalServerError, 500),
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")),
        RuntimeError("something nobody anticipated"),
    ],
    ids=["no-key", "rate-limited", "server-error", "offline", "unexpected"],
)
async def test_no_failure_escapes(client, error):
    """A parse failure must not take down the tick or a leg submission."""
    client(error=error)
    assert await leg_parser.parse_leg("Bijan 2 TDS") is None


async def test_an_unreadable_leg_is_a_result_not_a_failure(client):
    """understood=False is an answer to record, distinct from a call that failed."""
    unreadable = ParsedLeg(
        understood=False, market=None, subject=None, team=None,
        direction=None, line=None, note="Not a bet.",
    )
    client(result=FakeResponse(parsed=unreadable))
    result = await leg_parser.parse_leg("lol good luck")
    assert result is not None
    assert result["understood"] is False


async def test_without_a_key_it_neither_calls_nor_spams_the_log(client, monkeypatch, caplog):
    """Production before the key is added: no request, and one warning -- not a traceback
    per leg on every tick."""
    fake = client()
    monkeypatch.setattr(leg_parser.settings, "anthropic_api_key", "")
    monkeypatch.setattr(leg_parser, "_warned_no_key", False)

    with caplog.at_level("WARNING", logger="app.services.leg_parser"):
        for text in ("Saquon TD", "Bijan 2 TDS", "Giants money line"):
            assert await leg_parser.parse_leg(text) is None

    assert fake.calls == []
    warnings = [r for r in caplog.records if "ANTHROPIC_API_KEY" in r.getMessage()]
    assert len(warnings) == 1
    assert not any(r.exc_info for r in caplog.records)
