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

Sending one real email is the only authoritative check, so that is what this does. The
domain listing beforehand is advisory: it needs a full-access key, while this app only
needs a sending key, so being refused there says nothing about whether mail will go out.
"""

import asyncio
import os
import sys

import httpx

DOMAINS = "https://api.resend.com/domains"
EMAILS = "https://api.resend.com/emails"


def _explain_bad_key(body: str) -> None:
    print(f"   Resend said: {body}")
    print("   Resend reveals a key's full value only once, at creation. A value copied")
    print("   from the dashboard afterwards is masked and can never work. If that is what")
    print("   happened, create a new key and save the value it shows you that one time.")


async def main() -> int:
    key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("EMAIL_FROM", "")
    to = sys.argv[1] if len(sys.argv) > 1 else ""

    if not key:
        print("RESEND_API_KEY is not set.\n")
        print(__doc__)
        return 2
    print(f"RESEND_API_KEY   <{len(key)} chars>")
    if key != key.strip():
        print("!! The key has leading or trailing whitespace. Strip it.")
        return 1

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

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=30) as client:
        # --- advisory: what does Resend consider verified? ---
        r = await client.get(DOMAINS, headers=headers)
        if r.status_code == 200:
            domains = r.json().get("data", [])
            print("\nDomains Resend knows about:")
            for d in domains:
                mark = "OK " if d.get("status") == "verified" else "NOT"
                print(f"  {mark}  {d.get('name')}  status={d.get('status')}")
            if not domains:
                print("  (none)")
            at = sender.split("@")[-1].rstrip(">").strip()
            verified = any(
                d.get("name") == at and d.get("status") == "verified" for d in domains
            )
            if domains and not verified:
                print(f"\n!! EMAIL_FROM sends from '{at}', which is not verified above.")
            elif verified:
                print(f"\nEMAIL_FROM's domain '{at}' is verified.")
        else:
            print(f"\nCould not list domains (HTTP {r.status_code}) -- skipping that check.")
            print("  A sending-only key is refused here and still sends fine, so this on its")
            print("  own means nothing. The send below is what actually decides.")

        # --- authoritative: actually send ---
        if not to:
            print("\nPass an address to send a real test email:")
            print("  ./.venv/Scripts/python.exe scripts/check_email.py you@example.com")
            return 0

        print(f"\nSending a test email to {to} ...")
        r = await client.post(
            EMAILS,
            headers=headers,
            json={
                "from": sender,
                "to": [to],
                "subject": "WeeklyLay: notification test",
                "html": (
                    "<p>If you are reading this, WeeklyLay can send email: the key is good, "
                    "the domain is verified, and the from-address is accepted.</p>"
                    "<p>This is the same path the round-opened and reminder emails use.</p>"
                ),
            },
        )

        if r.status_code in (400, 401, 403) and "api key" in r.text.lower():
            print(f"!! The API key is not valid for sending (HTTP {r.status_code}).")
            _explain_bad_key(r.text)
            return 1
        if r.status_code >= 400:
            print(f"!! Resend refused the send: HTTP {r.status_code}")
            print(f"   {r.text}")
            if "domain" in r.text.lower():
                print("   Looks like a domain problem: the from-address must be on a domain")
                print("   showing 'verified' in Resend, not merely added.")
            return 1

        print(f"Accepted by Resend (id {r.json().get('id')}). Check the inbox, and spam.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
