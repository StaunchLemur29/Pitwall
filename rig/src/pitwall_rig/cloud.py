"""Cloud sync: your laps on the hub (Supabase), so the MacBook can see them
while the rig PC is off.

The rig signs in to your Supabase project as you (email + password once; only
the refresh token is kept, in ``cloud.json`` next to the database, never in the
settings the dashboard can read). A background thread then uploads laps that
haven't been uploaded yet: the lap, its corner-by-corner analysis and its
telemetry reduced to ~20 samples a second, plus the track layout and the car's
profile. Offline? It retries later; nothing is lost.

Talks to Supabase's plain HTTP APIs (GoTrue auth + PostgREST), so there's no
extra dependency.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .reference import downsample
from .storage import Store

log = logging.getLogger(__name__)

TRACE_HZ = 20
BATCH = 10  # laps per upload request
# Bump when uploads gain something the hub needs from laps already uploaded:
# every lap then goes up once more on the next start.
UPLOAD_VERSION = 4  # 2: track-width advice and battery & DRS with each lap; 3: optimal racing line; 4: the lap review


class CloudError(Exception):
    pass


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class Supabase:
    """The few Supabase calls Pitwall needs."""

    def __init__(self, url: str, anon_key: str, timeout: float = 15.0) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.timeout = timeout
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.user_id: str | None = None
        self._expires_at = 0.0

    # -- auth -----------------------------------------------------------------

    def _auth(self, grant: str, body: dict[str, Any]) -> None:
        data = self._request("POST", f"/auth/v1/token?grant_type={grant}", body, auth=False)
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.user_id = data["user"]["id"]
        self._expires_at = time.time() + float(data.get("expires_in", 3600)) - 60

    def sign_in(self, email: str, password: str) -> None:
        self._auth("password", {"email": email, "password": password})

    def ensure_token(self) -> None:
        if self.access_token and time.time() < self._expires_at:
            return
        if not self.refresh_token:
            raise CloudError("Not signed in")
        self._auth("refresh_token", {"refresh_token": self.refresh_token})

    # -- data -----------------------------------------------------------------

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
        if not rows:
            return
        self.ensure_token()
        q = urllib.parse.urlencode({"on_conflict": on_conflict})
        self._request("POST", f"/rest/v1/{table}?{q}", rows,
                      prefer="resolution=merge-duplicates,return=minimal")

    def _request(self, method: str, path: str, body: Any, auth: bool = True, prefer: str | None = None) -> Any:
        headers = {"apikey": self.anon_key, "Content-Type": "application/json"}
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            try:
                msg = json.loads(detail)
                detail = msg.get("error_description") or msg.get("msg") or msg.get("message") or detail
            except ValueError:
                pass
            raise CloudError(f"{e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise CloudError(f"Can't reach Supabase ({e})") from e
        return json.loads(raw) if raw else None


class CloudSync:
    """Background uploader. ``status()`` says how it's doing, for Settings."""

    def __init__(
        self,
        store: Store,
        data_dir: Path,
        geometry_for: Callable[[str, str, str], dict[str, Any] | None] = lambda g, c, t: None,
        extras_for: Callable[[int], dict[str, Any] | None] = lambda lap_id: None,
        every_s: float = 20.0,
    ) -> None:
        self.store = store
        self.path = data_dir / "cloud.json"
        self.geometry_for = geometry_for
        self.extras_for = extras_for  # the PC's full analysis of a lap (advice, battery & DRS)
        self.every_s = every_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.client: Supabase | None = None
        self.settings: dict[str, Any] = {}
        self.state = "off"  # off | idle | syncing | error
        self.error: str | None = None
        self.last_sync: float | None = None
        self._tracks_done: set[tuple[str, str]] = set()
        self._cars_done: set[tuple[str, str]] = set()
        self._load()

    # -- settings ---------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self.settings = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError:
            return
        s = self.settings
        if s.get("url") and s.get("anon_key") and s.get("refresh_token"):
            self.client = Supabase(s["url"], s["anon_key"])
            self.client.refresh_token = s["refresh_token"]
            self.client.user_id = s.get("user_id")
            self.state = "idle"
            if s.get("upload_version", 1) < UPLOAD_VERSION:
                log.info("Cloud: uploading every lap again with the fuller analysis")
                self.store.mark_all_unsynced()
                s["upload_version"] = UPLOAD_VERSION
                self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def connect(self, url: str, anon_key: str, email: str, password: str) -> None:
        """Sign in once; keeps the refresh token, not the password."""
        client = Supabase(url, anon_key)
        client.sign_in(email, password)
        with self._lock:
            self.client = client
            self.settings = {
                "url": client.url,
                "anon_key": anon_key,
                "email": email,
                "user_id": client.user_id,
                "refresh_token": client.refresh_token,
                "rig_id": self.settings.get("rig_id") or uuid.uuid4().hex[:12],
                "upload_version": UPLOAD_VERSION,
            }
            self._save()
            self.state, self.error = "idle", None
            self._tracks_done.clear()
            self._cars_done.clear()
        self.sync_soon()

    def disconnect(self) -> None:
        with self._lock:
            self.client = None
            rig_id = self.settings.get("rig_id")
            self.settings = {"rig_id": rig_id} if rig_id else {}
            self._save()
            self.state, self.error = "off", None

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.client is not None,
            "state": self.state,
            "error": self.error,
            "email": self.settings.get("email"),
            "url": self.settings.get("url"),
            "last_sync": self.last_sync,
            "pending": self.store.unsynced_count(),
        }

    # -- the work -----------------------------------------------------------------

    def sync_once(self) -> int:
        """Upload everything not yet uploaded. Returns how many laps went up."""
        with self._lock:
            client = self.client
            rig_id = self.settings.get("rig_id", "rig")
        if client is None:
            return 0
        sent = 0
        self.state = "syncing"
        try:
            while True:
                ids = self.store.unsynced_lap_ids(BATCH)
                if not ids:
                    break
                laps = [self._lap_row(i, rig_id) for i in ids]
                laps = [r for r in laps if r is not None]
                self._send_context(client, laps)
                client.upsert("laps", laps, "user_id,rig_id,local_id")
                self.store.mark_synced(ids, time.time())
                sent += len(ids)
            self._send_debriefs(client)
            if client.refresh_token != self.settings.get("refresh_token"):
                with self._lock:  # tokens rotate on refresh: keep the new one
                    self.settings["refresh_token"] = client.refresh_token
                    self._save()
            self.state, self.error, self.last_sync = "idle", None, time.time()
        except CloudError as e:
            msg = str(e)
            if ("column" in msg and "schema cache" in msg) or "no unique or exclusion constraint" in msg:
                msg = ("Your Supabase tables are out of date: run 'Apply database schema' from GitHub → Actions "
                       "(or paste cloud/schema.sql into the SQL Editor).")
            self.state, self.error = "error", msg
            log.warning("Cloud sync: %s", e)
        return sent

    def _lap_row(self, lap_id: int, rig_id: str) -> dict[str, Any] | None:
        info = self.store.lap(lap_id)
        if info is None:
            return None
        trace = self.store.trace(lap_id)
        try:
            extras = self.extras_for(lap_id) or {}
        except Exception:  # noqa: BLE001 - upload the plain lap rather than nothing
            log.exception("Couldn't analyse lap %s for upload", lap_id)
            extras = {}
        return {
            "user_id": self.client.user_id if self.client else None,
            "rig_id": rig_id,
            "local_id": lap_id,
            "game": info["game"],
            "car": info["car"],
            "track_key": info["track_key"],
            "lap_number": info["lap_number"],
            "lap_time_ms": info["lap_time_ms"],
            "valid": info["valid"],
            "out_lap": info["out_lap"],
            "rewound": info.get("rewound", False),
            "started_at": _iso(info["started_at"]),
            "sector_ms": info["sector_ms"],
            "corners": extras.get("corners") or self.store.latest_lap_corners(lap_id),
            "systems": extras.get("systems"),
            "time_to_beat": extras.get("time_to_beat"),
            "review": extras.get("review"),
            "trace": downsample(trace, TRACE_HZ) if trace else None,
        }

    def _send_debriefs(self, client: Supabase) -> None:
        while True:
            rows = self.store.unsynced_debriefs(20)
            if not rows:
                return
            client.upsert("debriefs", [{
                "user_id": client.user_id, "game": r["game"], "car": r["car"], "track_key": r["track_key"],
                "session_start": _iso(r["session_start"]), "body": r["body"], "model": r["model"],
                "created_at": _iso(r["created_at"]),
            } for r in rows], "user_id,game,car,track_key,session_start")
            self.store.mark_debriefs_synced([r["id"] for r in rows], time.time())

    def _send_context(self, client: Supabase, laps: list[dict[str, Any]]) -> None:
        """Track layouts and car profiles the hub needs for these laps (once per run)."""
        tracks, cars = [], []
        for r in laps:
            tk = (r["game"], r["track_key"])
            if tk not in self._tracks_done:
                geo = self.geometry_for(r["game"], r["car"], r["track_key"])
                if geo:
                    tracks.append({"user_id": client.user_id, "game": tk[0], "track_key": tk[1], "geometry": geo})
                self._tracks_done.add(tk)
            ck = (r["game"], r["car"])
            if ck not in self._cars_done:
                prof = self.store.car_profile(*ck)
                if prof:
                    cars.append({"user_id": client.user_id, "game": ck[0], "car": ck[1], "profile": prof})
                self._cars_done.add(ck)
        client.upsert("tracks", tracks, "user_id,game,track_key")
        client.upsert("car_profiles", cars, "user_id,game,car")

    # -- background thread ------------------------------------------------------------

    def sync_soon(self) -> None:
        self._wake.set()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pitwall-cloud", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        backoff = self.every_s
        while not self._stop.is_set():
            self._wake.wait(backoff)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.sync_once()
            except Exception as e:  # noqa: BLE001 - never let the sync thread die
                log.exception("Cloud sync failed")
                self.state, self.error = "error", f"Unexpected problem: {e}"
            backoff = self.every_s if self.state != "error" else min(300.0, backoff * 2)
