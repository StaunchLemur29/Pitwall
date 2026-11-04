import json
import time
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from pitwall_rig.debrief import MODEL, AISettings, DebriefError, Debriefer, write_debrief
from pitwall_rig.rig import Rig


class FakeClaude:
    """Stands in for anthropic.Anthropic: records requests, returns a canned debrief."""

    def __init__(self, text="**Solid session.**\n\n**Focus next time:** brake 10 m later into Turn 1.",
                 stop="end_turn", good_key="sk-ant-good-key-1234"):
        self.calls = []
        self.text, self.stop, self.good_key = text, stop, good_key
        outer = self

        class Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return SimpleNamespace(stop_reason=outer.stop, model=kw["model"],
                                       content=[SimpleNamespace(type="text", text=outer.text)])

        class Models:
            def retrieve(self, model):
                if outer.key != outer.good_key:
                    req = httpx2.Request("GET", "https://api.anthropic.com/v1/models")
                    raise anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(401, request=req), body=None)
                return SimpleNamespace(id=model)

        self.beta = SimpleNamespace(messages=Messages())
        self.models = Models()
        self.key = None

    def factory(self, key):
        self.key = key
        return self


def drive(rig, clock, clean=4):
    for _ in range(60 * 60 * 8):
        clock.advance(1 / 60)
        rig.tick()
        s = rig.session
        if s and len(rig.store.valid_lap_ids(s.game, s.track_key, s.car)) >= clean:
            return


def test_session_summary_and_request(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    s0 = rig.session
    assert s0 is None or rig.session_summary("demo", "demo_gt3", "demo_circuit") is None
    drive(rig, clock)
    s = rig.session
    summary = rig.session_summary(s.game, s.car, s.track_key)
    assert summary["session"]["clean_laps"] >= 3 and summary["session"]["best"].count(":") == 1
    names = [c["corner"] for c in summary["corners_on_best_lap"]]
    assert "Hairpin 1" in names and summary["practice_sections"] and "DRS" in summary["car_has"]
    json.dumps(summary)  # it has to go over the wire

    fake = FakeClaude()
    body, model = write_debrief(summary, "sk-ant-good-key-1234", fake.factory)
    assert body.startswith("**Solid session.**") and model == MODEL
    (kw,) = fake.calls
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["output_config"] == {"effort": "medium"}
    assert "race engineer" in kw["system"] and "ADHD" in kw["system"]
    assert "Hairpin 1" in kw["messages"][0]["content"]

    with pytest.raises(DebriefError, match="declined"):
        write_debrief(summary, "k", FakeClaude(stop="refusal").factory)


def test_debrief_is_saved_and_written_automatically_once(demo, clock, config, store, tmp_path):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock)
    s = rig.session
    fake = FakeClaude()
    settings = AISettings(tmp_path)
    saved = []
    d = Debriefer(store, settings, rig.session_summary, on_saved=lambda: saved.append(1), client_factory=fake.factory)
    with pytest.raises(DebriefError, match="API key"):
        d.write_now(s.game, s.car, s.track_key)
    settings.api_key = "sk-ant-good-key-1234"
    # When the session ends (e.g. AC closed), it's written in the background.
    rig.on_session_end = d.session_ended
    demo.session = lambda: None
    clock.advance(1 / 60)
    rig.tick()
    for _ in range(50):
        if store.debriefs(s.game, s.car, s.track_key):
            break
        time.sleep(0.05)
    (db,) = store.debriefs(s.game, s.car, s.track_key)
    assert db["body"].startswith("**Solid session.**") and saved == [1]
    d.session_ended(s.game, s.car, s.track_key)  # already has one: not written again
    time.sleep(0.2)
    assert len(fake.calls) == 1
    settings.auto = False
    store._db.execute("DELETE FROM debriefs")
    d.session_ended(s.game, s.car, s.track_key)
    time.sleep(0.2)
    assert len(fake.calls) == 1  # auto off: only on request


def test_ai_settings_and_debrief_api(config, store, tmp_path):
    import asyncio  # noqa: F401

    from aiohttp.test_utils import TestClient, TestServer

    from pitwall_rig.adapters.demo import DemoAdapter
    from pitwall_rig.server import AI_KEY, Hub, make_app

    async def go():
        hub = Hub()
        clock_rig = Rig(DemoAdapter(seed=1, start_in_pit_s=0.0), store, config, emit=hub.emit)
        fake = FakeClaude()
        app = make_app(clock_rig, hub, static_dir=None)
        app[AI_KEY] = Debriefer(store, AISettings(tmp_path), clock_rig.session_summary, client_factory=fake.factory)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.post("/api/ai", json={"api_key": "sk-ant-wrong"})
            assert r.status == 400 and "wasn't accepted" in (await r.json())["error"]
            r = await client.post("/api/ai", json={"api_key": "sk-ant-good-key-1234", "auto": False})
            st = await r.json()
            assert st["configured"] and st["auto"] is False and st["key_hint"] == "sk-ant-…1234"
            assert "good-key" not in json.dumps(await (await client.get("/api/ai")).json())
            assert "sk-ant" not in json.dumps(await (await client.get("/api/config")).json())
            r = await client.post("/api/debrief", json={"game": "demo", "car": "demo_gt3", "track_key": "demo_circuit"})
            assert r.status == 400 and "clean laps" in (await r.json())["error"]  # nothing driven yet
        finally:
            await client.close()

    asyncio_run(go())


def asyncio_run(coro):
    import asyncio

    asyncio.new_event_loop().run_until_complete(coro)


def test_debriefs_reach_the_cloud(demo, clock, config, store, tmp_path):
    from pitwall_rig.cloud import CloudSync

    from .fake_supabase import FakeSupabase

    supa = FakeSupabase()
    try:
        store.add_debrief("ac", "car", "spa", 1_700_000_000.0, MODEL, "**Good session.**", 1_700_003_000.0)
        sync = CloudSync(store, tmp_path)
        sync.connect(supa.url, "anon", "me@example.com", "pw")
        sync.sync_once()
        (row,) = supa.rows("debriefs")
        assert row["body"] == "**Good session.**" and row["user_id"] == supa.user_id and "T" in row["session_start"]
        assert store.unsynced_debriefs() == []
    finally:
        supa.close()


def test_hub_function_uses_the_same_prompt_and_model() -> None:
    """The hub's debrief function (cloud/supabase/functions/debrief/prompt.ts) mirrors debrief.py."""
    import re
    from pathlib import Path

    from pitwall_rig.debrief import MIN_CLEAN_LAPS, MODEL, SYSTEM

    ts = (Path(__file__).resolve().parents[2] / "cloud" / "supabase" / "functions" / "debrief" / "prompt.ts").read_text(encoding="utf-8")
    assert f'export const MODEL = "{MODEL}";' in ts
    assert f"export const MIN_CLEAN_LAPS = {MIN_CLEAN_LAPS};" in ts
    m = re.search(r"export const SYSTEM = `(.*?)`;", ts, re.S)
    assert m and m.group(1) == SYSTEM
