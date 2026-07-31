"""Tests for the Slack HMAC signature verification — the only auth on /events."""

import hashlib
import hmac
import time

import pytest

import lifetime_reserve.slackbot.verify as verify

SECRET = "test-signing-secret"
BODY = b'{"type":"event_callback","event":{}}'


def sign(body: bytes, ts: str, secret: str = SECRET) -> str:
    base = f"v0:{ts}:{body.decode()}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


@pytest.fixture
def secret(monkeypatch):
    """Default: a known non-empty secret. Tests can re-patch for the empty case."""
    monkeypatch.setattr(verify, "load_signing_secret", lambda: SECRET)


def test_valid_signature(secret):
    ts = str(int(time.time()))
    assert verify.verify_slack(BODY, ts, sign(BODY, ts)) is True


def test_tampered_body(secret):
    ts = str(int(time.time()))
    sig = sign(b'{"different":"body"}', ts)   # signed for other bytes
    assert verify.verify_slack(BODY, ts, sig) is False


def test_wrong_secret(secret):
    ts = str(int(time.time()))
    sig = sign(BODY, ts, secret="not-the-secret")
    assert verify.verify_slack(BODY, ts, sig) is False


def test_timestamp_too_old(secret):
    ts = str(int(time.time()) - 400)           # outside the 300s window
    assert verify.verify_slack(BODY, ts, sign(BODY, ts)) is False


def test_timestamp_too_far_future(secret):
    ts = str(int(time.time()) + 400)
    assert verify.verify_slack(BODY, ts, sign(BODY, ts)) is False


def test_non_integer_timestamp(secret):
    assert verify.verify_slack(BODY, "not-a-number", "v0=whatever") is False


def test_empty_secret_bypasses(monkeypatch):
    # Documented slash-command back-compat: no secret configured → allow (verify True).
    # B3 stops this bypass from applying to the /events route specifically.
    monkeypatch.setattr(verify, "load_signing_secret", lambda: "")
    assert verify.verify_slack(BODY, "0", "v0=irrelevant") is True
