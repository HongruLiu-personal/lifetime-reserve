"""Command-line entry point for the reservation engine.

Owns argument parsing, file logging, the login-retry loop, the --wait-until spin-wait,
and dispatch to the mode handlers. This is the only layer that calls sys.exit.
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime

from lifetime_reserve.config import load_config, validate_config, ConfigError, LOG_DIR
from lifetime_reserve.api.client import LifetimeClient
from lifetime_reserve.notify import notify
from lifetime_reserve.reports import (
    emit_report, build_auto_report, build_slot_report, build_date_report,
    build_list_report, build_cancel_report)
from lifetime_reserve import modes

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)


def setup_file_logging():
    """Add a FileHandler that writes to logs/YYYY-MM-DD.log (append mode)."""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{date.today().strftime('%Y-%m-%d')}.log"
    fh = logging.FileHandler(log_file, mode="a")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(fh)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Lifetime Fitness Pickleball Court Reservation")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", action="store_true",
                       help="Auto-book best available slot from preferred_times config (day 8 only by default)")
    parser.add_argument("--fallback", action="store_true",
                        help="With --auto: if day 8 has no preferred slot, also scan days 1–(N-1)")
    group.add_argument("--dry-run", action="store_true",
                       help="Show available slots without booking")
    group.add_argument("--slot", metavar="DATETIME",
                       help="Book a specific slot: 'YYYY-MM-DD HH:MM' (24h, e.g. '2026-03-16 04:30')")
    group.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Book best preferred slot on a specific date")
    group.add_argument("--cancel", metavar="YYYY-MM-DD",
                       help="Cancel reservation on a specific date")
    group.add_argument("--list", action="store_true", dest="list_reservations",
                       help="List current upcoming reservations")
    parser.add_argument("--no-notify", action="store_true",
                        help="Skip Slack notification (used when called from the slash command server)")
    parser.add_argument("--wait-until", metavar="HH:MM:SS",
                        help="Login immediately, then wait until this time before booking (e.g. 09:00:00)")
    return parser.parse_args(argv)


def login_with_retry(client, config, attempts=3):
    """Log in, retrying transient failures. Exits the process if all attempts fail."""
    for attempt in range(1, attempts + 1):
        try:
            client.login(config["username"], config["password"])
            return
        except Exception as e:
            log.error("Login attempt %d/%d failed: %s", attempt, attempts, e)
            if attempt == attempts:
                log.error("All login attempts failed — exiting")
                sys.exit(1)
            time.sleep(2)


def wait_until(hhmmss):
    """Sleep (then briefly spin) until the given HH:MM:SS today. No-op if in the past."""
    if not hhmmss:
        return
    try:
        target_time = datetime.strptime(hhmmss, "%H:%M:%S").time()
    except ValueError:
        log.error("Invalid --wait-until format. Use HH:MM:SS (e.g. 09:00:00)")
        sys.exit(1)
    now = datetime.now()
    target_dt = datetime.combine(now.date(), target_time)
    wait_seconds = (target_dt - now).total_seconds()
    if wait_seconds <= 0:
        log.warning("--wait-until time %s is in the past, proceeding immediately", hhmmss)
        return
    log.info("Logged in early — waiting %.2fs until %s", wait_seconds, hhmmss)
    # Use monotonic clock for drift-free polling; datetime.now() only for initial gap.
    mono_target = time.monotonic() + wait_seconds
    while True:
        remaining = mono_target - time.monotonic()
        if remaining <= 0.020:
            break  # hand off to spin for final 20 ms
        time.sleep(min(remaining - 0.020, 0.5))
    # Spin for the last ~20 ms to avoid scheduler overshoot
    while time.monotonic() < mono_target:
        pass
    log.info("Reached target time %s (overshoot: %.1f ms)",
             hhmmss, (time.monotonic() - mono_target) * 1000)


def dispatch(args, client, config):
    """Run the selected mode and return a report string (or None for modes that print
    their own output, e.g. dry-run / interactive)."""
    if args.cancel:
        target_date, cancelled, found_count = modes.run_cancel(client, config, args.cancel)
        upcoming = modes._fetch_upcoming(client, config)
        return build_cancel_report(target_date, cancelled, found_count, upcoming)
    if args.date:
        target_date, booked_slot, reason, slots = modes.run_date(client, config, args.date)
        upcoming = modes._fetch_upcoming(client, config)
        return build_date_report(target_date, booked_slot, reason, slots, upcoming)
    if args.slot:
        dt, booked_slot, reason = modes.run_slot(client, config, args.slot)
        upcoming = modes._fetch_upcoming(client, config)
        return build_slot_report(dt, booked_slot, reason, upcoming)
    if args.auto:
        result = modes.run_auto(client, config, fallback=args.fallback)
        return build_auto_report(
            result["status"], result["target_date"], result.get("booked_slot"),
            result.get("day8_slots", []), result.get("reservation_labels", []),
        )
    if args.list_reservations:
        upcoming = modes._fetch_upcoming(client, config)
        return build_list_report(upcoming)
    if args.dry_run:
        modes.run_dry_run(client, config)
        return None
    modes.run_interactive(client, config)
    return None


def _mode_label(args):
    return ("auto" if args.auto else "dry-run" if args.dry_run
            else f"slot({args.slot})" if args.slot
            else f"date({args.date})" if args.date
            else f"cancel({args.cancel})" if args.cancel
            else "list" if args.list_reservations
            else "interactive")


def main(argv=None):
    setup_file_logging()
    args = parse_args(argv)
    log.info("=" * 60)
    log.info("Run started — mode: %s", _mode_label(args))
    try:
        config = load_config()
        validate_config(config)
    except ConfigError as e:
        log.error("%s", e)
        sys.exit(1)

    client = LifetimeClient()
    login_with_retry(client, config)
    wait_until(args.wait_until)

    try:
        report = dispatch(args, client, config)
    except (ValueError, ConfigError) as e:
        # Input-validation failures from the mode handlers.
        log.error("%s", e)
        sys.exit(1)

    if report is not None:
        emit_report(report)
        if not args.no_notify:
            notify(config, report)
