"""Slack posting — unified for both entrypoints.

`post_message` / `update_message` are the low-level Web API calls (they take an
explicit `channel`, which the Events API path needs since replies go to the event's
channel, not a fixed config channel). `notify` is the convenience wrapper used by
reserve.py's post-run notification. All three log failures and never raise.
"""

import logging

import requests

log = logging.getLogger(__name__)

SLACK_TIMEOUT = (5, 10)


def post_message(token, channel, text, thread_ts=None):
    """chat.postMessage. Returns (ts, channel) or (None, None) on failure."""
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=SLACK_TIMEOUT,
        )
        data = resp.json()
    except Exception as e:
        log.warning("chat.postMessage failed: %s", e)
        return None, None
    if not data.get("ok"):
        log.error("chat.postMessage failed: %s", data.get("error"))
        return None, None
    return data["ts"], data["channel"]


def update_message(token, channel, ts, text):
    """chat.update — edit a message in place. Returns the API response dict."""
    try:
        resp = requests.post(
            "https://slack.com/api/chat.update",
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": channel, "ts": ts, "text": text},
            timeout=SLACK_TIMEOUT,
        )
        data = resp.json()
    except Exception as e:
        log.error("chat.update failed: %s (ts=%s, channel=%s)", e, ts, channel)
        return {"ok": False, "error": str(e)}
    if not data.get("ok"):
        log.error("chat.update failed: %s (ts=%s, channel=%s)", data.get("error"), ts, channel)
    return data


def notify(config, text, channel=None, thread_ts=None):
    """Post `text` using the config's bot token + channel. Logs, never raises.

    Replaces reserve.py's send_slack(). No-ops silently if token/channel absent.
    """
    token = config.get("slack_bot_token", "")
    ch = channel or config.get("slack_channel", "")
    if not token or not ch:
        return None, None
    ts, ch2 = post_message(token, ch, text, thread_ts=thread_ts)
    if ts:
        log.info("Slack notification sent")
    return ts, ch2
