import json

import pytest

from pitwall_rig.config import DEFAULTS, Config, ConfigError, deep_merge, validate


def test_defaults_are_valid():
    assert validate(DEFAULTS) == []


def test_creates_and_merges_user_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"server": {"port": 9000}, "display": {"accent": "#00ff00"}}))
    cfg = Config(path)
    assert cfg["server"]["port"] == 9000
    assert cfg["server"]["host"] == "127.0.0.1"  # default kept
    assert cfg["display"]["accent"] == "#00ff00"


def test_bad_values_are_explained(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"rates": {"poll_hz": 0}, "layouts": {"driving": [[{"widget": "nope"}]]}}))
    with pytest.raises(ConfigError) as e:
        Config(path)
    msg = str(e.value)
    assert "poll_hz" in msg and "unknown widget" in msg


def test_update_rejects_invalid_and_keeps_old(config):
    errs = config.update({"server": {"port": 80}})
    assert errs and config["server"]["port"] == 8765
    assert config.update({"server": {"port": 9100}}) == []
    assert json.loads(config.path.read_text())["server"]["port"] == 9100


def test_bindings_replace_rather_than_merge():
    out = deep_merge(DEFAULTS, {"bindings": {"next_page": []}})
    assert out["bindings"] == {"next_page": []}
