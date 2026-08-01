import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.session import get_current_user
from app.db import Base, get_session
from app.main import app
from app.models import League, LeagueMember, SleeperLink, User
from app.ratelimit import reset as reset_ratelimit


@pytest_asyncio.fixture
async def engine():
    # StaticPool keeps every connection pointed at the same in-memory database.
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine, session) -> AsyncGenerator[AsyncClient, None]:
    reset_ratelimit()

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def login(session):
    """Authenticate as a given user by overriding the session dependency."""

    def _login(user: User):
        async def _current_user():
            return user

        app.dependency_overrides[get_current_user] = _current_user
        return user

    return _login


@pytest_asyncio.fixture
async def user_factory(session):
    async def _make(name: str, sleeper_user_id: str | None = None) -> User:
        user = User(
            google_sub=f"sub-{name}-{uuid.uuid4().hex[:6]}",
            email=f"{name}@example.com",
            display_name=name.title(),
        )
        session.add(user)
        await session.flush()
        if sleeper_user_id:
            session.add(
                SleeperLink(
                    user_id=user.id,
                    sleeper_user_id=sleeper_user_id,
                    sleeper_username=name,
                    sleeper_display_name=name.title(),
                )
            )
            await session.flush()
        await session.commit()
        return user

    return _make


@pytest_asyncio.fixture
async def league_factory(session):
    async def _make(name: str = "Test League", season: str = "2025") -> League:
        league = League(
            sleeper_league_id=f"L{uuid.uuid4().hex[:10]}",
            season=season,
            name=name,
            total_rosters=0,
        )
        session.add(league)
        await session.flush()
        await session.commit()
        return league

    return _make


@pytest_asyncio.fixture
async def member_factory(session):
    async def _make(
        league: League,
        roster_id: int,
        display_name: str,
        user: User | None = None,
        role: str = "member",
    ) -> LeagueMember:
        member = LeagueMember(
            league_id=league.id,
            sleeper_roster_id=roster_id,
            display_name=display_name,
            user_id=user.id if user else None,
            sleeper_user_id=f"S{roster_id}",
            role=role,
        )
        session.add(member)
        await session.flush()
        await session.commit()
        return member

    return _make
