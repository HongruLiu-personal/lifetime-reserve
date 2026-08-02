"""Pure command/date parsing for the Slack layer — no network, no I/O.

Turns Slack command text into `reserve.py` CLI args, used by the Events API dispatcher
(`@mention` in channel + DM).
"""

import re
from datetime import date, datetime, timedelta

WEEKDAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
WEEKDAY_PATTERN = re.compile(
    r"\b(monday|mon|tuesday|tue|wednesday|wed|thursday|thu|friday|fri|saturday|sat|sunday|sun)\b",
    re.IGNORECASE,
)


def strip_mention(text: str) -> str:
    """Remove a leading <@USERID> mention from app_mention text."""
    return re.sub(r"^\s*<@[A-Z0-9]+>\s*", "", text)


def parse_date_token(text):
    """Return a date parsed from `text`: either YYYY-MM-DD or a weekday name.
    Same-weekday-as-today rolls forward 7 days (since same-day booking isn't allowed)."""
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    m = WEEKDAY_PATTERN.search(text)
    if m:
        target_wd = WEEKDAY_MAP[m.group(1).lower()]
        today = date.today()
        delta = (target_wd - today.weekday()) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    return None


def parse_command_text(text):
    """Parse Slack command text into (args, label, verbose).

    Append 'verbose' to the command to see full log output.
    Date can be YYYY-MM-DD or a weekday name (Mon, Tuesday, etc.).
    Returns (None, error_message, False) on parse failure.
    """
    text = text.strip()
    verbose = bool(re.search(r"\bverbose\b", text, re.IGNORECASE))
    text = re.sub(r"\bverbose\b", "", text, flags=re.IGNORECASE).strip()

    if not text:
        return ["--auto"], "Auto-reserve (day 8)", verbose

    target_date = parse_date_token(text)
    date_str = target_date.strftime("%Y-%m-%d") if target_date else None
    date_label = target_date.strftime("%a %b %-d") if target_date else None

    time_m = re.search(r"\b(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\b", text)
    time_str = None
    if time_m:
        raw = time_m.group(1).strip()
        try:
            fmt = "%I:%M%p" if re.search(r"[AaPp][Mm]", raw) else "%H:%M"
            time_str = datetime.strptime(raw.upper().replace(" ", ""), fmt).strftime("%H:%M")
        except ValueError:
            pass

    if date_str and time_str:
        return ["--slot", f"{date_str} {time_str}"], f"Book {date_label} at {time_str}", verbose
    if date_str:
        return ["--date", date_str], f"Book best slot on {date_label}", verbose
    return None, (
        f'Could not parse: `{text}`\n'
        "Usage (@mention me or DM me): `reserve`, `reserve <date>`, or "
        "`reserve <date> HH:MM`\n"
        "Date can be `YYYY-MM-DD` or a weekday name (`Mon`, `Tuesday`, ...)"
    ), False
