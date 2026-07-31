---
name: check-run
description: Read `/Users/hongruliu/src/lifetime-reserve/logs/` and produce a summary table of every auto-mode run found in the log.
argument-hint: "[YYYY-MM-DD | today]"
---

Read all log files in `/Users/hongruliu/src/lifetime-reserve/logs/` (daily files named `YYYY-MM-DD.log`) and produce a summary table of every auto-mode run found.

A run starts at a `Run started — mode: auto` line (or, for older entries without that marker, at the first timestamped line of a new calendar date). Each run ends just before the next run begins.

For each run, extract and display:

| Column | Source |
|--------|--------|
| **Date** | Calendar date of the run |
| **Start** | Wall-clock time the script started (first timestamp) |
| **9AM overshoot** | From `overshoot: X ms` — omit if not present |
| **Day 8 target** | The date searched as "day 8" |
| **Day 8 result** | `booked HH:MM AM/PM CourtN` on success; `no preferred` if no preferred time matched; `error (Nxx / connection)` if all attempts failed; include attempt count if retries happened (e.g. `no preferred (5 attempts)`) |
| **Fallback** | If the day-1–7 scan ran: `booked HH:MM AM/PM CourtN on YYYY-MM-DD`, or `no preferred`, or `skipped (all reserved)` |
| **Outcome** | `✓ Booked — HH:MM AM/PM CourtN on YYYY-MM-DD` or `✗ No booking` |
| **Errors** | Any ERROR lines (brief), or — |

Sort rows by date ascending. After the table, print a one-line summary: total runs, how many resulted in a booking, how many had errors.

If $ARGUMENTS is provided and looks like a date (YYYY-MM-DD) or "today", filter the table to that date only and also show the full timestamped log lines for that run below the table.
