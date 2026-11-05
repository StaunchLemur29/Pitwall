from pitwall_rig.models import Lap
from pitwall_rig.rig import Rig
from pitwall_rig.tracks.live import TrackState


def _trace(n=2000, lap_s=100.0, off_at=None):
    """A lap at an even pace: progress 0..1 over ``lap_s`` seconds."""
    tr = {k: [0.0] * n for k in ("x", "y", "z", "speed", "gas", "brake", "steer", "gear", "rpm", "batt", "drs", "ffb")}
    tr["t"] = [lap_s * i / (n - 1) for i in range(n)]
    tr["p"] = [i / (n - 1) for i in range(n)]
    tr["off"] = [3 if off_at and off_at[0] <= p <= off_at[1] else 0 for p in tr["p"]]
    return tr


def test_a_sections_best_counts_from_any_lap(demo, store, config, clock):
    """Your best through a section counts however the lap went: an out lap, a lap
    you crashed out of later. Not a lap with a rewind, nor a section you went off in."""
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    track = TrackState(demo.track_model(demo.session()))
    ps = next(p for p in track.model.practice if p.end > p.start)
    s = demo.session()

    def add(n, lap_s, **kw):
        trace = kw.pop("trace", None) or _trace(lap_s=lap_s)
        lap = Lap(game=s.game, car=s.car, track_key=s.track_key, lap_number=n, lap_time_ms=int(lap_s * 1000),
                  valid=kw.pop("valid", True), out_lap=kw.pop("out_lap", False), started_at=1000.0 + n, trace=trace, **kw)
        lap.id = store.add_lap(lap)
        rig._record_sections(lap, track)

    span = ps.end - ps.start
    add(1, 100.0)                                     # a normal lap
    add(2, 90.0, out_lap=True, valid=False)           # an out lap, quicker through it
    add(3, 80.0, rewound=True)                        # a rewind: never a best
    add(4, 85.0, valid=False, trace=_trace(lap_s=85.0, off_at=(ps.start, ps.end)))  # off in the section itself
    best = store.best_section_ms(s.game, s.car, s.track_key, ps.start, ps.end)
    assert best == round(90.0 * span * 1000)
    # a lap you crashed out of: unfinished, but it drove the section first
    crashed = _trace(lap_s=70.0)
    stop = next(i for i, p in enumerate(crashed["p"]) if p > ps.end + 0.01)
    for k in crashed:
        del crashed[k][stop:]
    add(5, 70.0, valid=False, out_lap=True, unfinished=True, trace=crashed)
    assert store.best_section_ms(s.game, s.car, s.track_key, ps.start, ps.end) == round(70.0 * span * 1000)
