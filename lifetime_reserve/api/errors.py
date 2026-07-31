"""API error helpers."""

import requests


class ApiError(RuntimeError):
    """Raised for Lifetime API failures not already covered by requests exceptions."""


def raise_for_status_with_body(resp):
    """Like raise_for_status() but includes the response body in the exception message."""
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body = resp.text[:500] if resp.text else "(empty)"
        raise requests.HTTPError(f"{e} — body: {body}", response=resp) from None
