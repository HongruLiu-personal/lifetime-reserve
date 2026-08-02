import subprocess

import lifetime_reserve.slackbot.dispatch as dispatch
from lifetime_reserve.protocol import REPORT_START, REPORT_END


class FakeProc:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


def set_proc(monkeypatch, stdout="", stderr=""):
    monkeypatch.setattr(dispatch.subprocess, "run",
                        lambda *a, **k: FakeProc(stdout, stderr))


# ── run_script ───────────────────────────────────────────────────────────────

def test_run_script_prefers_report(monkeypatch):
    stdout = f"2026 INFO searching\n{REPORT_START}\nMY REPORT\n{REPORT_END}\n"
    set_proc(monkeypatch, stdout=stdout)
    details, all_lines = dispatch.run_script(["--auto"], "Auto")
    assert details == "MY REPORT"                 # report used verbatim, no label prefix
    assert "searching" in all_lines


def test_run_script_summary_fallback(monkeypatch):
    # No markers, but a SUMMARY_KEYWORDS line ("Confirmed:") is present.
    set_proc(monkeypatch, stdout="2026 INFO Confirmed: regId=1\n2026 INFO other\n")
    details, _ = dispatch.run_script(["--auto"], "Auto")
    assert details.startswith("*Auto*")
    assert "Confirmed: regId=1" in details


def test_run_script_last_lines_fallback(monkeypatch):
    set_proc(monkeypatch, stdout="2026 INFO a\n2026 INFO b\n2026 INFO c\n2026 INFO d\n")
    details, _ = dispatch.run_script(["--auto"], "Auto")
    # no keyword match → last 3 lines
    assert "b" in details and "c" in details and "d" in details


def test_run_script_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=120)
    monkeypatch.setattr(dispatch.subprocess, "run", boom)
    details, all_lines = dispatch.run_script(["--auto"], "Auto")
    assert details == "*Auto*\nScript timed out after 120s"
    assert all_lines == []


# ── run_and_report_threaded ────────────────────────────────────────────────────

def test_run_and_report_threaded_threads_under_user_message(monkeypatch):
    # Events path: parent + verbose reply both go to the event channel and thread under
    # the USER's message (thread_ts), NOT under the parent result ts.
    posts = []
    monkeypatch.setattr(dispatch, "slack_post",
                        lambda text, thread_ts=None, channel=None: (posts.append((text, channel, thread_ts)) or ("pts", "C_EVENT")))
    updates = []
    monkeypatch.setattr(dispatch, "slack_update", lambda ts, ch, text: updates.append((ts, ch, text)))
    monkeypatch.setattr(dispatch, "run_script", lambda args, label: ("RESULT", ["log1"]))

    dispatch.run_and_report_threaded(["--list"], "Reservations", True,
                                     channel="C_EVENT", thread_ts="user.ts")
    assert posts[0] == ("Reservations...", "C_EVENT", "user.ts")   # parent in user thread
    assert updates == [("pts", "C_EVENT", "RESULT")]
    # verbose reply threads under user.ts (not the parent "pts")
    assert any(c == "C_EVENT" and t == "user.ts" and "Full log" in text for text, c, t in posts)
