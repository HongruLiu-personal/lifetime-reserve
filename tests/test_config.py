import json

import pytest

from lifetime_reserve.config import load_config, validate_config, ConfigError

COMPLETE = {
    "username": "u", "password": "p", "club_id": "36",
    "sport": "Pickleball: Indoor", "duration": 60, "days_ahead": 8,
}


def test_load_config_reads_json(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(COMPLETE))
    assert load_config(p) == COMPLETE


def test_validate_config_passes_when_complete():
    validate_config(COMPLETE)  # no raise


def test_validate_config_raises_and_lists_missing():
    with pytest.raises(ConfigError) as ei:
        validate_config({"username": "u", "password": "p"})
    msg = str(ei.value)
    assert "club_id" in msg and "days_ahead" in msg
