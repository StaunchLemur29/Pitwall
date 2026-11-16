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


def test_store_is_safe_from_several_threads(tmp_path):
    """The telemetry thread, the web server and the cloud sync share one store."""
    import threading

    from pitwall_rig.models import Lap
    from pitwall_rig.storage import Store

    store = Store(tmp_path / "laps.sqlite")
    errors = []
    trace = {"t": [0.0, 1.0], "p": [0.0, 0.5], "speed": [100.0, 110.0]}

    def writer():
        try:
            for i in range(200):
                lap_id = store.add_lap(Lap("ac", "car", "track", i, 90000 + i, True, False, 0.0, [], trace))
                store.set_lap_corners(lap_id, "sig", [{"corner": 1, "time_s": 1.0}])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def reader():
        try:
            for _ in range(400):
                for i in store.unsynced_lap_ids(5):
                    store.trace(i)
                    store.latest_lap_corners(i)
                store.laps(limit=20)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert store.unsynced_count() == 200


def test_a_rewound_lap_is_never_the_best(store):
    store.add_lap(make_lap(61_000, sectors=[20_000, 20_000, 21_000]))
    fast = make_lap(59_000, sectors=[19_000, 19_000, 21_000])
    fast.rewound = True
    store.add_lap(fast)
    assert store.best_lap("ac", "spa", "car_a")["lap_time_ms"] == 61_000
    assert store.best_sectors("ac", "spa", "car_a") == [20_000, 20_000, 21_000]
    assert store.combos()[0]["best_ms"] == 61_000
    assert store.combos()[0]["valid_laps"] == 2  # still counts as a lap
    assert sorted(lap["rewound"] for lap in store.laps()) == [False, True]


def test_old_databases_get_the_rewound_column(tmp_path):
    import sqlite3

    from pitwall_rig.storage import Store

    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE laps (id INTEGER PRIMARY KEY, game TEXT NOT NULL, car TEXT NOT NULL,
                  track_key TEXT NOT NULL, lap_number INTEGER NOT NULL, lap_time_ms INTEGER NOT NULL,
                  valid INTEGER NOT NULL, out_lap INTEGER NOT NULL, started_at REAL NOT NULL,
                  sector_ms TEXT NOT NULL, trace BLOB NOT NULL, synced_at REAL)""")
    db.execute("INSERT INTO laps (game, car, track_key, lap_number, lap_time_ms, valid, out_lap, started_at,"
               " sector_ms, trace) VALUES ('ac','car_a','spa',1,60000,1,0,1.0,'[]',x'')")
    db.commit()
    db.close()
    s = Store(path)
    assert s.laps()[0]["rewound"] is False
    assert s.best_lap("ac", "spa", "car_a")["lap_time_ms"] == 60_000


def test_traces_pack_small_and_round_trip_including_old_ones():
    import json
    import zlib

    from pitwall_rig.storage import pack_trace, unpack_trace

    tr = {"t": [0.0, 0.016, 0.033], "p": [0.0, 0.00001, 0.00002], "gear": [2, 2, 3], "off": [0, 4, 0]}
    back = unpack_trace(pack_trace(tr))
    assert back == {k: [float(x) for x in v] for k, v in tr.items()}
    legacy = zlib.compress(json.dumps(tr).encode())  # laps saved before the binary format
    assert unpack_trace(legacy) == tr


def test_best_sectors_go_by_the_sector_count_most_laps_have(tmp_path):
    from pitwall_rig.models import Lap
    from pitwall_rig.storage import Store

    store = Store(tmp_path / "p.sqlite")

    def add(sectors):
        store.add_lap(Lap(game="g", car="c", track_key="t", lap_number=1, lap_time_ms=sum(sectors) or 60000, valid=True,
                          out_lap=False, started_at=1.0, sector_ms=sectors, trace={"t": [0.0], "p": [0.0]}))

    add([])  # an odd lap first used to decide the count, and no sectors ever showed
    add([20000, 21000, 22000])
    add([20500, 20000, 23000])
    add([30000, 33000])
    assert store.best_sectors("g", "t", "c") == [20000, 20000, 22000]
