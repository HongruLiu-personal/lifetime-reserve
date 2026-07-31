#!/usr/bin/env python3
"""
Slack slash command server for /reserve and /cancel.

Commands:
  /reserve                      → auto-book day 8
  /reserve YYYY-MM-DD           → book best preferred slot on that date
  /reserve YYYY-MM-DD HH:MM     → book that exact date/time (24h)
  /cancel  YYYY-MM-DD           → cancel reservation on that date
  /list                         → list current upcoming reservations

Setup:
  Set slack_signing_secret in config.json, then run:
    python3 server.py
  or via systemd (see reserve-server.service).
"""

import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import requests

from lifetime_reserve.slackbot.parsing import parse_date_token, parse_command_text
from lifetime_reserve.slackbot.logparse import (
    SUMMARY_KEYWORDS, extract_report, extract_log_lines, truncate)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SCRIPT = os.path.join(BASE_DIR, "reserve.py")
PYTHON = sys.executable
PORT = int(os.environ.get("PORT", "5000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_signing_secret():
    try:
        return load_config().get("slack_signing_secret", "")
    except Exception:
        return ""


def slack_post(text, thread_ts=None):
    """Post a new message via bot API. Returns (ts, channel) or (None, None) on failure."""
    cfg = load_config()
    payload = {"channel": cfg.get("slack_channel", ""), "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {cfg.get('slack_bot_token', '')}"},
        json=payload,
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        log.error("chat.postMessage failed: %s", data.get("error"))
        return None, None
    return data["ts"], data["channel"]


def slack_update(ts, channel, text):
    """Edit an existing message in place via bot API."""
    cfg = load_config()
    resp = requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {cfg.get('slack_bot_token', '')}"},
        json={"channel": channel, "ts": ts, "text": text},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        log.error("chat.update failed: %s (ts=%s, channel=%s)", data.get("error"), ts, channel)
    return data


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


def run_and_report(args: list, response_url: str, label: str, verbose: bool = False):
    """Single-parent thread flow:
      - HTTP response has already posted "{label}..." (loading indicator, stays as-is).
      - Post a parent via chat.postMessage — we own its ts for threading.
      - Run reserve.py, then chat.update the parent with the final result.
      - Verbose log posts as a reply in the parent's thread.

    We do NOT try to remove the HTTP-posted "..." because Slack's response_url doesn't
    actually replace slash-command in_channel messages (it posts new ones instead).
    """
    log.info("Running: python3 reserve.py %s", " ".join(args))

    parent_ts, parent_channel = slack_post(f"{label}...")

    details_text = None
    all_lines = []
    try:
        proc = subprocess.run(
            [PYTHON, SCRIPT] + args,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = proc.stderr + proc.stdout
        all_lines = extract_log_lines(raw)

        report = extract_report(raw)
        if report:
            details_text = truncate(report)
        else:
            summary_lines = [l for l in all_lines if any(k in l for k in SUMMARY_KEYWORDS)]
            if not summary_lines:
                summary_lines = all_lines[-3:] if all_lines else ["(no output)"]
            details_text = truncate(f"*{label}*\n```{chr(10).join(summary_lines)}```")
    except subprocess.TimeoutExpired:
        details_text = f"*{label}*\nScript timed out after 120s"
    except Exception as e:
        details_text = f"*{label}*\nError: {e}"

    if parent_ts:
        slack_update(parent_ts, parent_channel, details_text)
        if verbose and all_lines:
            slack_post(truncate(f"*Full log:*\n```{chr(10).join(all_lines)}```"),
                       thread_ts=parent_ts)
    else:
        # Fallback: no parent ts (chat.postMessage failed) — post via response_url
        try:
            r = requests.post(
                response_url,
                json={"replace_original": False, "response_type": "in_channel", "text": details_text},
                timeout=10,
            )
            log.info("fallback response_url: HTTP %s %s", r.status_code, r.text[:200])
        except Exception as e:
            log.error("Failed to post fallback result: %s", e)


class SlackHandler(BaseHTTPRequestHandler):
    timeout = 10  # close half-open connections so port-scanners can't wedge threads

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        ts = self.headers.get("X-Slack-Request-Timestamp", "0")
        sig = self.headers.get("X-Slack-Signature", "")
        if not verify_slack(body, ts, sig):
            self._send(403, {"error": "Invalid signature"})
            return

        params = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        text = params.get("text", "").strip()
        response_url = params.get("response_url", "")

        if self.path == "/reserve":
            args, label, verbose = parse_command_text(text)
            if args is None:
                self._send(200, {"response_type": "ephemeral", "text": label})
                return
            # Respond in_channel immediately — this keeps the user's /reserve visible
            # and posts "label..." as the bot's initial message. response_url will
            # replace it with the result once the script finishes.
            self._send(200, {"response_type": "in_channel", "text": f"{label}..."})
            threading.Thread(
                target=run_and_report,
                args=(args + ["--no-notify"], response_url, label, verbose),
                daemon=True,
            ).start()

        elif self.path == "/cancel":
            verbose = bool(re.search(r"\bverbose\b", text, re.IGNORECASE))
            clean = re.sub(r"\bverbose\b", "", text, flags=re.IGNORECASE).strip()
            target_date = parse_date_token(clean)
            if target_date is None:
                self._send(200, {"response_type": "ephemeral",
                                 "text": "Usage: `/cancel <date>` — date is `YYYY-MM-DD` or a weekday name (`Mon`, `Tuesday`, ...)"})
                return
            date_str = target_date.strftime("%Y-%m-%d")
            label = f"Cancel {target_date.strftime('%a %b %-d')}"
            self._send(200, {"response_type": "in_channel", "text": f"{label}..."})
            threading.Thread(
                target=run_and_report,
                args=(["--cancel", date_str, "--no-notify"], response_url, label, verbose),
                daemon=True,
            ).start()

        elif self.path == "/list":
            verbose = bool(re.search(r"\bverbose\b", text, re.IGNORECASE))
            label = "Reservations"
            self._send(200, {"response_type": "in_channel", "text": f"{label}..."})
            threading.Thread(
                target=run_and_report,
                args=(["--list", "--no-notify"], response_url, label, verbose),
                daemon=True,
            ).start()

        else:
            self._send(404, {"error": "Not found"})

    def _ack(self):
        """Respond 200 with empty body — tells Slack we received the command, no visible reply."""
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info("Slack request: " + fmt, *args)


if __name__ == "__main__":
    log.info("Starting Slack command server on port %d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), SlackHandler).serve_forever()
