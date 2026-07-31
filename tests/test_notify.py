import lifetime_reserve.notify as notify
from tests.conftest import FakeResponse


class RecordingPost:
    """Stand-in for requests.post that records calls and returns a queued response."""
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._responses.pop(0) if self._responses else FakeResponse()


# ── post_message ─────────────────────────────────────────────────────────────

def test_post_message_success(monkeypatch):
    post = RecordingPost(FakeResponse({"ok": True, "ts": "123.45", "channel": "C1"}))
    monkeypatch.setattr(notify.requests, "post", post)
    ts, ch = notify.post_message("tok", "C1", "hi")
    assert (ts, ch) == ("123.45", "C1")
    assert post.calls[0][1]["json"]["channel"] == "C1"


def test_post_message_threaded(monkeypatch):
    post = RecordingPost(FakeResponse({"ok": True, "ts": "1", "channel": "C1"}))
    monkeypatch.setattr(notify.requests, "post", post)
    notify.post_message("tok", "C1", "hi", thread_ts="99.9")
    assert post.calls[0][1]["json"]["thread_ts"] == "99.9"


def test_post_message_not_ok(monkeypatch):
    post = RecordingPost(FakeResponse({"ok": False, "error": "channel_not_found"}))
    monkeypatch.setattr(notify.requests, "post", post)
    assert notify.post_message("tok", "C1", "hi") == (None, None)


def test_post_message_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(notify.requests, "post", boom)
    assert notify.post_message("tok", "C1", "hi") == (None, None)


# ── update_message ───────────────────────────────────────────────────────────

def test_update_message_ok(monkeypatch):
    post = RecordingPost(FakeResponse({"ok": True}))
    monkeypatch.setattr(notify.requests, "post", post)
    assert notify.update_message("tok", "C1", "1.2", "edited")["ok"] is True


# ── notify wrapper ───────────────────────────────────────────────────────────

def test_notify_noop_without_token_or_channel(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(notify, "post_message", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or ("t", "c"))
    assert notify.notify({}, "hi") == (None, None)          # no token/channel
    assert notify.notify({"slack_bot_token": "t"}, "hi") == (None, None)  # no channel
    assert called["n"] == 0


def test_notify_posts_with_config(monkeypatch):
    seen = {}
    def fake_post(token, channel, text, thread_ts=None):
        seen.update(token=token, channel=channel, text=text)
        return "ts1", channel
    monkeypatch.setattr(notify, "post_message", fake_post)
    cfg = {"slack_bot_token": "tok", "slack_channel": "C9"}
    ts, ch = notify.notify(cfg, "hello")
    assert (ts, ch) == ("ts1", "C9")
    assert seen == {"token": "tok", "channel": "C9", "text": "hello"}


def test_notify_channel_override(monkeypatch):
    seen = {}
    monkeypatch.setattr(notify, "post_message",
                        lambda t, c, x, thread_ts=None: seen.update(channel=c) or ("ts", c))
    notify.notify({"slack_bot_token": "tok", "slack_channel": "C9"}, "hi", channel="COVERRIDE")
    assert seen["channel"] == "COVERRIDE"
