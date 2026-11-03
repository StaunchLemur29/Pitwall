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


def test_saves_only_changes(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.update({"display": {"accent": "#00ff00"}})
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved == {"display": {"accent": "#00ff00"}}


def test_picks_vertical_secondary_monitor():
    from pitwall_rig.monitors import Monitor, pick_dashboard_monitor

    main = Monitor(0, 0, 2560, 1440, True)
    side = Monitor(-1080, -200, 1080, 1920, False)
    assert pick_dashboard_monitor([main, side]) == side
    assert pick_dashboard_monitor([main]) is None
    other = Monitor(2560, 0, 1920, 1080, False)
    assert pick_dashboard_monitor([main, other]) == other


def test_old_default_layouts_are_upgraded(tmp_path):
    from pitwall_rig.config import _OLD_DEFAULT_LAYOUTS

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"layouts": _OLD_DEFAULT_LAYOUTS[0], "display": {"accent": "#111111"}}))
    cfg = Config(path)
    assert "turn_by_turn" in json.dumps(cfg["layouts"])
    assert cfg["display"]["accent"] == "#111111"


def test_old_default_layout_upgrades_to_the_new_page_one(tmp_path):
    import json

    from pitwall_rig.config import _OLD_DEFAULT_LAYOUTS, Config

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"layouts": _OLD_DEFAULT_LAYOUTS[0]}))
    cfg = Config(p)
    assert cfg["layouts"]["driving"][0][-1]["widget"] == "status_line"
