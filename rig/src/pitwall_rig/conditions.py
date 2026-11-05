"""The conditions you're driving in, and the changes the coach should tell you
about: a crash (damage, dirty or cold tyres), the track getting hotter or
grippier, rain, dusk, worn tyres.

Fed every frame (plus what the in-game CSP app knows: time of day, weather).
``notice`` is the latest thing worth saying, as one plain sentence, for the
side screen's coach strip; ``snapshot`` is what goes with each lap.

The AC numbers it reads (tyre wear, dirt, damage) aren't documented with
units, so the thresholds are cautious and relative to where the stint
started; they're checked on the rig before they're trusted further.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .laps import slip_deg
from .models import Frame, GameStatus

DAMAGE_STEP = 0.5  # a jump in AC's damage numbers this big is contact, not noise
DIRTY = 0.5  # AC tyre dirt level above this: picked up grass or gravel
CLEAN = 0.1
ROAD_STEP_C = 4.0  # track this much hotter or cooler than at the start of the stint
GRIP_STEP = 0.02  # track grip (AC surfaceGrip, 0..1) up or down by two points
WEAR_STEPS = (3.0, 6.0, 10.0)  # tyre wear lost since the stint started (AC's wear numbers)
NOTICE_S = 20.0  # how long a notice stays up
DAMAGE_PARTS = ("front", "rear", "left side", "right side", "centre")


@dataclass
class Env:
    """What only the in-game app knows (None until it says)."""

    time: str | None = None  # "14:20" in the session's time of day
    hour: float | None = None
    weather: int | None = None  # CSP's weather type
    rain: float | None = None  # 0..1
    ambient_c: float | None = None
    road_grip: float | None = None  # CSP's track grip, 0..1


@dataclass
class Conditions:
    env: Env = field(default_factory=Env)
    notice: dict[str, Any] | None = None  # {"kind", "text", "at"}
    _start: dict[str, Any] | None = None  # the stint's starting conditions
    _damage: list[float] | None = None
    _dirty: bool = False
    _wear_said: int = 0
    _road_said: float | None = None
    _grip_said: float | None = None
    _rain: bool = False
    _dark: bool | None = None
    _last: Frame | None = None
    _speeds: deque = field(default_factory=lambda: deque(maxlen=400))  # (t, km/h) for the last moments
    _stopped: bool = False

    def set_env(self, env: dict[str, Any] | None) -> None:
        if not env:
            return
        h, m = env.get("time_h"), env.get("time_m")
        self.env = Env(
            time=f"{int(h):02d}:{int(m):02d}" if h is not None and m is not None else None,
            hour=float(h) + float(m or 0) / 60 if h is not None else None,
            weather=env.get("weather"),
            rain=env.get("rain"),
            ambient_c=env.get("ambient_c"),
            road_grip=env.get("road_grip"),
        )

    def reset(self) -> None:
        """A new session, car or track: start again."""
        env = self.env
        self.__init__()  # type: ignore[misc]
        self.env = env

    def _say(self, kind: str, text: str, now: float) -> None:
        self.notice = {"kind": kind, "text": text, "at": now}

    def current_notice(self, now: float) -> dict[str, Any] | None:
        n = self.notice
        return {k: v for k, v in n.items() if k != "at"} if n and now - n["at"] < NOTICE_S else None

    def update(self, f: Frame, now: float) -> None:
        if f.status != GameStatus.LIVE:
            return
        self._last = f
        self._speeds.append((now, f.speed_kmh))
        while self._speeds and now - self._speeds[0][0] > 5.0:
            self._speeds.popleft()
        if f.in_pit_box or self._start is None:
            # a fresh stint (out of the pits, or the first frame): measure from here
            self._start = self._read(f)
            self._damage = list(f.damage) if f.damage else None
            self._wear_said = 0
            self._road_said = self._start.get("road_c")
            self._grip_said = self._start.get("grip")
            return

        # Contact: AC's damage numbers jump. Say where, and what else the crash did.
        if f.damage and self._damage and len(f.damage) == len(self._damage):
            jumps = [i for i, (a, b) in enumerate(zip(f.damage, self._damage, strict=False)) if a - b >= DAMAGE_STEP]
            if jumps:
                where = " and ".join(DAMAGE_PARTS[i] for i in jumps if i < len(DAMAGE_PARTS)) or "car"
                self._say("crash", f"Contact: {where} damaged. The car won't be as quick from here: "
                          "compare with care, and pit to repair if it's bad.", now)
            self._damage = list(f.damage)

        # Off into the grass or gravel: dirty tyres for a bit.
        dirt = max(f.tyre_dirt) if f.tyre_dirt else None
        if dirt is not None:
            if not self._dirty and dirt > DIRTY:
                self._dirty = True
                self._say("dirt", "Dirty tyres after going off: less grip for the next few corners. "
                          "Take it easy until they clean up.", now)
            elif self._dirty and dirt < CLEAN:
                self._dirty = False
                self._say("clean", "Tyres clean again: back to full grip.", now)

        # Big moment: nearly stopped on track having been at speed moments ago, or
        # the car turned side-on (a crash or a spin). Tyres cool, maybe dirty or
        # flat-spotted. (Hard braking for a hairpin doesn't get below 20 km/h.)
        top = max(v for _, v in self._speeds)
        spun = slip_deg(f) > 90
        if not self._stopped and not f.in_pit_lane and ((f.speed_kmh < 20 and top > 60) or spun):
            self._stopped = True
            self._say("crash", "You crashed or spun: the tyres will be cooler and may be dirty or flat-spotted. "
                      "Build back up for a lap before pushing.", now)
        elif self._stopped and f.speed_kmh > 80:
            self._stopped = False

        cur = self._read(f)
        # Worn tyres: say it at a few steps through the stint.
        if cur.get("wear") is not None and self._start.get("wear") is not None:
            lost = self._start["wear"] - cur["wear"]
            steps = [s for s in WEAR_STEPS if lost >= s]
            if len(steps) > self._wear_said:
                self._wear_said = len(steps)
                self._say("wear", f"Tyres worn about {lost:.0f}% this stint: less grip, so brake a little earlier "
                          "and expect the car to slide sooner.", now)
        # The track: hotter or cooler, grippier or slipperier.
        road = cur.get("road_c")
        if road is not None and self._road_said is not None and abs(road - self._road_said) >= ROAD_STEP_C:
            word = "hotter" if road > self._road_said else "cooler"
            self._say("track", f"Track {abs(road - self._road_said):.0f}° {word} than earlier ({road:.0f}°): "
                      f"{'a little less' if word == 'hotter' else 'different'} grip, lap times may move.", now)
            self._road_said = road
        grip = cur.get("grip")
        if grip is not None and self._grip_said is not None and abs(grip - self._grip_said) >= GRIP_STEP:
            word = "up" if grip > self._grip_said else "down"
            self._say("track", f"Track grip {word} to {grip * 100:.0f}%"
                      f"{' (rubbering in): you can brake a bit later' if word == 'up' else ': brake a bit earlier'}.", now)
            self._grip_said = grip
        # Weather and light, from the in-game app.
        rain = self.env.rain
        if rain is not None:
            if not self._rain and rain > 0.05:
                self._rain = True
                self._say("weather", "Rain: brake earlier and smoother, and stay off the kerbs and white lines.", now)
            elif self._rain and rain < 0.01:
                self._rain = False
                self._say("weather", "Rain stopped: the track will dry and grip will come back gradually.", now)
        if self.env.hour is not None:
            dark = self.env.hour >= 19.5 or self.env.hour < 6
            if self._dark is not None and dark and not self._dark:
                self._say("light", "Getting dark: braking markers are harder to see, pick your points early.", now)
            self._dark = dark

    def _read(self, f: Frame) -> dict[str, Any]:
        return {
            "air_c": round(f.air_c, 1) if f.air_c is not None else self.env.ambient_c,
            "road_c": round(f.road_c, 1) if f.road_c is not None else None,
            "grip": round(f.grip, 3) if f.grip else self.env.road_grip,
            "wear": round(sum(f.tyre_wear) / len(f.tyre_wear), 2) if f.tyre_wear else None,
        }

    def snapshot(self, f: Frame | None) -> dict[str, Any] | None:
        """The conditions to keep with a lap."""
        if f is None:
            return None
        cur = self._read(f)
        start = self._start or {}
        out = {
            "air_c": cur["air_c"],
            "road_c": cur["road_c"],
            "grip": cur["grip"],
            "tyre_wear_pct": round(start["wear"] - cur["wear"], 1)
            if cur.get("wear") is not None and start.get("wear") is not None else None,
            "damage": round(sum(f.damage), 2) if f.damage else None,
            "fuel_l": round(f.fuel_l, 1),
            "time": self.env.time,
            "rain": self.env.rain,
            "weather": self.env.weather,
        }
        return out if any(v is not None for k, v in out.items() if k != "fuel_l") else {"fuel_l": out["fuel_l"]}
