"""Slack Events API dispatch — threaded replies under the user's message.

Handles `app_mention` (channel) and `message.im` (DM) events. All bot replies thread
under the triggering message. Deduplication is thread-safe because ThreadingHTTPServer
runs each request (including Slack's retries) on its own thread — an unlocked
check-then-set could let two concurrent retries both dispatch a booking.
"""

import logging
import re
import threading
from collections import OrderedDict

from lifetime_reserve import notify
from lifetime_reserve.slackbot.parsing import (
    strip_mention, parse_date_token, parse_command_text)

log = logging.getLogger(__name__)

RECENT_EVENT_IDS: OrderedDict = OrderedDict()
RECENT_EVENT_IDS_MAX = 500
_DEDUP_LOCK = threading.Lock()


def dedup_seen(event_id) -> bool:
    """True if this event_id was already processed. Bounded LRU, thread-safe.

    In-memory only: a process restart between the original delivery and a retry loses
    the record and can re-process once (bounded, rare — accepted).
    """
    with _DEDUP_LOCK:
        if event_id in RECENT_EVENT_IDS:
            return True
        RECENT_EVENT_IDS[event_id] = None
        if len(RECENT_EVENT_IDS) > RECENT_EVENT_IDS_MAX:
            RECENT_EVENT_IDS.popitem(last=False)
        return False


def should_process_event(event: dict) -> bool:
    """Pure predicate: does this event warrant a booking dispatch?

    Drops non-message/mention types, edits (subtype), bot echoes (bot_id — prevents
    loops), and non-DM `message` events.
    """
    if event.get("type") not in ("app_mention", "message"):
        return False
    if event.get("subtype") or event.get("bot_id"):
        return False
    if event["type"] == "message" and event.get("channel_type") != "im":
        return False
    return True


def build_command(raw_text: str):
    """Map event text → (args, label, verbose), or (None, error_msg, False) on failure.

    First word decides the command: `cancel` → cancel, `list` → list; otherwise a
    leading `reserve` is stripped and the remainder is parsed like a slash command.
    """
    text = strip_mention(raw_text).strip()
    lower = text.lower()

    if lower.startswith("cancel"):
        rest = text[len("cancel"):].strip()
        verbose = bool(re.search(r"\bverbose\b", rest, re.IGNORECASE))
        rest = re.sub(r"\bverbose\b", "", rest, flags=re.IGNORECASE).strip()
        target_date = parse_date_token(rest)
        if target_date is None:
            return None, ("Usage: `cancel <date>` — date is `YYYY-MM-DD` or a weekday "
                          "name (`Mon`, `Tuesday`, ...)"), False
        date_str = target_date.strftime("%Y-%m-%d")
        label = f"Cancel {target_date.strftime('%a %b %-d')}"
        return ["--cancel", date_str], label, verbose

    if lower.startswith("list"):
        rest = text[len("list"):]
        verbose = bool(re.search(r"\bverbose\b", rest, re.IGNORECASE))
        return ["--list"], "Reservations", verbose

    body = re.sub(r"^\s*reserve\b", "", text, flags=re.IGNORECASE).strip()
    return parse_command_text(body)


def handle_event(event, config, run_fn):
    """Dispatch one event. `run_fn` is injected for testability (normally
    dispatch.run_and_report_threaded). All replies thread under the user's message."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]  # reply in existing thread if any
    args, label, verbose = build_command(event.get("text", ""))
    if args is None:
        notify.notify(config, label, channel=channel, thread_ts=thread_ts)  # label = error
        return
    run_fn(args + ["--no-notify"], label, verbose, channel=channel, thread_ts=thread_ts)
