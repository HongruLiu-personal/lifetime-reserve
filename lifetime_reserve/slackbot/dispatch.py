"""Subprocess dispatch — run reserve.py and turn its output into a Slack reply.

Keeps the process boundary: the reservation engine runs as a subprocess (isolation +
a hard 120s timeout), and its marker-wrapped report / log lines are parsed back here.
`slack_post` / `slack_update` are thin wrappers over `notify` that read the bot token +
default channel from config.
"""

import logging
import subprocess
import sys

import requests

from lifetime_reserve import notify
from lifetime_reserve.config import load_config, BASE_DIR
from lifetime_reserve.slackbot.logparse import (
    SUMMARY_KEYWORDS, extract_report, extract_log_lines, truncate)

log = logging.getLogger(__name__)

SCRIPT = str(BASE_DIR / "reserve.py")
PYTHON = sys.executable


def slack_post(text, thread_ts=None, channel=None):
    """Post a new message via bot API. Returns (ts, channel) or (None, None) on failure."""
    cfg = load_config()
    return notify.post_message(
        cfg.slack_bot_token,
        channel or cfg.slack_channel,
        text,
        thread_ts=thread_ts,
    )


def slack_update(ts, channel, text):
    """Edit an existing message in place via bot API."""
    cfg = load_config()
    return notify.update_message(cfg.slack_bot_token, channel, ts, text)


def run_script(args, label):
    """Run `reserve.py <args>` as a subprocess. Returns (details_text, all_log_lines).

    Prefers the marker-wrapped report (no label prefix); otherwise falls back to
    keyword-matched summary lines / last few lines (label-prefixed), matching the
    original behavior. Handles timeout and unexpected errors.
    """
    log.info("Running: python3 reserve.py %s", " ".join(args))
    try:
        proc = subprocess.run(
            [PYTHON, SCRIPT] + args,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return f"*{label}*\nScript timed out after 120s", []
    except Exception as e:
        return f"*{label}*\nError: {e}", []

    raw = proc.stderr + proc.stdout
    all_lines = extract_log_lines(raw)
    report = extract_report(raw)
    if report:
        return truncate(report), all_lines
    summary_lines = [l for l in all_lines if any(k in l for k in SUMMARY_KEYWORDS)]
    if not summary_lines:
        summary_lines = all_lines[-3:] if all_lines else ["(no output)"]
    return truncate(f"*{label}*\n```{chr(10).join(summary_lines)}```"), all_lines


def run_and_report(args: list, response_url: str, label: str, verbose: bool = False):
    """Slash-command flow: post "{label}..." as a parent message we own, run the
    script, then chat.update the parent with the result. Verbose posts the full log as
    a thread reply. Falls back to response_url if the parent post fails."""
    parent_ts, parent_channel = slack_post(f"{label}...")
    details_text, all_lines = run_script(args, label)

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


def run_and_report_threaded(args, label, verbose, channel, thread_ts):
    """Events API flow: every message threads under the user's message (thread_ts).

    Post "{label}..." as a thread reply we own, run the script, chat.update it with the
    result, and (if verbose) post the full log as another reply in the same thread.
    No response_url fallback — events have no response_url.
    """
    parent_ts, parent_channel = slack_post(f"{label}...", channel=channel, thread_ts=thread_ts)
    details_text, all_lines = run_script(args, label)

    if parent_ts:
        slack_update(parent_ts, parent_channel, details_text)
        if verbose and all_lines:
            slack_post(truncate(f"*Full log:*\n```{chr(10).join(all_lines)}```"),
                       channel=channel, thread_ts=thread_ts)
    else:
        log.error("Could not post threaded reply for %s (chat.postMessage failed)", label)
