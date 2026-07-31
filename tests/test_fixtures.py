"""Validate our parsers against real (captured + scrubbed) API payloads.

These complement the synthetic-payload tests: they pin behavior against the *actual*
shapes the Lifetime API returns — e.g. the reservation `location` has no ` | `
separator, and a reservation can have empty `registeredMembers` (no attendee id).
"""

from datetime import date

from lifetime_reserve.slots import collect_slots, auto_pick, pick_by_time
from lifetime_reserve.api.client import LifetimeClient
from tests.conftest import FakeResponse, FakeSession, load_fixture


# ── search.json ──────────────────────────────────────────────────────────────

def test_collect_slots_on_real_search():
    slots = collect_slots(load_fixture("search.json"))
    assert len(slots) == 20
    assert {s["_part"] for s in slots} == {"Morning", "Evening"}


def test_auto_pick_court_order_on_real_search():
    slots = collect_slots(load_fixture("search.json"))
    # 5:00 AM is offered on Courts 1/2/3 → court preference decides
    picked = auto_pick(slots, ["5:00 AM"], ["Court 3", "Court 2", "Court 1"])
    assert picked["resourceName"] == "Court 3"
    assert picked["resourceId"] == "res-3"


def test_auto_pick_returns_none_for_unoffered_time_on_real_search():
    slots = collect_slots(load_fixture("search.json"))
    assert auto_pick(slots, ["7:00 AM"], []) is None   # 7:00 AM not in this payload


def test_pick_by_time_on_real_search():
    slots = collect_slots(load_fixture("search.json"))
    assert pick_by_time(slots, "8:00 AM")["resourceName"] == "Court 3"
    assert pick_by_time(slots, "3:00 AM") is None


# ── reservations.json ────────────────────────────────────────────────────────

def _client_with_reservations():
    c = LifetimeClient(session=FakeSession().queue(
        "GET", FakeResponse(load_fixture("reservations.json"))))
    c.token, c.sso_id = "T", "S"
    return c


def test_get_reservations_parses_and_sorts_real_payload():
    res = _client_with_reservations().get_reservations(
        [1], date(2026, 7, 31), date(2026, 8, 8))
    assert [r["date_str"] for r in res] == [
        "2026-07-31", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08"]


def test_real_empty_registered_members_yields_no_attendee_id():
    by = {r["date_str"]: r for r in
          _client_with_reservations().get_reservations([1], date(2026, 7, 31), date(2026, 8, 8))}
    # reg-1 has empty registeredMembers — real edge case
    assert by["2026-07-31"]["attendee_id"] is None


def test_real_online_cta_registration_id_is_attendee_id():
    by = {r["date_str"]: r for r in
          _client_with_reservations().get_reservations([1], date(2026, 7, 31), date(2026, 8, 8))}
    assert by["2026-08-04"]["attendee_id"] == "cancel-2"


def test_real_label_keeps_full_location_without_pipe_separator():
    by = {r["date_str"]: r for r in
          _client_with_reservations().get_reservations([1], date(2026, 7, 31), date(2026, 8, 8))}
    # real location "Indoor Pickleball Court 1, Fairfax" has no ' | ' → kept whole
    assert by["2026-08-04"]["label"] == "Tue Aug 4 — 7:00 AM, Indoor Pickleball Court 1, Fairfax"
