#!/usr/bin/env python3
"""Entry point shim — the Slack server lives in lifetime_reserve.slackbot.server.

Kept at the repo root so systemd (reserve-server.service) keeps invoking
`python3 server.py` unchanged. See MODULARIZATION_AND_SLACKBOT_PLAN.md.
"""

from lifetime_reserve.slackbot.server import main

if __name__ == "__main__":
    main()
