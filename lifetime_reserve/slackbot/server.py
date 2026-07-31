"""Slack slash-command HTTP server.

Endpoints: POST /reserve, /cancel, /list. Verifies the Slack signature, parses the
command, ACKs immediately, and dispatches the reserve.py subprocess on a worker thread.
(The Events API /events endpoint is added in Phase 4.)
"""

import json
import logging
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from lifetime_reserve.slackbot.verify import verify_slack
from lifetime_reserve.slackbot.parsing import parse_date_token, parse_command_text
from lifetime_reserve.slackbot.dispatch import run_and_report

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
    log.info("Starting Slack command server on port %d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), SlackHandler).serve_forever()


if __name__ == "__main__":
    main()
