# Pitwall — Spec

A personal sim-racing coach and racing hub. A live dashboard runs on a vertical second monitor while driving; a cloud-synced hub (on a MacBook or anywhere) holds history, lessons, guides and analysis.

Status: design agreed, not yet built. Owner: single user (for now).

---

## 1. Goals

1. **Improve an already-quick, self-taught driver** (~600 h, mostly hotlaps/practice/AI races) — find the gaps in fundamentals they don't know they have, without re-teaching what they already do well.
2. **Learn tracks fast**, including long ones (Nordschleife) section by section, with repeatable drills.
3. **Learn cars**, especially the large modded collection (RSS open-wheel, GT, road, etc.).
4. **Teach car electronics and setup** progressively (BB/ABS/TC first), without overload.
5. **Build online racing confidence** through racecraft and etiquette teaching.
6. Be a clean, portfolio-worthy project (private repo first, public later).

### Driver context that shapes the design
- ADHD: one focus per session, bite-sized lessons, minimal clutter, no nagging, optional gamification.
- Drives first-person with the car's own dash visible; the in-game HUD already shows sectors, tyres, radar and a reference delta bar. **Pitwall must not duplicate these.**
- Hardware: Thrustmaster TS-PC base, SF1000 rim (spare buttons/dials/one rear clutch paddle available) and a plain rim (no spare buttons → keyboard fallback). Second monitor: LG 24G411A-B, 1920×1080 used in portrait (1080×1920), not touch, same PC as the game.

