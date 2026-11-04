"""Local SQLite store for laps and markers. Full-resolution traces live here."""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
import time
import zlib
from array import array
from pathlib import Path
from typing import Any, Self

from .models import Lap

SCHEMA = """
CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL,
    car TEXT NOT NULL,
    track_key TEXT NOT NULL,
    lap_number INTEGER NOT NULL,
    lap_time_ms INTEGER NOT NULL,
    valid INTEGER NOT NULL,
    out_lap INTEGER NOT NULL,
    rewound INTEGER NOT NULL DEFAULT 0,  -- used a rewind after a mistake: never a best lap
    unfinished INTEGER NOT NULL DEFAULT 0,  -- didn't get to the line: only some corners driven
    started_at REAL NOT NULL,
    sector_ms TEXT NOT NULL,
    trace BLOB NOT NULL,
    synced_at REAL
);
CREATE INDEX IF NOT EXISTS laps_combo ON laps (game, track_key, car, lap_time_ms);
CREATE INDEX IF NOT EXISTS laps_recent ON laps (game, track_key, car, valid, started_at);

CREATE TABLE IF NOT EXISTS markers (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL,
    car TEXT NOT NULL,
    track_key TEXT NOT NULL,
    progress REAL NOT NULL,
    x REAL, z REAL,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lap_corners (
    lap_id INTEGER PRIMARY KEY REFERENCES laps(id) ON DELETE CASCADE,
    model_sig TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS section_attempts (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL,
    car TEXT NOT NULL,
    track_key TEXT NOT NULL,
    start_p REAL NOT NULL,
    end_p REAL NOT NULL,
    time_ms INTEGER NOT NULL,
    clean INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS debriefs (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL,
    car TEXT NOT NULL,
    track_key TEXT NOT NULL,
    session_start REAL NOT NULL,
    created_at REAL NOT NULL,
    model TEXT NOT NULL,
    body TEXT NOT NULL,
    synced_at REAL,
    UNIQUE (game, car, track_key, session_start)
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

SCHEMA_VERSION = "1"


_TRACE_V2 = b"PWT2"  # binary traces: channel names, then each channel as float64s


def pack_trace(trace: dict[str, list[float]]) -> bytes:
    """A lap's telemetry for the database. Binary (not JSON): a Nordschleife lap
    is ~30,000 samples, and this happens as you cross the line."""
    names = list(trace)
    n = len(trace[names[0]]) if names else 0
    head = json.dumps({"n": n, "ch": names}).encode()
    body = b"".join(array("d", trace[k]).tobytes() for k in names)
    return _TRACE_V2 + zlib.compress(struct.pack("<I", len(head)) + head + body, level=1)


def unpack_trace(blob: bytes) -> dict[str, list[float]]:
    if not blob.startswith(_TRACE_V2):
        return json.loads(zlib.decompress(blob))  # laps saved before the binary format
    raw = zlib.decompress(blob[len(_TRACE_V2):])
    (hl,) = struct.unpack_from("<I", raw)
    head = json.loads(raw[4 : 4 + hl])
    n, out, at = head["n"], {}, 4 + hl
    for k in head["ch"]:
        a = array("d")
        a.frombytes(raw[at : at + n * 8])
        out[k] = a.tolist()
        at += n * 8
    return out


class _Result:
    """A query's rows, already fetched (so the connection is free again)."""

    def __init__(self, rows: list[sqlite3.Row], lastrowid: int | None) -> None:
        self._rows = rows
        self.lastrowid = lastrowid

    def fetchone(self) -> sqlite3.Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[sqlite3.Row]:
        return self._rows


