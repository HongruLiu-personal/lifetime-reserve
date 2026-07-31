"""Mode-handler tests, driven by FakeClient. The run_auto retry/fallback state machine
is the highest-value behavioral coverage in the suite."""

from datetime import date, timedelta

import pytest
import requests

from lifetime_reserve.config import Config, ConfigError
from lifetime_reserve import modes
from lifetime_reserve.modes import run_auto, run_slot, run_date, run_cancel
from tests.conftest import FakeClient, FakeResponse, make_slot, search_envelope

DAY8 = date.today() + timedelta(days=8)
BOOKING = {"regId": "R1", "regStatus": "completed", "location": "Court 3"}


def http_error(status):
    return requests.HTTPError(str(status), response=FakeResponse(status_code=status))


def cfg(**over):
    base = {"preferred_times": ["7:00 AM"], "preferred_courts": ["Court 3"],
            "retry_count": 2, "retry_delay_seconds": 0, "days_ahead": 8}
    base.update(over)
    return Config.from_dict(base)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(modes.time, "sleep", lambda *_: None)


# ── run_auto: happy path ─────────────────────────────────────────────────────

def test_auto_books_day8():
    c = FakeClient(search_results=[search_envelope([make_slot("7:00 AM", "Court 3", "RA")])],
                   book_results=[BOOKING])
    res = run_auto(c, cfg())
    assert res["status"] == "booked"
    assert res["target_date"] == DAY8
    assert res["booked_slot"]["resourceName"] == "Court 3"
    assert c.book_calls == [("RA", "2026-08-10T07:00:00")]


# ── run_auto: 5xx retries the SAME slot (no re-search) ───────────────────────

def test_auto_5xx_retries_same_slot():
    c = FakeClient(search_results=[search_envelope([make_slot("7:00 AM", "Court 3", "RA")])],
                   book_results=[http_error(503), BOOKING])
    res = run_auto(c, cfg())
    assert res["status"] == "booked"
    assert len(c.search_calls) == 1                    # 5xx did NOT re-search
    assert c.book_calls == [("RA", "2026-08-10T07:00:00"),
                            ("RA", "2026-08-10T07:00:00")]


# ── run_auto: 4xx re-searches and picks a NEW slot ───────────────────────────

def test_auto_4xx_researches_new_slot():
    c = FakeClient(
        search_results=[search_envelope([make_slot("7:00 AM", "Court 3", "RA")]),
                        search_envelope([make_slot("7:00 AM", "Court 3", "RB")])],
        book_results=[http_error(409), BOOKING])
    res = run_auto(c, cfg())
    assert res["status"] == "booked"
    assert len(c.search_calls) == 2                    # 4xx triggered a re-search
    assert [rid for rid, _ in c.book_calls] == ["RA", "RB"]


def test_auto_4xx_then_no_slot_is_booking_failed():
    c = FakeClient(
        search_results=[search_envelope([make_slot("7:00 AM", "Court 3", "RA")]),
                        search_envelope([])],          # re-search finds nothing
        book_results=[http_error(409)])
    res = run_auto(c, cfg())
    assert res["status"] == "booking_failed"


# ── run_auto: skip / empty / no-preferred ────────────────────────────────────

def test_auto_already_reserved_skips_booking():
    c = FakeClient(reserved=({DAY8.strftime("%Y-%m-%d")}, ["existing"]))
    res = run_auto(c, cfg(member_ids=[1]))
    assert res["status"] == "already_reserved"
    assert c.search_calls == [] and c.book_calls == []


def test_auto_no_courts():
    c = FakeClient(search_results=[search_envelope([])])
    res = run_auto(c, cfg())
    assert res["status"] == "no_courts"


def test_auto_no_preferred_time():
    c = FakeClient(search_results=[search_envelope([make_slot("9:00 AM", "Court 1", "RX")])])
    res = run_auto(c, cfg())
    assert res["status"] == "no_preferred"
    assert res["day8_slots"]                           # available slots reported
    assert c.book_calls == []


# ── run_auto: --fallback scans earlier days ──────────────────────────────────

def test_auto_fallback_books_earlier_day():
    c = FakeClient(
        search_results=[search_envelope([]),                                   # day 8: empty
                        search_envelope([make_slot("7:00 AM", "Court 3", "RD1")])],  # day 1
        book_results=[BOOKING])
    res = run_auto(c, cfg(), fallback=True)
    assert res["status"] == "booked"
    assert res["target_date"] == date.today() + timedelta(days=1)


def test_auto_fallback_skips_reserved_and_survives_errors():
    today = date.today()
    d1 = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    c = FakeClient(
        search_results=[search_envelope([]),           # day 8 empty
                        RuntimeError("boom"),           # day 2 search raises (day 1 is skipped)
                        search_envelope([make_slot("7:00 AM", "Court 3", "RD3")])],  # day 3
        book_results=[BOOKING],
        reserved=({d1}, []))
    res = run_auto(c, cfg(member_ids=[1]), fallback=True)
    assert res["status"] == "booked"
    assert res["target_date"] == today + timedelta(days=3)


# ── run_slot / run_date / run_cancel: validation now raises (was sys.exit) ────

def test_run_slot_bad_format_raises():
    with pytest.raises(ValueError):
        run_slot(FakeClient(), cfg(), "not-a-datetime")


def test_run_slot_books_matching_time():
    c = FakeClient(search_results=[search_envelope([make_slot("7:00 AM", "Court 3", "RA")])],
                   book_results=[BOOKING])
    dt, slot, reason = run_slot(c, cfg(), "2026-08-10 07:00")
    assert slot is not None and reason is None


def test_run_slot_not_available():
    c = FakeClient(search_results=[search_envelope([make_slot("9:00 AM", "Court 1", "RX")])])
    dt, slot, reason = run_slot(c, cfg(), "2026-08-10 07:00")
    assert slot is None and "not available" in reason


def test_run_date_bad_date_raises():
    with pytest.raises(ValueError):
        run_date(FakeClient(), cfg(), "08/10/2026")


def test_run_cancel_bad_date_raises():
    with pytest.raises(ValueError):
        run_cancel(FakeClient(), Config.from_dict({"member_ids": [1]}), "not-a-date")


def test_run_cancel_missing_member_ids_raises_config_error():
    with pytest.raises(ConfigError):
        run_cancel(FakeClient(), Config.from_dict({}), "2026-08-10")


def test_run_cancel_cancels_found_reservations():
    c = FakeClient(reservations=[{"attendee_id": "A1", "label": "Mon Aug 10"}])
    td, cancelled, found = run_cancel(c, Config.from_dict({"member_ids": [1]}), "2026-08-10")
    assert cancelled == ["Mon Aug 10"]
    assert found == 1
    assert c.cancelled == ["A1"]
