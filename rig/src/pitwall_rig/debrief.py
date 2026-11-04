"""AI debrief: a short race-engineer write-up of a session, by Claude.

Runs on the rig PC with your Anthropic API key (kept in ``ai.json`` next to
the database, never in the settings the dashboard can read). After a session
with a few clean laps, Pitwall sends Claude a compact summary of the session
(lap times, the best lap's corners against your best ever, consistency,
battery & DRS notes, practice sections) and stores the debrief that comes
back; the cloud sync takes it to the hub.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MIN_CLEAN_LAPS = 3  # fewer than this and there's not enough to say

SYSTEM = """You are the race engineer for one sim racer, writing a short debrief after their session.

Who they are: self-taught, about 600 hours in Assetto Corsa, mostly hotlaps; quick, still building technique (braking, use of track width, electronics, setups). They have ADHD: lead with the single most useful point, keep every line short and concrete, and use plain words.

Voice: a real race engineer on the radio: direct, specific, calm, encouraging without fuss. Name corners and use the numbers in the data (metres, km/h, tenths of a second). Metric units, New Zealand English.

Work only from the data you're given. Where it's thin (few clean laps, no comparison), say what more driving would show instead of guessing.

Reply in Markdown with exactly these parts:
**<one-sentence headline: how the session went, with the key number>**

**Focus next time:** the one change worth the most time: where, what to do differently, and a concrete target (a brake point, a minimum speed, a line, or the corner's time to beat).

**Also:** up to two short bullets.

**Going well:** one bullet.

**Drill:** one practice section to drill, with its time to beat as the target (from time_to_beat when given).

Stay under 170 words."""


class DebriefError(Exception):
    pass


class AISettings:
    """Your API key and whether debriefs are written automatically (``ai.json``)."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "ai.json"
        self.api_key: str | None = None
        self.auto = True
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.api_key = d.get("api_key") or None
                self.auto = bool(d.get("auto", True))
            except ValueError:
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"api_key": self.api_key, "auto": self.auto}, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def status(self) -> dict[str, Any]:
        k = self.api_key
        return {"configured": bool(k), "key_hint": f"{k[:7]}…{k[-4:]}" if k and len(k) > 12 else None,
                "auto": self.auto, "model": MODEL}


def anthropic_client(api_key: str) -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=2)


def check_key(api_key: str, client_factory: Callable[[str], Any] = anthropic_client) -> None:
    """A free call that fails if the key is wrong."""
    import anthropic

    try:
        client_factory(api_key).models.retrieve(MODEL)
    except anthropic.AuthenticationError as e:
        raise DebriefError("That API key wasn't accepted.") from e
    except anthropic.PermissionDeniedError as e:
        raise DebriefError("That API key doesn't have access to the model.") from e
    except anthropic.APIConnectionError as e:
        raise DebriefError("Couldn't reach Anthropic (no internet?).") from e


def write_debrief(summary: dict[str, Any], api_key: str,
                  client_factory: Callable[[str], Any] = anthropic_client) -> tuple[str, str]:
    """Ask Claude for the debrief. Returns (markdown text, model that wrote it)."""
    import anthropic

    client = client_factory(api_key)
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            # If a safety check declines the request, the API retries it on the
            # model Anthropic recommends for that case, in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium"},
            system=SYSTEM,
            messages=[{"role": "user", "content": "Session data (JSON):\n" + json.dumps(summary, indent=1)}],
        )
    except anthropic.AuthenticationError as e:
        raise DebriefError("Your API key wasn't accepted: check it in Settings → AI.") from e
    except anthropic.RateLimitError as e:
        raise DebriefError("Anthropic says slow down (rate limit). It'll try again next session.") from e
    except anthropic.BadRequestError as e:
        msg = str(getattr(e, "message", e))
        if "credit" in msg.lower() or "billing" in msg.lower():
            raise DebriefError("Your Anthropic account is out of credit.") from e
        raise DebriefError(f"Anthropic rejected the request: {msg}") from e
    except anthropic.APIStatusError as e:
        raise DebriefError(f"Anthropic had a problem ({e.status_code}). Try again later.") from e
    except anthropic.APIConnectionError as e:
        raise DebriefError("Couldn't reach Anthropic (no internet?).") from e
    if resp.stop_reason == "refusal":
        raise DebriefError("Claude declined to write this one.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise DebriefError("Claude sent back an empty debrief.")
    return text, resp.model


class Debriefer:
    """Writes debriefs: on request, or automatically when a session ends (in the background)."""

    def __init__(
        self,
        store: Any,
        settings: AISettings,
        summary_for: Callable[[str, str, str], dict[str, Any] | None],
        on_saved: Callable[[], None] = lambda: None,
        client_factory: Callable[[str], Any] = anthropic_client,
    ) -> None:
        self.store = store
        self.settings = settings
        self.summary_for = summary_for
        self.on_saved = on_saved
        self.client_factory = client_factory
        self.state = "idle"  # idle | writing | error
        self.error: str | None = None
        self._lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        return {**self.settings.status(), "state": self.state, "error": self.error}

    def write_now(self, game: str, car: str, track_key: str) -> dict[str, Any]:
        """Write (or rewrite) the debrief for this car + track's latest session."""
        if not self.settings.api_key:
            raise DebriefError("Add your Anthropic API key in Settings → AI first.")
        summary = self.summary_for(game, car, track_key)
        if summary is None:
            raise DebriefError(f"Drive at least {MIN_CLEAN_LAPS} clean laps first.")
        with self._lock:
            self.state, self.error = "writing", None
            try:
                body, model = write_debrief(summary, self.settings.api_key, self.client_factory)
            except DebriefError as e:
                self.state, self.error = "error", str(e)
                raise
            start = summary["session"]["start"]
            now = time.time()
            self.store.add_debrief(game, car, track_key, start, model, body, now)
            self.state = "idle"
        log.info("Debrief written for %s on %s", car, track_key)
        self.on_saved()
        return {"game": game, "car": car, "track_key": track_key, "session_start": start,
                "created_at": now, "model": model, "body": body}

    def session_ended(self, game: str, car: str, track_key: str) -> None:
        """Called when a session ends; writes a debrief in the background if it's worth one."""
        if not (self.settings.api_key and self.settings.auto):
            return
        summary = self.summary_for(game, car, track_key)
        if summary is None or self.store.has_debrief(game, car, track_key, summary["session"]["start"]):
            return

        def run() -> None:
            try:
                self.write_now(game, car, track_key)
            except DebriefError as e:
                log.warning("Debrief: %s", e)
            except Exception:
                log.exception("Debrief failed")

        threading.Thread(target=run, name="pitwall-debrief", daemon=True).start()
