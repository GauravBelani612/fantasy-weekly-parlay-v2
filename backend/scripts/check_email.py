"""Prove the Resend configuration works before a real notification depends on it.

Worth doing deliberately, because a misconfigured key fails silently and destructively:
notify.py commits the notifications_log row *before* attempting the send, so a send that
fails is still recorded as sent and is never retried. A bad key on the night a round opens
means those emails are gone, not delayed.

Run with the same values Render has:

    # PowerShell
    $env:RESEND_API_KEY = 're_...'
    $env:EMAIL_FROM = 'WeeklyLay <parlay@weeklylay.com>'
    ./.venv/Scripts/python.exe scripts/check_email.py you@example.com

Checks the key, lists what Resend considers verified, then optionally sends one real email.
"""

import asyncio
import os
import sys

import httpx


async def main() -> int:
    key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("EMAIL_FROM", "")
    to = sys.argv[1] if len(sys.argv) > 1 else ""

    if not key:
        print("RESEND_API_KEY is not set.\n")
        print(__doc__)
        return 2
    print(f"RESEND_API_KEY   <{len(key)} chars>")

    if not sender:
        print("!! EMAIL_FROM is not set. Render must set it too, or the app falls back to")
        print("   'Parlay <onboarding@resend.dev>', which only ever delivers to you.")
        return 1
    print(f"EMAIL_FROM       {sender}")

    if "onboarding@resend.dev" in sender:
        print("\n!! EMAIL_FROM uses Resend's shared onboarding domain. That address only")
        print("   delivers to the Resend account owner -- your league would receive nothing,")
        print("   with no error. Use an address on your verified domain.")
        return 1

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://api.resend.com/domains", headers={"Authorization": f"Bearer {key}"}
        )
        if r.status_code == 401:
            print("\n!! Resend rejected the API key (401). It is wrong, or it was revoked.")
            return 1
        if r.status_code >= 400:
            print(f"\n!! Resend returned {r.status_code}: {r.text}")
            return 1

        domains = r.json().get("data", [])
        print("\nDomains Resend knows about:")
        if not domains:
            print("  (none) -- nothing is verified, so sending will fail.")
            return 1
        for d in domains:
            mark = "OK  " if d.get("status") == "verified" else "NOT "
            print(f"  {mark} {d.get('name')}  status={d.get('status')}")

        at = sender.split("@")[-1].rstrip(">").strip()
        if not any(d.get("name") == at and d.get("status") == "verified" for d in domains):
            print(f"\n!! EMAIL_FROM sends from '{at}', which is not a verified domain above.")
            return 1
        print(f"\nEMAIL_FROM's domain '{at}' is verified.")

        if not to:
            print("\nPass an address to send a real test email:")
            print("  ./.venv/Scripts/python.exe scripts/check_email.py you@example.com")
            return 0

        print(f"\nSending a test email to {to} ...")
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "from": sender,
                "to": [to],
                "subject": "WeeklyLay: notification test",
                "html": (
                    "<p>If you are reading this, WeeklyLay can send email: the API key is "
                    "good, the domain is verified, and the from-address is accepted.</p>"
                    "<p>This is the same path the round-opened and reminder emails use.</p>"
                ),
            },
        )
        if r.status_code >= 400:
            print(f"!! Resend rejected it: {r.status_code} {r.text}")
            return 1
        print(f"Accepted by Resend (id {r.json().get('id')}). Check the inbox, and spam.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
