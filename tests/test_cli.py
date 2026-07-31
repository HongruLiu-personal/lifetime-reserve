"""B1: hard failures of a direct run post a Slack alert (unless --no-notify)."""

import pytest

from lifetime_reserve.config import Config
from lifetime_reserve import cli

CFG = Config.from_dict({"username": "u", "password": "p",
                        "slack_bot_token": "tok", "slack_channel": "C"})


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(cli, "setup_file_logging", lambda: None)
    monkeypatch.setattr(cli, "load_config", lambda: CFG)
    monkeypatch.setattr(cli.time, "sleep", lambda *_: None)  # skip login-retry backoff
    monkeypatch.setattr(cli, "emit_report", lambda text: None)


class BoomClient:
    def login(self, u, p):
        raise RuntimeError("api down")


class OkClient:
    def login(self, u, p):
        return ("t", "s")


def test_hard_failure_notifies_and_exits(monkeypatch):
    monkeypatch.setattr(cli, "LifetimeClient", lambda: BoomClient())
    notified = {}
    monkeypatch.setattr(cli, "notify", lambda config, text, **k: notified.update(text=text))
    with pytest.raises(SystemExit) as ei:
        cli.main(["--auto"])
    assert ei.value.code == 1
    assert "failed" in notified["text"]


def test_hard_failure_with_no_notify_is_silent(monkeypatch):
    monkeypatch.setattr(cli, "LifetimeClient", lambda: BoomClient())
    called = []
    monkeypatch.setattr(cli, "notify", lambda *a, **k: called.append(1))
    with pytest.raises(SystemExit) as ei:
        cli.main(["--auto", "--no-notify"])
    assert ei.value.code == 1
    assert called == []                       # server owns the reply; no double-post


def test_success_notifies_report(monkeypatch):
    monkeypatch.setattr(cli, "LifetimeClient", lambda: OkClient())
    monkeypatch.setattr(cli, "dispatch", lambda args, client, config: "THE REPORT")
    notified = {}
    monkeypatch.setattr(cli, "notify", lambda config, text, **k: notified.update(text=text))
    cli.main(["--auto"])                       # no SystemExit
    assert notified["text"] == "THE REPORT"
