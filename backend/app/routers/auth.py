from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.google import verify_google_id_token
from app.auth.session import (
    CurrentUser,
    DbSession,
    clear_session_cookie,
    create_session_token,
    set_session_cookie,
)
from app.models import User
from app.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleLoginIn(BaseModel):
    credential: str


@router.post("/google", response_model=UserOut)
async def login_with_google(payload: GoogleLoginIn, response: Response, session: DbSession):
    """Exchange a Google ID token for our own session cookie."""
    profile = await verify_google_id_token(payload.credential)

    user = await session.scalar(select(User).where(User.google_sub == profile.sub))
    if user is None:
        # Same person, previously seen by email (e.g. re-created Google account).
        user = await session.scalar(select(User).where(User.email == profile.email))
        if user is not None:
            user.google_sub = profile.sub

    if user is None:
        user = User(
            google_sub=profile.sub,
            email=profile.email,
            display_name=profile.name,
            avatar_url=profile.picture,
        )
        session.add(user)
    else:
        user.display_name = profile.name
        user.avatar_url = profile.picture

    await session.commit()
    await session.refresh(user)

    set_session_cookie(response, create_session_token(user.id))
    return UserOut.model_validate(user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
async def whoami(user: CurrentUser):
    return UserOut.model_validate(user)
