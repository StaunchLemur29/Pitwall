"""End to end: a real Assetto Corsa recording (one lap of Spa) played through
the whole rig service, as `pitwall-rig run --replay` does: the live loop, the
post-lap worker, the store, a drill run during the lap, the analysis with its
lap review, the cloud upload row and the SF1000 sender.

The recording has one full lap, so there's no history for a time to beat:
that part is checked on the demo car (test_time_to_beat)."""

import time
from pathlib import Path

from pitwall_rig.adapters.replay import ReplayAdapter
from pitwall_rig.cloud import CloudSync
from pitwall_rig.config import Config
from pitwall_rig.rig import Rig
from pitwall_rig.storage import Store

SPA = Path(__file__).parent / "fixtures" / "ac_spa_one_lap.pwrec"


class FakeSocket:
    def __init__(self):
        self.sent: list[tuple[bytes, tuple]] = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


def test_spa_recording_through_the_whole_service(tmp_path):
    t = [0.0]
    clock = lambda: t[0]
    store = Store(tmp_path / "p.sqlite")
    config = Config(tmp_path / "c.json")
    config.update({"sf1000": {"enabled": True, "ip": "10.0.0.9"}})
    rig = Rig(ReplayAdapter(SPA, clock=clock, loop=False), store, config, emit=lambda e: None, clock=clock)
    rig.start_post_lap_worker()  # as the real service runs: lap work off the live thread
    sock = FakeSocket()
    duration = rig.adapter._duration
    drill_set = False
    while t[0] < duration + 2:
        t[0] += 1 / 60
        if rig.sf1000 is not None and rig.sf1000.sock is not sock:
            rig.sf1000.sock = sock
        rig.tick()
        f = rig.frame
        if not drill_set and f is not None and 0.02 < f.lap_progress < 0.25:
            # Early in the full lap (the clip starts just before the line): once the
            # post-lap worker has learnt the track, set a drill on a stretch ahead.
            deadline = time.monotonic() + 10
            while rig.track is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert rig.start_drill(0.30, 0.40, "Test stretch")
            drill_set = True
    assert drill_set
    drill = rig.track.drill.to_wire()
    assert drill["attempts"] == 1 and 5_000 < drill["last"]["time_ms"] < 60_000

    deadline = time.monotonic() + 30
    while len(store.laps(limit=10)) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    laps = sorted(store.laps(limit=10), key=lambda x: x["started_at"])
    assert [x["lap_time_ms"] for x in laps] == [149045, 148252]
    assert not laps[0]["valid"] and laps[1]["valid"]

    best = store.best_lap("ac", "spa@2022", laps[1]["car"])
    assert best and best["id"] == laps[1]["id"]
    trace = store.trace(best["id"])
    assert trace and len(trace["t"]) > 1000

    rep = rig.corner_report(best["id"], None)
    assert rep.get("review") is not None, "the lap review (good and bad) is there"
    assert rep is not None and rep.get("lap"), "the corner report has corners"
    assert all(c["time_s"] > 0 for c in rep["lap"])

    # What the hub gets for this lap (built locally; nothing is sent).
    sync = CloudSync(store, tmp_path, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    row = sync._lap_row(best["id"], "test")
    assert row["valid"] and row["lap_time_ms"] == 148252
    assert row["corners"] and row["review"] is not None
    assert row["trace"] and 0 < len(row["trace"]["t"]) < len(trace["t"])  # downsampled

    # The wheel screen got the F1 23 packets, each the size the wheel expects.
    sizes = {len(d) for d, _ in sock.sent}
    assert {1352, 1239, 1131}.issubset(sizes)
    assert all(addr == ("10.0.0.9", 20777) for _, addr in sock.sent)
