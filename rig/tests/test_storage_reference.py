from pitwall_rig.models import Lap
from pitwall_rig.reference import ReferenceLap, downsample


def make_lap(ms, valid=True, car="car_a", sectors=None, n=600):
    lap_s = ms / 1000
    trace = {
        "t": [lap_s * i / n for i in range(n)],
        "p": [i / n for i in range(n)],
        "x": [float(i) for i in range(n)],
        "z": [0.0] * n,
    }
    return Lap(game="ac", car=car, track_key="spa", lap_number=1, lap_time_ms=ms, valid=valid,
               out_lap=False, started_at=0, sector_ms=sectors or [], trace=trace)


def test_store_roundtrip_and_best(store):
    a = store.add_lap(make_lap(140_000, sectors=[50_000, 45_000, 45_000]))
    store.add_lap(make_lap(138_500, sectors=[49_000, 46_000, 43_500]))
    store.add_lap(make_lap(120_000, valid=False, sectors=[40_000, 40_000, 40_000]))
    store.add_lap(make_lap(130_000, car="car_b"))
    best = store.best_lap("ac", "spa", "car_a")
    assert best["lap_time_ms"] == 138_500
    assert store.best_sectors("ac", "spa", "car_a") == [49_000, 45_000, 43_500]
    assert len(store.laps("ac", "spa", "car_a")) == 3
    assert store.trace(a)["x"][10] == 10.0


def test_markers(store):
    store.add_marker("ac", "car_a", "spa", 0.42, 10.0, 20.0)
    store.add_marker("ac", "car_a", "spa", 0.12, None, None)
    assert [m["progress"] for m in store.markers("ac", "spa")] == [0.12, 0.42]


def test_reference_delta():
    ref = ReferenceLap(make_lap(100_000).trace, 100_000)
    assert ref.time_at(0.5) == 50.0
    assert ref.delta(0.5, 51_000) == 1.0   # 1 s slower
    assert ref.delta(0.5, 49_500) == -0.5  # half a second up
    assert ref.delta(0.99, 1_000) is None  # just after the line


def test_reference_ignores_wrapped_start_samples():
    tr = {"t": [0.0, 0.02, 0.5, 1.0, *[1 + i for i in range(1, 20)]],
          "p": [0.995, 0.999, 0.001, 0.01, *[0.01 + i * 0.05 for i in range(1, 20)]]}
    ref = ReferenceLap(tr, 20_000)
    assert ref.time_at(0.005) is not None and ref.time_at(0.005) < 1.0


def test_downsample():
    tr = {"t": [i / 60 for i in range(600)], "v": list(range(600))}
    ds = downsample(tr, 10)
    assert 99 <= len(ds["t"]) <= 102
    assert ds["v"][-1] == 599
