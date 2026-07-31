"""Configuration — a typed, frozen dataclass with defaults in one place.

`load_config()` validates the required keys against the raw JSON (preserving the
original required set + error) and returns a `Config`. Every default that used to be
scattered as `config.get(key, default)` across the handlers now lives here, once.
Paths are absolute (resolved from this file), so behavior no longer depends on the
process working directory.
"""

import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # repo root
CONFIG_FILE = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"

REQUIRED = ["username", "password", "club_id", "sport", "duration", "days_ahead"]


class ConfigError(RuntimeError):
    """Raised for missing/invalid configuration. The CLI catches it and exits."""


@dataclass(frozen=True)
class Config:
    # Required in config.json (defaults here are belt-and-suspenders; load_config
    # enforces their presence). Defaults for the optional keys match the values the
    # old code passed to config.get(...).
    username: str = ""
    password: str = ""
    club_id: str = "36"
    sport: str = "Pickleball: Indoor"
    duration: int = 60
    days_ahead: int = 8
    preferred_times: list = field(default_factory=list)
    preferred_courts: list = field(default_factory=list)
    member_ids: list = field(default_factory=list)
    retry_count: int = 3
    retry_delay_seconds: int = 10
    slack_bot_token: str = ""
    slack_channel: str = ""
    slack_signing_secret: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            # A typo like "preferred_time" (missing s) would otherwise be silently
            # ignored and fall back to a default — warn so it's noticed.
            log.warning("Ignoring unknown config keys: %s", ", ".join(sorted(unknown)))
        return cls(**{k: v for k, v in d.items() if k in known})


def validate_config(data: dict) -> None:
    """Raise ConfigError if any required key is absent from the raw config dict."""
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ConfigError(f"Missing required config keys: {', '.join(missing)}")


def load_config(path=CONFIG_FILE) -> Config:
    with open(path) as f:
        data = json.load(f)
    validate_config(data)
    return Config.from_dict(data)
