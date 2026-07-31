#!/usr/bin/env python3
"""Entry point shim — the reservation engine lives in lifetime_reserve.cli.

Kept at the repo root so cron / launchd / the Slack server subprocess keep invoking
`python3 reserve.py ...` unchanged. See MODULARIZATION_AND_SLACKBOT_PLAN.md.
"""

from lifetime_reserve.cli import main

if __name__ == "__main__":
    main()
