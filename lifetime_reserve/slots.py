"""Pure slot utilities — no network, no I/O.

Flatten the search API's response into a flat list of slot dicts, convert time
formats, and pick slots by preference. `auto_pick` logs a warning when no preferred
time is available (behavior preserved from the original monolith).
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)


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
