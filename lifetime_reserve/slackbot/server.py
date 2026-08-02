"""Slack HTTP server.

Endpoint:
  POST /events  — Events API (JSON): app_mention + message.im, with threaded replies
                  under the user's message

Verifies the Slack signature on every request, ACKs within Slack's 3s window, and
dispatches the reserve.py subprocess on a worker thread.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lifetime_reserve.config import load_config
from lifetime_reserve.slackbot.verify import verify_slack, load_signing_secret
from lifetime_reserve.slackbot.dispatch import run_and_report_threaded
from lifetime_reserve.slackbot.events import (
    dedup_seen, should_process_event, handle_event)

PORT = int(os.environ.get("PORT", "5000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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

        if self.path == "/events":
            self._handle_events(body)
            return

        self._send(404, {"error": "Not found"})

    def _handle_events(self, body):
        # /events triggers real bookings, so require a configured signing secret —
        # fail closed rather than inherit verify_slack's empty-secret allow.
        if not load_signing_secret():
            log.error("/events rejected: slack_signing_secret not configured")
            self._send(403, {"error": "events disabled: signing secret not configured"})
            return
        try:
            payload = json.loads(body)
        except Exception:
            self._send(400, {"error": "invalid JSON"})
            return

        # One-time URL verification handshake when enabling Event Subscriptions.
        if payload.get("type") == "url_verification":
            self._send(200, {"challenge": payload.get("challenge", "")})
            return

        if payload.get("type") != "event_callback":
            self._ack()
            return

        # ACK within Slack's 3s window BEFORE doing any work (Slack retries otherwise).
        self._ack()

        event_id = payload.get("event_id")
        if not event_id or dedup_seen(event_id):
            return
        event = payload.get("event", {})
        if not should_process_event(event):
            return
        threading.Thread(
            target=handle_event,
            args=(event, load_config(), run_and_report_threaded),
            daemon=True,
        ).start()

    def _ack(self):
        """Respond 200 with empty body — tells Slack we received the request, no visible reply."""
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


def main():
    if not load_signing_secret():
        log.warning("SECURITY: slack_signing_secret is not set — /events is "
                    "UNAUTHENTICATED and will act on any POST. Set it before exposing "
                    "this server.")
    log.info("Starting Slack server (/events) on port %d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), SlackHandler).serve_forever()


if __name__ == "__main__":
    main()
