import threading

import pytest

from lifetime_reserve.config import Config
from lifetime_reserve.slackbot import events
from lifetime_reserve.slackbot.events import (
    dedup_seen, should_process_event, build_command, handle_event)


@pytest.fixture(autouse=True)
def _clear_dedup():
    events.RECENT_EVENT_IDS.clear()
    yield
    events.RECENT_EVENT_IDS.clear()


# ── build_command ────────────────────────────────────────────────────────────

def test_build_command_mention_reserve_weekday_verbose():
    args, label, verbose = build_command("<@U0BOT> reserve tue verbose")
    assert args[0] == "--date"
    assert verbose is True


def test_build_command_bare_and_reserve_are_auto():
    assert build_command("")[0] == ["--auto"]
    assert build_command("reserve")[0] == ["--auto"]
    assert build_command("<@U0BOT> reserve")[0] == ["--auto"]


def test_build_command_cancel_iso():
    args, label, verbose = build_command("cancel 2026-08-03")
    assert args == ["--cancel", "2026-08-03"]
    assert label.startswith("Cancel")
    assert verbose is False


def test_build_command_cancel_verbose():
    args, label, verbose = build_command("cancel 2026-08-03 verbose")
    assert args[0] == "--cancel"
    assert verbose is True


def test_build_command_cancel_bad_date_is_error():
    args, err, verbose = build_command("cancel not-a-date")
    assert args is None
    assert "Usage" in err


def test_build_command_list():
    args, label, verbose = build_command("list")
    assert args == ["--list"]
    assert label == "Reservations"
    assert verbose is False


def test_build_command_list_verbose_and_mention():
    args, label, verbose = build_command("<@U0BOT> list verbose")
    assert args == ["--list"]
    assert verbose is True


def test_build_command_unparseable_is_error():
    args, err, verbose = build_command("zzzz")
    assert args is None
    assert "Could not parse" in err


# ── dedup_seen (incl. thread safety + eviction) ──────────────────────────────

def test_dedup_first_seen_then_repeat():
    assert dedup_seen("E1") is False
    assert dedup_seen("E1") is True


def test_dedup_lru_eviction():
    for i in range(events.RECENT_EVENT_IDS_MAX + 10):
        dedup_seen(f"E{i}")
    # oldest ids evicted → treated as new again
    assert dedup_seen("E0") is False
    assert len(events.RECENT_EVENT_IDS) <= events.RECENT_EVENT_IDS_MAX + 1


def test_dedup_concurrent_single_winner():
    results = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        results.append(dedup_seen("SAME"))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # exactly one thread saw it as new (False); the rest saw True
    assert results.count(False) == 1


# ── should_process_event ─────────────────────────────────────────────────────

@pytest.mark.parametrize("event, expected", [
    ({"type": "app_mention", "ts": "1", "channel": "C"}, True),
    ({"type": "message", "channel_type": "im", "ts": "1", "channel": "D"}, True),
    ({"type": "message", "channel_type": "channel", "ts": "1"}, False),  # non-DM message
    ({"type": "message", "channel_type": "im", "subtype": "message_changed"}, False),
    ({"type": "app_mention", "bot_id": "B1"}, False),                    # bot echo
    ({"type": "reaction_added"}, False),                                 # unrelated type
])
def test_should_process_event(event, expected):
    assert should_process_event(event) is expected


# ── handle_event ─────────────────────────────────────────────────────────────

CONFIG = Config.from_dict({"slack_bot_token": "tok", "slack_channel": "C_DEFAULT"})


def test_handle_event_success_calls_run_fn_with_no_notify():
    calls = []
    def run_fn(args, label, verbose, channel, thread_ts):
        calls.append((args, label, verbose, channel, thread_ts))
    event = {"type": "app_mention", "text": "<@U0BOT> reserve", "ts": "111.0", "channel": "C9"}
    handle_event(event, CONFIG, run_fn)
    args, label, verbose, channel, thread_ts = calls[0]
    assert args == ["--auto", "--no-notify"]
    assert channel == "C9"
    assert thread_ts == "111.0"


def test_handle_event_uses_existing_thread_ts():
    calls = []
    event = {"type": "app_mention", "text": "reserve", "ts": "111.0",
             "thread_ts": "100.0", "channel": "C9"}
    handle_event(event, CONFIG, lambda *a, **k: calls.append(k))
    assert calls[0]["thread_ts"] == "100.0"


def test_handle_event_error_posts_message_and_skips_run_fn(monkeypatch):
    posted = {}
    monkeypatch.setattr(events.notify, "notify",
                        lambda cfg, text, channel=None, thread_ts=None: posted.update(
                            text=text, channel=channel, thread_ts=thread_ts))
    ran = []
    event = {"type": "app_mention", "text": "zzzz", "ts": "111.0", "channel": "C9"}
    handle_event(event, CONFIG, lambda *a, **k: ran.append(1))
    assert ran == []                       # run_fn NOT called on parse error
    assert "Could not parse" in posted["text"]
    assert posted["channel"] == "C9" and posted["thread_ts"] == "111.0"


def test_handle_event_worker_guard_posts_apology_on_run_fn_error(monkeypatch):
    # B2: an exception in the worker must not escape the daemon thread silently —
    # it's logged and surfaced to the user as a threaded reply.
    posted = {}
    monkeypatch.setattr(events.notify, "notify",
                        lambda cfg, text, channel=None, thread_ts=None: posted.update(
                            text=text, channel=channel, thread_ts=thread_ts))

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    event = {"type": "app_mention", "text": "reserve", "ts": "111.0", "channel": "C9"}
    handle_event(event, CONFIG, boom)      # must not raise
    assert "went wrong" in posted["text"]
    assert posted["channel"] == "C9" and posted["thread_ts"] == "111.0"
