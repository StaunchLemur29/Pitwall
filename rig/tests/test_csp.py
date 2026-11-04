from pitwall_rig.rig import Rig


def drive(rig, clock, laps=1):
    for _ in range(60 * 60 * 4):
        clock.advance(1 / 60)
        rig.tick()
        s = rig.session
        if s and len(rig.store.valid_lap_ids(s.game, s.track_key, s.car)) >= laps and rig.track:
            return


def test_app_gets_track_drill_and_runs_the_retry(demo, clock, config, store):
    events = []
    rig = Rig(demo, store, config, emit=events.append, clock=clock)
    drive(rig, clock)
    # Track data: every corner with its reference brake point, and the speed profile.
    tr = rig.csp_track()
    assert tr["length_m"] > 0 and len(tr["ref_speed"]) == 1000
    assert all({"n", "label", "dir", "grade", "entry", "apex", "exit", "brake_p"} <= c.keys() for c in tr["corners"])

    out = rig.csp_sync({"abs": 3, "abs_modes": 12, "tc": 0, "tc_modes": 8, "bb": 0.56, "reset_allowed": True})
    assert out["track_version"] == tr["version"] and out["drill"] is None
    assert out["overlay"]["show_brake"] is True and out["overlay"]["show_from_m"] == 250
    el = rig.live()["electronics"]
    assert {k: el[k] for k in ("abs", "abs_modes", "tc", "tc_modes", "bb")} == {
        "abs": 3, "abs_modes": 12, "tc": 0, "tc_modes": 8, "bb": 0.56}
    assert el["drs_present"] is None  # not reported: the car doesn't have it

    assert rig.drill_corner(1)
    drill = rig.csp_sync({"reset_allowed": True})["drill"]
    assert drill["name"] and drill["run_up_p"] != drill["start_p"]

    # The app has saved the car at the run-up point: retry goes through the app.
    rig.csp_sync({"reset_allowed": True, "has_launch": True})
    assert rig.start_retry()
    cmds = rig.csp_sync({"reset_allowed": True, "has_launch": True})["commands"]
    assert cmds == [{"cmd": "retry", "key": drill["key"]}]
    rig.csp_sync({"reset_allowed": True, "has_launch": True, "events": [{"type": "retry", "ok": True}]})
    assert [e["state"] for e in events if e["type"] == "retry"] == ["rewinding", "ready"]
    assert rig._retry is None


def test_retry_falls_back_when_the_app_is_gone(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock)
    assert rig.drill_corner(1)
    rig.csp_sync({"reset_allowed": True, "has_launch": True})
    assert rig.start_retry() and rig._retry.get("csp")
    held = []
    rig.keys.down = lambda key: held.append(key) or True  # stand in for the Windows key sender
    clock.advance(2.5)  # the app never answers
    rig.tick()
    assert held == ["insert"] and not rig._retry.get("csp")  # Time Shift took over
    clock.advance(5)
    assert rig.live()["electronics"] is None  # app gone: back to on/off from shared memory


def test_track_change_tells_the_app_to_refetch(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock)
    v = rig.csp_sync({})["track_version"]
    rig._load_track()
    assert rig.csp_sync({})["track_version"] > v  # (the optimal run arriving can bump it again)


def test_app_installs_and_updates(tmp_path):
    from pitwall_rig.csp import APP_SOURCE, install_app

    assert (APP_SOURCE / "manifest.ini").exists() and (APP_SOURCE / "Pitwall.lua").exists()
    root = tmp_path / "assettocorsa"
    assert install_app(root) == "installed"
    dest = root / "apps" / "lua" / "Pitwall"
    assert (dest / "Pitwall.lua").read_bytes() == (APP_SOURCE / "Pitwall.lua").read_bytes()
    assert (dest / "icons" / "turn_L1.png").exists() and (dest / "fonts" / "Inter-Bold.ttf").exists()
    assert install_app(root) == "up to date"
    (dest / "Pitwall.lua").write_text("-- old version")
    assert install_app(root) == "updated"



def test_go_to_a_drill_teleports_once_then_retries_rewind(demo, clock, config, store):
    events = []
    rig = Rig(demo, store, config, emit=events.append, clock=clock)
    drive(rig, clock)
    assert rig.drill_corner(1)
    assert not rig.teleport_to_drill()  # no in-game app yet
    assert rig.live()["can_teleport"] is False
    rig.csp_sync({"reset_allowed": True})
    assert rig.live()["can_teleport"] is True

    assert rig.teleport_to_drill()
    (cmd,) = rig.csp_sync({"reset_allowed": True})["commands"]
    d = rig.track.drill.drill
    length = rig.track.model.length_m
    back_m = ((d.start_p - cmd["p"]) % 1.0) * length
    run_up_m = rig.track.lead_in_m(d, config["drills"]["lead_in_s"])
    assert cmd["cmd"] == "teleport" and cmd["key"] == rig._drill_key()
    # Parked before the Time Shift run-up, far enough back to be up to speed by the section.
    assert back_m >= run_up_m + rig.TELEPORT_EXTRA_M - 0.01
    assert back_m >= rig.track.standing_start_m(d) - 1
    rig.csp_sync({"reset_allowed": True, "events": [{"type": "teleport", "ok": True}]})
    assert [e["state"] for e in events if e["type"] == "retry"] == ["teleporting", "teleported"]

    # Retrying is the rewind as before, not another teleport.
    held = []
    rig.keys.down = lambda key: held.append(key) or True
    assert rig.start_retry()
    assert held == ["insert"] and rig.csp_sync({"reset_allowed": True})["commands"] == []
