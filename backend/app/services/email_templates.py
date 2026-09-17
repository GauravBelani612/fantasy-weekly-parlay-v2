"""HTML for the notification emails.

Email is not the web. Gmail strips <style> blocks in forwarded and clipped messages,
Outlook's renderer has no flexbox or grid, and custom fonts are ignored almost everywhere.
So everything here is table-based with fully inline styles and system font stacks.

The body is light on purpose even though the app is dark: several clients auto-invert dark
emails and produce unreadable results. The brand lives in a dark header bar instead, which
survives inversion intact.

Every caller-supplied string is escaped -- league names, display names and leg text all
come from Sleeper or from what someone typed.
"""

from html import escape

# Kept close to the app's palette, with the green darkened where it sits on white.
INK = "#16202a"
MUTED = "#5d6b79"
RULE = "#e3e8ed"
PAGE = "#edf1f4"
CARD = "#ffffff"
DARK = "#0b0e11"
BRAND = "#00944f"
BRAND_BRIGHT = "#03e786"
BUTTON = "#01c46e"
BUTTON_INK = "#052b1a"

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"


def _button(label: str, url: str) -> str:
    """A link styled as a button. Not a <button> -- clients strip form elements."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:24px 0 4px;"><tr><td style="border-radius:6px;background:{BUTTON};">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:13px 26px;'
        f'font-family:{FONT};font-size:15px;font-weight:700;color:{BUTTON_INK};'
        f'text-decoration:none;border-radius:6px;">{escape(label)}</a>'
        f"</td></tr></table>"
    )


def shell(preheader: str, heading: str, body: str, league_name: str) -> str:
    """Wrap content in the branded frame.

    `preheader` is the grey line an inbox shows next to the subject. Left unset, clients
    scrape the first words of the body instead, which is usually the wordmark.
    """
    return f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{PAGE};padding:24px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           style="width:100%;max-width:600px;background:{CARD};border-radius:10px;overflow:hidden;">

      <tr><td style="background:{DARK};padding:18px 28px;">
        <span style="font-family:{FONT};font-size:19px;font-weight:800;letter-spacing:-0.2px;
                     color:#ffffff;">Weekly<span style="color:{BRAND_BRIGHT};">Lay</span></span>
        <span style="font-family:{FONT};font-size:12px;color:#7d8892;float:right;
                     padding-top:6px;">{escape(league_name.strip())}</span>
      </td></tr>

      <tr><td style="padding:30px 28px 32px;">
        <h1 style="margin:0 0 18px;font-family:{FONT};font-size:22px;line-height:1.3;
                   font-weight:700;color:{INK};">{escape(heading)}</h1>
        {body}
      </td></tr>

      <tr><td style="background:#f7f9fb;border-top:1px solid {RULE};padding:16px 28px;">
        <p style="margin:0;font-family:{FONT};font-size:12px;line-height:1.5;color:{MUTED};">
          You get this because you are in {escape(league_name.strip())} on WeeklyLay.
          The low scorer funds the parlay, everyone adds one leg.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def _p(text: str, size: int = 15) -> str:
    return (
        f'<p style="margin:0 0 14px;font-family:{FONT};font-size:{size}px;'
        f'line-height:1.6;color:{INK};">{text}</p>'
    )


def _callout(label: str, value: str, note: str = "") -> str:
    """A single figure worth pulling out of the prose."""
    extra = (
        f'<div style="font-family:{FONT};font-size:13px;color:{MUTED};'
        f'padding-top:2px;">{escape(note)}</div>'
        if note
        else ""
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 18px;background:#f4faf6;border-left:3px solid {BRAND};'
        f'border-radius:0 6px 6px 0;"><tr><td style="padding:14px 16px;">'
        f'<div style="font-family:{FONT};font-size:11px;letter-spacing:0.8px;'
        f'text-transform:uppercase;color:{BRAND};font-weight:700;">{escape(label)}</div>'
        f'<div style="font-family:{FONT};font-size:19px;font-weight:700;color:{INK};'
        f'padding-top:3px;">{escape(value)}</div>{extra}'
        f"</td></tr></table>"
    )


def scoreboard(rows: list[tuple[str, float]], loser_name: str) -> str:
    """Every roster's score for the week, lowest first.

    The interesting part of losing is usually how close it was, and the scores are already
    cached for the calculation, so showing them costs nothing.
    """
    if not rows:
        return ""
    out = [
        f'<div style="font-family:{FONT};font-size:11px;letter-spacing:0.8px;'
        f'text-transform:uppercase;color:{MUTED};font-weight:700;margin:22px 0 8px;">'
        f"Week scores</div>",
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="border-collapse:collapse;">',
    ]
    for i, (name, pts) in enumerate(rows):
        low = name == loser_name
        bg = "#f4faf6" if low else ("#ffffff" if i % 2 else "#fafbfc")
        weight = "700" if low else "400"
        colour = INK if low else MUTED
        bar = f"border-left:3px solid {BRAND};" if low else "border-left:3px solid transparent;"
        tag = (
            f' <span style="font-size:11px;color:{BRAND};font-weight:700;">PAYS</span>'
            if low
            else ""
        )
        out.append(
            f'<tr style="background:{bg};">'
            f'<td style="{bar}padding:7px 10px;font-family:{FONT};font-size:14px;'
            f'font-weight:{weight};color:{colour};">{escape(name)}{tag}</td>'
            f'<td align="right" style="padding:7px 10px;font-family:{MONO};font-size:14px;'
            f'font-weight:{weight};color:{colour};">{pts:.2f}</td></tr>'
        )
    out.append("</table>")
    return "".join(out)


def leg_list(legs: list[tuple[str, str]]) -> str:
    """Numbered legs with the person who picked each."""
    if not legs:
        return _p(f'<span style="color:{MUTED};">No legs were submitted.</span>')
    rows = []
    for i, (text, who) in enumerate(legs, 1):
        rows.append(
            f'<tr><td valign="top" style="padding:8px 10px 8px 0;font-family:{MONO};'
            f'font-size:13px;color:{BRAND};font-weight:700;width:22px;">{i}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid {RULE};">'
            f'<div style="font-family:{FONT};font-size:15px;color:{INK};">{escape(text)}</div>'
            f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};padding-top:2px;">'
            f"{escape(who)}</div></td></tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="border-collapse:collapse;margin:4px 0 8px;">'
        + "".join(rows)
        + "</table>"
    )


def copy_block(legs: list[tuple[str, str]]) -> str:
    """The legs as plain lines, for pasting into a sportsbook without the names."""
    if not legs:
        return ""
    lines = "<br>".join(escape(text) for text, _ in legs)
    return (
        f'<div style="font-family:{FONT};font-size:11px;letter-spacing:0.8px;'
        f'text-transform:uppercase;color:{MUTED};font-weight:700;margin:22px 0 8px;">'
        f"Plain list to copy</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="background:#f7f9fb;border:1px solid {RULE};border-radius:6px;'
        f'padding:14px 16px;font-family:{MONO};font-size:13px;line-height:1.8;color:{INK};">'
        f"{lines}</td></tr></table>"
    )


def progress(submitted: int, eligible: int) -> str:
    if not eligible:
        return ""
    return _p(
        f'<span style="color:{MUTED};">'
        f"<strong style=\"color:{INK};\">{submitted} of {eligible}</strong> legs are in."
        f"</span>",
        size=14,
    )


# ---------------------------------------------------------------- the four emails


def round_opened(
    league_name: str,
    loser_name: str,
    loser_points: float | None,
    scored_week: int,
    bet_week: int,
    deadline: str,
    scores: list[tuple[str, float]],
    url: str,
) -> str:
    pts = f"{loser_points:.2f} pts" if loser_points is not None else "lowest score"
    body = (
        _callout(
            "Funding this week",
            loser_name,
            f"{pts} in week {scored_week}, lowest in the league",
        )
        + _p(f"Everyone adds one leg to the week {bet_week} parlay.")
        + _callout("Your leg is due", deadline, "60 minutes before the first kickoff")
        + _button("Submit your leg", url)
        + scoreboard(scores, loser_name)
    )
    return shell(
        preheader=f"{loser_name} was low scorer. Your week {bet_week} leg is due {deadline}.",
        heading=f"Week {scored_week} is settled",
        body=body,
        league_name=league_name,
    )


def reminder(
    league_name: str,
    loser_name: str,
    bet_week: int,
    deadline: str,
    missing_names: list[str],
    submitted: int,
    eligible: int,
    url: str,
) -> str:
    others = [n for n in missing_names]
    if len(others) > 1:
        tail = f"You are one of {len(others)} still to submit."
    else:
        tail = "You are the last one."

    body = (
        _p(f"Your leg for the week {bet_week} parlay is still missing.")
        + _callout("Legs lock", deadline, tail)
        + progress(submitted, eligible)
        + _p(
            f'<span style="color:{MUTED};">'
            f"{escape(loser_name)} is funding this one. Miss the deadline and the parlay "
            f"goes in without you.</span>",
            size=14,
        )
        + _button("Add your leg", url)
    )
    return shell(
        preheader=f"Locks {deadline}. {submitted} of {eligible} legs are in.",
        heading="Still need your leg",
        body=body,
        league_name=league_name,
    )


def legs_ready(
    league_name: str,
    loser_name: str,
    bet_week: int,
    deadline: str,
    legs: list[tuple[str, str]],
    url: str,
    locked: bool,
    missing_names: list[str],
    is_payer: bool = True,
) -> str:
    """The finished parlay.

    Everyone who put a leg in gets to see what it became, so this serves two audiences.
    The payer is being told to go and place it; everyone else is being shown the result.
    Only the payer gets the copy block, since only they are pasting it anywhere.
    """
    count = len(legs)

    if locked:
        heading = f"Week {bet_week} parlay is locked"
        if is_payer:
            intro = _p(f"Final list, {count} legs. Nothing can change now.")
        else:
            intro = _p(
                f"Final list, {count} legs. "
                f"{escape(loser_name)} is placing it."
            )
        if missing_names:
            names = ", ".join(escape(n) for n in missing_names)
            intro += _p(
                f'<span style="color:{MUTED};">Did not submit: {names}</span>', size=14
            )
        pre = (
            f"{count} legs, final. You are placing this one."
            if is_payer
            else f"{count} legs, final. {loser_name} is placing it."
        )
    else:
        if is_payer:
            heading = "Everyone is in"
            intro = _p(
                f"All {count} legs are in with time to spare, so you can place it now "
                f"rather than waiting for {escape(deadline)}."
            )
            pre = f"All {count} legs are in early. Ready to place."
        else:
            heading = "The parlay is set"
            intro = _p(
                f"All {count} legs are in. {escape(loser_name)} is funding it and will "
                f"place it before {escape(deadline)}."
            )
            pre = f"All {count} legs are in. Here is the full parlay."

    callout = (
        _callout("You are funding this", loser_name, f"Week {bet_week} parlay")
        if is_payer
        else _callout("Funding this week", loser_name, f"Week {bet_week} parlay")
    )

    body = intro + callout + leg_list(legs)
    if is_payer:
        body += copy_block(legs)
    body += _button("Open the board", url)

    return shell(preheader=pre, heading=heading, body=body, league_name=league_name)


# ---------------------------------------------------------------- settling the parlay

# Result -> (label, text colour, background). Void is neutral: the leg's player didn't
# sportsbook both simply drop out of the parlay.
_RESULT_CHIPS = {
    "hit": ("HIT", "#00794a", "#e3f5eb"),
    "miss": ("MISS", "#b42318", "#fdeceb"),
    "void": ("VOID", "#5d6b79", "#eef1f4"),
}


def _result_chip(result: str) -> str:
    label, fg, bg = _RESULT_CHIPS.get(result, ("OPEN", "#8a96a3", "#f2f4f6"))
    return (
        f'<span style="display:inline-block;padding:3px 7px;border-radius:4px;'
        f"font-family:{MONO};font-size:11px;font-weight:700;letter-spacing:0.4px;"
        f'color:{fg};background:{bg};">{label}</span>'
    )


def graded_leg_list(legs: list[tuple[str, str, str, str | None]]) -> str:
    """Each leg with its result and the stat that decided it: (text, who, result, detail)."""
    rows = []
    for text, who, result, detail in legs:
        why = (
            f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};padding-top:3px;">'
            f"{escape(detail)}</div>"
            if detail
            else ""
        )
        rows.append(
            f'<tr><td valign="top" style="padding:10px 12px 10px 0;width:52px;">'
            f"{_result_chip(result)}</td>"
            f'<td style="padding:10px 0;border-bottom:1px solid {RULE};">'
            f'<div style="font-family:{FONT};font-size:15px;color:{INK};">{escape(text)}</div>'
            f'<div style="font-family:{FONT};font-size:12px;color:{MUTED};padding-top:2px;">'
            f"{escape(who)}</div>{why}</td></tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="border-collapse:collapse;margin:4px 0 8px;">'
        + "".join(rows)
        + "</table>"
    )


def parlay_resolved(
    league_name: str,
    loser_name: str,
    bet_week: int,
    outcome: str,
    legs: list[tuple[str, str, str, str | None]],
    url: str,
) -> str:
    """The parlay has settled. Sent to the whole league: everyone put a leg in."""
    count = len(legs)
    hits = sum(1 for _, _, result, _ in legs if result == "hit")
    dropped = sum(1 for _, _, result, _ in legs if result == "void")

    if outcome == "lost":
        misses = [leg for leg in legs if leg[2] == "miss"]
        text, who, _, detail = misses[0]
        heading = f"Week {bet_week} parlay busted"
        # Leads with the leg that sank it -- the thing everyone opens this to find out.
        lead = _callout("Sunk by", f"{who}: {text}", detail or "")
        if len(misses) > 1:
            lead += _p(
                f'<span style="color:{MUTED};">{len(misses)} legs missed in all.</span>',
                size=14,
            )
        intro = _p(f"{hits} of {count} legs hit before it went down.")
        pre = f"Busted by {who}'s {text}."
    elif outcome == "won":
        heading = f"Week {bet_week} parlay cashed"
        note = f"{dropped} voided and dropped out" if dropped else "Clean sweep"
        lead = _callout("Every leg came in", f"{hits} of {hits} hit", note)
        intro = _p(f"{escape(loser_name)} funded it, and it paid.")
        pre = f"All {hits} legs hit. Week {bet_week} cashed."
    else:
        heading = f"Week {bet_week} parlay voided"
        lead = ""
        intro = _p("Every leg was voided, so there was no parlay left to settle.")
        pre = f"Week {bet_week} parlay voided."

    body = intro + lead + graded_leg_list(legs) + _button("Open the board", url)
    return shell(preheader=pre, heading=heading, body=body, league_name=league_name)
