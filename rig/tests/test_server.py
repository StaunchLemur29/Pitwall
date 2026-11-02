import asyncio

from aiohttp.test_utils import TestClient, TestServer

from pitwall_rig.adapters.demo import DemoAdapter
from pitwall_rig.input import InputEvent
from pitwall_rig.rig import Rig
from pitwall_rig.server import Hub, make_app


async def make_client(config, store, **demo_kw):
    hub = Hub()
    rig = Rig(DemoAdapter(seed=1, start_in_pit_s=0.0, **demo_kw), store, config, emit=hub.emit)
    client = TestClient(TestServer(make_app(rig, hub, static_dir=None)))
    await client.start_server()
    return client, rig


async def next_of(ws, kind, timeout=3.0):
    async def go():
        while True:
            msg = await ws.receive_json()
            if msg["type"] == kind:
                return msg
    return await asyncio.wait_for(go(), timeout)


async def test_websocket_streams_hello_and_frames(config, store):
    client, _ = await make_client(config, store)
    try:
        ws = await client.ws_connect("/ws")
        hello = await next_of(ws, "hello")
        assert hello["game"] == "demo"
        assert "electronics" in str(hello["config"]["layouts"])
        frame = await next_of(ws, "frame")
        assert frame["frame"]["status"] == "live"
        await ws.close()
    finally:
        await client.close()


async def test_config_api_validates(config, store):
    client, _ = await make_client(config, store)
    try:
        bad = await client.put("/api/config", json={"server": {"port": 1}})
        assert bad.status == 400
        assert "port" in (await bad.json())["errors"][0]
        good = await client.put("/api/config", json={"display": {"accent": "#123456"}})
        assert good.status == 200
        assert (await (await client.get("/api/config")).json())["display"]["accent"] == "#123456"
    finally:
        await client.close()


async def test_mark_corner_and_bind(config, store):
    client, rig = await make_client(config, store)
    try:
        ws = await client.ws_connect("/ws")
        await next_of(ws, "frame")
        await ws.send_json({"type": "action", "action": "mark_corner"})
        markers = await next_of(ws, "markers")
        assert len(markers["markers"]) == 1

        r = await client.post("/api/bind/next_page")
        assert r.status == 200
        rig.raw_input(InputEvent("button", "guid-1", "Thrustmaster TS-PC Racer", 7))
        bound = await next_of(ws, "bound")
        assert bound["binding"]["index"] == 7
        binds = config["bindings"]["next_page"]
        assert any(b.get("type") == "key" for b in binds)  # keyboard fallback kept
        assert any(b.get("index") == 7 for b in binds)
        await ws.close()
    finally:
        await client.close()


async def test_laps_are_recorded_and_served(config, store):
    client, rig = await make_client(config, store, time_scale=40.0)
    try:
        ws = await client.ws_connect("/ws")
        lap = await next_of(ws, "lap", timeout=10)
        assert lap["lap"]["lap_time_ms"] > 0
        laps = await (await client.get("/api/laps?current=1")).json()
        assert laps and laps[0]["id"] == lap["lap"]["id"]
        trace = await (await client.get(f"/api/laps/{laps[0]['id']}/trace?hz=10")).json()
        assert len(trace["t"]) > 50  # sparse: demo runs at 40x speed
        outline = await (await client.get("/api/track/outline")).json()
        assert len(outline["points"]) > 50
        await ws.close()
    finally:
        await client.close()
