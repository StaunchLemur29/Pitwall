"""Run the CSP app (Pitwall.lua) outside Assetto Corsa, against a real Pitwall service.

A development check: it fakes just enough of CSP (car state, web requests,
UI text, saving/loading car state) to drive a pretend car round the track and
confirm the app connects, loads the track, shows the next corner and brake
countdown, teleports to a drill (stopped, before the section), saves the drill
run-up and performs a retry.

    uv run --with lupa python csp/harness.py      # with `pitwall-rig run --game demo` running
"""

from __future__ import annotations

import json
import sys
import time
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
              tractionControlMode = 2, tractionControlModes = 8, brakeBias = 0.57,
              mgukDelivery = 1, mgukDeliveryCount = 4, mgukRecovery = 5, kersPresent = true,
              currentEngineBrakeSetting = 2, engineBrakeSettingsCount = 5 }
      sim = { isReplayActive = false, isPaused = false }
      jumped = {}
      ac = {
        getSim = function () return sim end,
        getCar = function () return car end,
        isCarResetAllowed = function () return true end,
        onCarJumped = function (i, fn) jumped[#jumped + 1] = fn end,
        -- a pretend track: progress p is x = p * 1000 m along a straight line
        trackProgressToWorldCoordinate = function (p) return vec3(p * 1000, 0, 0) end,
      }
      vec2 = function (x, y) return { x = x, y = y } end
      local V = {}
      V.__index = V
      vec3 = function (x, y, z) return setmetatable({ x = x, y = y, z = z }, V) end
      V.__sub = function (a, b) return vec3(a.x - b.x, a.y - b.y, a.z - b.z) end
      V.__unm = function (a) return vec3(-a.x, -a.y, -a.z) end
      function V:length() return math.sqrt(self.x ^ 2 + self.y ^ 2 + self.z ^ 2) end
      function V:normalize() local l = self:length(); return vec3(self.x / l, self.y / l, self.z / l) end
      function V:dot(b) return self.x * b.x + self.y * b.y + self.z * b.z end
      teleports = {}
      tyreTemps = {}
      car.look = vec3(1, 0, 0)
      -- tyres warmed by driving; optimum from the car's data
      car.wheels = {}
      for i = 0, 3 do car.wheels[i] = { tyreCoreTemperature = 88, tyreOptimumTemperature = 85 } end
      physics = {
        setCarPosition = function (i, pos, dir)
          teleports[#teleports + 1] = { pos = pos, dir = dir }
          car.splinePosition = pos.x / 1000
          car.look = dir -- the opposite of CSP's own apps' convention, so the app has to turn it round
          car.speedKmh = 0
          for i = 0, 3 do car.wheels[i].tyreCoreTemperature = 20 end -- a reset: cold tyres
          for _, fn in ipairs(jumped) do fn(0) end
        end,
        setTyresTemperature = function (i, wheel, t)
          tyreTemps[#tyreTemps + 1] = { car = i, wheel = wheel, t = t }
          for w = 0, 3 do car.wheels[w].tyreCoreTemperature = t end
        end,
      }
      ac.Wheel = { All = 15 }
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
    posted: list[str] = []

    def post(url, headers, data, cb):
        posted.append(data or "")
        status, body = http("POST", url, data)
        if state.get("fake_session") and status == 200 and url.endswith("/api/csp/sync"):
            d = json.loads(body)
            d["session"] = state["fake_session"]  # as if the car or track changed
            body = json.dumps(d)
        if state.get("fake_tip") and status == 200 and url.endswith("/api/csp/sync"):
            d = json.loads(body)
            d["tip"] = state["fake_tip"]
            body = json.dumps(d)
        respond(cb, status, body)

    web.post = post
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
    ui.pathLineTo = lambda *a: None
    ui.pathArcTo = lambda *a: None
    ui.pathStroke = lambda *a: None
    ui.drawImage = lambda path, *a: state["texts"].append("<arrow>") if str(path).startswith("icons/turn_") else None
    ui.drawRect = lambda *a: None
    ui.drawTriangleFilled = lambda *a: None
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

    # A freshly started demo service has no braking points until it has driven a
    # lap: wait for them (up to two minutes) rather than failing on timing.
    for _ in range(120):
        status, body = http("GET", RIG + "/api/csp/track")
        track = json.loads(body) if status == 200 else None
        if track and any(c.get("brake_p") is not None for c in track.get("corners") or []):
            break
        time.sleep(1)
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
        seen_corner |= "<arrow>" in texts
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
    def lap_texts():
        out, q = set(), 0.0
        while q < 1.0:
            g.car.splinePosition = q
            script.update(1 / 60)
            state["texts"].clear()
            script.windowMain(1 / 60)
            out.update(state["texts"])
            q += 8 / track["length_m"]
        return out

    texts = lap_texts()
    gears = {str(c["gear"]) for c in track["corners"] if c.get("gear")}
    check("turn arrow comes with the gear to be in", "<arrow>" in texts and gears & texts, str(sorted(texts))[:200])
    # Turn the turn off in Pitwall's settings: the overlay follows.
    _, cfg = http("GET", RIG + "/api/config")
    cfg = json.loads(cfg)
    cfg["overlay"]["show_turn"] = False
    http("PUT", RIG + "/api/config", json.dumps(cfg))
    tick(2)
    texts = lap_texts()
    check("'show the turn' off in Pitwall hides it in game", "<arrow>" not in texts and "BRAKE" in texts,
          str(sorted(texts))[:200])
    cfg["overlay"]["show_turn"] = True
    http("PUT", RIG + "/api/config", json.dumps(cfg))
    tick(2)

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

    # "Go there" at speed: the app saved car states as you drove (above); it loads
    # the one just before the run-up, so you arrive at speed with warm tyres.
    tick(2)  # the app checks in (the bare sync above didn't say resets are allowed)
    check("car states saved along the lap for Go there", state["saved"] > 0, str(state["saved"]))
    loaded0, tp0 = state["loaded"], len(to_py(g.teleports) or [])
    posted.clear()
    g.car.splinePosition = (run_up + 0.3) % 1.0
    http("POST", RIG + "/api/drill", json.dumps({"corner": c1["n"], "teleport": True}))
    tick(3)
    gap_m = ((run_up - g.car.splinePosition) % 1.0) * track["length_m"]
    tick(1)
    at_speed = [e for b in posted for e in (json.loads(b).get("events") or []) if e.get("type") == "teleport"]
    check("Go there arrives at speed from a saved state, before the run-up",
          state["loaded"] == loaded0 + 1 and len(to_py(g.teleports) or []) == tp0 and 150 <= gap_m <= 1500
          and at_speed and at_speed[-1].get("at_speed"), f"{state['loaded']} {gap_m:.0f} m {at_speed}")
    # A different car or track: those states don't apply; Go there parks you, stopped.
    state["fake_session"] = "other car@other track"
    tick(2)
    saved_mark = state["saved"]

    # Go to the section: the service picks a spot before it, the app parks the car there.
    g.car.splinePosition = (run_up + 0.3) % 1.0
    status, body = http("POST", RIG + "/api/drill", json.dumps({"corner": c1["n"], "teleport": True}))
    check("dashboard can ask to teleport to a drill", status == 200 and "errors" not in json.loads(body), body)
    tick(3)
    for _ in range(3):
        script.update(1 / 60)
    tp = to_py(g.teleports)
    before_m = ((drill["start_p"] - g.car.splinePosition) % 1.0) * track["length_m"]
    run_up_m = ((drill["start_p"] - run_up) % 1.0) * track["length_m"]
    check("teleported, stopped", len(tp) >= 1 and g.car.speedKmh == 0, str(tp)[:200])
    check("... before the Time Shift run-up", run_up_m < before_m < track["length_m"] / 2, f"{before_m} vs {run_up_m}")
    check("... facing down the track", g.car.look.x > 0, str(to_py(g.car.look)))
    check("teleport isn't saved as the run-up state", state["saved"] == saved_mark)
    temps = to_py(g.tyreTemps)
    # Warm to what Pitwall learnt the car runs at (sent with the teleport), else
    # the car's optimum (85 here): never a cold reading.
    target = temps[0]["t"] if temps else None
    check("tyres put back to working temperature after the teleport",
          temps and target >= 75 and all(t["t"] == target and t["wheel"] == 15 for t in temps)
          and g.car.wheels[0].tyreCoreTemperature == target,
          str(temps)[:200])

    def tyre_events():
        out = []
        for body in posted:
            try:
                out += [e for e in json.loads(body).get("events") or [] if e.get("type") == "tyres"]
            except (ValueError, AttributeError):
                pass
        return out

    # Two seconds on, the app checks the tyres really are warm before saying so.
    for _ in range(125):
        script.update(1 / 60)
    tick(2)
    ev = tyre_events()
    check("... and checks they really are warm", ev and ev[-1]["result"] == "warm", str(ev)[-200:])
    # A CSP that takes the call but doesn't warm them: say so, don't claim warm.
    lua.execute("_realWarm = physics.setTyresTemperature; physics.setTyresTemperature = function () end")
    posted.clear()
    http("POST", RIG + "/api/drill", json.dumps({"corner": c1["n"], "teleport": True}))
    tick(3)
    for _ in range(125):
        script.update(1 / 60)
    tick(2)
    ev = tyre_events()
    check("... and says when they stayed cold", ev and ev[-1]["result"] == "no_effect", str(ev)[-200:])
    lua.execute("physics.setTyresTemperature = _realWarm")
    g.car.speedKmh = 180

    p = (run_up - 0.01) % 1.0
    for _ in range(60):
        g.car.splinePosition = p
        script.update(1 / 60)
        p = (p + 0.0005) % 1.0
    check("car state saved at the run-up point", state["saved"] >= 1)
    # A slower pass over the run-up point (e.g. the first one after "Go there")
    # mustn't replace a state saved at speed: retries would all start slow.
    saved = state["saved"]
    g.car.speedKmh = 40
    p = (run_up - 0.01) % 1.0
    for _ in range(60):
        g.car.splinePosition = p
        script.update(1 / 60)
        p = (p + 0.0005) % 1.0
    check("... and a slower pass doesn't replace it", state["saved"] == saved, f"{state['saved']} vs {saved}")
    g.car.speedKmh = 180
    tick(2)  # tell the service a launch state exists
    status, _ = http("POST", RIG + "/api/action/rewind")
    tick(3)  # app picks up the retry command and loads the state
    check("retry loaded the saved state", state["loaded"] == loaded0 + 2)
    check("car back at the run-up point", abs(g.car.splinePosition - run_up) < 0.002,
          f"{g.car.splinePosition} vs {run_up}")
    # The drill timer in the overlay: counts through the section, then shows the result.
    tick(2)
    status, body = http("POST", RIG + "/api/csp/sync", json.dumps({}))
    drill = json.loads(body)["drill"]
    seen_running = seen_target = seen_result = False
    p = (drill["start_p"] - 0.01) % 1.0
    end = drill["end_p"] if drill["end_p"] > drill["start_p"] else drill["end_p"] + 1.0
    while p < end + 0.01:
        g.car.splinePosition = p % 1.0
        g.car.speedKmh = 150
        script.update(1 / 60)
        state["texts"].clear()
        script.windowMain(1 / 60)
        texts = list(state["texts"])
        seen_running |= any(t.replace(".", "", 1).isdigit() and "." in t and len(t) <= 5 for t in texts)
        seen_target |= any(t.startswith(("to beat ", "best ")) for t in texts)
        seen_result |= any(t.startswith(("+", "-", "beat it", "new best")) for t in texts)
        p += 0.0005
    check("in-game drill timer counts through the section", seen_running)
    check("... with the time to beat (or your best) beside it", seen_target, str(drill)[:200])
    check("... and shows the result at the end", seen_result)
    http("DELETE", RIG + "/api/drill")

    # A live tip from Pitwall shows in the overlay, and goes when Pitwall stops sending it.
    state["fake_tip"] = "Turn 3: you've gone off here on 2 of your last 4 laps."
    tick(2)
    state["texts"].clear()
    script.windowMain(1 / 60)
    check("live tip shows in the game", state["fake_tip"] in state["texts"], str(state["texts"])[:200])
    state["fake_tip"] = None
    tick(2)
    state["texts"].clear()
    script.windowMain(1 / 60)
    check("... and goes away", not any("gone off here" in t for t in state["texts"]))

    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
