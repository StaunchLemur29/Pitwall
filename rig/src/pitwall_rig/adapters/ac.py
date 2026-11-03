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

class PageReader(Protocol):
    def read(self, tag: str, size: int) -> bytes | None:
        """Bytes of the named page, or None if it doesn't exist (game not running)."""
        ...


class WindowsSharedMemory:
    """Opens AC's named shared memory read-only. Windows only.

    We only ever *open* existing mappings: creating them first (as
    ``mmap.mmap(tagname=...)`` would) can leave AC mapping a page smaller than
    it expects. Pages are re-opened after ``reset()`` (e.g. when AC restarts).
    """

    FILE_MAP_READ = 0x0004

    def __init__(self) -> None:
        from ctypes import wintypes

        k32 = C.WinDLL("kernel32", use_last_error=True)
        k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k32.OpenFileMappingW.restype = wintypes.HANDLE
        k32.MapViewOfFile.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, C.c_size_t,
        ]
        k32.MapViewOfFile.restype = C.c_void_p
        k32.UnmapViewOfFile.argtypes = [C.c_void_p]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32
        self._views: dict[str, tuple[int, int, int]] = {}  # tag -> (handle, view, size)

    def read(self, tag: str, size: int) -> bytes | None:
        view = self._views.get(tag)
        if view is None or view[2] < size:
            if view is not None:
                self._close(tag)
            handle = self._k32.OpenFileMappingW(self.FILE_MAP_READ, False, tag)
            if not handle:
                return None
            ptr = self._k32.MapViewOfFile(handle, self.FILE_MAP_READ, 0, 0, size)
            if not ptr:
                self._k32.CloseHandle(handle)
                return None
            view = (handle, ptr, size)
            self._views[tag] = view
        return C.string_at(view[1], size)

    def _close(self, tag: str) -> None:
        handle, ptr, _ = self._views.pop(tag)
        self._k32.UnmapViewOfFile(ptr)
        self._k32.CloseHandle(handle)

    def reset(self) -> None:
        for tag in list(self._views):
            self._close(tag)

    def close(self) -> None:
        self.reset()


def _player_name(first: str, last: str) -> str:
    # Content Manager often puts the full name in both fields.
    if not last or last in first:
        return first
    if first in last:
        return last
    return f"{first} {last}"


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
        stale_after_s: float = 3.0,
        install_dir: str = "",
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
        self._stale_after_s = stale_after_s
        from ..tracks.loader import TrackLoader

        self._tracks = TrackLoader(install_dir)
        self._last_packet = -1
        self._packet_changed_at = clock()

    # -- public -------------------------------------------------------------

    def poll(self) -> Frame | None:
        now = self._clock()
        raw_phys = self._reader.read(PHYSICS_TAG, C.sizeof(SPageFilePhysics))
        raw_gfx = self._reader.read(GRAPHICS_TAG, C.sizeof(SPageFileGraphic))
        if raw_phys is None or raw_gfx is None:
            self._static = None
            return Frame(t=now, status=GameStatus.OFF)
        phys = _parse(SPageFilePhysics, raw_phys)
        gfx = _parse(SPageFileGraphic, raw_gfx)
        status = _STATUS.get(gfx.status, GameStatus.OFF)
        self._session_type = SessionType(SESSION_TYPES.get(gfx.session, "unknown"))

        # When AC quits, our open handle keeps the last page alive, frozen on
        # "live". Treat a live page whose packet id stops moving as closed.
        if phys.packetId != self._last_packet:
            self._last_packet = int(phys.packetId)
            self._packet_changed_at = now
        elif status == GameStatus.LIVE and now - self._packet_changed_at > self._stale_after_s:
            reset = getattr(self._reader, "reset", None)
            if reset:
                reset()
            self._static = None
            return Frame(t=now, status=GameStatus.OFF)

        if status == GameStatus.OFF:
            return Frame(t=now, status=status)

        bb = float(phys.brakeBias)
        left = float(gfx.sessionTimeLeft)
        return Frame(
            t=now,
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
            velocity=(float(phys.velocity[0]), float(phys.velocity[1]), float(phys.velocity[2])),
            yaw=float(phys.heading),
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
            raw = self._reader.read(STATIC_TAG, C.sizeof(SPageFileStatic))
            if raw is None:
                self._static = None
                return None
            st = _parse(SPageFileStatic, raw)
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
                    player_name=_player_name(decode_wstr(st.playerName), decode_wstr(st.playerSurname)),
                )
        if self._static is not None:
            self._static.session_type = self._session_type
        return self._static

    def track_model(self, session: SessionInfo):
        return self._tracks.load(session)

    def close(self) -> None:
        close = getattr(self._reader, "close", None)
        if close:
            close()
