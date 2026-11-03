# Pitwall

A sim-racing coach and racing hub. A live dashboard runs on a vertical second
monitor while you drive; laps, lessons and guides follow later (see
[SPEC.md](SPEC.md) for the whole plan).

**Status: phases 0–1 (foundation + track learning).** Reads Assetto Corsa
telemetry and records every lap. Reads each track's layout from the game files,
with corners, their severity, practice sections, and Nordschleife chapters.
While you drive it shows the next corner, a brake countdown that adjusts to
your speed, and the road ahead with your left/right position. Practice drills
use one-button rewind (CSP Time Shift). Lap analysis runs on the vertical
screen and in a detailed window on the main screen, for any car + track you've
driven. Coaching, the in-game CSP app and the cloud hub come next.

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

This rebuilds the dashboard if needed, starts the service, and opens the
dashboard full-screen on the vertical monitor (found automatically; Chrome
preferred, Edge as a fallback). If it picks the wrong screen, choose one under
**Settings → General** (the gear icon, or `http://localhost:8765/#/settings`).

- **Analysis ↗** (top bar) opens the full lap analysis on your main screen.
- The **–** button minimises the dashboard; **⏻** stops Pitwall.
- Press **L** on the dashboard for the lag meter and **Record performance**
  (saves a report to `%APPDATA%\Pitwall\perf`).

Try it without the game: `scripts\demo.bat`.

### Wheel buttons

Settings → Controls → **Set up recommended controls** walks you through binding
rewind, drills, pages and analysis to wheel buttons. Or bind any single action
with **Bind wheel / pedal**: press the SF1000 button, turn an encoder or pull a
clutch paddle. Keyboard shortcuts work too (default `Ctrl+Alt+→` / `Ctrl+Alt+←`
to change page, `Ctrl+Alt+M` to mark a spot), even while the game has focus.

### Rewind and drills (CSP Time Shift)

Bind the same key in CSP's **Time Shift** app as **Settings → Controls → Time
Shift rewind key** (default `Insert`). The **Rewind** button then rewinds while
held. During a drill, one press rewinds to a run-up before the section
(**Drill run-up**, 4 s by default). Time Shift only works offline, in
single-car practice.

### Recording a session (helps development)

```bat
scripts\start.bat --record "%USERPROFILE%\Desktop\spa.pwrec"
```

A `.pwrec` file is the raw telemetry of that session. It can be replayed through
the dashboard anywhere: `pitwall-rig run --replay spa.pwrec`.

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
- **Tracks** (`rig/src/pitwall_rig/tracks/`) read the layout from the game's
  files (`ai/fast_lane.ai`, `data/sections.ini`): centre line, edges, corners,
  practice sections; track packs (`packs/`) add chapters.
- **Analysis** (`analysis.py`) breaks each lap down corner by corner and
  compares it with another lap.
- **Rig** ties it together: live delta to your best lap, theoretical best,
  next corner and brake point, drills and rewind, driving mode vs analysis
  mode, wheel actions. It runs on its own precisely-timed thread.
- **Server** pushes live frames over a WebSocket (60 Hz) and serves a small
  REST API for settings, laps, traces, corners and drills.
- **Dashboard** renders pages of widgets from `config.json`, so the layout is
  edited in the Settings page, not in code.
