from datetime import date

from lifetime_reserve.protocol import REPORT_START, REPORT_END
from lifetime_reserve.reports import (
    _upcoming_block, emit_report, build_auto_report, build_slot_report,
    build_date_report, build_list_report, build_cancel_report)

TARGET = date(2026, 8, 10)
DATE_LABEL = TARGET.strftime("%a %b %-d")  # "Mon Aug 10"
SLOT = {"time": "7:00 AM", "resourceName": "Court 3"}
UPCOMING = ["Mon Aug 3 — 7:00 AM, Court 03"]


# ── _upcoming_block ──────────────────────────────────────────────────────────

def test_upcoming_block_none():
    assert _upcoming_block([]) == "*Upcoming reservations:*\n• (none)"


def test_upcoming_block_list():
    out = _upcoming_block(["a", "b"])
    assert "• a" in out and "• b" in out


# ── build_auto_report (all five statuses) ────────────────────────────────────

def test_auto_booked():
    out = build_auto_report("booked", TARGET, SLOT, [], UPCOMING)
    assert f"*Booked:* 7:00 AM Court 3 on {DATE_LABEL}" in out
    assert "• Mon Aug 3" in out


def test_auto_already_reserved():
    out = build_auto_report("already_reserved", TARGET, None, [], [])
    assert "already reserved that day" in out


def test_auto_no_courts():
    out = build_auto_report("no_courts", TARGET, None, [], [])
    assert "no courts available" in out


def test_auto_no_preferred_lists_available():
    day8 = [{"time": "5:00 AM", "resourceName": "Court 1"}]
    out = build_auto_report("no_preferred", TARGET, None, day8, [])
    assert "no preferred time available" in out
    assert "Available: 5:00 AM Court 1" in out


def test_auto_booking_failed():
    out = build_auto_report("booking_failed", TARGET, None, [], [])
    assert "all retries failed" in out


# ── build_slot_report / build_date_report ────────────────────────────────────

def test_slot_report_booked_vs_failed():
    ok = build_slot_report(TARGET, SLOT, None, [])
    assert f"*Booked:* 7:00 AM Court 3 on {DATE_LABEL}" in ok
    fail = build_slot_report(TARGET, None, "slot not available", [])
    assert "Failed to book" in fail and "slot not available" in fail


def test_date_report_booked_vs_failed_with_available():
    ok = build_date_report(TARGET, SLOT, None, [], [])
    assert "*Booked:*" in ok
    slots = [{"time": "5:00 AM", "resourceName": "Court 1"}]
    fail = build_date_report(TARGET, None, "no preferred time available", slots, [])
    assert "no preferred time available" in fail
    assert "Available: 5:00 AM Court 1" in fail


# ── build_list_report / build_cancel_report ──────────────────────────────────

def test_list_report():
    out = build_list_report(UPCOMING)
    assert "Reservations" in out and "• Mon Aug 3" in out


def test_cancel_report_success():
    out = build_cancel_report(TARGET, [f"{DATE_LABEL} — 7:00 AM"], 1, [])
    assert f"*Cancelled on {DATE_LABEL}:*" in out


def test_cancel_report_found_but_failed():
    out = build_cancel_report(TARGET, [], 1, [])
    assert "Cancel failed" in out


def test_cancel_report_none_found():
    out = build_cancel_report(TARGET, [], 0, [])
    assert "No reservation to cancel" in out


# ── emit_report ──────────────────────────────────────────────────────────────

def test_emit_report_wraps_markers(capsys):
    emit_report("hello world")
    out = capsys.readouterr().out
    assert REPORT_START in out and REPORT_END in out
    assert "hello world" in out
