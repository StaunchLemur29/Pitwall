import json

import pytest

from pitwall_rig.cloud import CloudError, CloudSync
from pitwall_rig.rig import Rig

from .fake_supabase import FakeSupabase


@pytest.fixture
def supa():
    s = FakeSupabase()
    yield s
    s.close()


def drive(rig, clock, laps=2):
    for _ in range(60 * 60 * 6):
        clock.advance(1 / 60)
        rig.tick()
        if len(rig.store.laps(limit=100)) >= laps + 1:
            return


def test_laps_tracks_and_profiles_reach_the_cloud(demo, clock, config, store, tmp_path, supa):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock)
    sync = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    assert sync.status()["connected"] is False
    with pytest.raises(CloudError):
        sync.connect(supa.url, "anon", "me@example.com", "wrong password")
    sync.connect(supa.url, "anon", "me@example.com", "pw")
    sent = sync.sync_once()
    local = store.laps(limit=100)
    assert sent == len(local) and store.unsynced_count() == 0
    laps = supa.rows("laps")
    assert len(laps) == len(local) and all(r["user_id"] == supa.user_id for r in laps)
    best = min((r for r in laps if r["valid"]), key=lambda r: r["lap_time_ms"])
    assert best["corners"] and best["trace"]["p"] and "T" in best["started_at"]
    assert "advice" in best["corners"][0] and "vs_s" not in best["corners"][0]  # comparisons are the hub's job
    assert best["systems"] is not None and "notes" in best["systems"]
    assert len(best["trace"]["t"]) < 40 * best["lap_time_ms"] / 1000  # reduced to ~20 Hz
    (track,) = supa.rows("tracks")
    assert track["geometry"]["corners"] and track["track_key"] == local[0]["track_key"]
    assert supa.rows("car_profiles")[0]["profile"]["drs"] is True
    # The password is never stored; the refresh token is.
    saved = json.loads((tmp_path / "cloud.json").read_text())
    assert "password" not in saved and saved["refresh_token"] and saved["email"] == "me@example.com"
    assert sync.sync_once() == 0  # nothing new


def test_offline_laps_go_up_later_and_reanalysis_re_uploads(demo, clock, config, store, tmp_path, supa):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    sync = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    sync.connect(supa.url, "anon", "me@example.com", "pw")
    supa.down = True
    drive(rig, clock)
    assert sync.sync_once() == 0 and sync.status()["state"] == "error"
    assert store.unsynced_count() > 0
    supa.down = False
    assert sync.sync_once() > 0 and store.unsynced_count() == 0
    # A lap's analysis is redone: it goes up again.
    lap_id = store.valid_lap_ids(rig.session.game, rig.session.track_key, rig.session.car, limit=1)[0]
    store.set_lap_corners(lap_id, "v-next", [{"corner": 1, "time_s": 1.0}])
    assert sync.sync_once() == 1
    row = next(r for r in supa.rows("laps") if r["local_id"] == lap_id)
    assert row["corners"][0]["corner"] == 1 and "advice" in row["corners"][0]  # the PC's full, current analysis


def test_sync_survives_a_restart_with_the_saved_token(demo, clock, config, store, tmp_path, supa):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    first = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    first.connect(supa.url, "anon", "me@example.com", "pw")
    drive(rig, clock, laps=1)
    again = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)  # Pitwall restarted
    assert again.status()["connected"] and again.status()["email"] == "me@example.com"
    assert again.sync_once() > 0  # signs in again with the stored refresh token
    again.disconnect()
    assert CloudSync(store, tmp_path).status()["connected"] is False


def test_laps_from_an_older_upload_go_up_again_once(demo, clock, config, store, tmp_path, supa):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock, laps=1)
    sync = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    sync.connect(supa.url, "anon", "me@example.com", "pw")
    sync.sync_once()
    assert store.unsynced_count() == 0
    # Pretend these went up with the first version of the sync.
    saved = json.loads((tmp_path / "cloud.json").read_text())
    saved.pop("upload_version")
    (tmp_path / "cloud.json").write_text(json.dumps(saved))
    restarted = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    assert store.unsynced_count() == len(store.laps(limit=100))  # all queued again
    assert restarted.sync_once() == len(store.laps(limit=100))
    CloudSync(store, tmp_path)  # and only once
    assert store.unsynced_count() == 0


def test_the_optimal_run_and_drill_bests_reach_the_hub_once(demo, clock, config, store, tmp_path, supa):
    """Per car + track: the optimal run (so the hub can compare with it) and your
    best drill runs, uploaded when they change, not on every sync."""
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock, laps=5)
    rig._optimal_run(rig._live_ctx(), wait=True)
    s = rig.session
    store.add_section_attempt(s.game, s.car, s.track_key, 0.1, 0.2, 9000, True)
    sync = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras,
                     combo_for=rig.cloud_combo)
    sync.connect(supa.url, "anon", "me@example.com", "pw")
    sync.sync_once()
    (row,) = supa.rows("combo_extras")
    assert row["optimal"]["lap_s"] > 0 and row["optimal"]["trace"]["speed"]
    assert row["drill_bests"] == [[0.1, 0.2, 9000]]
    # the same again: nothing new to send (the stored row isn't replaced)
    supa.tables["combo_extras"][next(iter(supa.tables["combo_extras"]))]["marker"] = 1
    sync._send_context(sync.client, store.laps(limit=10))
    (row,) = supa.rows("combo_extras")
    assert row.get("marker") == 1
