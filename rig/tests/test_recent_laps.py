from pitwall_rig.models import Lap, SessionInfo
from pitwall_rig.rig import Rig


def test_your_best_lap_is_listed_however_old(demo, store, config, clock):
    """The analysis compares with faster laps: the page's lap list must hold your
    fastest laps even after many newer ones (it only gets the latest 30)."""
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    rig.session = SessionInfo(game="demo", car="c", track="t")
    s = rig.session

    def add(n, ms, valid=True, rewound=False):
        return store.add_lap(Lap(game=s.game, car=s.car, track_key=s.track_key, lap_number=n, lap_time_ms=ms,
                                 valid=valid, out_lap=False, started_at=1000.0 + n, rewound=rewound))

    best = add(1, 60_000)
    rewound = add(2, 59_000, rewound=True)  # never a best
    for n in range(3, 60):
        add(n, 70_000 + n)
    ids = [x["id"] for x in rig.recent_laps()]
    assert best in ids and rewound not in ids
    assert len(ids) == 30 + Rig.FASTEST_IN_LIST  # the latest 30 + the 10 fastest clean laps
    assert ids[-1] == best  # newest first, as before