### Non-goals (for now)
- Duplicating the in-game HUD (speed, gear, radar, sector times, tyre widget).
- Multi-user / social features (structure for them, don't build them).
- Full garage-setup coaching before the electronics stage is learned.

---

## 2. Games

| Game | Priority | Telemetry | Section retry | Notes |
|---|---|---|---|---|
| Assetto Corsa (CM + CSP + Pure, heavily modded) | **Primary** | Shared memory `acpmf_physics/graphics/static` | CSP Lua companion app: rewind mod (TBC) or `physics.setCarPosition` teleport (offline only) | Exposes BB, ABS, TC, tyre pressures |
| Assetto Corsa EVO | Casual, later | Shared memory `acevo_pmf_*` (undocumented, changes between builds — patch 0.6 renamed segments) | None (lap-pass attempts only) | BB/ABS/TC levels & pressures unconfirmed; version-check the layout |
| BeamNG.drive | Later | OutGauge / MotionSim UDP | Vehicle Lua `setPositionRotation` | No third-party reference data |
| iRacing | Future (if bought) | iRacing SDK memory map (60 Hz) + .ibt | Simulated "Active Reset" keybind (solo practice only) | Garage61 API for reference laps |

**Rule:** each game is an *adapter* that declares capabilities (e.g. `canRetrySection`, `reportsBrakeBias`). UI features appear only when the active game supports them.

---

## 3. Architecture

```
┌──────────── Rig PC (Windows) ────────────┐        ┌──── Cloud ────┐
│ Game ──shared mem/UDP──► Rig Service (Py)│        │ Supabase      │
│   ▲  CSP Lua companion ◄─socket─┘   │    │──sync─►│  Postgres     │
│   │  (rewind/teleport, markers)     │    │        │  Storage      │
│ SF1000 (DirectInput, background) ──►│    │        │  Auth (1 user)│
│ Windows media session (music) ◄────►│    │        │  Edge fns (AI)│
│ Local SQLite + full 60 Hz traces    │    │        └──────┬────────┘
│        │ WebSocket 30–60 Hz         │    │               │
│        ▼                                 │        ┌──────▼────────┐
│ Dashboard (browser, fullscreen, 1080×1920)│        │ Hub (Vercel)  │
└──────────────────────────────────────────┘        │ MacBook/any   │
                                                    └───────────────┘
```

- **Rig Service (Python)**: game adapters, lap/section detection, corner detection, live rules coach, TTS output, wheel input (DirectInput background, non-exclusive), music control via Windows `GlobalSystemMediaTransportControls` (works with Spotify and Apple Music), local SQLite, sync uploader, demo/replay source.
- **Dashboard (TypeScript/React)**: the live portrait view, served locally; also openable on the LAN (e.g. the Mac as a second live screen when the PC is on).
- **Hub (TypeScript/React, hosted on Vercel)**: history, progress, comparison, guides, lessons, quizzes, AI debrief; works when the rig PC is off.
- **Cloud (Supabase)**: lap summaries, corner stats, progress, lesson state, downsampled traces (10–20 Hz). Full-res traces stay on the PC. Data model keeps a `user_id` everywhere so sharing/public profile can come later.
- **AI**: Claude, called server-side only (Supabase edge function / rig service) so the API key is never in the browser. All AI features toggleable; everything else works without a key.
- **Config without code**: layouts, widgets, thresholds, button mappings, verbosity, toggles — all editable in a settings UI (backed by a config file).
- **Demo mode**: replay recorded sessions through the same pipeline (dev, Mac, portfolio).

---

## 4. Modes

The dashboard switches mode automatically from game state:

- **Driving** (on track): glanceable, high contrast.
- **Analysis** (pits/menus/replay): last-stint summary, corner breakdown, debrief, start a drill.
- **Pre-race** (race session before start): briefing (see §9).

### Driving layout (default, 1080×1920, rearrangeable)

```
┌──────────────────────┐
│  NEXT CORNER CARD    │  name/№, direction, gear, brake marker
├──────────────────────┤
│  MINI MAP + next 2   │  active section highlighted
├──────────────────────┤
│  DRILL / FOCUS       │  "Focus: trail brake T1 · 3/5 clean"
│  + section delta     │
├──────────────────────┤
│  COACH TIP (1 line)  │  fades
├──────────────────────┤
│  BB / ABS / TC → sugg│
├──────────────────────┤
│  session timer · ♪   │
└──────────────────────┘
```

---

## 5. Input mapping

- SF1000: 3–4 buttons/dials + optional rear clutch paddle. Default actions: next page, play/pause & skip, repeat last tip, retry section (rewind/teleport), mark corner.
- Plain rim: keyboard shortcuts fallback.
- All mappings set in the settings UI ("press the button to bind").

---

## 6. Coaching

### Delivery
- Audio + visual. Default **max one tip per lap**, delivered on a straight, never mid-corner.
- Verbosity: silent / key only / chatty. **Quiet mode** silences audio in the corner being worked on.
- **One focus per session** ("today: brake bias") — the coach ignores everything else.

### Live rules engine (offline, free)
Examples: lock-ups → BB/ABS advice; exit wheelspin → TC/throttle advice; braking earlier than reference; coasting; stepped brake release; throttle hesitation; not using track width; wrong gear; lifting instead of light braking; not adjusting BB/TC as fuel/tyres change.

### Blind-spot scan
Order: **telemetry scan first, then the quiz.**
1. **Scan** — runs silently over the first sessions. Only surfaces fundamentals the telemetry shows being missed; each becomes a 2-min lesson + drill.
2. **Quiz** — offered once the scan has enough data: a one-off ~5-min **knowledge quiz** (on the Mac) for things telemetry can't reveal (flags, pressures, ABS/TC theory, track limits). It skips topics the scan already shows you handle, so it stays short.

### AI debrief (Claude)
Post-session race-engineer debrief: explains *why*, answers follow-up questions, teaches theory in context. Also generates the **AI "time to beat"**: a realistic per-corner stretch target based on consistency and where time is lost.

### Electronics & setup (progressive unlock tree)
1. BB, ABS, TC (+ engine map where present) — explanation + telemetry-based suggestion.
2. Tyre pressures (AC reports them live).
3. Deeper garage setup (springs, dampers, aero…) — only once earlier stages are mastered.

---

## 7. Reference laps & targets

Selectable / combinable:
- Own best lap (**default delta**)
- Theoretical best (best sectors)
- AI time to beat (**default in drills**)
- Online lap times as *targets* (via RSR / SRS / CM leaderboards — times only, no telemetry), labelled elite / average / your level
- Imported laps (own older laps, friend's file, exports from paid tools where permitted)
- AC AI line (for line drawing on the map)
- **Optimal racing line** (done, 2026-11-03): worked out from the track's edges in AC's `fast_lane.ai` as the *minimum-curvature* line (the smoothest path the edges allow, car centre kept 1.2 m inside each edge; kerbs not assumed usable). Geometric only, so it's a placement guide, not a lap-time prediction. Shown dotted on each corner's close-up and as a toggle on the lap map; turn-in/apex/exit distance from it per corner; the track-width tips measure against it (the outside-inside-outside rule of thumb stays as the fallback for tracks without edges). Worked out once per track in the background (a few seconds on the Nordschleife).
- **Optimal run** (done, 2026-11-03, owner request: "optimal brake, throttle etc."): the optimal line driven at the car's grip, learnt from your 8 fastest valid laps of that car on that track (lateral, braking and accelerating g at each speed, high percentiles; a v² term for aero). Point-mass lap sim with a friction ellipse. Gives speed, brake % and throttle % along the lap (pedals are estimates: needed ÷ the most the car managed), per-corner numbers (braking point, slowest point, full throttle, exit speed, time), "Against the optimal run" notes, and a lap-time estimate. Shown as a third, dotted series in the corner charts and an "Optimal run" table column. Only as good as the laps it learnt from. The hub gets the per-corner numbers and notes; the charts' optimal curves are rig-only for now. Later: a minimum-time line (bending the line to the car instead of minimum curvature).
- **Famous times**: real records and well-known laps per track pack, **compared within car class**; where official timing with sector splits exists (e.g. Nürburgring 24h, Spa), use it as a sector-level reference
- Future: Garage61 full-telemetry references (iRacing)

Known gap: no free source of other drivers' telemetry exists for AC/EVO.

---

## 8. Track learning

- **Auto corner detection** from lap/AI-line curvature → numbered corners on any (modded) track from day one.
- **Track packs** (JSON/Markdown) override with real names, reference points, common mistakes, video timestamps, famous times; matched by track folder + layout. Corners can be renamed/merged in the hub.
- **Next-corner card + map** (driving mode).
- **Corner progress**: green when mastered, red when inconsistent.
- **Audio pace notes** (rally-style), auto-fade per corner once consistent.
- **Drill mode**: picks the weakest corner and focuses coaching there.

### Section practice
- Pick a section: one corner, a dragged range on the map, or a named section from a pack.
- Section gets its own timer, delta, all-time best; every pass is an attempt.
- **Retry** (AC + CSP, offline): rewind mod if it can be triggered (keeps momentum), else teleport slightly before section start. **Retry is button-only by default**; auto-retry-after-mistake optional per drill.
- **Pass targets** (e.g. 3 clean attempts within 0.3 s of best).
- End-of-drill summary ("12 attempts, best −0.4 s, consistency ↑").

### Guides (structured, not just a clickable map)
Each section/corner guide is a short chaptered lesson:
1. Why it matters / what's tricky
2. How to drive it (reference points, line, gear, where time can be sacrificed)
3. Your data there
4. Drive-along lap with pace notes
5. Drill with pass target
6. Recap → unlocks next chapter

Nordschleife ≈ 8–10 chapters, one per session. Clickable map, line-vs-reference scrubber, onboard video timestamps and quiz cards support the guides.

**Starter packs:** Nordschleife, Spa, Hampton Downs; then the major circuits.

---

## 9. Car learning

- **Car profile card**: drivetrain, power/weight, aero dependence, electronics available + ranges, category. From readable data files where possible; otherwise **learned from telemetry** (real braking g, top speed, cornering g, rotation tendency) — many RSS/mod cars are encrypted.
- **Shakedown routine** (3–5 laps, guided tasks: find braking limit, TC needs, where aero comes in) → AI summary.
- **Transfer tips** relative to known cars.
- **Per-car and car×track progress.**

---

## 10. Racecraft & online confidence

(No radar/gaps — the in-game HUD has them.)
1. Lesson cards: overtaking, defending, blue flags, rejoining, starts, lap 1.
2. **Pre-race briefing**: track-specific danger corners, 3 rules to remember, safe passing spots.
3. **Post-race incident review** from telemetry (contact, offs, unsafe rejoins) with what to do differently.
4. Scenario drills vs AI ("follow 3 laps no contact, then pass clean").

Assists/realism guidance (what servers expect) lives inside the guides.

---

## 11. Lessons & content

- **Curated library** (Markdown, written once, reviewed): fundamentals, setup unlock tree, racecraft.
- **AI follow-ups** for deeper questions.
- Format: 1–3 min cards, never walls of text.
- Gamification (streaks, corner greens, drills passed, car/track XP): light, on by default, can be turned off.

### Voice
Natural, informative race-engineer voice (not generic/obviously-AI). Pace notes rally-style. High-quality TTS **generated once and cached** for pace notes and lessons; Windows local TTS for instant live tips. 2–3 candidate voices to be auditioned.

---

## 12. Settings tools (for new users; owner already set up)

Standalone tools, recommended during onboarding:
1. FOV calculator (monitor size/aspect/distance → FOV, seat/camera position)
2. Wheel/FFB: Thrustmaster Control Panel, AC FFB, CSP FFB tweaks; per-car steering lock & FFB
3. Controls: deadzones, curves, brake gamma, SF1000 bindings
   - Hardware walkthroughs per wheel rim / wheelbase / pedal set (e.g. Thrustmaster TS-PC + SF1000), recommended in-game and driver settings
4. Assists & realism (in guides)
5. Graphics/performance (CSP + Pure)

Reads AC `cfg/*.ini`; writes only after one-click confirm, with automatic backup, only while AC is closed.

---

## 13. Extras

- **Music**: now playing + play/pause/skip via Windows media session (Spotify, Apple Music) and wheel buttons.
- **Session timer**: compact — race time/laps remaining when relevant, rig-session timer, optional break reminder.
- **Discord** (low priority): Rich Presence status ("Nordschleife · 911 GT3 · PB 7:12.4 · learning Fuchsröhre") via local IPC.
- **Car systems & hardware** (from docs/research/car-and-hardware.md):
  - done: car systems strip (DRS, battery, deploy, engine brake), battery & DRS along the lap in analysis ("ran out of battery", "DRS available but not opened"), per-car profile of which systems a car has (used by the UI now, by coaching later)
  - FFB clipping meter from AC's `finalFF` (per lap, per car, with a gain suggestion) for the TS-PC
  - T-LCM pedal check: peak brake per stop vs 100 %, consistency, release smoothness; calibration advice
- **SF1000 wheel screen** (big feature): Pitwall drives the SF1000's built-in display with its own data, so key info sits on the wheel in your eyeline.
  - Two possible routes:
    - **USB ("Native" mode)**: the wheel's screen and LEDs are driven through the wheelbase's USB link (Wi-Fi off). Games with Thrustmaster's SDK built in use this, and Thrustmaster's "SDK Test" PC app drives the screen this way, so a PC-side library exists. Preferred if it's usable by other apps (no Wi-Fi, no re-enabling after power-up), but no public documentation was found: research spike needed.
    - **Wi-Fi UDP** (known to work, fallback): in the F1 games' telemetry format (port 20777; F1 2020 or F1 23 format, chosen by firmware). Pitwall sends those packets itself, filling the fields with Pitwall data. Prior art: the community SimHub SF1000 UDP plugin feeds AC this way. On firmware v5 and older, UDP mode has to be switched on at the wheel after every power-up.
  - What to show (configurable, no code): gear/speed/RPM lights as normal, plus Pitwall's own: live delta to your reference, brake-in countdown and next corner grade, drill timer/target and pass streak, lap/sector times vs best, ABS/TC/BB once the CSP app reports real levels, flags/pit limiter.
  - Constraint: the wheel's screen layouts are Thrustmaster's F1 pages, so "custom" means choosing which F1 field carries which Pitwall value (e.g. the delta field, lap times, ERS/DRS bars repurposed). First step is a research spike: map every field each SF1000 page actually displays, then design pages around that.
  - Settings tool: wheel IP, format (F1 2020 / F1 23), what goes on each page, a "test pattern" button.
- **Home Assistant** (very last): flags, shift light, pit lane, PB flash via HA WebSocket API; each toggleable.

---

## 14. Units & locale

Metric (km/h, m, °C), tyre pressure in **psi**, NZ date/time formats.

---

## 15. Roadmap

| Phase | Contents |
|---|---|
| **0 Foundation** | AC adapter, lap recording, SQLite, WebSocket, driving layout, settings UI, SF1000 input, demo/replay mode |
| **1 Track learning core** | Auto corner detection, map, next-corner card, corner progress, section timing, drills + pass targets, CSP companion app (rewind/teleport), **mini Nordschleife pack** (corner names + chapter boundaries) |
| **2 Cloud hub** | Supabase sync, hosted hub, history, lap comparison, AI debrief, AI time to beat. Done: sync (laps, corner analysis, ~20 Hz telemetry, track layouts, car profiles) and the hub site (same analysis screens, read-only, compares laps in the browser; Vercel). Next: AI debrief (Anthropic API key on the PC), progress over time, AI time to beat |
| **3 Coaching** | Live tips (audio+visual), blind-spot scan, electronics + pressure advisor, music, session timer |
| **— v1 = phases 0–3 —** | |
| 4 Content | Full Nordschleife/Spa/Hampton Downs packs, lesson library, setup unlock tree, quiz, pace notes, drive-along, famous times |
| 5 Car learning | Profiles, shakedown, transfer tips |
| 6 Racecraft | Lessons, pre-race briefing, incident review, AI scenario drills |
| 7 Settings tools | FOV, FFB, controls, graphics; more track packs |
| 8 Extras | SF1000 wheel screen (UDP), Discord RP, EVO + BeamNG adapters, iRacing + Garage61, Home Assistant, polished README + demo GIF, public repo |

---

## 15b. Notes for later

- **In-game CSP Lua app** (v0.1 built: `csp/Pitwall`, installed by start.bat; next corner + brake countdown overlay, instant drill retry via saved car state, real ABS/TC/BB. Still to do: in-game drill timer, coaching tips in game). Original plan: zero-latency overlays (brake countdown, next corner, drill), real ABS/TC levels (`car.absMode`, `car.tractionControlMode`), its own rewind using `ac.saveCarStateAsync` / `ac.loadCarState` (same approach as Time Shift), talking to the rig over `web.get/post`.
- A deeper AC/CSP **mod** is also an option if an app can't do something.
- Second-screen smoothness depends on GPU headroom: capping AC's frame rate leaves room for Chrome.

## 16. Open items

- **NEXT UP (owner request, 2026-11-03): drill teleport.** Pick a section and get put at its run-up straight away, over and over, without driving round first. Today the in-game app's retry only works after you've driven through the run-up once (it saves the car state there). Plan: `physics.setCarPosition` to the run-up point (offline only, like Time Shift), and use CSP's car-state helpers ("alter car position and velocity in a blob from `ac.saveCarStateAsync()`", lua-shared/sim/cars.lua) to arrive at the reference lap's speed there, not from a standstill. Bind it to the drill / retry buttons; "teleport to section N" from the dashboard's practice list.

- **Rewind mod**: name and whether it can be triggered from a CSP Lua app / externally. Affects only phase 1 retry implementation; teleport is the fallback.
- **AC EVO fields**: confirm BB/ABS/TC levels and tyre pressures exist before building EVO electronics features.
- **TTS voice**: audition 2–3 voices.
- **SF1000 screen**: whether Thrustmaster's SDK (USB/Native mode) can be used by a third-party app; which F1-format fields each wheel page shows, the user's firmware version, and whether the screen accepts a second sender alongside a game's own output. Could move earlier than phase 8 if wanted, since it's independent of the rest.

- **GitHub Student Developer Pack** perks to check and use (offers change; verify at education.github.com/pack): free domain for the hosted hub, Azure for Students credit (Azure neural TTS as a voice candidate), Sentry for error tracking, Copilot, cloud credits as a fallback host.

---

## 17. Key technical facts (from research, 2026-11)

- AC EVO shared memory: `Local\acevo_pmf_physics|graphics|static`, ACC-style, undocumented; layout changed in patch 0.6.
- CSP Lua: `physics.setCarPosition(carIndex, pos, dir)` — offline only; `shared/socket` and `web.*` available for talking to the rig service.
- iRacing: no teleport API; Active Reset is keybind-only, solo practice.
- BeamNG: OutGauge/MotionSim UDP; teleport via vehicle Lua (resets momentum).
- Background wheel input: DirectInput `DISCL_BACKGROUND | DISCL_NONEXCLUSIVE` (or SDL with `SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1`).
- Reference platforms (Track Titan, Coach Dave Delta, VRS) have no public APIs; Garage61 (iRacing) has one.
- Discord Rich Presence still works via local IPC (`\\.\pipe\discord-ipc-0`).
