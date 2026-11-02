# Pitwall

A sim-racing coach and racing hub. A live dashboard runs on a vertical second
monitor while you drive; laps, lessons and guides follow later (see
[SPEC.md](SPEC.md) for the whole plan).

**Status: phase 0 (foundation).** Reads Assetto Corsa telemetry, records every
lap, and shows a configurable portrait dashboard. Coaching, corners, drills and
the cloud hub come in later phases.

```
rig/        Python service: reads the game, records laps, serves the dashboard
dashboard/  React + TypeScript dashboard (portrait 1080×1920, also works on a laptop)
scripts/    Windows helpers (setup, start, demo)
```

## Running it on the rig PC (Windows)

One-time setup — install [uv](https://docs.astral.sh/uv/) and Node.js, then run
`scripts\setup.bat`:

```bat
winget install astral-sh.uv
winget install OpenJS.NodeJS.LTS
scripts\setup.bat
```

Then, whenever you drive:

```bat
scripts\start.bat
```

This starts the service and opens the dashboard full-screen on the vertical
monitor. If it opens on the wrong screen, set the monitor's position under
**Settings → General → Vertical monitor** (the gear icon, or
`http://localhost:8765/#/settings`). By default the dashboard expects the
vertical monitor to sit to the right of a 1920-wide main screen.

Try it without the game: `scripts\demo.bat`.

### Wheel buttons

Settings → Controls → **Bind wheel / pedal**, then press the SF1000 button,
turn an encoder or pull a clutch paddle. Keyboard shortcuts work too (default
`Ctrl+Alt+→` / `Ctrl+Alt+←` to change page, `Ctrl+Alt+M` to mark a spot), even
while the game has focus.

### Recording a session (helps development)

```bat
scripts\start.bat --record "%USERPROFILE%\Desktop\spa.pwrec"
```

A `.pwrec` file is the raw telemetry of that session. It can be replayed through
the dashboard anywhere: `pitwall-rig run --game replay --replay spa.pwrec`.

## Where things are stored

Settings and laps live in `%APPDATA%\Pitwall` (`~/.pitwall` on Mac/Linux):
`config.json` (everything the Settings page edits) and `pitwall.sqlite` (every
lap with its full telemetry trace).

## Development

```bash
# rig service
cd rig
uv sync
uv run pytest
uv run pitwall-rig run --game demo --time-scale 4   # fake car, 4× speed

# dashboard (hot reload on :5173, talks to the rig service on :8765)
cd dashboard
npm install
npm run dev
npm test
```

On macOS/Linux there's no Assetto Corsa, so use `--game demo` or `--game replay`.

### How it fits together

- **Adapters** (`rig/src/pitwall_rig/adapters/`) turn a game's telemetry into a
  common `Frame`. Assetto Corsa reads the `acpmf_*` shared memory; `demo`
  simulates a car; `replay` plays a `.pwrec` recording. Each adapter declares
  *capabilities* so the dashboard hides what a game can't report.
- **LapRecorder** cuts the stream into laps (valid / cut / out-lap, sectors,
  a 60 Hz trace) and **Store** keeps them in SQLite.
- **Rig** ties it together: live delta to your best lap, theoretical best,
  driving mode vs analysis mode, wheel actions.
- **Server** pushes live frames over a WebSocket (30 Hz by default) and serves
  a small REST API for settings, laps and traces.
- **Dashboard** renders pages of widgets from `config.json`, so the layout is
  edited in the Settings page, not in code.
