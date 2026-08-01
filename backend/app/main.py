import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
from app.integrations.http import close_client
from app.routers import auth, internal, leagues, legs, me, rounds

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.is_sqlite:
        # Local dev convenience only. Postgres deployments are migrated with Alembic.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await close_client()
    await engine.dispose()


app = FastAPI(title="Fantasy Weekly Parlay", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,  # required for the session cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(leagues.router)
app.include_router(rounds.router)
app.include_router(legs.router)
app.include_router(internal.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
