"""Route-glue tests for POST /events — drives SlackHandler._handle_events with the
socket methods (_send/_ack) stubbed, so no real HTTP is involved."""

import json

import pytest

from lifetime_reserve.config import Config
from lifetime_reserve.slackbot import server as srv
from lifetime_reserve.slackbot import events

CONFIG = Config.from_dict({"slack_bot_token": "tok", "slack_channel": "C"})


class FakeHandler(srv.SlackHandler):
    def __init__(self):  # bypass BaseHTTPRequestHandler.__init__ (no socket)
        self.sent = []
        self.acked = False

    def _send(self, code, data):
        self.sent.append((code, data))

    def _ack(self):
        self.acked = True


class FakeThread:
    instances = []

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args
        FakeThread.instances.append(self)

    def start(self):
        pass


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    events.RECENT_EVENT_IDS.clear()
    FakeThread.instances.clear()
    monkeypatch.setattr(srv.threading, "Thread", FakeThread)
    monkeypatch.setattr(srv, "load_config", lambda: CONFIG)
    # B3 guard reads the signing secret; stub it so these tests don't depend on a real
    # config.json (absent on CI → would otherwise 403 everything). B3's own test overrides.
    monkeypatch.setattr(srv, "load_signing_secret", lambda: "sekret")
    yield
    events.RECENT_EVENT_IDS.clear()


def _events(payload):
    h = FakeHandler()
    h._handle_events(json.dumps(payload).encode())
    return h


def test_url_verification_echoes_challenge():
    h = _events({"type": "url_verification", "challenge": "abc123"})
    assert h.sent == [(200, {"challenge": "abc123"})]
    assert not FakeThread.instances


def test_event_callback_acks_and_dispatches():
    h = _events({"type": "event_callback", "event_id": "E1",
                 "event": {"type": "app_mention", "text": "reserve",
                           "ts": "1.0", "channel": "C9"}})
    assert h.acked is True
    assert len(FakeThread.instances) == 1
    assert FakeThread.instances[0].target is srv.handle_event


def test_event_callback_dedup_second_delivery_not_dispatched():
    payload = {"type": "event_callback", "event_id": "DUP",
               "event": {"type": "app_mention", "text": "reserve", "ts": "1.0", "channel": "C9"}}
    _events(payload)
    _events(payload)  # retry with same event_id
    assert len(FakeThread.instances) == 1  # only the first dispatched


def test_event_callback_filtered_event_not_dispatched():
    # bot echo → should_process_event False → acked but no dispatch
    h = _events({"type": "event_callback", "event_id": "E2",
                 "event": {"type": "app_mention", "bot_id": "B1", "ts": "1.0", "channel": "C9"}})
    assert h.acked is True
    assert not FakeThread.instances


def test_invalid_json_returns_400():
    h = FakeHandler()
    h._handle_events(b"not json{")
    assert h.sent == [(400, {"error": "invalid JSON"})]


def test_events_fail_closed_without_signing_secret(monkeypatch):
    # B3: /events must reject (not inherit verify_slack's empty-secret allow) when no
    # signing secret is configured, since it triggers real bookings.
    monkeypatch.setattr(srv, "load_signing_secret", lambda: "")
    h = _events({"type": "url_verification", "challenge": "x"})
    assert h.sent == [(403, {"error": "events disabled: signing secret not configured"})]
    assert not FakeThread.instances
