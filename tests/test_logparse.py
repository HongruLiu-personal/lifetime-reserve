from lifetime_reserve.protocol import REPORT_START, REPORT_END
from lifetime_reserve.slackbot.logparse import (
    extract_report, extract_log_lines, truncate)


# ── extract_report ───────────────────────────────────────────────────────────

def test_extract_report_between_markers():
    raw = f"noise\n{REPORT_START}\nthe report\n{REPORT_END}\nmore noise"
    assert extract_report(raw) == "the report"


def test_extract_report_missing_markers():
    assert extract_report("no markers here") is None


def test_extract_report_reversed_markers():
    raw = f"{REPORT_END}\nx\n{REPORT_START}"
    assert extract_report(raw) is None


# ── extract_log_lines ────────────────────────────────────────────────────────

def test_extract_log_lines_strips_prefix_and_framing():
    raw = "\n".join([
        "2026-08-03 09:00:00 INFO ============================================================",
        "2026-08-03 09:00:00 INFO Run started — mode: auto",
        "2026-08-03 09:00:01 INFO Logged in as user",
        "2026-08-03 09:00:02 WARNING No slots available",
        "2026-08-03 09:00:03 ERROR Booking failed",
        f"2026-08-03 09:00:04 INFO {REPORT_START}",
        "a plain line with no level",
    ])
    lines = extract_log_lines(raw)
    assert "Logged in as user" in lines
    assert "No slots available" in lines
    assert "Booking failed" in lines
    # framing / marker / non-level lines dropped
    assert not any(l.startswith("===") for l in lines)
    assert not any(l.startswith("Run started") for l in lines)
    assert not any(REPORT_START in l for l in lines)
    assert "a plain line with no level" not in lines


# ── truncate ─────────────────────────────────────────────────────────────────

def test_truncate_under_limit_unchanged():
    assert truncate("short", limit=100) == "short"


def test_truncate_at_exact_limit_unchanged():
    s = "x" * 50
    assert truncate(s, limit=50) == s


def test_truncate_over_limit_cuts_and_suffixes():
    s = "y" * 60
    out = truncate(s, limit=50)
    assert out.startswith("y" * 50)
    assert out.endswith("\n…```")
