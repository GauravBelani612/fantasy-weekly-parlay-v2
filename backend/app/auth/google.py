"""Google Identity Services ID token verification.

The browser gets an ID token from the GIS button and posts it here; we verify it against
Google's public certs and then mint our own session cookie. No third-party auth service.
"""

from dataclasses import dataclass

from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from starlette.concurrency import run_in_threadpool

from app.config import settings

_VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    name: str
    picture: str | None


def _verify_sync(token: str) -> dict:
    # Blocking: fetches and caches Google's signing certs.
    return google_id_token.verify_oauth2_token(
        token, google_requests.Request(), settings.google_client_id
    )


async def verify_google_id_token(token: str) -> GoogleProfile:
    if not settings.google_client_id:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "GOOGLE_CLIENT_ID is not configured on the server",
        )

    try:
        claims = await run_in_threadpool(_verify_sync, token)
    except ValueError as exc:  # bad signature, wrong audience, expired
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid Google token: {exc}") from exc

    if claims.get("iss") not in _VALID_ISSUERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token issuer")
    if not claims.get("email_verified"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google email is not verified")

    email = claims.get("email")
    sub = claims.get("sub")
    if not email or not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google token missing email or subject")

    return GoogleProfile(
        sub=sub,
        email=email.lower(),
        name=claims.get("name") or email.split("@")[0],
        picture=claims.get("picture"),
    )
