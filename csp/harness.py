"""Run the CSP app (Pitwall.lua) outside Assetto Corsa, against a real Pitwall service.

A development check: it fakes just enough of CSP (car state, web requests,
UI text, saving/loading car state) to drive a pretend car round the track and
confirm the app connects, loads the track, shows the next corner and brake
countdown, teleports to a drill's run-up (from a gear snapshot, and the plain
fallback), saves the run-up state and performs a retry from it. The fake CSP
is in fake_csp.lua.

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
FAKE = Path(__file__).parent / "fake_csp.lua"  # just enough of CSP


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

    state = {"texts": [], "intervals": [], "sync": {}}
    lua.execute(FAKE.read_text(encoding="utf-8"))
    g.JSON = to_lua({})
    g.JSON.stringify = lambda t: json.dumps(to_py(t))
    g.JSON.parse = lambda s: to_lua(json.loads(s))

    def respond(cb, status, body):
        cb(None if status else "connection failed", to_lua({"status": status, "body": body}))

    web = to_lua({})
    web.timeouts = lambda *a: None
    web.get = lambda url, cb: respond(cb, *http("GET", url))
    def post(url, headers, data, cb):
        state["sync"] = json.loads(data) if data else {}  # what the app last told the service
        respond(cb, *http("POST", url, data))

    web.post = post
    g.web = web
    g.setInterval = lambda fn, every: state["intervals"].append(fn)
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
            g.NOW += 0.1
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
    g.TRACK_L = track["length_m"]
    g.SAVE_OK = False  # no car-state snapshots until the plain teleport has been tried

    # Drive a lap: the overlay should name corners and count down to braking.
    seen_corner = seen_brake = False
    quiet_frames = 0
    seen_cue = False
    p = 0.0
    while p < 1.0:
        g.place(p)
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
            g.place(q)
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
    check("drill comes with teleport speed and gear", drill.get("teleport") and drill.get("run_up_kmh"), body[:300])

    dot = lua.eval("function (a, b) return a:dot(b) end")
    gear, kmh = drill.get("run_up_gear"), drill["run_up_kmh"]
    mid = (run_up + 0.3) % 1.0

    def speed():
        v = g.car.velocity
        return (v.x ** 2 + v.y ** 2 + v.z ** 2) ** 0.5 * 3.6

    def retry():
        tick(2)  # the app checks in (a bare sync from here says nothing about resets)
        http("POST", RIG + "/api/action/rewind")
        tick(3)
        for _ in range(5):
            script.update(1 / 60)

    def at_run_up():
        return abs((g.car.splinePosition - run_up + 0.5) % 1.0 - 0.5) < 0.002

    # 1. Nothing saved at all yet: a plain move to the run-up point.
    g.place(mid)
    retry()
    tp = to_py(g.teleports)
    check("with no snapshots, retry moves the car", len(tp) >= 1 and g.loaded == 0, str(tp)[:200])
    check("... to the run-up point", at_run_up(), f"{g.car.splinePosition} vs {run_up}")
    check("... facing down the track", dot(g.car.look, g.line_dir(run_up)) > 0.99, str(to_py(g.car.look)))
    tick(2)
    check("... and nothing is kept as the run-up state", not state["sync"].get("has_launch"), str(state["sync"])[:200])

    # 2. Drive a bit in a few gears: the app snapshots the car on straights.
    g.SAVE_OK, g.saved = True, 0
    for gr, q0 in ((2, run_up + 0.1), (gear or 3, run_up + 0.35), (5, run_up + 0.6)):  # not through the run-up
        q = q0
        for _ in range(240):  # 4 s
            g.place(q, kmh if gr == gear else 100 + 25 * gr, gr)
            script.update(1 / 60)
            q += (kmh / 3.6) / 60 / track["length_m"]
    check("snapshots taken while driving", g.saved >= 6, str(g.saved))
    g.place(mid, 60, 1)
    script.update(1 / 60)
    retry()
    check("retry teleports from a snapshot", g.loaded == 1, str(g.loaded))
    check("... to the run-up point", at_run_up(), f"{g.car.splinePosition} vs {run_up}")
    check("... facing down the track", dot(g.car.look, g.line_dir(run_up)) > 0.99, str(to_py(g.car.look)))
    check("... at the reference speed", abs(speed() - kmh) < 1, f"{speed()} vs {kmh}")
    check("... moving down the track", dot(g.car.velocity, g.line_dir(run_up)) > 0, str(to_py(g.car.velocity)))
    check("... in the reference gear", gear is None or g.car.gear == gear, f"{g.car.gear} vs {gear}")
    check("... sitting on the road as it was", abs(g.car.position.y - (g.CAR_H + 0.05)) < 0.01, str(g.car.position.y))
    tick(2)
    check("... and kept for the next retry", state["sync"].get("has_launch"))

    # 3. Driving through the run-up saves the real car there; retry loads that.
    p = (run_up - 0.01) % 1.0
    for _ in range(60):
        g.place(p, kmh, gear or 3)
        script.update(1 / 60)
        p = (p + 0.0005) % 1.0
    tick(2)
    loaded = g.loaded
    http("POST", RIG + "/api/action/rewind")
    tick(3)
    check("retry loads the state saved at the run-up", g.loaded == loaded + 1)
    check("car back at the run-up point", at_run_up(), f"{g.car.splinePosition} vs {run_up}")
    http("DELETE", RIG + "/api/drill")

    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
