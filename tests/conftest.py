"""Shared pytest fixtures and fakes.

`FakeResponse` / `FakeSession` stand in for `requests` so the API client can be tested
with no network. `FakeClient` (Phase 3) drives the mode handlers.
"""

import requests


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


class FakeSession:
    """Records requests and returns queued responses per HTTP method.

    Queue a response with `queue(method, resp)`; calls pop FIFO. A queued value may be
    a FakeResponse or a zero-arg callable (e.g. to raise). Exhausted queues return a
    default 200/empty response.
    """

    def __init__(self):
        self.headers = {}
        self.calls = []          # list of (method, url, kwargs)
        self._responses = {}     # method -> list

    def queue(self, method, *responses):
        self._responses.setdefault(method, []).extend(responses)
        return self

    def _handle(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        q = self._responses.get(method, [])
        r = q.pop(0) if q else FakeResponse()
        return r() if callable(r) else r

    def post(self, url, **kwargs):
        return self._handle("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._handle("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self._handle("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._handle("DELETE", url, **kwargs)
