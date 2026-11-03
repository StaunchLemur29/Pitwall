"""Game-agnostic telemetry model.

Every game adapter converts its native data into these types, so everything
downstream (lap recording, storage, the dashboard) never needs to know which
game is running.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class GameStatus(str, Enum):
    OFF = "off"  # game not running / no session
    REPLAY = "replay"
    LIVE = "live"
    PAUSED = "paused"


class SessionType(str, Enum):
    UNKNOWN = "unknown"
    PRACTICE = "practice"
    QUALIFY = "qualify"
    RACE = "race"
    HOTLAP = "hotlap"
    TIME_ATTACK = "time_attack"
    DRIFT = "drift"
    DRAG = "drag"


class Mode(str, Enum):
    """Dashboard mode, derived from game state."""

    DRIVING = "driving"
    ANALYSIS = "analysis"
    IDLE = "idle"


@dataclass(frozen=True)
class Capabilities:
    """What an adapter can report or do. The UI hides features a game lacks."""

    reports_brake_bias: bool = False
    reports_abs_level: bool = False
    reports_tc_level: bool = False
    reports_tyre_pressure: bool = False
    reports_world_position: bool = False
    can_retry_section: bool = False


@dataclass
class SessionInfo:
    """Mostly-static facts about the current session."""

    game: str
    car: str
    track: str
    track_config: str = ""
    session_type: SessionType = SessionType.UNKNOWN
    track_length_m: float = 0.0
    max_rpm: int = 0
    max_fuel_l: float = 0.0
    sector_count: int = 0
    player_name: str = ""
    # The car's systems, as the game reports them (see car_profile.py).
    has_drs: bool = False
    has_ers: bool = False  # hybrid energy recovery (MGU-K / MGU-H)
    has_kers: bool = False  # simple KERS boost button
    engine_brake_maps: int = 0
    ers_power_modes: int = 0

    @property
    def track_key(self) -> str:
        """Stable identifier for a track layout (mod tracks often have several)."""
        return f"{self.track}@{self.track_config}" if self.track_config else self.track

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["session_type"] = self.session_type.value
        d["track_key"] = self.track_key
        return d


@dataclass
class Frame:
    """One telemetry sample. Units: metric, seconds, km/h, psi, °C."""

    t: float  # seconds (perf_counter), from the rig clock
    status: GameStatus = GameStatus.OFF
    packet_id: int = 0

    # driver inputs
    gas: float = 0.0  # 0..1
    brake: float = 0.0  # 0..1
    clutch: float = 0.0  # 0..1
    steer: float = 0.0  # radians at the wheel, as reported by the game

    # car state
    speed_kmh: float = 0.0
    gear: int = 0  # -1 reverse, 0 neutral, 1.. forward
    rpm: int = 0
    fuel_l: float = 0.0

    # electronics (None when the game doesn't report it)
    brake_bias: float | None = None  # front fraction, 0..1
    abs: float | None = None
    tc: float | None = None
    abs_active: bool = False
    tc_active: bool = False

    # tyres, order FL FR RL RR
    tyre_pressure_psi: list[float] | None = None
    tyre_core_temp_c: list[float] | None = None
    tyres_out: int = 0  # number of wheels off track

    # position on track
    lap: int = 0  # completed laps
    lap_time_ms: int = 0  # current lap time
    last_lap_ms: int = 0
    best_lap_ms: int = 0
    lap_progress: float = 0.0  # 0..1 along the track spline
    sector: int = 0
    in_pit_box: bool = False
    in_pit_lane: bool = False
    world: tuple[float, float, float] | None = None  # x, y(up), z in metres
    velocity: tuple[float, float, float] | None = None  # world-space m/s, same axes as world
    yaw: float | None = None  # the game's raw heading angle (radians); calibrated downstream
    world_t: float | None = None  # rig-clock time the game last moved ``world`` (for precise prediction)
    session_time_left_s: float | None = None
    position: int = 0

    # car systems (None when the game doesn't report them)
    drs_available: bool = False  # in a DRS zone and allowed to open it
    drs_open: bool = False
    battery: float | None = None  # hybrid / KERS charge, 0..1
    ers_deploy: int | None = None  # ERS power (deploy) mode
    ers_recovery: int | None = None
    engine_brake: int | None = None

    def to_wire(self) -> dict[str, Any]:
        """Compact dict for the dashboard websocket."""
        d = asdict(self)
        d["status"] = self.status.value
        d.pop("world_t", None)
        return d


@dataclass
class Lap:
    """A completed lap with its trace."""

    game: str
    car: str
    track_key: str
    lap_number: int
    lap_time_ms: int
    valid: bool
    out_lap: bool
    started_at: float  # unix time
    sector_ms: list[int] = field(default_factory=list)
    trace: dict[str, list[float]] = field(default_factory=dict)
    id: int | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game": self.game,
            "car": self.car,
            "track_key": self.track_key,
            "lap_number": self.lap_number,
            "lap_time_ms": self.lap_time_ms,
            "valid": self.valid,
            "out_lap": self.out_lap,
            "started_at": self.started_at,
            "sector_ms": self.sector_ms,
        }


def mode_for(frame: Frame | None) -> Mode:
    """Driving when live on track; analysis in pits, menus, pause or replay."""
    if frame is None or frame.status == GameStatus.OFF:
        return Mode.IDLE
    if frame.status == GameStatus.LIVE and not frame.in_pit_box:
        return Mode.DRIVING
    return Mode.ANALYSIS
