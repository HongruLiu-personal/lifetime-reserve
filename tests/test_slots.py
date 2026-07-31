import pytest

from lifetime_reserve.slots import (
    collect_slots, to_api_time, auto_pick, pick_by_time, fmt_slots)


def slot(time, court):
    return {"time": time, "resourceName": court}


# ── to_api_time ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hhmm, expected", [
    ("04:30", "4:30 AM"),
    ("13:00", "1:00 PM"),
    ("00:00", "12:00 AM"),
    ("12:00", "12:00 PM"),
    ("23:45", "11:45 PM"),
])
def test_to_api_time(hhmm, expected):
    assert to_api_time(hhmm) == expected


# ── collect_slots ────────────────────────────────────────────────────────────

def test_collect_slots_flattens_and_tags_part():
    search = {"results": {"dayParts": [
        {"name": "Morning", "availableTimes": [
            {"time": "7:00 AM", "resourceName": "Court 1"},
            {"time": "7:30 AM", "resourceName": "Court 2"},
        ]},
        {"name": "Evening", "availableTimes": [
            {"time": "6:00 PM", "resourceName": "Court 3"},
        ]},
    ]}}
    slots = collect_slots(search)
    assert len(slots) == 3
    assert [s["_part"] for s in slots] == ["Morning", "Morning", "Evening"]
    assert slots[0]["time"] == "7:00 AM"


def test_collect_slots_empty():
    assert collect_slots({}) == []
    assert collect_slots({"results": {"dayParts": []}}) == []


# ── auto_pick ────────────────────────────────────────────────────────────────

def test_auto_pick_prefers_first_available_time():
    slots = [slot("7:00 AM", "Court 1"), slot("8:00 AM", "Court 1")]
    # 8:00 is listed first in preferences but 7:30 is absent → 8:00 wins over 7:00
    picked = auto_pick(slots, ["7:30 AM", "8:00 AM", "7:00 AM"], [])
    assert picked["time"] == "8:00 AM"


def test_auto_pick_orders_by_preferred_court_within_time():
    slots = [slot("7:00 AM", "Court 1"), slot("7:00 AM", "Court 3"),
             slot("7:00 AM", "Court 2")]
    picked = auto_pick(slots, ["7:00 AM"], ["Court 3", "Court 2", "Court 1"])
    assert picked["resourceName"] == "Court 3"


def test_auto_pick_unknown_court_sorts_last():
    slots = [slot("7:00 AM", "Court 9"), slot("7:00 AM", "Court 2")]
    picked = auto_pick(slots, ["7:00 AM"], ["Court 2"])
    assert picked["resourceName"] == "Court 2"


def test_auto_pick_returns_none_when_no_preferred_time():
    slots = [slot("9:00 AM", "Court 1")]
    assert auto_pick(slots, ["7:00 AM", "7:30 AM"], ["Court 1"]) is None


def test_auto_pick_never_falls_back_to_arbitrary_slot():
    # A slot exists, but not at any preferred time → must return None, not that slot.
    slots = [slot("5:00 AM", "Court 1")]
    assert auto_pick(slots, ["7:00 AM"], []) is None


# ── pick_by_time ─────────────────────────────────────────────────────────────

def test_pick_by_time_match_and_miss():
    slots = [slot("7:00 AM", "Court 1"), slot("8:00 AM", "Court 2")]
    assert pick_by_time(slots, "8:00 AM")["resourceName"] == "Court 2"
    assert pick_by_time(slots, "9:00 AM") is None


# ── fmt_slots ────────────────────────────────────────────────────────────────

def test_fmt_slots():
    assert fmt_slots([slot("7:00 AM", "Court 1"), slot("8:00 AM", "Court 2")]) == \
        "7:00 AM Court 1, 8:00 AM Court 2"
    assert fmt_slots([]) == ""
