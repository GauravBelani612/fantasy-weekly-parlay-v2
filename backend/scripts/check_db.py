"""Validate a DATABASE_URL before pasting it into a deploy platform.

Every connection-string mistake produces a different confusing failure several minutes
into a remote build. This checks the same string locally in about two seconds, and names
the specific problem instead of making you read an asyncpg traceback.

Reads the URL from the environment so the password never lands in a file or an argument:

    # PowerShell
    $env:DATABASE_URL = 'postgresql+asyncpg://user:pass@host/neondb?ssl=require'
    ./.venv/Scripts/python.exe scripts/check_db.py
"""

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def describe(raw: str) -> tuple[str, list[str]]:
    """Print a masked breakdown and return (cleaned_url, problems)."""
    problems: list[str] = []

    if raw != raw.strip():
        # A trailing newline is invisible in every UI that would show you this string,
        # and it lands inside the database name: 'neondb\n' does not exist.
        problems.append("has leading/trailing whitespace -- strip it before pasting")
        raw = raw.strip()

    url = make_url(raw)
    query = dict(url.query)

    print(f"  driver   : {url.drivername}")
    print(f"  user     : {url.username}")
    print(f"  password : <{len(url.password or '')} chars>")
    print(f"  host     : {url.host}")
    print(f"  database : {url.database}")
    print(f"  query    : {query or '{}'}")
    print()

    if url.drivername != "postgresql+asyncpg":
        problems.append(f"driver is {url.drivername!r}, should be 'postgresql+asyncpg'")
    if "-pooler" in (url.host or ""):
        problems.append("host is the pooled endpoint -- use the direct one (app/db.py pools)")
    if "sslmode" in query:
        problems.append("asyncpg rejects 'sslmode' as an unknown kwarg -- use 'ssl' instead")
    if "channel_binding" in query:
        problems.append("'channel_binding' is not understood by asyncpg -- remove it")
    if query.get("ssl") != "require":
        problems.append("missing '?ssl=require' -- without it asyncpg falls back to plaintext")
    if not url.password:
        problems.append("no password in the URL")

    return raw, problems


async def probe(url: str) -> int:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("select version()"))).scalar_one()
            tables = (
                await conn.execute(
                    text(
                        "select count(*) from information_schema.tables "
                        "where table_schema = 'public'"
                    )
                )
            ).scalar_one()
        print("  CONNECTED")
        print(f"  {version.split(',')[0]}")
        print(f"  tables in public schema: {tables}")
        if tables == 0:
            print("  (empty -- alembic will create them on the next deploy)")
        return 0
    except Exception as exc:
        name = type(exc).__name__
        print(f"  FAILED: {name}: {exc}")
        hint = {
            "InvalidPasswordError": (
                "Wrong password for this host. If you recently made a new Neon project "
                "or reset the role password, copy the whole string fresh from that "
                "project -- do not paste an old password onto a new host."
            ),
            "InvalidCatalogNameError": (
                "The database name is wrong. A trailing newline is the usual cause: "
                "the name becomes 'neondb\\n'."
            ),
            "InvalidAuthorizationSpecificationError": (
                "Neon refused an insecure connection. Add '?ssl=require'."
            ),
        }.get(name)
        if hint:
            print(f"  -> {hint}")
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        print(__doc__)
        return 2

    print("\nURL breakdown:")
    cleaned, problems = describe(raw)

    if problems:
        print("Problems found:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix these first; not attempting a connection.")
        return 1

    print("Shape looks right. Connecting...")
    return asyncio.run(probe(cleaned))


if __name__ == "__main__":
    sys.exit(main())
