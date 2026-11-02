"""Assetto Corsa (original) shared-memory layouts.

Mirrors Kunos' ``SharedFileOut.h`` (the ``acpmf_*`` pages). Structs are packed
to 4 bytes. ``wchar_t`` on Windows is 2 bytes (UTF-16), so strings are declared
as ``c_uint16`` arrays and decoded explicitly; that keeps these structs
byte-identical on every platform, which lets the tests run on Linux/macOS.

Only fields up to the point we need are declared. Reading a prefix of a larger
mapping is fine, and newer AC/CSP builds only ever append fields.
"""

from __future__ import annotations

import ctypes as C

F4 = C.c_float * 4
F3 = C.c_float * 3


def wstr(n: int) -> type[C.Array]:
    return C.c_uint16 * n


def decode_wstr(arr: C.Array) -> str:
    raw = bytes(arr)
    return raw.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]


# AC_STATUS
AC_OFF, AC_REPLAY, AC_LIVE, AC_PAUSE = 0, 1, 2, 3

# AC_SESSION_TYPE
SESSION_TYPES = {
    -1: "unknown",
    0: "practice",
    1: "qualify",
    2: "race",
    3: "hotlap",
    4: "time_attack",
    5: "drift",
    6: "drag",
}


class SPageFilePhysics(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", C.c_int),
        ("gas", C.c_float),
        ("brake", C.c_float),
        ("fuel", C.c_float),
        ("gear", C.c_int),  # 0 = R, 1 = N, 2 = 1st ...
        ("rpms", C.c_int),
        ("steerAngle", C.c_float),
        ("speedKmh", C.c_float),
        ("velocity", F3),
        ("accG", F3),
        ("wheelSlip", F4),
        ("wheelLoad", F4),
        ("wheelsPressure", F4),
        ("wheelAngularSpeed", F4),
        ("tyreWear", F4),
        ("tyreDirtyLevel", F4),
        ("tyreCoreTemperature", F4),
        ("camberRAD", F4),
        ("suspensionTravel", F4),
        ("drs", C.c_float),
        ("tc", C.c_float),
        ("heading", C.c_float),
        ("pitch", C.c_float),
        ("roll", C.c_float),
        ("cgHeight", C.c_float),
        ("carDamage", C.c_float * 5),
        ("numberOfTyresOut", C.c_int),
        ("pitLimiterOn", C.c_int),
        ("abs", C.c_float),
        ("kersCharge", C.c_float),
        ("kersInput", C.c_float),
        ("autoShifterOn", C.c_int),
        ("rideHeight", C.c_float * 2),
        ("turboBoost", C.c_float),
        ("ballast", C.c_float),
        ("airDensity", C.c_float),
        ("airTemp", C.c_float),
        ("roadTemp", C.c_float),
        ("localAngularVel", F3),
        ("finalFF", C.c_float),
        ("performanceMeter", C.c_float),
        ("engineBrake", C.c_int),
        ("ersRecoveryLevel", C.c_int),
        ("ersPowerLevel", C.c_int),
        ("ersHeatCharging", C.c_int),
        ("ersIsCharging", C.c_int),
        ("kersCurrentKJ", C.c_float),
        ("drsAvailable", C.c_int),
        ("drsEnabled", C.c_int),
        ("brakeTemp", F4),
        ("clutch", C.c_float),
        ("tyreTempI", F4),
        ("tyreTempM", F4),
        ("tyreTempO", F4),
        ("isAIControlled", C.c_int),
        ("tyreContactPoint", F3 * 4),
        ("tyreContactNormal", F3 * 4),
        ("tyreContactHeading", F3 * 4),
        ("brakeBias", C.c_float),
        ("localVelocity", F3),
    ]


class SPageFileGraphic(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", C.c_int),
        ("status", C.c_int),
        ("session", C.c_int),
        ("currentTime", wstr(15)),
        ("lastTime", wstr(15)),
        ("bestTime", wstr(15)),
        ("split", wstr(15)),
        ("completedLaps", C.c_int),
        ("position", C.c_int),
        ("iCurrentTime", C.c_int),
        ("iLastTime", C.c_int),
        ("iBestTime", C.c_int),
        ("sessionTimeLeft", C.c_float),  # ms
        ("distanceTraveled", C.c_float),
        ("isInPit", C.c_int),
        ("currentSectorIndex", C.c_int),
        ("lastSectorTime", C.c_int),
        ("numberOfLaps", C.c_int),
        ("tyreCompound", wstr(33)),
        ("replayTimeMultiplier", C.c_float),
        ("normalizedCarPosition", C.c_float),
        ("carCoordinates", F3),
        ("penaltyTime", C.c_float),
        ("flag", C.c_int),
        ("idealLineOn", C.c_int),
        ("isInPitLane", C.c_int),
        ("surfaceGrip", C.c_float),
        ("mandatoryPitDone", C.c_int),
        ("windSpeed", C.c_float),
        ("windDirection", C.c_float),
    ]


class SPageFileStatic(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", wstr(15)),
        ("acVersion", wstr(15)),
        ("numberOfSessions", C.c_int),
        ("numCars", C.c_int),
        ("carModel", wstr(33)),
        ("track", wstr(33)),
        ("playerName", wstr(33)),
        ("playerSurname", wstr(33)),
        ("playerNick", wstr(33)),
        ("sectorCount", C.c_int),
        ("maxTorque", C.c_float),
        ("maxPower", C.c_float),
        ("maxRpm", C.c_int),
        ("maxFuel", C.c_float),
        ("suspensionMaxTravel", F4),
        ("tyreRadius", F4),
        ("maxTurboBoost", C.c_float),
        ("deprecated_1", C.c_float),
        ("deprecated_2", C.c_float),
        ("penaltiesEnabled", C.c_int),
        ("aidFuelRate", C.c_float),
        ("aidTireRate", C.c_float),
        ("aidMechanicalDamage", C.c_float),
        ("aidAllowTyreBlankets", C.c_int),
        ("aidStability", C.c_float),
        ("aidAutoClutch", C.c_int),
        ("aidAutoBlip", C.c_int),
        ("hasDRS", C.c_int),
        ("hasERS", C.c_int),
        ("hasKERS", C.c_int),
        ("kersMaxJ", C.c_float),
        ("engineBrakeSettingsCount", C.c_int),
        ("ersPowerControllerCount", C.c_int),
        ("trackSPlineLength", C.c_float),
        ("trackConfiguration", wstr(33)),
        ("ersMaxJ", C.c_float),
        ("isTimedRace", C.c_int),
        ("hasExtraLap", C.c_int),
        ("carSkin", wstr(33)),
        ("reversedGridPositions", C.c_int),
        ("pitWindowStart", C.c_int),
        ("pitWindowEnd", C.c_int),
    ]


PHYSICS_TAG = "Local\\acpmf_physics"
GRAPHICS_TAG = "Local\\acpmf_graphics"
STATIC_TAG = "Local\\acpmf_static"
