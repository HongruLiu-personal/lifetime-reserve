"""Pure report builders — format Slack-flavored summaries from run results.

Each run mode produces a fully formatted report string; `emit_report` prints it to
stdout wrapped in the protocol markers so the Slack server can extract it from the
subprocess output. No network, no I/O beyond the stdout print in `emit_report`.
"""

from datetime import date

from lifetime_reserve.protocol import REPORT_START, REPORT_END
from lifetime_reserve.slots import fmt_slots


def _upcoming_block(labels):
    if not labels:
        return "*Upcoming reservations:*\n• (none)"
    return "*Upcoming reservations:*\n" + "\n".join(f"• {l}" for l in labels)


def emit_report(text):
    """Print report to stdout with markers for the Slack server to extract."""
    print(f"\n{REPORT_START}\n{text}\n{REPORT_END}\n", flush=True)


def build_auto_report(status, target_date, booked_slot, day8_slots, reservation_labels):
    """status is one of: booked | already_reserved | no_courts | no_preferred | booking_failed."""
    today = date.today()
    date_label = target_date.strftime("%a %b %-d")
    parts = [f"*Auto-reserve · {today.strftime('%a %b %-d')}*", ""]
    if status == "booked":
        parts.append(f"*Booked:* {booked_slot['time']} {booked_slot['resourceName']} on {date_label}")
    elif status == "already_reserved":
        parts.append(f"*No booking on {date_label}* — already reserved that day")
    elif status == "no_courts":
        parts.append(f"*No booking on {date_label}* — no courts available")
    elif status == "no_preferred":
        parts.append(f"*No booking on {date_label}* — no preferred time available")
        if day8_slots:
            parts.append(f"Available: {fmt_slots(day8_slots)}")
    elif status == "booking_failed":
        parts.append(f"*No booking on {date_label}* — all retries failed (slot taken or API error)")
    parts += ["", _upcoming_block(reservation_labels)]
    return "\n".join(parts)


def build_slot_report(dt, booked_slot, reason, reservation_labels):
    today = date.today()
    date_label = dt.strftime("%a %b %-d")
    parts = [f"*Book slot · {today.strftime('%a %b %-d')}*", ""]
    if booked_slot is not None:
        parts.append(f"*Booked:* {booked_slot['time']} {booked_slot['resourceName']} on {date_label}")
    else:
        parts.append(f"*Failed to book {date_label} at {dt.strftime('%-I:%M %p')}* — {reason}")
    parts += ["", _upcoming_block(reservation_labels)]
    return "\n".join(parts)


def build_date_report(target_date, booked_slot, reason, day_slots, reservation_labels):
    today = date.today()
    date_label = target_date.strftime("%a %b %-d")
    parts = [f"*Book {date_label} · {today.strftime('%a %b %-d')}*", ""]
    if booked_slot is not None:
        parts.append(f"*Booked:* {booked_slot['time']} {booked_slot['resourceName']} on {date_label}")
    else:
        parts.append(f"*No booking on {date_label}* — {reason}")
        if day_slots:
            parts.append(f"Available: {fmt_slots(day_slots)}")
    parts += ["", _upcoming_block(reservation_labels)]
    return "\n".join(parts)


def build_list_report(reservation_labels):
    today = date.today()
    parts = [f"*Reservations · {today.strftime('%a %b %-d')}*", ""]
    parts.append(_upcoming_block(reservation_labels))
    return "\n".join(parts)


def build_cancel_report(target_date, cancelled_labels, found_count, reservation_labels):
    today = date.today()
    date_label = target_date.strftime("%a %b %-d")
    parts = [f"*Cancel · {today.strftime('%a %b %-d')}*", ""]
    if cancelled_labels:
        parts.append(f"*Cancelled on {date_label}:*")
        parts.extend(f"• {l}" for l in cancelled_labels)
    elif found_count:
        parts.append(f"*Cancel failed on {date_label}* — reservation found but the API rejected the request (see logs)")
    else:
        parts.append(f"*No reservation to cancel on {date_label}*")
    parts += ["", _upcoming_block(reservation_labels)]
    return "\n".join(parts)
