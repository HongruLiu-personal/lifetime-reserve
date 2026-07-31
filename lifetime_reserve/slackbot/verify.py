"""Slack request signature verification (HMAC + timestamp window)."""

import hashlib
import hmac
import logging
import time

from lifetime_reserve.config import load_config

log = logging.getLogger(__name__)


def load_signing_secret():
    try:
        return load_config().slack_signing_secret
    except Exception:
        return ""


def verify_slack(body: bytes, timestamp: str, signature: str) -> bool:
    secret = load_signing_secret()
    if not secret:
        log.warning("slack_signing_secret not set — skipping signature verification")
        return True
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
        base = f"v0:{timestamp}:{body.decode()}".encode()
        expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False
