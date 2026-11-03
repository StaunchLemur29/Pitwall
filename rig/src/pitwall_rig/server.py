"""HTTP + WebSocket server for the dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from .config import ACTIONS
from .rig import Event, Rig

log = logging.getLogger(__name__)

RIG_KEY = web.AppKey("rig", Rig)
HUB_KEY: web.AppKey[Hub] = web.AppKey("hub")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


class Hub:
    """Fans events out to every connected dashboard."""

    def __init__(self) -> None:
        self.clients: set[web.WebSocketResponse] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, event: Event) -> None:
        """Safe to call from any thread."""
        if self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(self.broadcast(event))
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast(event), self._loop)

    async def broadcast(self, event: Event) -> None:
        if not self.clients:
            return
        msg = _dumps(event)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_str(msg)
            except (ConnectionError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    rig, hub = request.app[RIG_KEY], request.app[HUB_KEY]
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(request)
    hub.clients.add(ws)
    await ws.send_str(_dumps(rig.hello()))
    await ws.send_str(_dumps({"type": "outline", **rig.outline()}))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "action":
                rig.action(str(data.get("action")))
    finally:
        hub.clients.discard(ws)
    return ws


# -- REST -------------------------------------------------------------------


async def get_config(request: web.Request) -> web.Response:
    return web.json_response(request.app[RIG_KEY].config.data)


async def put_config(request: web.Request) -> web.Response:
    rig, hub = request.app[RIG_KEY], request.app[HUB_KEY]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"errors": ["Body must be JSON"]}, status=400)
    errs = rig.config.update(body)
    if errs:
        return web.json_response({"errors": errs}, status=400)
    on_change = request.app.get(ON_CONFIG_KEY)
    if on_change:
        on_change()
    await hub.broadcast({"type": "config", "config": rig.config.data})
    return web.json_response(rig.config.data)


async def reset_config(request: web.Request) -> web.Response:
    rig, hub = request.app[RIG_KEY], request.app[HUB_KEY]
    rig.config.reset()
    on_change = request.app.get(ON_CONFIG_KEY)
    if on_change:
        on_change()
    await hub.broadcast({"type": "config", "config": rig.config.data})
    return web.json_response(rig.config.data)


async def get_laps(request: web.Request) -> web.Response:
    rig = request.app[RIG_KEY]
    q = request.query
    limit = min(int(q.get("limit", "50")), 500)
    if q.get("current") == "1":
        return web.json_response(rig.recent_laps(limit))
    return web.json_response(
        rig.store.laps(q.get("game"), q.get("track_key"), q.get("car"), limit=limit)
    )


async def get_trace(request: web.Request) -> web.Response:
    rig = request.app[RIG_KEY]
    hz = float(request.query.get("hz", "20"))
    tr = rig.lap_trace(int(request.match_info["lap_id"]), hz)
    if tr is None:
        raise web.HTTPNotFound()
    return web.json_response(tr)


async def get_outline(request: web.Request) -> web.Response:
    return web.json_response(request.app[RIG_KEY].outline())


async def post_action(request: web.Request) -> web.Response:
    rig = request.app[RIG_KEY]
    rig.action(request.match_info["action"])
    return web.json_response({"ok": True})


async def post_bind(request: web.Request) -> web.Response:
    rig, hub = request.app[RIG_KEY], request.app[HUB_KEY]
    action = request.match_info["action"]
    if action not in ACTIONS:
        raise web.HTTPNotFound()
    rig.pending_bind = action
    await hub.broadcast({"type": "binding", "action": action})
    return web.json_response({"ok": True, "waiting_for": action})


async def cancel_bind(request: web.Request) -> web.Response:
    request.app[RIG_KEY].pending_bind = None
    return web.json_response({"ok": True})


async def get_track(request: web.Request) -> web.Response:
    rig = request.app[RIG_KEY]
    return web.json_response(rig.track.model.geometry() if rig.track else None)


async def get_corners(request: web.Request) -> web.Response:
    lap_id = request.query.get("lap_id")
    return web.json_response(request.app[RIG_KEY].corner_report(int(lap_id) if lap_id else None))


async def post_drill(request: web.Request) -> web.Response:
    rig = request.app[RIG_KEY]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    if "corner" in body:
        ok = rig.drill_corner(int(body["corner"]))
    elif "section" in body:
        ok = rig.drill_section(int(body["section"]))
    elif "chapter" in body:
        ok = rig.drill_chapter(int(body["chapter"]))
    elif "start_p" in body and "end_p" in body:
        ok = rig.start_drill(float(body["start_p"]), float(body["end_p"]), str(body.get("name") or "Section"))
    else:
        return web.json_response({"errors": ["Give a corner number or start_p/end_p"]}, status=400)
    if not ok:
        return web.json_response({"errors": ["No track loaded yet — start a session first"]}, status=409)
    return web.json_response({"ok": True})


async def delete_drill(request: web.Request) -> web.Response:
    request.app[RIG_KEY].stop_drill()
    return web.json_response({"ok": True})


async def window_op(request: web.Request) -> web.Response:
    which, op = request.match_info["which"], request.match_info["op"]
    if which not in ("dashboard", "analysis") or op not in ("close", "minimize"):
        raise web.HTTPNotFound()
    rig = request.app[RIG_KEY]
    (rig.on_close_window if op == "close" else rig.on_minimize_window)(which)
    return web.json_response({"ok": True})


async def shutdown(request: web.Request) -> web.Response:
    rig, hub = request.app[RIG_KEY], request.app[HUB_KEY]
    await hub.broadcast({"type": "shutdown"})
    asyncio.get_running_loop().call_later(0.2, rig.on_shutdown)
    return web.json_response({"ok": True})


async def get_monitors(request: web.Request) -> web.Response:
    from .monitors import list_monitors, pick_dashboard_monitor

    mons = list_monitors()
    pick = pick_dashboard_monitor(mons)
    return web.json_response(
        {"monitors": [m.to_dict() for m in mons], "auto": pick.to_dict() if pick else None}
    )


async def get_devices(request: web.Request) -> web.Response:
    inp = request.app.get(INPUT_KEY)
    return web.json_response(
        {
            "joystick": bool(inp and inp.joystick_available),
            "keyboard": bool(inp and inp.keyboard_available),
            "devices": inp.devices if inp else [],
        }
    )


ON_CONFIG_KEY: web.AppKey[Any] = web.AppKey("on_config")
INPUT_KEY: web.AppKey[Any] = web.AppKey("input")
TASK_KEY: web.AppKey[Any] = web.AppKey("rig_task")


# -- app --------------------------------------------------------------------


async def _rig_loop(app: web.Application) -> None:
    rig, hub = app[RIG_KEY], app[HUB_KEY]
    loop = asyncio.get_running_loop()
    next_poll = next_send = loop.time()
    while True:
        poll_dt = 1.0 / rig.config["rates"]["poll_hz"]
        send_dt = 1.0 / rig.config["rates"]["broadcast_hz"]
        now = loop.time()
        if now >= next_poll:
            try:
                rig.tick()
            except Exception:  # noqa: BLE001 - never let one bad frame kill the loop
                log.exception("Error while reading telemetry")
            next_poll = max(next_poll + poll_dt, now)
        if now >= next_send:
            await hub.broadcast(rig.live())
            next_send = max(next_send + send_dt, now)
        await asyncio.sleep(max(0.0, min(next_poll, next_send) - loop.time()))


async def _start_background(app: web.Application) -> None:
    app[HUB_KEY].bind_loop(asyncio.get_running_loop())
    app[TASK_KEY] = asyncio.create_task(_rig_loop(app))


async def _stop_background(app: web.Application) -> None:
    task = app.get(TASK_KEY)
    if task:
        task.cancel()
    for ws in list(app[HUB_KEY].clients):
        await ws.close()


def make_app(rig: Rig, hub: Hub, static_dir: Path | None = None, run_loop: bool = True) -> web.Application:
    app = web.Application()
    app[RIG_KEY] = rig
    app[HUB_KEY] = hub
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/config", get_config)
    app.router.add_put("/api/config", put_config)
    app.router.add_post("/api/config/reset", reset_config)
    app.router.add_get("/api/laps", get_laps)
    app.router.add_get("/api/laps/{lap_id}/trace", get_trace)
    app.router.add_get("/api/track/outline", get_outline)
    app.router.add_post("/api/action/{action}", post_action)
    app.router.add_post("/api/bind/{action}", post_bind)
    app.router.add_delete("/api/bind", cancel_bind)
    app.router.add_get("/api/input/devices", get_devices)
    app.router.add_get("/api/monitors", get_monitors)
    app.router.add_post("/api/window/{which}/{op}", window_op)
    app.router.add_post("/api/shutdown", shutdown)
    app.router.add_get("/api/track", get_track)
    app.router.add_get("/api/corners", get_corners)
    app.router.add_post("/api/drill", post_drill)
    app.router.add_delete("/api/drill", delete_drill)

    if static_dir is not None and (static_dir / "index.html").exists():
        index = static_dir / "index.html"

        async def spa(request: web.Request) -> web.StreamResponse:
            rel = request.match_info.get("path", "")
            target = (static_dir / rel).resolve()
            if rel and target.is_file() and static_dir.resolve() in target.parents:
                return web.FileResponse(target)
            return web.FileResponse(index)

        app.router.add_get("/", spa)
        app.router.add_get("/{path:.*}", spa)
    else:

        async def no_ui(request: web.Request) -> web.Response:
            return web.Response(
                text="Pitwall rig service is running, but the dashboard isn't built.\n"
                "Run `npm run build` in dashboard/ (or use `npm run dev` on port 5173).\n",
            )

        app.router.add_get("/", no_ui)

    if run_loop:
        app.on_startup.append(_start_background)
        app.on_cleanup.append(_stop_background)
    return app