class _LockedConnection:
    """One SQLite connection shared by the telemetry thread, the web server and
    the cloud sync: every statement takes the lock, reads included."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, sql: str, args: Any = ()) -> _Result:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return _Result(cur.fetchall(), cur.lastrowid)

    def executemany(self, sql: str, rows: Any) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:  # a transaction (the caller holds the lock)
        self._conn.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self._conn.__exit__(*exc)


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db = _LockedConnection(conn, self._lock)
        self._traces: dict[int, dict[str, list[float]]] = {}  # lap id -> trace, oldest first
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
            cols = {r["name"] for r in self._db.execute("PRAGMA table_info(laps)").fetchall()}
            if "rewound" not in cols:  # databases from before rewinds were tracked
                self._db.execute("ALTER TABLE laps ADD COLUMN rewound INTEGER NOT NULL DEFAULT 0")
            if "unfinished" not in cols:  # ...and before unfinished laps were kept
                self._db.execute("ALTER TABLE laps ADD COLUMN unfinished INTEGER NOT NULL DEFAULT 0")
            self._db.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    # -- laps ---------------------------------------------------------------

    def add_lap(self, lap: Lap) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                """INSERT INTO laps (game, car, track_key, lap_number, lap_time_ms, valid,
                   out_lap, rewound, unfinished, started_at, sector_ms, trace) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lap.game,
                    lap.car,
                    lap.track_key,
                    lap.lap_number,
                    lap.lap_time_ms,
                    int(lap.valid),
                    int(lap.out_lap),
                    int(lap.rewound),
                    int(lap.unfinished),
                    lap.started_at,
                    json.dumps(lap.sector_ms),
                    pack_trace(lap.trace),
                ),
            )
            lap.id = int(cur.lastrowid)
            self._traces[lap.id] = lap.trace  # about to be looked at: no need to unpack it again
            while len(self._traces) > self.TRACE_CACHE:
                self._traces.pop(next(iter(self._traces)))
            return lap.id

    def laps(
        self,
        game: str | None = None,
        track_key: str | None = None,
        car: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where, args = self._filter(game, track_key, car)
        rows = self._db.execute(
            f"""SELECT id, game, car, track_key, lap_number, lap_time_ms, valid, out_lap, rewound, unfinished,
                started_at, sector_ms FROM laps {where} ORDER BY started_at DESC LIMIT ?""",
            (*args, limit),
        ).fetchall()
        return [self._summary(r) for r in rows]

    def combos(self) -> list[dict[str, Any]]:
        """Every game + car + track with laps, most recently driven first."""
        rows = self._db.execute(
            """SELECT game, car, track_key, COUNT(*) AS laps, SUM(valid) AS valid_laps,
                      MAX(started_at) AS last_driven,
                      MIN(CASE WHEN valid=1 AND rewound=0 THEN lap_time_ms END) AS best_ms
               FROM laps GROUP BY game, car, track_key ORDER BY last_driven DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    # -- AI debriefs --------------------------------------------------------------

    def add_debrief(self, game: str, car: str, track_key: str, session_start: float, model: str, body: str,
                    created_at: float) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                """INSERT OR REPLACE INTO debriefs (game, car, track_key, session_start, created_at, model, body)
                   VALUES (?,?,?,?,?,?,?)""",
                (game, car, track_key, session_start, created_at, model, body),
            )
            return int(cur.lastrowid or 0)

    def debriefs(self, game: str, car: str, track_key: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """SELECT id, game, car, track_key, session_start, created_at, model, body FROM debriefs
               WHERE game=? AND car=? AND track_key=? ORDER BY session_start DESC LIMIT ?""",
            (game, car, track_key, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def has_debrief(self, game: str, car: str, track_key: str, session_start: float) -> bool:
        return self._db.execute(
            "SELECT 1 FROM debriefs WHERE game=? AND car=? AND track_key=? AND session_start=?",
            (game, car, track_key, session_start),
        ).fetchone() is not None

    def unsynced_debriefs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """SELECT id, game, car, track_key, session_start, created_at, model, body FROM debriefs
               WHERE synced_at IS NULL ORDER BY created_at LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_debriefs_synced(self, ids: list[int], when: float) -> None:
        with self._lock, self._db:
            self._db.executemany("UPDATE debriefs SET synced_at=? WHERE id=?", [(when, i) for i in ids])

    # -- cloud sync -------------------------------------------------------------

    def unsynced_lap_ids(self, limit: int = 10) -> list[int]:
        rows = self._db.execute(
            "SELECT id FROM laps WHERE synced_at IS NULL ORDER BY started_at LIMIT ?", (limit,)
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def mark_all_unsynced(self) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE laps SET synced_at=NULL")

    def unsynced_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM laps WHERE synced_at IS NULL").fetchone()[0])

    def mark_synced(self, lap_ids: list[int], when: float) -> None:
        with self._lock, self._db:
            self._db.executemany("UPDATE laps SET synced_at=? WHERE id=?", [(when, i) for i in lap_ids])

    def latest_lap_corners(self, lap_id: int) -> list[dict[str, Any]] | None:
        """The lap's corner analysis, whichever track-model version made it."""
        row = self._db.execute("SELECT data FROM lap_corners WHERE lap_id=?", (lap_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    # -- car profiles (which systems each car has), kept in the meta table --

    def car_profile(self, game: str, car: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (f"car_profile:{game}:{car}",)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_car_profile(self, game: str, car: str, profile: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (f"car_profile:{game}:{car}", json.dumps(profile)),
            )

    def lap(self, lap_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            """SELECT id, game, car, track_key, lap_number, lap_time_ms, valid, out_lap, rewound, unfinished,
               started_at, sector_ms FROM laps WHERE id=?""",
            (lap_id,),
        ).fetchone()
        return self._summary(row) if row else None

    def best_lap(self, game: str, track_key: str, car: str) -> dict[str, Any] | None:
        row = self._db.execute(
            """SELECT id, game, car, track_key, lap_number, lap_time_ms, valid, out_lap, rewound, unfinished,
               started_at, sector_ms FROM laps
               WHERE game=? AND track_key=? AND car=? AND valid=1 AND rewound=0
               ORDER BY lap_time_ms ASC LIMIT 1""",
            (game, track_key, car),
        ).fetchone()
        return self._summary(row) if row else None

    def best_sectors(self, game: str, track_key: str, car: str) -> list[int]:
        """Best time for each sector over valid laps (for the theoretical best)."""
        rows = self._db.execute(
            "SELECT sector_ms FROM laps WHERE game=? AND track_key=? AND car=? AND valid=1 AND rewound=0",
            (game, track_key, car),
        ).fetchall()
        best: list[int] = []
        for r in rows:
            secs = json.loads(r["sector_ms"])
            if not best:
                best = list(secs)
            elif len(secs) == len(best):
                best = [min(a, b) for a, b in zip(best, secs, strict=True)]
        return best

    TRACE_CACHE = 4  # recently read laps kept unpacked (a long lap takes a while to unpack)

    def trace(self, lap_id: int) -> dict[str, list[float]] | None:
        """A lap's telemetry. Don't change what you get: it's shared (laps never change once saved)."""
        with self._lock:
            hit = self._traces.pop(lap_id, None)
            if hit is not None:
                self._traces[lap_id] = hit  # most recent last
                return hit
        row = self._db.execute("SELECT trace FROM laps WHERE id=?", (lap_id,)).fetchone()
        if not row:
            return None
        tr = unpack_trace(row["trace"])
        with self._lock:
            self._traces[lap_id] = tr
            while len(self._traces) > self.TRACE_CACHE:
                self._traces.pop(next(iter(self._traces)))
        return tr

    def outline_lap_id(self, game: str, track_key: str) -> int | None:
        """A lap to draw the track map from: the best valid lap in any car,
        falling back to any complete lap."""
        row = self._db.execute(
            """SELECT id FROM laps WHERE game=? AND track_key=?
               ORDER BY valid DESC, out_lap ASC, rewound ASC, lap_time_ms ASC LIMIT 1""",
            (game, track_key),
        ).fetchone()
        return int(row["id"]) if row else None

    # -- per-corner analysis ---------------------------------------------------

    def set_lap_corners(self, lap_id: int, model_sig: str, data: list[dict[str, Any]]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO lap_corners (lap_id, model_sig, data) VALUES (?,?,?)",
                (lap_id, model_sig, json.dumps(data, separators=(",", ":"))),
            )
            # The hub should get the new analysis: upload the lap again.
            self._db.execute("UPDATE laps SET synced_at=NULL WHERE id=?", (lap_id,))

    def lap_corners(self, lap_id: int, model_sig: str) -> list[dict[str, Any]] | None:
        row = self._db.execute(
            "SELECT data FROM lap_corners WHERE lap_id=? AND model_sig=?", (lap_id, model_sig)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def fastest_valid_lap_ids(self, game: str, track_key: str, car: str, limit: int = 8) -> list[int]:
        rows = self._db.execute(
            """SELECT id FROM laps WHERE game=? AND track_key=? AND car=? AND valid=1 AND rewound=0
               ORDER BY lap_time_ms ASC, id ASC LIMIT ?""",
            (game, track_key, car, limit),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def valid_lap_ids(self, game: str, track_key: str, car: str, limit: int = 50) -> list[int]:
        rows = self._db.execute(
            """SELECT id FROM laps WHERE game=? AND track_key=? AND car=? AND valid=1
               ORDER BY started_at DESC LIMIT ?""",
            (game, track_key, car, limit),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    # -- section attempts ------------------------------------------------------

    def add_section_attempt(
        self, game: str, car: str, track_key: str, start_p: float, end_p: float, time_ms: int, clean: bool
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO section_attempts (game, car, track_key, start_p, end_p, time_ms, clean,
                   created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (game, car, track_key, start_p, end_p, time_ms, int(clean), time.time()),
            )

    def best_sections(self, game: str, car: str, track_key: str) -> list[tuple[float, float, int]]:
        """(start_p, end_p, best clean time) of every section you've drilled on this car + track."""
        rows = self._db.execute(
            """SELECT start_p, end_p, MIN(time_ms) AS best FROM section_attempts
               WHERE game=? AND car=? AND track_key=? AND clean=1
               GROUP BY round(start_p, 4), round(end_p, 4)""",
            (game, car, track_key),
        ).fetchall()
        return [(float(r["start_p"]), float(r["end_p"]), int(r["best"])) for r in rows]

    def best_section_ms(self, game: str, car: str, track_key: str, start_p: float, end_p: float) -> int | None:
        row = self._db.execute(
            """SELECT MIN(time_ms) AS best FROM section_attempts WHERE game=? AND car=? AND track_key=?
               AND abs(start_p-?)<1e-4 AND abs(end_p-?)<1e-4 AND clean=1""",
            (game, car, track_key, start_p, end_p),
        ).fetchone()
        return int(row["best"]) if row and row["best"] is not None else None

    # -- markers ------------------------------------------------------------

    def add_marker(
        self, game: str, car: str, track_key: str, progress: float, x: float | None, z: float | None
    ) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                """INSERT INTO markers (game, car, track_key, progress, x, z, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (game, car, track_key, progress, x, z, time.time()),
            )
            return int(cur.lastrowid)

    def markers(self, game: str, track_key: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM markers WHERE game=? AND track_key=? ORDER BY progress",
            (game, track_key),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _filter(game: str | None, track_key: str | None, car: str | None) -> tuple[str, list[str]]:
        clauses, args = [], []
        for col, val in (("game", game), ("track_key", track_key), ("car", car)):
            if val is not None:
                clauses.append(f"{col}=?")
                args.append(val)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", args

    @staticmethod
    def _summary(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["valid"] = bool(d["valid"])
        d["out_lap"] = bool(d["out_lap"])
        d["rewound"] = bool(d.get("rewound", 0))
        d["unfinished"] = bool(d.get("unfinished", 0))
        d["sector_ms"] = json.loads(d["sector_ms"])
        return d

    def close(self) -> None:
        self._db.close()
