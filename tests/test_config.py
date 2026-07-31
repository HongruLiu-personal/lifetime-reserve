import json

import pytest

from lifetime_reserve.config import Config, load_config, validate_config, ConfigError

COMPLETE = {
    "username": "u", "password": "p", "club_id": "36",
    "sport": "Pickleball: Indoor", "duration": 60, "days_ahead": 8,
}


# ── load_config ──────────────────────────────────────────────────────────────

def test_load_config_returns_typed_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(COMPLETE))
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.username == "u" and cfg.days_ahead == 8


def test_load_config_raises_on_missing_required(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"username": "u", "password": "p"}))  # missing club_id etc.
    with pytest.raises(ConfigError):
        load_config(p)


# ── validate_config (operates on the raw dict) ───────────────────────────────

def test_validate_config_passes_when_complete():
    validate_config(COMPLETE)  # no raise


def test_validate_config_raises_and_lists_missing():
    with pytest.raises(ConfigError) as ei:
        validate_config({"username": "u", "password": "p"})
    msg = str(ei.value)
    assert "club_id" in msg and "days_ahead" in msg


# ── Config.from_dict ─────────────────────────────────────────────────────────

def test_from_dict_applies_defaults():
    cfg = Config.from_dict({"username": "u", "password": "p"})
    # defaults match the old inline config.get(...) defaults
    assert cfg.club_id == "36"
    assert cfg.sport == "Pickleball: Indoor"
    assert cfg.duration == 60
    assert cfg.days_ahead == 8
    assert cfg.retry_count == 3
    assert cfg.retry_delay_seconds == 10
    assert cfg.preferred_times == [] and cfg.preferred_courts == []
    assert cfg.member_ids == []
    assert cfg.slack_bot_token == "" and cfg.slack_channel == ""


def test_from_dict_ignores_unknown_keys():
    cfg = Config.from_dict({"username": "u", "unknown_key": "x"})
    assert cfg.username == "u"
    assert not hasattr(cfg, "unknown_key")


def test_from_dict_warns_on_unknown_keys(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="lifetime_reserve.config"):
        cfg = Config.from_dict({"username": "u", "preferred_time": ["7:00 AM"]})  # typo: missing s
    assert "preferred_time" in caplog.text
    assert cfg.preferred_times == []   # typo'd key ignored → falls back to default
