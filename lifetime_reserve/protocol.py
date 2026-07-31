"""The stdout contract between the reservation engine and the Slack layer.

`reserve.py` prints its final report wrapped in these markers (via
`reports.emit_report`); the Slack server's `slackbot.logparse` extracts the text
between them. Defined here, in a neutral module both sides import, so the marker
strings live in exactly one place.
"""

REPORT_START = "<<<REPORT>>>"
REPORT_END = "<<<ENDREPORT>>>"
