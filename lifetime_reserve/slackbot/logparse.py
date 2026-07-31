"""Pure parsing of `reserve.py`'s subprocess output — no network, no I/O.

Extracts the marker-wrapped report, strips log-level framing, and truncates to Slack's
message limit. Marker strings come from `lifetime_reserve.protocol` (single source).
"""

from lifetime_reserve.protocol import REPORT_START, REPORT_END

SUMMARY_KEYWORDS = ("Confirmed:", "Cancelled", "No courts", "No preferred",
                    "No reservation", "No booking", "ERROR", "failed")


def extract_report(raw: str):
    """Extract the reserve.py report between markers. Returns None if not found."""
    start = raw.find(REPORT_START)
    end = raw.find(REPORT_END)
    if start == -1 or end == -1 or end < start:
        return None
    return raw[start + len(REPORT_START):end].strip()


def extract_log_lines(raw: str) -> list:
    """Extract log lines (INFO/WARNING/ERROR), stripping the level prefix and framing."""
    lines = []
    for line in raw.splitlines():
        for lvl in ("INFO ", "WARNING ", "ERROR "):
            if lvl in line:
                lines.append(line.split(lvl, 1)[-1].strip())
                break
    return [l for l in lines
            if not l.startswith("===")
            and not l.startswith("Run started")
            and REPORT_START not in l and REPORT_END not in l]


def truncate(text: str, limit: int = 3800) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…```"
