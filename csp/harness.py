"""Run the CSP app (Pitwall.lua) outside Assetto Corsa, against a real Pitwall service.

A development check: it fakes just enough of CSP (car state, web requests,
UI text, saving/loading car state) to drive a pretend car round the track and
confirm the app connects, loads the track, shows the next corner and brake
countdown, saves the drill run-up and performs a retry.

    uv run --with lupa python csp/harness.py      # with `pitwall-rig run --game demo` running
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from lupa import luajit21 as lj

RIG = "http://127.0.0.1:8765"
APP = Path(__file__).parent / "Pitwall" / "Pitwall.lua"


def http(method: str, url: str, body: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body.encode() if body else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.read().decode()
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def main() -> int:
    lua = lj.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()

    def to_py(v):
        if lj.lua_type(v) == "table":
            keys = list(v.keys())
            if keys and all(isinstance(k, int) for k in keys):
                return [to_py(v[i]) for i in range(1, len(keys) + 1)]
            return {k: to_py(v[k]) for k in keys}
        return v

    def to_lua(v):
        if isinstance(v, dict):
            return lua.table_from({k: to_lua(x) for k, x in v.items()})
        if isinstance(v, list):
            return lua.table_from([to_lua(x) for x in v])
        return v

    state = {"texts": [], "saved": 0, "loaded": 0, "intervals": [], "now": 0.0}
    lua.execute("""
      car = { splinePosition = 0, speedKmh = 180, absMode = 3, absModes = 12,
              tractionControlMode = 2, tractionControlModes = 8, brakeBias = 0.57 }
      sim = { isReplayActive = false, isPaused = false }
      jumped = {}
      ac = {
        getSim = function () return sim end,
        getCar = function () return car end,
        isCarResetAllowed = function () return true end,
        onCarJumped = function (i, fn) jumped[#jumped + 1] = fn end,
      }
      vec2 = function (x, y) return { x = x, y = y } end
      rgbm = function (r, g, b, a) return { r = r, g = g, b = b, mult = a } end
      ac.storage = function (defaults) return defaults end
      script = {}
    """)
    g.JSON = to_lua({})
    g.JSON.stringify = lambda t: json.dumps(to_py(t))
    g.JSON.parse = lambda s: to_lua(json.loads(s))

    def respond(cb, status, body):
        cb(None if status else "connection failed", to_lua({"status": status, "body": body}))

    web = to_lua({})
    web.timeouts = lambda *a: None
    web.get = lambda url, cb: respond(cb, *http("GET", url))
    web.post = lambda url, headers, data, cb: respond(cb, *http("POST", url, data))
    g.web = web
    g.setInterval = lambda fn, every: state["intervals"].append(fn)
    g.os.preciseClock = lambda: state["now"]

    def save(cb):
        state["saved"] += 1
        cb(None, "STATE@%.6f" % g.car.splinePosition)

    def load(data, frames):
        state["loaded"] += 1
        g.car.splinePosition = float(data.split("@")[1])
        return True

    g.ac.saveCarStateAsync = save
    g.ac.loadCarState = load
    ui = to_lua({})
    ui.windowWidth = lambda: 360
    ui.getCursorY = lambda: 0
    for name in ("pushDWriteFont", "popDWriteFont", "drawRectFilled", "dummy", "beginOutline", "endOutline",
                 "separator", "text"):
        ui[name] = lambda *a: None
    ui.textColored = lambda text, colour: state["texts"].append(text)
    ui.checkbox = lambda label, value: False
    ui.slider = lambda label, value, lo, hi, fmt, power: value
    ui.dwriteText = lambda text, size, colour: state["texts"].append(text)
    ui.dwriteTextAligned = lambda text, size, h, v, box, wrap, colour: state["texts"].append(text)
    ui.measureDWriteText = lambda text, size: lua.eval("function(n) return { x = n, y = 20 } end")(len(text) * size * 0.55)
    ui.setCursor = lambda *a: None
    ui.textWrapped = lambda *a: None
    g.ui = ui
    lua.execute("ui.Alignment = { Start = 0, Center = 1, End = 2 }")

    lua.execute(APP.read_text(encoding="utf-8"))
    script = g.script

    def tick(n=1):
        for _ in range(n):
            state["now"] += 0.1
            for fn in state["intervals"]:
                fn()

    tick(3)
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))

    status, body = http("GET", RIG + "/api/csp/track")
    track = json.loads(body) if status == 200 else None
    check("service reachable and has a track", track and track.get("corners"), body[:200])
    if not track:
        return 1

    # Drive a lap: the overlay should name corners and count down to braking.
    seen_corner = seen_brake = False
    quiet_frames = 0
    seen_cue = False
    p = 0.0
    while p < 1.0:
        g.car.splinePosition = p
        script.update(1 / 60)
        state["texts"].clear()
        script.windowMain(1 / 60)
        texts = list(state["texts"])
        seen_corner |= any(t in ("L1", "L2", "L3", "L4", "L5", "L6", "R1", "R2", "R3", "R4", "R5", "R6") for t in texts)
        seen_brake |= any(t.isdigit() for t in texts)
        seen_cue |= "BRAKE" in texts
        quiet_frames += not texts
        p += 8 / track["length_m"]
        if int(p * 1000) % 50 == 0:
            tick()
    check("overlay shows the next corner", seen_corner)
    check("overlay shows the brake countdown near braking points", seen_brake)
    check("overlay says BRAKE at the braking point", seen_cue)
    check("overlay stays empty away from braking points", quiet_frames > 10, str(quiet_frames))
    state["texts"].clear()
    script.windowSettings(1 / 60)
    check("settings window says it's connected", "Connected to Pitwall" in state["texts"], str(state["texts"]))

    status, live = http("GET", RIG + "/api/corners")
    # Real ABS / TC reached the service.
    tick()

    # Drill: start one, drive through its run-up, then ask for a retry.
    c1 = track["corners"][0]
    status, _ = http("POST", RIG + "/api/drill", json.dumps({"corner": c1["n"]}))
    tick(2)
    status, body = http("POST", RIG + "/api/csp/sync", json.dumps({}))
    drill = json.loads(body)["drill"]
    check("app receives the drill with a run-up point", drill and "run_up_p" in drill, body[:200])
    run_up = drill["run_up_p"]
    p = (run_up - 0.01) % 1.0
    for _ in range(60):
        g.car.splinePosition = p
        script.update(1 / 60)
        p = (p + 0.0005) % 1.0
    check("car state saved at the run-up point", state["saved"] >= 1)
    tick(2)  # tell the service a launch state exists
    status, _ = http("POST", RIG + "/api/action/rewind")
    tick(3)  # app picks up the retry command and loads the state
    check("retry loaded the saved state", state["loaded"] == 1)
    check("car back at the run-up point", abs(g.car.splinePosition - run_up) < 0.002,
          f"{g.car.splinePosition} vs {run_up}")
    http("DELETE", RIG + "/api/drill")
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
