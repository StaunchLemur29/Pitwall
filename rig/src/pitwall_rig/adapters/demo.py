"""A fake car on a fake circuit, for development and demo mode.

Generates plausible telemetry without any game running: a closed circuit built
from control points, a grip-limited speed profile, and a driver with some
lap-to-lap variation (and the occasional track-limits cut).
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

from ..models import Capabilities, Frame, GameStatus, SessionInfo, SessionType
from .base import GameAdapter

# A made-up ~3.6 km circuit (metres). Clockwise-ish, with a hairpin, a fast
# sweeper, a chicane and a long straight.
CONTROL_POINTS: list[tuple[float, float]] = [
    (0, 0), (420, 0), (620, 10), (700, 80), (690, 180), (600, 230), (520, 260),
    (500, 330), (560, 400), (700, 430), (820, 500), (840, 620), (760, 700),
    (620, 690), (540, 640), (420, 640), (300, 700), (180, 690), (90, 610),
    (40, 520), (60, 430), (20, 330), (-80, 280), (-150, 190), (-130, 80), (-70, 20),
]

A_LAT = 14.0  # m/s² cornering grip (~1.4 g)
A_BRAKE = 15.0
A_ACCEL = 6.5
V_TOP = 78.0  # m/s (~280 km/h)
GEAR_TOP_SPEEDS = [0, 22, 34, 45, 56, 67, 79]  # m/s at redline per gear
REDLINE = 8000
IDLE_RPM = 1500


def _catmull_rom(points: list[tuple[float, float]], per_segment: int) -> list[tuple[float, float]]:
    n = len(points)
    out: list[tuple[float, float]] = []
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        for s in range(per_segment):
            t = s / per_segment
            t2, t3 = t * t, t * t * t
            out.append(
                tuple(
                    0.5
                    * (
                        2 * p1[k]
                        + (-p0[k] + p2[k]) * t
                        + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                        + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3
                    )
                    for k in range(2)
                )  # type: ignore[misc]
            )
    return out


class DemoTrack:
    def __init__(self, points: list[tuple[float, float]] = CONTROL_POINTS, step_m: float = 2.0):
        dense = _catmull_rom(points, 60)
        # resample at a uniform step
        pts = [dense[0]]
        acc = 0.0
        for a, b in zip(dense, dense[1:] + dense[:1], strict=True):
            seg = math.dist(a, b)
            acc += seg
            if acc >= step_m:
                pts.append(b)
                acc = 0.0
        self.points = pts
        self.n = len(pts)
        self.step = step_m
        self.length = self.n * step_m
        self.curvature = [self._curvature(i) for i in range(self.n)]
        self.v_limit = self._speed_profile()

    def _curvature(self, i: int, span: int = 6) -> float:
        a, b, c = self.points[i - span], self.points[i], self.points[(i + span) % self.n]
        ab, bc, ca = math.dist(a, b), math.dist(b, c), math.dist(c, a)
        area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        if ab * bc * ca == 0:
            return 0.0
        return 2 * area2 / (ab * bc * ca)

    def _speed_profile(self) -> list[float]:
        v = [min(V_TOP, math.sqrt(A_LAT / k)) if k > 1e-6 else V_TOP for k in self.curvature]
        # two passes around the loop so the wrap-around settles
        for _ in range(2):
            for i in range(1, self.n * 2):  # accel limit forwards
                j, p = i % self.n, (i - 1) % self.n
                v[j] = min(v[j], math.sqrt(v[p] ** 2 + 2 * A_ACCEL * self.step))
            for i in range(self.n * 2, 0, -1):  # brake limit backwards
                j, nx = i % self.n, (i + 1) % self.n
                v[j] = min(v[j], math.sqrt(v[nx] ** 2 + 2 * A_BRAKE * self.step))
        return v

    def at(self, dist_m: float) -> tuple[tuple[float, float], int]:
        i = int(dist_m / self.step) % self.n
        return self.points[i], i


class DemoAdapter(GameAdapter):
    game_id = "demo"
    capabilities = Capabilities(
        reports_brake_bias=True,
        reports_abs_level=True,
        reports_tc_level=True,
        reports_tyre_pressure=True,
        reports_world_position=True,
    )

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        time_scale: float = 1.0,
        seed: int | None = None,
        pit_every_laps: int = 5,
        pit_stop_s: float = 8.0,
        start_in_pit_s: float = 3.0,
    ) -> None:
        self._clock = clock
        self._scale = time_scale
        self._rng = random.Random(seed)
        self.track = DemoTrack()
        self._pit_every = pit_every_laps
        self._pit_stop_s = pit_stop_s
        self._t_prev: float | None = None
        self._sim_t = 0.0
        self._dist = 0.0
        self._v = 0.0
        self._lap = 0
        self._lap_t = 0.0
        self._last_ms = 0
        self._best_ms = 0
        self._pit_left = start_in_pit_s
        self._packet = 0
        self._fuel = 60.0
        self._bb = 0.58
        self._new_lap_variation()

    # -- simulation ---------------------------------------------------------

    def _new_lap_variation(self) -> None:
        # Driver pace for this lap (0.97..1.0 of the limit), plus a few "mistakes".
        self._pace = self._rng.uniform(0.95, 0.995)
        self._cut_at = self._rng.uniform(0.2, 0.9) if self._rng.random() < 0.15 else None

    def _step(self, dt: float) -> None:
        if self._pit_left > 0:
            self._pit_left -= dt
            self._v = 0.0
            return
        target = self.track.v_limit[self.track.at(self._dist)[1]] * self._pace
        ahead = self.track.v_limit[self.track.at(self._dist + max(self._v, 10) * 0.5)[1]] * self._pace
        target = min(target, ahead + 3)
        if self._v < target:
            self._v = min(target, self._v + A_ACCEL * dt)
        else:
            self._v = max(target, self._v - A_BRAKE * dt)
        self._dist += self._v * dt
        self._lap_t += dt
        self._fuel = max(0.0, self._fuel - self._v * dt * 0.0003)
        if self._dist >= self.track.length:
            self._dist -= self.track.length
            self._lap += 1
            self._last_ms = int(self._lap_t * 1000)
            if self._best_ms == 0 or self._last_ms < self._best_ms:
                self._best_ms = self._last_ms
            self._lap_t = 0.0
            self._new_lap_variation()
            if self._pit_every and self._lap % self._pit_every == 0:
                self._pit_left = self._pit_stop_s

    def poll(self) -> Frame:
        now = self._clock()
        dt_real = 0.0 if self._t_prev is None else now - self._t_prev
        self._t_prev = now
        dt_sim = dt_real * self._scale
        # integrate in small steps so high time scales stay stable
        while dt_sim > 0:
            h = min(dt_sim, 1 / 120)
            self._step(h)
            dt_sim -= h
        self._packet += 1

        (x, z), idx = self.track.at(self._dist)
        target = self.track.v_limit[idx] * self._pace
        braking = self._v > target + 0.5 or (
            self._pit_left <= 0
            and self.track.v_limit[self.track.at(self._dist + max(self._v, 10) * 0.5)[1]] * self._pace
            < self._v - 1
        )
        gas = 0.0 if braking else (1.0 if self._v < target - 0.5 else 0.6)
        brake = min(1.0, 0.4 + (self._v - target) / 15) if braking else 0.0
        if self._pit_left > 0:
            gas = brake = 0.0
        gear = next((g for g, top in enumerate(GEAR_TOP_SPEEDS) if g and self._v <= top), 6)
        gear = 0 if self._pit_left > 0 else gear
        rpm = (
            IDLE_RPM
            if gear == 0
            else int(IDLE_RPM + (REDLINE - IDLE_RPM) * min(1.0, self._v / GEAR_TOP_SPEEDS[gear]))
        )
        k = self.track.curvature[idx]
        progress = self._dist / self.track.length
        cutting = self._cut_at is not None and abs(progress - self._cut_at) < 0.01
        sector = min(2, int(progress * 3))
        return Frame(
            t=now,
            status=GameStatus.LIVE,
            packet_id=self._packet,
            gas=gas,
            brake=brake,
            steer=max(-1.0, min(1.0, k * 40)),
            speed_kmh=self._v * 3.6,
            gear=gear,
            rpm=rpm,
            fuel_l=self._fuel,
            brake_bias=self._bb,
            abs=0.3,
            tc=0.2,
            abs_active=braking and brake > 0.9,
            tc_active=gas > 0.9 and gear <= 2,
            tyre_pressure_psi=[27.4, 27.6, 26.9, 27.1],
            tyre_core_temp_c=[82, 84, 78, 79],
            tyres_out=3 if cutting else 0,
            lap=self._lap,
            lap_time_ms=int(self._lap_t * 1000),
            last_lap_ms=self._last_ms,
            best_lap_ms=self._best_ms,
            lap_progress=progress,
            sector=sector,
            in_pit_box=self._pit_left > 0,
            world=(x, 0.0, z),
            velocity=self._velocity(idx),
            position=1,
        )

    def track_model(self, session: SessionInfo):
        from ..tracks.ac_files import Section, TrackLine
        from ..tracks.model import TrackModel, detect_corners

        pts = self.track.points
        n = len(pts)
        line = TrackLine(
            x=[p[0] for p in pts],
            y=[0.0] * n,
            z=[p[1] for p in pts],
            dist=[i * self.track.step for i in range(n)],
            side_left=[6.0] * n,
            side_right=[6.0] * n,
            speed=list(self.track.v_limit),
        )
        sections = [Section("Hairpin", 0.30, 0.40), Section("The Esses", 0.55, 0.70)]
        return TrackModel(session.track_key, self.track.length, line, detect_corners(line, sections), sections)

    def _velocity(self, idx: int) -> tuple[float, float, float]:
        a = self.track.points[idx]
        b = self.track.points[(idx + 1) % self.track.n]
        d = math.dist(a, b) or 1.0
        return ((b[0] - a[0]) / d * self._v, 0.0, (b[1] - a[1]) / d * self._v)

    def session(self) -> SessionInfo:
        return SessionInfo(
            game=self.game_id,
            car="demo_gt3",
            track="demo_circuit",
            session_type=SessionType.PRACTICE,
            track_length_m=self.track.length,
            max_rpm=REDLINE,
            max_fuel_l=100.0,
            sector_count=3,
            player_name="Demo Driver",
        )
