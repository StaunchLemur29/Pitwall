"""Assetto Corsa (original) adapter, via the ``acpmf_*`` shared memory pages."""

from __future__ import annotations

import ctypes as C
import sys
import time
from collections.abc import Callable
from typing import Protocol

from ..models import Capabilities, Frame, GameStatus, SessionInfo, SessionType
from .base import GameAdapter
from .ac_structs import (
    AC_LIVE,
    AC_PAUSE,
    AC_REPLAY,
    GRAPHICS_TAG,
    PHYSICS_TAG,
    SESSION_TYPES,
    STATIC_TAG,
    SPageFileGraphic,
    SPageFilePhysics,
    SPageFileStatic,
    decode_wstr,
)

_STATUS = {AC_REPLAY: GameStatus.REPLAY, AC_LIVE: GameStatus.LIVE, AC_PAUSE: GameStatus.PAUSED}

# Reserve more than we declare: real pages are larger and grow with AC/CSP versions.
_MAP_SIZE = {PHYSICS_TAG: 2048, GRAPHICS_TAG: 2048, STATIC_TAG: 2048}


class PageReader(Protocol):
    def read(self, tag: str, size: int) -> bytes: ...


class WindowsSharedMemory:
    """Reads named shared memory. Windows only."""

    def __init__(self) -> None:
        import mmap

        self._maps = {tag: mmap.mmap(-1, size, tagname=tag) for tag, size in _MAP_SIZE.items()}

    def read(self, tag: str, size: int) -> bytes:
        m = self._maps[tag]
        m.seek(0)
        return m.read(size)

    def close(self) -> None:
        for m in self._maps.values():
            m.close()


def _parse(struct: type[C.Structure], data: bytes) -> C.Structure:
    need = C.sizeof(struct)
    if len(data) < need:
        data = data + bytes(need - len(data))
    return struct.from_buffer_copy(data[:need])


class AssettoCorsaAdapter(GameAdapter):
    game_id = "ac"
    capabilities = Capabilities(
        reports_brake_bias=True,
        reports_abs_level=True,
        reports_tc_level=True,
        reports_tyre_pressure=True,
        reports_world_position=True,
        can_retry_section=False,  # comes with the CSP companion app (phase 1)
    )

    def __init__(
        self,
        reader: PageReader | None = None,
        clock: Callable[[], float] = time.monotonic,
        static_refresh_s: float = 2.0,
    ) -> None:
        if reader is None:
            if sys.platform != "win32":
                raise RuntimeError("The Assetto Corsa adapter needs Windows (shared memory).")
            reader = WindowsSharedMemory()
        self._reader = reader
        self._clock = clock
        self._static_refresh_s = static_refresh_s
        self._static: SessionInfo | None = None
        self._static_read_at = -1e9
        self._session_type = SessionType.UNKNOWN

    # -- public -------------------------------------------------------------

    def poll(self) -> Frame | None:
        phys = _parse(SPageFilePhysics, self._reader.read(PHYSICS_TAG, C.sizeof(SPageFilePhysics)))
        gfx = _parse(SPageFileGraphic, self._reader.read(GRAPHICS_TAG, C.sizeof(SPageFileGraphic)))
        status = _STATUS.get(gfx.status, GameStatus.OFF)
        self._session_type = SessionType(SESSION_TYPES.get(gfx.session, "unknown"))
        if status == GameStatus.OFF:
            return Frame(t=self._clock(), status=status)

        bb = float(phys.brakeBias)
        left = float(gfx.sessionTimeLeft)
        return Frame(
            t=self._clock(),
            status=status,
            packet_id=int(phys.packetId),
            gas=float(phys.gas),
            brake=float(phys.brake),
            clutch=float(phys.clutch),
            steer=float(phys.steerAngle),
            speed_kmh=float(phys.speedKmh),
            gear=int(phys.gear) - 1,
            rpm=int(phys.rpms),
            fuel_l=float(phys.fuel),
            brake_bias=bb if bb > 0 else None,
            abs=float(phys.abs),
            tc=float(phys.tc),
            tyre_pressure_psi=[float(v) for v in phys.wheelsPressure],
            tyre_core_temp_c=[float(v) for v in phys.tyreCoreTemperature],
            tyres_out=int(phys.numberOfTyresOut),
            lap=int(gfx.completedLaps),
            lap_time_ms=int(gfx.iCurrentTime),
            last_lap_ms=int(gfx.iLastTime),
            best_lap_ms=int(gfx.iBestTime),
            lap_progress=float(gfx.normalizedCarPosition),
            sector=int(gfx.currentSectorIndex),
            in_pit_box=bool(gfx.isInPit),
            in_pit_lane=bool(gfx.isInPitLane),
            world=(
                float(gfx.carCoordinates[0]),
                float(gfx.carCoordinates[1]),
                float(gfx.carCoordinates[2]),
            ),
            session_time_left_s=left / 1000.0 if left > 0 else None,
            position=int(gfx.position),
        )

    def session(self) -> SessionInfo | None:
        now = self._clock()
        if now - self._static_read_at >= self._static_refresh_s:
            self._static_read_at = now
            st = _parse(SPageFileStatic, self._reader.read(STATIC_TAG, C.sizeof(SPageFileStatic)))
            car = decode_wstr(st.carModel)
            track = decode_wstr(st.track)
            if not car or not track:
                self._static = None
            else:
                self._static = SessionInfo(
                    game=self.game_id,
                    car=car,
                    track=track,
                    track_config=decode_wstr(st.trackConfiguration),
                    track_length_m=float(st.trackSPlineLength),
                    max_rpm=int(st.maxRpm),
                    max_fuel_l=float(st.maxFuel),
                    sector_count=int(st.sectorCount),
                    player_name=" ".join(
                        p for p in (decode_wstr(st.playerName), decode_wstr(st.playerSurname)) if p
                    ),
                )
        if self._static is not None:
            self._static.session_type = self._session_type
        return self._static

    def close(self) -> None:
        close = getattr(self._reader, "close", None)
        if close:
            close()
