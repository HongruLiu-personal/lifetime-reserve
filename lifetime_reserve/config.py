"""Configuration loading + paths — single source for both entrypoints.

`config` is a plain dict in this phase; it becomes a typed `Config` dataclass in
Phase 3g. Paths are absolute (resolved from this file), so behavior no longer depends
on the process working directory.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # repo root
CONFIG_FILE = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"


class ConfigError(RuntimeError):
    """Raised for missing/invalid configuration. The CLI catches it and exits."""


def load_config(path=CONFIG_FILE):
    with open(path) as f:
        return json.load(f)


def validate_config(config):
    required = ["username", "password", "club_id", "sport", "duration", "days_ahead"]
    missing = [k for k in required if k not in config]
    if missing:
        raise ConfigError(f"Missing required config keys: {', '.join(missing)}")
