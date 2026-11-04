"""Writes dashboard/src/hub/__fixtures__/demo.json: demo laps as the hub sees
them (uploaded rows) next to the rig's own breakdowns of the same laps, so the
hub's TypeScript copy of the comparison logic can be checked against Python.

    cd rig && uv run python -m tests.make_hub_fixture
"""

from __future__ import annotations

import json
from pathlib import Path

from pitwall_rig.adapters.demo import DemoAdapter
from pitwall_rig.cloud import CloudSync
from pitwall_rig.config import Config
from pitwall_rig.rig import Rig
from pitwall_rig.storage import Store

from .conftest import FakeClock

OUT = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "hub" / "__fixtures__" / "demo.json"


def main() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    clock = FakeClock()
    store = Store(":memory:")
    rig = Rig(DemoAdapter(clock=clock, seed=7, start_in_pit_s=1.0), store, Config(tmp / "c.json"), clock=clock)
    while len([x for x in store.laps(limit=100) if x["valid"]]) < 6:
        clock.advance(1 / 60)
        rig.tick()
    s = rig.session
    # One of the fastest laps used a rewind: it must never be the best, on the PC or the hub.
    fastest = store.fastest_valid_lap_ids(s.game, s.track_key, s.car, limit=1)[0]
    store._db.execute("UPDATE laps SET rewound=1 WHERE id=?", (fastest,))
    rig._load_reference()
    rig._optimal_run(rig._live_ctx(), wait=True)  # settle it now, so every lap sees the same targets
    sync = CloudSync(store, tmp, geometry_for=rig.track_geometry, extras_for=rig.cloud_extras)
    sync.settings["rig_id"] = "fixture"
    rows = []
    for info in store.laps(s.game, s.track_key, s.car, limit=100):
        r = sync._lap_row(info["id"], "fixture")
        rows.append({
            "id": info["id"], "lap_number": r["lap_number"], "lap_time_ms": r["lap_time_ms"], "valid": r["valid"], "out_lap": r["out_lap"], "rewound": r["rewound"],
            "started_at": info["started_at"], "sector_ms": r["sector_ms"], "corners": r["corners"],
            "systems": r["systems"], "time_to_beat": r["time_to_beat"], "review": r["review"],
            "trace": {"t": r["trace"]["t"], "p": r["trace"]["p"]} if r["trace"] else None,
        })
    valid = [r["id"] for r in rows if r["valid"]]
    by_time = sorted(valid, key=lambda i: next(r["lap_time_ms"] for r in rows if r["id"] == i))
    cases = []
    # latest lap; the slowest valid lap against the best and the second best; the best (vs next best)
    for lap_id in [None, by_time[-1], by_time[0], by_time[len(by_time) // 2]]:
        for compare in [None, by_time[1], -1]:  # -1: the optimal run
            if compare is not None and compare == lap_id:
                continue
            rep = rig.corner_report(lap_id, compare)
            cases.append({"lap_id": lap_id, "compare_id": compare, "report": rep})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "game": s.game, "car": s.car, "track_key": s.track_key,
        "geometry": rig.track_geometry(s.game, s.car, s.track_key),
        "profile": rig.car_profile, "laps": rows, "cases": cases,
        "session_summary": rig.session_summary(s.game, s.car, s.track_key),
    }))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(rows)} laps, {len(cases)} cases)")


if __name__ == "__main__":
    main()
