#!/usr/bin/env python3
"""
Lifetime Fitness Pickleball Court Auto-Reservation

Modes:
  Interactive (default): choose date, time, and court interactively
  Auto:                  book best slot automatically (for scheduled runs)
  Dry-run:               show available slots without booking
  Slot:                  book a specific date/time directly (no prompts)

Usage:
    .venv/bin/python reserve.py                              # interactive
    .venv/bin/python reserve.py --auto                       # auto-book day 8 only (default)
    .venv/bin/python reserve.py --auto --fallback            # auto-book day 8, then scan days 1–7
    .venv/bin/python reserve.py --dry-run                    # show slots only
    .venv/bin/python reserve.py --slot "2026-03-16 04:30"   # book specific slot (24h)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

CONFIG_FILE = "config.json"
API_BASE = "https://api.lifetimefitness.com"
APIM_KEY = "924c03ce573d473793e184219a6a19bd"
ORIGIN = "https://my.lifetime.life"
HTTP_TIMEOUT = (5, 10)  # (connect, read) in seconds
LOG_DIR = Path(__file__).resolve().parent / "logs"

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)


def setup_file_logging():
    """Add a FileHandler that writes to logs/YYYY-MM-DD.log (append mode)."""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{date.today().strftime('%Y-%m-%d')}.log"
    fh = logging.FileHandler(log_file, mode="a")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(fh)


# ── Configuration ──────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def validate_config(config):
    required = ["username", "password", "club_id", "sport", "duration", "days_ahead"]
    missing = [k for k in required if k not in config]
    if missing:
        log.error("Missing required config keys: %s", ", ".join(missing))
        sys.exit(1)


# ── HTTP session ───────────────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update({
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "origin": ORIGIN,
        "ocp-apim-subscription-key": APIM_KEY,
    })
    return s


# ── API calls ──────────────────────────────────────────────────────────────────

def login(session, username, password):
    resp = session.post(
        f"{API_BASE}/auth/v2/login",
        json={"username": username, "password": password},
        headers={"content-type": "application/json; charset=UTF-8"},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "0":
        raise RuntimeError(f"Login failed: {data}")
    log.info("Logged in as %s", data["username"])
    return data["token"], data["ssoId"]


def auth_headers(token, sso_id):
    return {"x-ltf-jwe": token, "x-ltf-ssoid": sso_id}


def search_courts(session, token, sso_id, club_id, sport, target_date, duration):
    resp = session.get(
        f"{API_BASE}/ux/web-schedules/v2/resources/booking/search",
        params={
            "homeClub": club_id,
            "clubId": club_id,
            "sport": sport,
            "date": target_date.strftime("%Y-%m-%d"),
            "startTime": "-1",
            "duration": str(duration),
        },
        headers=auth_headers(token, sso_id),
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_reservations_list(session, token, sso_id, member_ids, start_date, end_date):
    """Return list of {date_str, reg_id, label} dicts sorted by date."""
    params = [
        ("start", start_date.strftime("%-m/%-d/%Y")),
        ("end", end_date.strftime("%-m/%-d/%Y")),
        ("groupCamps", "true"),
        ("pageSize", "0"),
    ]
    for mid in member_ids:
        params.append(("memberIds", str(mid)))
    resp = session.get(
        f"{API_BASE}/ux/web-schedules/v3/reservations",
        params=params,
        headers=auth_headers(token, sso_id),
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    out = []
    for item in sorted(resp.json().get("results", []), key=lambda x: x.get("start", "")):
        start = item.get("start", "")
        if not start:
            continue
        reg_id = item.get("regId") or item.get("registrationId") or item.get("id")
        # Extract the attendee id used by the cancel endpoint. The reservations
        # API exposes it under registration.registeredMembers[].cancelCtas (the
        # online CTA) — the top-level id is NOT accepted by the cancel endpoint.
        attendee_id = None
        for member in (item.get("registration", {}) or {}).get("registeredMembers", []):
            attendee_id = member.get("attendeeId") or attendee_id
            for cta in member.get("cancelCtas", []):
                if cta.get("method") == "online" and cta.get("registrationId"):
                    attendee_id = cta["registrationId"]
                    break
            if attendee_id:
                break
        try:
            dt = datetime.fromisoformat(start[:19])
            date_label = dt.strftime("%a %b %-d")
            time_label = dt.strftime("%-I:%M %p")
        except Exception:
            date_label = start[:10]
            time_label = ""
        raw_loc = item.get("location") or item.get("resourceName") or ""
        if " | " in raw_loc:
            raw_loc = raw_loc.split(" | ")[-1].split(",")[0].strip()
        court = raw_loc.strip()
        label = f"{date_label} — {time_label}" + (f", {court}" if court else "")
        out.append({"date_str": start[:10], "reg_id": reg_id,
                    "attendee_id": attendee_id, "label": label})
    return out


def get_reserved_dates(session, token, sso_id, member_ids, start_date, end_date):
    """Return (date_set, label_list) for existing reservations in the date range."""
    reservations = get_reservations_list(session, token, sso_id, member_ids, start_date, end_date)
    reserved = {r["date_str"] for r in reservations}
    labels = [r["label"] for r in reservations]
    return reserved, labels


def raise_for_status_with_body(resp):
    """Like raise_for_status() but includes the response body in the exception message."""
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body = resp.text[:500] if resp.text else "(empty)"
        raise requests.HTTPError(f"{e} — body: {body}", response=resp) from None


def book_court(session, token, sso_id, resource_id, start, duration):
    """Create a booking and immediately complete it (accept waiver)."""
    resp = session.post(
        f"{API_BASE}/sys/registrations/V3/ux/resource",
        json={
            "resourceId": resource_id,
            "start": start,
            "service": None,
            "duration": str(duration),
        },
        headers={**auth_headers(token, sso_id), "content-type": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    raise_for_status_with_body(resp)
    booking = resp.json()

    # Complete the booking (accept waiver) — moves from pending → completed
    reg_id = booking.get("regId")
    agreement_id = booking.get("agreement", {}).get("agreementId")
    if reg_id and agreement_id and not booking.get("registrationType", {}).get("skipConfirmation", True):
        complete_resp = session.put(
            f"{API_BASE}/sys/registrations/V3/ux/resource/{reg_id}/complete",
            json={"acceptedDocuments": [int(agreement_id)]},
            headers={**auth_headers(token, sso_id), "content-type": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        try:
            raise_for_status_with_body(complete_resp)
            booking["regStatus"] = "completed"
        except requests.HTTPError as e:
            # Booking exists but waiver confirmation failed — slot is ours (pending).
            # Don't raise: returning here stops the retry loop from re-booking the same slot.
            log.warning("Booking created (regId=%s) but /complete failed: %s", reg_id, e)
            log.warning("Slot is pending — check your reservations page manually")

    return booking


# ── Slot utilities ─────────────────────────────────────────────────────────────

def collect_slots(search_result):
    slots = []
    for part in search_result.get("results", {}).get("dayParts", []):
        for slot in part.get("availableTimes", []):
            slot["_part"] = part["name"]
            slots.append(slot)
    return slots


def to_api_time(hhmm_24h):
    """Convert '04:30' (24h) to '4:30 AM' (API time format)."""
    return datetime.strptime(hhmm_24h, "%H:%M").strftime("%-I:%M %p")


def auto_pick(slots, preferred_times, preferred_courts):
    """Pick best slot by preferred time then preferred court. Returns None if no match."""
    def court_rank(slot):
        name = slot.get("resourceName", "")
        try:
            return preferred_courts.index(name)
        except ValueError:
            return len(preferred_courts)

    for pref_time in preferred_times:
        candidates = [s for s in slots if s["time"] == pref_time]
        if candidates:
            candidates.sort(key=court_rank)
            return candidates[0]

    log.warning("No slots available at preferred times — skipping booking")
    return None


def pick_by_time(slots, api_time):
    """Return first available slot matching api_time (e.g. '4:30 AM')."""
    return next((s for s in slots if s["time"] == api_time), None)


def fmt_slots(slots):
    return ", ".join(f"{s['time']} {s['resourceName']}" for s in slots)


# ── Report emission ────────────────────────────────────────────────────────────
# server.py extracts text between these markers from stdout to build the Slack
# details message. Any run mode that completes calls emit_report() with a fully
# formatted Slack-flavored report.

REPORT_START = "<<<REPORT>>>"
REPORT_END = "<<<ENDREPORT>>>"


def _upcoming_block(labels):
    if not labels:
        return "*Upcoming reservations:*\n• (none)"
    return "*Upcoming reservations:*\n" + "\n".join(f"• {l}" for l in labels)


def _fetch_upcoming(session, token, sso_id, config):
    """Fetch upcoming reservation labels for the horizon. Empty list on error / no member_ids."""
    member_ids = config.get("member_ids", [])
    if not member_ids:
        return []
    days_ahead = config.get("days_ahead", 8)
    today = date.today()
    try:
        _, labels = get_reserved_dates(
            session, token, sso_id, member_ids,
            today + timedelta(days=1),
            today + timedelta(days=days_ahead),
        )
        return labels
    except Exception as e:
        log.warning("Could not fetch upcoming reservations: %s", e)
        return []


def emit_report(text):
    """Print report to stdout with markers for server.py to extract."""
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


def send_slack(config, text):
    """Post a message to the configured Slack channel via bot API. Failures are logged, not raised."""
    token = config.get("slack_bot_token", "")
    channel = config.get("slack_channel", "")
    if not token or not channel:
        return
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": channel, "text": text},
            timeout=(5, 10),
        )
        data = resp.json()
        if not data.get("ok"):
            log.warning("Slack notification failed: %s", data.get("error"))
        else:
            log.info("Slack notification sent")
    except Exception as e:
        log.warning("Slack notification failed: %s", e)


# ── Interactive prompts ────────────────────────────────────────────────────────

def prompt_date(days_ahead):
    print("\nWhich date would you like to book?")
    today = date.today()
    options = [today + timedelta(days=i) for i in range(1, 15)]
    for i, d in enumerate(options, 1):
        marker = " (default)" if (d - today).days == days_ahead else ""
        print(f"  {i}) {d.strftime('%A %Y-%m-%d')}{marker}")
    print(f"  or press Enter for default (+{days_ahead} days = {today + timedelta(days=days_ahead)})")

    while True:
        raw = input("Choice: ").strip()
        if raw == "":
            return today + timedelta(days=days_ahead)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  Invalid — enter a number or press Enter.")


def prompt_slot(slots):
    if not slots:
        return None
    print("\nAvailable slots:")
    for i, s in enumerate(slots, 1):
        print(f"  {i}) {s['time']:>10}  {s['resourceName']}")
    while True:
        raw = input("Choose a slot (number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(slots):
            return slots[int(raw) - 1]
        print("  Invalid — enter a number from the list.")


# ── Mode handlers ──────────────────────────────────────────────────────────────

def run_interactive(session, token, sso_id, config):
    club_id = config.get("club_id", "36")
    sport = config.get("sport", "Pickleball: Indoor")
    duration = config.get("duration", 60)
    days_ahead = config.get("days_ahead", 8)

    target_date = prompt_date(days_ahead)
    log.info("Searching courts for %s ...", target_date.strftime("%A %Y-%m-%d"))
    result = search_courts(session, token, sso_id, club_id, sport, target_date, duration)
    slots = collect_slots(result)
    if not slots:
        log.info("No courts available for %s", target_date)
        sys.exit(0)

    slot = prompt_slot(slots)
    if slot is None:
        print("No slot selected.")
        sys.exit(0)

    print(f"\nSelected: {slot['time']} — {slot['resourceName']}")
    if input("Confirm booking? [y/N] ").strip().lower() != "y":
        print("Cancelled.")
        return

    log.info("Booking %s %s ...", slot["time"], slot["resourceName"])
    booking = book_court(session, token, sso_id, slot["resourceId"], slot["start"], duration)
    log.info("Confirmed: regId=%s, status=%s, location=%s",
             booking["regId"], booking["regStatus"], booking.get("location", ""))


def run_slot(session, token, sso_id, config, slot_datetime_str):
    """Book a specific date/time directly. Returns (dt, booked_slot_or_None, reason_or_None)."""
    try:
        dt = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M")
    except ValueError:
        log.error("Invalid --slot format. Use: YYYY-MM-DD HH:MM (e.g. '2026-03-16 04:30')")
        sys.exit(1)

    target_date = dt.date()
    api_time = to_api_time(dt.strftime("%H:%M"))
    club_id = config.get("club_id", "36")
    sport = config.get("sport", "Pickleball: Indoor")
    duration = config.get("duration", 60)

    log.info("Searching courts for %s at %s ...", target_date.strftime("%A %Y-%m-%d"), api_time)
    try:
        result = search_courts(session, token, sso_id, club_id, sport, target_date, duration)
        slots = collect_slots(result)
    except Exception as e:
        log.error("Search failed: %s", e)
        return dt, None, f"search failed: {e}"

    slot = pick_by_time(slots, api_time)
    if slot is None:
        available = fmt_slots(slots) if slots else "none"
        log.error("No slot available at %s. Available: %s", api_time, available)
        return dt, None, f"slot not available (options: {available})"

    log.info("Booking %s %s ...", slot["time"], slot["resourceName"])
    try:
        booking = book_court(session, token, sso_id, slot["resourceId"], slot["start"], duration)
        log.info("Confirmed: regId=%s, status=%s, location=%s",
                 booking["regId"], booking["regStatus"], booking.get("location", ""))
        return dt, slot, None
    except Exception as e:
        log.error("Booking failed: %s", e)
        return dt, None, f"booking failed: {e}"


def run_auto(session, token, sso_id, config, fallback=False):
    club_id = config.get("club_id", "36")
    sport = config.get("sport", "Pickleball: Indoor")
    duration = config.get("duration", 60)
    days_ahead = config.get("days_ahead", 8)
    preferred_times = config.get("preferred_times", [])
    preferred_courts = config.get("preferred_courts", [])
    retry_count = config.get("retry_count", 3)
    retry_delay = config.get("retry_delay_seconds", 10)

    today = date.today()
    member_ids = config.get("member_ids", [])
    reserved_dates = set()
    reservation_labels = []

    if member_ids:
        reserved_dates, reservation_labels = get_reserved_dates(
            session, token, sso_id, member_ids,
            today + timedelta(days=1),
            today + timedelta(days=days_ahead),
        )
        log.info("Already reserved dates: %s", sorted(reserved_dates) or "none")
    else:
        log.warning("member_ids not in config — skipping reservation check")

    def try_date(target_date):
        """Search and book a single date. Returns the booked slot dict, or None if skipped/no slot."""
        date_str = target_date.strftime("%Y-%m-%d")
        if date_str in reserved_dates:
            log.info("Skipping %s — already have a reservation", date_str)
            return None

        log.info("Searching %s ...", target_date.strftime("%A %Y-%m-%d"))
        result = search_courts(session, token, sso_id, club_id, sport, target_date, duration)
        slots = collect_slots(result)

        if not slots:
            log.info("No courts available on %s", date_str)
            return None

        log.info("Available: %s", fmt_slots(slots))

        slot = auto_pick(slots, preferred_times, preferred_courts)
        if slot is None:
            log.info("No preferred slot on %s", date_str)
            return None

        log.info("Booking %s %s ...", slot["time"], slot["resourceName"])
        booking = book_court(session, token, sso_id, slot["resourceId"], slot["start"], duration)
        log.info("Confirmed: regId=%s, status=%s, location=%s",
                 booking["regId"], booking["regStatus"], booking.get("location", ""))
        return slot

    # Priority 1: day 8 — search once, then retry only the booking step
    # Retrying book (not search) on 5xx means we keep the slot locked across attempts
    # rather than re-competing after each server error.
    day8 = today + timedelta(days=days_ahead)
    day8_str = day8.strftime("%Y-%m-%d")

    if day8_str in reserved_dates:
        log.info("Day %d (%s) already reserved — skipping booking attempt", days_ahead, day8_str)
        return {"status": "already_reserved", "target_date": day8, "booked_slot": None,
                "day8_slots": [], "reservation_labels": reservation_labels}

    log.info("Searching %s ...", day8.strftime("%A %Y-%m-%d"))
    try:
        result = search_courts(session, token, sso_id, club_id, sport, day8, duration)
        day8_slots = collect_slots(result)
    except Exception as e:
        log.error("Search failed for %s: %s", day8_str, e)
        day8_slots = []

    slot = None
    slot_picked_initially = False
    if day8_slots:
        log.info("Available: %s", fmt_slots(day8_slots))
        slot = auto_pick(day8_slots, preferred_times, preferred_courts)
        if slot is None:
            log.info("No preferred slot on %s", day8_str)
        else:
            slot_picked_initially = True
    else:
        log.info("No courts available on %s", day8_str)

    booked_slot = None
    booked_date = None

    if slot is not None:
        for attempt in range(1, retry_count + 1):
            if attempt > 1:
                log.info("Day %d booking retry %d/%d in %ds ...",
                         days_ahead, attempt, retry_count, retry_delay)
                time.sleep(retry_delay)
            try:
                log.info("Booking %s %s (attempt %d/%d) ...",
                         slot["time"], slot["resourceName"], attempt, retry_count)
                booking = book_court(session, token, sso_id,
                                     slot["resourceId"], slot["start"], duration)
                log.info("Confirmed: regId=%s, status=%s, location=%s",
                         booking["regId"], booking["regStatus"], booking.get("location", ""))
                booked_slot = slot
                booked_date = day8
                break
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                log.error("Day %d booking attempt %d/%d failed: %s",
                          days_ahead, attempt, retry_count, e)
                if status is not None and status < 500:
                    # 4xx: slot is gone — re-search for another preferred slot
                    log.info("Slot taken — re-searching %s ...", day8_str)
                    try:
                        result = search_courts(session, token, sso_id,
                                               club_id, sport, day8, duration)
                        new_slots = collect_slots(result)
                        if new_slots:
                            log.info("Available: %s", fmt_slots(new_slots))
                        slot = auto_pick(new_slots, preferred_times, preferred_courts) if new_slots else None
                    except Exception as search_e:
                        log.error("Re-search failed: %s", search_e)
                        slot = None
                    if slot is None:
                        log.info("No preferred slot after re-search — done with day %d", days_ahead)
                        break
                # 5xx: keep same slot, retry booking
            except Exception as e:
                log.error("Day %d booking attempt %d/%d failed: %s",
                          days_ahead, attempt, retry_count, e)

    if booked_slot is not None:
        return {"status": "booked", "target_date": booked_date, "booked_slot": booked_slot,
                "day8_slots": day8_slots, "reservation_labels": reservation_labels}

    # Determine day-8 failure reason (used in report if no fallback booking either)
    if not day8_slots:
        day8_status = "no_courts"
    elif not slot_picked_initially:
        day8_status = "no_preferred"
    else:
        day8_status = "booking_failed"  # slot was picked but all retries failed

    if not fallback:
        log.info("No booking on day %d — fallback scan disabled (use --fallback to scan days 1–%d)",
                 days_ahead, days_ahead - 1)
        return {"status": day8_status, "target_date": day8, "booked_slot": None,
                "day8_slots": day8_slots, "reservation_labels": reservation_labels}

    # Priority 2: scan days 1–7 once (no retry)
    log.info("No booking on day %d — scanning days 1–%d ...", days_ahead, days_ahead - 1)
    for i in range(1, days_ahead):
        target = today + timedelta(days=i)
        try:
            booked = try_date(target)
            if booked is not None:
                return {"status": "booked", "target_date": target, "booked_slot": booked,
                        "day8_slots": day8_slots, "reservation_labels": reservation_labels}
        except Exception as e:
            log.error("Error trying %s: %s — skipping", target.strftime("%Y-%m-%d"), e)

    log.info("No preferred slots found on any day (1–%d).", days_ahead)
    return {"status": day8_status, "target_date": day8, "booked_slot": None,
            "day8_slots": day8_slots, "reservation_labels": reservation_labels}


def run_dry_run(session, token, sso_id, config):
    club_id = config.get("club_id", "36")
    sport = config.get("sport", "Pickleball: Indoor")
    duration = config.get("duration", 60)
    days_ahead = config.get("days_ahead", 8)
    preferred_times = config.get("preferred_times", [])
    preferred_courts = config.get("preferred_courts", [])

    today = date.today()

    member_ids = config.get("member_ids", [])
    if member_ids:
        reserved_dates, _ = get_reserved_dates(
            session, token, sso_id, member_ids,
            today + timedelta(days=1),
            today + timedelta(days=days_ahead),
        )
        log.info("Already reserved dates: %s", sorted(reserved_dates) or "none")
    else:
        reserved_dates = set()

    for i in range(1, days_ahead + 1):
        target_date = today + timedelta(days=i)
        date_str = target_date.strftime("%Y-%m-%d")
        label = target_date.strftime("%A %Y-%m-%d")

        if date_str in reserved_dates:
            log.info("%s: already reserved", label)
            continue

        result = search_courts(session, token, sso_id, club_id, sport, target_date, duration)
        slots = collect_slots(result)

        if not slots:
            log.info("%s: no slots available", label)
            continue

        slot = auto_pick(slots, preferred_times, preferred_courts)
        all_times = fmt_slots(slots)
        if slot:
            log.info("%s: would book %s %s", label, slot["time"], slot["resourceName"])
            log.info("  All available: %s", all_times)
        else:
            log.info("%s: no preferred time available", label)
            log.info("  All available: %s", all_times)


def run_date(session, token, sso_id, config, date_str):
    """Search a specific date and book best preferred slot.
    Returns (target_date, booked_slot_or_None, reason_or_None, slots)."""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        log.error("Invalid date: %s. Use YYYY-MM-DD.", date_str)
        sys.exit(1)
    club_id = config.get("club_id", "36")
    sport = config.get("sport", "Pickleball: Indoor")
    duration = config.get("duration", 60)
    preferred_times = config.get("preferred_times", [])
    preferred_courts = config.get("preferred_courts", [])

    log.info("Searching %s ...", target_date.strftime("%A %Y-%m-%d"))
    try:
        result = search_courts(session, token, sso_id, club_id, sport, target_date, duration)
        slots = collect_slots(result)
    except Exception as e:
        log.error("Search failed: %s", e)
        return target_date, None, f"search failed: {e}", []

    if not slots:
        log.info("No courts available on %s", date_str)
        return target_date, None, "no courts available", []
    log.info("Available: %s", fmt_slots(slots))
    slot = auto_pick(slots, preferred_times, preferred_courts)
    if slot is None:
        log.info("No preferred slot on %s", date_str)
        return target_date, None, "no preferred time available", slots
    log.info("Booking %s %s ...", slot["time"], slot["resourceName"])
    try:
        booking = book_court(session, token, sso_id, slot["resourceId"], slot["start"], duration)
        log.info("Confirmed: regId=%s, status=%s, location=%s",
                 booking["regId"], booking["regStatus"], booking.get("location", ""))
        return target_date, slot, None, slots
    except Exception as e:
        log.error("Booking failed: %s", e)
        return target_date, None, f"booking failed: {e}", slots


def run_cancel(session, token, sso_id, config, date_str):
    """Cancel reservation(s) on a specific date. Returns (target_date, cancelled_labels)."""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        log.error("Invalid date: %s. Use YYYY-MM-DD.", date_str)
        sys.exit(1)
    member_ids = config.get("member_ids", [])
    if not member_ids:
        log.error("member_ids not configured — cannot look up reservation")
        sys.exit(1)
    reservations = get_reservations_list(
        session, token, sso_id, member_ids, target_date, target_date)
    if not reservations:
        log.info("No reservation found on %s", date_str)
        return target_date, [], 0
    cancelled = []
    for res in reservations:
        attendee_id = res.get("attendee_id")
        if not attendee_id:
            log.error("Cannot cancel %s: attendee ID missing from API response", res["label"])
            continue
        log.info("Cancelling %s (attendeeId=%s) ...", res["label"], attendee_id)
        try:
            resp = session.delete(
                f"{API_BASE}/sys/registrations/V3/ux/resource/0/attendees/{attendee_id}",
                headers=auth_headers(token, sso_id),
                timeout=HTTP_TIMEOUT,
            )
            raise_for_status_with_body(resp)
            log.info("Cancelled successfully")
            cancelled.append(res["label"])
        except Exception as e:
            log.error("Cancel failed for %s: %s", res["label"], e)
    return target_date, cancelled, len(reservations)


# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Lifetime Fitness Pickleball Court Reservation")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", action="store_true",
                       help="Auto-book best available slot from preferred_times config (day 8 only by default)")
    parser.add_argument("--fallback", action="store_true",
                        help="With --auto: if day 8 has no preferred slot, also scan days 1–(N-1)")
    group.add_argument("--dry-run", action="store_true",
                       help="Show available slots without booking")
    group.add_argument("--slot", metavar="DATETIME",
                       help="Book a specific slot: 'YYYY-MM-DD HH:MM' (24h, e.g. '2026-03-16 04:30')")
    group.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Book best preferred slot on a specific date")
    group.add_argument("--cancel", metavar="YYYY-MM-DD",
                       help="Cancel reservation on a specific date")
    group.add_argument("--list", action="store_true", dest="list_reservations",
                       help="List current upcoming reservations")
    parser.add_argument("--no-notify", action="store_true",
                        help="Skip Slack notification (used when called from the slash command server)")
    parser.add_argument("--wait-until", metavar="HH:MM:SS",
                        help="Login immediately, then wait until this time before booking (e.g. 09:00:00)")
    return parser.parse_args()


def main():
    setup_file_logging()
    args = parse_args()
    log.info("=" * 60)
    mode = ("auto" if args.auto else "dry-run" if args.dry_run
            else f"slot({args.slot})" if args.slot
            else f"date({args.date})" if args.date
            else f"cancel({args.cancel})" if args.cancel
            else "list" if args.list_reservations
            else "interactive")
    log.info("Run started — mode: %s", mode)
    config = load_config()
    validate_config(config)
    session = make_session()

    # Login with retry — transient network errors at 8:55 AM shouldn't abort the whole run
    for attempt in range(1, 4):
        try:
            token, sso_id = login(session, config["username"], config["password"])
            break
        except Exception as e:
            log.error("Login attempt %d/3 failed: %s", attempt, e)
            if attempt == 3:
                log.error("All login attempts failed — exiting")
                sys.exit(1)
            time.sleep(2)

    if args.wait_until:
        try:
            target_time = datetime.strptime(args.wait_until, "%H:%M:%S").time()
        except ValueError:
            log.error("Invalid --wait-until format. Use HH:MM:SS (e.g. 09:00:00)")
            sys.exit(1)
        now = datetime.now()
        target_dt = datetime.combine(now.date(), target_time)
        wait_seconds = (target_dt - now).total_seconds()
        if wait_seconds > 0:
            log.info("Logged in early — waiting %.2fs until %s", wait_seconds, args.wait_until)
            # Use monotonic clock for drift-free polling; datetime.now() only for initial gap.
            mono_target = time.monotonic() + wait_seconds
            while True:
                remaining = mono_target - time.monotonic()
                if remaining <= 0.020:
                    break  # hand off to spin for final 20 ms
                time.sleep(min(remaining - 0.020, 0.5))
            # Spin for the last ~20 ms to avoid scheduler overshoot
            while time.monotonic() < mono_target:
                pass
            log.info("Reached target time %s (overshoot: %.1f ms)",
                     args.wait_until, (time.monotonic() - mono_target) * 1000)
        else:
            log.warning("--wait-until time %s is in the past, proceeding immediately", args.wait_until)

    report = None
    if args.cancel:
        target_date, cancelled, found_count = run_cancel(session, token, sso_id, config, args.cancel)
        upcoming = _fetch_upcoming(session, token, sso_id, config)
        report = build_cancel_report(target_date, cancelled, found_count, upcoming)
    elif args.date:
        target_date, booked_slot, reason, slots = run_date(session, token, sso_id, config, args.date)
        upcoming = _fetch_upcoming(session, token, sso_id, config)
        report = build_date_report(target_date, booked_slot, reason, slots, upcoming)
    elif args.slot:
        dt, booked_slot, reason = run_slot(session, token, sso_id, config, args.slot)
        upcoming = _fetch_upcoming(session, token, sso_id, config)
        report = build_slot_report(dt, booked_slot, reason, upcoming)
    elif args.auto:
        result = run_auto(session, token, sso_id, config, fallback=args.fallback)
        report = build_auto_report(
            result["status"], result["target_date"], result.get("booked_slot"),
            result.get("day8_slots", []), result.get("reservation_labels", []),
        )
    elif args.list_reservations:
        upcoming = _fetch_upcoming(session, token, sso_id, config)
        report = build_list_report(upcoming)
    elif args.dry_run:
        run_dry_run(session, token, sso_id, config)
    else:
        run_interactive(session, token, sso_id, config)

    if report is not None:
        emit_report(report)
        if not args.no_notify:
            send_slack(config, report)


if __name__ == "__main__":
    main()
