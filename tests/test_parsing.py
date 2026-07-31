from datetime import date

import pytest

import lifetime_reserve.slackbot.parsing as parsing
from lifetime_reserve.slackbot.parsing import (
    parse_date_token, parse_command_text, strip_mention)

# Freeze "today" to Monday 2026-08-03 so weekday resolution is deterministic.
FROZEN_TODAY = date(2026, 8, 3)  # Monday


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return FROZEN_TODAY


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr(parsing, "date", _FrozenDate)


# ── parse_date_token ─────────────────────────────────────────────────────────

def test_parse_iso_date():
    assert parse_date_token("2026-08-15") == date(2026, 8, 15)


def test_parse_weekday_forward():
    # Tue is the day after Monday 2026-08-03.
    assert parse_date_token("tue") == date(2026, 8, 4)
    assert parse_date_token("sunday") == date(2026, 8, 9)


def test_parse_same_weekday_rolls_forward_7():
    # "mon" on a Monday must roll to next Monday, not today (same-day booking disallowed).
    assert parse_date_token("mon") == date(2026, 8, 10)
    assert parse_date_token("monday") == date(2026, 8, 10)


def test_parse_junk_returns_none():
    assert parse_date_token("hello there") is None


# ── parse_command_text ───────────────────────────────────────────────────────

def test_empty_is_auto():
    args, label, verbose = parse_command_text("")
    assert args == ["--auto"] and verbose is False


def test_date_only():
    args, label, verbose = parse_command_text("2026-08-15")
    assert args == ["--date", "2026-08-15"]


def test_date_and_time_24h():
    args, _, _ = parse_command_text("2026-08-15 07:00")
    assert args == ["--slot", "2026-08-15 07:00"]


def test_date_and_time_ampm():
    args, _, _ = parse_command_text("2026-08-15 7:00 AM")
    assert args == ["--slot", "2026-08-15 07:00"]


def test_verbose_detected_and_stripped():
    args, label, verbose = parse_command_text("2026-08-15 verbose")
    assert verbose is True
    assert args == ["--date", "2026-08-15"]


def test_weekday_command():
    args, _, _ = parse_command_text("tue")
    assert args == ["--date", "2026-08-04"]


def test_unparseable_returns_error():
    args, err, verbose = parse_command_text("zzzz")
    assert args is None
    assert "Could not parse" in err
    assert verbose is False


# ── strip_mention ────────────────────────────────────────────────────────────

def test_strip_leading_mention():
    assert strip_mention("<@U12345> reserve tue") == "reserve tue"


def test_strip_mention_no_mention_unchanged():
    assert strip_mention("reserve tue") == "reserve tue"


def test_strip_mention_only_leading():
    # A mention mid-string is left alone.
    assert strip_mention("hi <@U1> there") == "hi <@U1> there"
