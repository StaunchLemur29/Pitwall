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
- **Local API safety**: the rig service listens on this PC only (unless `--lan`) and refuses browser requests whose Origin isn't its own pages or the dev server, including the WebSocket, so another website open in Chrome can't drive Pitwall, read live data or spend the API key (2026-11-04).
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
   - **Built 2026-11-06** (scan.py, the analysis window's "Blind spots" panel, PC only): from your last 20 laps on a car + track, habits on 40 %+ of passes through a corner, at 2+ corners with 6+ passes each: coasting into corners, braking 15 m+ before the optimal run, full throttle 20 m+ after it, a different apex gear from it; plus an abrupt brake release on 40 %+ of stops (the rig showed 20 %, so it stays quiet for you) and 2+ corners graded red. Each says how often, where it shows most, why it matters, and offers the practice section with the worst corner as a drill.
2. **Quiz** — offered once the scan has enough data: a one-off ~5-min **knowledge quiz** (on the Mac) for things telemetry can't reveal (flags, pressures, ABS/TC theory, track limits). It skips topics the scan already shows you handle, so it stays short.

### AI debrief (Claude)
Post-session race-engineer debrief: explains *why*, answers follow-up questions, teaches theory in context. Also generates the **AI "time to beat"**: a realistic per-corner stretch target based on consistency and where time is lost.

### Electronics & setup (progressive unlock tree)
1. BB, ABS, TC (+ engine map where present) — explanation + telemetry-based suggestion.
2. Tyre pressures (AC reports them live).
3. Deeper garage setup (springs, dampers, aero…) — only once earlier stages are mastered.

**Advisor built 2026-11-16** (advisor.py; suggestions only, Pitwall never changes the car):
- **What it watches:** each wheel's speed against the car's. A wheel 25 %+ slower while braking for 0.15 s is a lock-up (fronts and rears told apart: they call for opposite changes); 20 %+ faster on the throttle for 0.25 s is wheelspin. Also how much of your braking the ABS is working, how much of your flat-out driving the TC is cutting, and hot tyre pressures. Wheel radius is learnt as you drive (rolling freely in a straight line), so it works for any mod.
- **When it speaks:** from your last 8 laps **on the current settings** (same brake bias, ABS and TC level): change one and it starts again. Needs 3 laps, and a habit: the same corner on 2 laps, or half your laps.
- **What it says:** rear lock-ups: bias 1 % forward. Front lock-ups: more ABS if it's on, else bias 1 % rearward. Wheelspin: more TC if it's on, else throttle technique. TC cutting 35 %+ of flat-out time: try a step less. ABS working 50 %+ of braking: brake to just under it. Pressures: even out left and right on an axle (1 psi+), or against the car's ideal hot pressure when known (read from the car's tyres.ini if its data folder is unpacked, else typed in on the Tools page).
- **Where:** Tools page card; the pit report's "Settings to try" (top two); and, for lock-ups and wheelspin at a corner, the live tip slot (after repeated mistakes, before the focus; the same suggestion at most every third lap).
- **Not done:** reading packed data.acd for ideal pressures; brake bias as fuel burns off; the garage setup stage; advice on the hub.

---

## 7. Reference laps & targets

Selectable / combinable:
- Own best lap (**default delta**)
- Theoretical best (best sectors)
- **Time to beat** (done, 2026-11-04; **shown in drills**): a realistic stretch target per corner, worked out (no API call): part of the way from your usual (median of your last 10 clean laps) towards your best ever, or towards the optimal run where you're already consistent; less of a stretch where you're inconsistent ("be consistent first"); at most 0.15 s past your best per corner. The lap's time to beat is your usual lap minus those gains, never more than 0.3 % under your best lap; sections and drills get theirs from your usual time through them. Shown on the side screen (lap card, drill card while it's quicker than your best run), in the analysis (lap, corner, section) and the hub (uploaded with each lap), and given to the AI debrief for its targets.
- Online lap times as *targets* (via RSR / SRS / CM leaderboards — times only, no telemetry), labelled elite / average / your level
- Imported laps (own older laps, friend's file, exports from paid tools where permitted)
- AC AI line (for line drawing on the map)
- **Optimal racing line** (done, 2026-11-03): worked out from the track's edges in AC's `fast_lane.ai` as the *minimum-curvature* line (the smoothest path the edges allow, car centre kept 1.2 m inside each edge; kerbs not assumed usable). Geometric only, so it's a placement guide, not a lap-time prediction. Shown dotted on each corner's close-up and as a toggle on the lap map; turn-in/apex/exit distance from it per corner; the track-width tips measure against it (the outside-inside-outside rule of thumb stays as the fallback for tracks without edges). Worked out once per track in the background (a few seconds on the Nordschleife).
- **Optimal run** (done, 2026-11-03, owner request: "optimal brake, throttle etc."): the optimal line driven at the car's grip, learnt from your 8 fastest valid laps of that car on that track (lateral, braking and accelerating g at each speed, high percentiles; a v² term for aero). Point-mass lap sim with a friction ellipse. Gives speed, brake % and throttle % along the lap (pedals are estimates: needed ÷ the most the car managed), per-corner numbers (braking point, slowest point, full throttle, exit speed, time), "Against the optimal run" notes, and a lap-time estimate. Shown as a third, dotted series in the corner charts and an "Optimal run" table column. Only as good as the laps it learnt from. The hub gets the per-corner numbers and notes; the charts' optimal curves are rig-only for now. Later: a minimum-time line (bending the line to the car instead of minimum curvature).
- **Famous times**: real records and well-known laps per track pack, **compared within car class**; where official timing with sector splits exists (e.g. Nürburgring 24h, Spa), use it as a sector-level reference
- Future: Garage61 full-telemetry references (iRacing)
- **Practice doesn't pollute laps** (decided 2026-11-04, owner requests): jumps are spotted from the telemetry itself (moving further than the speed allows, or going backwards along the track), whatever caused them. A **rewind after a mistake** (back up to a fifth of a lap, not in a drill) keeps the lap as a normal one tagged "rewind": the erased bit is dropped (samples, sector times, a cut), it counts in stats, but it's never a best lap, reference, PB, best sector or optimal-run input. A **teleport**, or any jump during a drill, makes it an out lap (never valid). A drill run with a jump in it is dropped.

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
- **Car systems only when they're real** (owner request, 2026-11-04): DRS and battery (ERS/KERS) are shown (side screen, analysis, hub, AI debrief) only once they've been seen working on track (DRS coming on, the charge moving), not just because AC or CSP says the car has them: some mod cars claim systems they don't have.
- **Good corners of any lap count** (owner request, 2026-11-04, "especially for Nürburgring"): laps you don't finish (quit, restart, back to the menu) are kept as **unfinished** laps (never valid). Every lap's corners are checked on their own: **driven** all the way through (telemetry from entry to exit, no jump) and **clean** (wheels on track there, from the per-lap wheels-off channel; older laps go by the whole lap). Your usual, bests, mastery and time to beat use the counting corners of every lap, finished or not, cut elsewhere or not. The analysis and lap review show only the corners a lap drove; section times only when the lap covered the section.
- **Coaching, not lap comparison** (owner, 2026-11-04: "this isn't a lap comparison app, it's a coaching app"; "comparisons with my own better laps are fine, just not against worse"): a lap is never compared with a slower one. By default it's compared with your best lap when that's faster; on your best lap (or one quicker only by cutting), with the benchmark, the optimal run. The "vs" picker offers only your faster laps and the optimal run. PC and hub. Until the optimal run is worked out (it needs the track's edges, a few clean laps and a moment), a best lap is compared with your best through each corner on any other lap (rewinds excluded), and the Gain / loss map colours each corner by what it lost there (2026-11-05: on the rig the best lap showed nothing at all).
- **A section's best counts from any lap** (owner, 2026-11-05: "out laps are still useful, I could set my best time for a section then crash out later"): every lap's clean pass through each practice section is kept: out laps, laps you didn't finish, invalid laps cut elsewhere. Not a lap with a rewind, not a section you went off in, and only where the lap drove all of it in one go. Your best for a section is the quickest of these and your drill runs: the drill target, the in-game timer and the analysis use it. Uploaded with each lap so the hub shows it too (drill runs stay on the PC). Laps from before this change are filled in once, in the background, when you next drive that car + track (2026-11-06). Slides can't be filled in for older laps: their traces have no heading to work them out from.
- **Live tips** (phase 3, 2026-11-06): at most one a lap, on the straight before the corner it's about (150 to 600 m out; on a run of linked corners, on the straight before the run, at most two corners back, and it says "Hairpin 2, after Turn 1"). What it says: the same mistake at the same corner on 2+ of your last 4 laps (offs included), else a trouble spot (the same corner going wrong in different ways), else the session focus. Always as something to do ("Brake 12 m later", "Use gear 2 at the apex"), never a difference where you were quicker. Never mid-corner, during a drill, with cold tyres or over a crash notice. On the side screen's coach strip and as a line in the in-game overlay; Settings > Coaching > Live tips: both, side screen only, or off. Text only for now; voice later.
- **Pit report** (owner, 2026-11-05: "some kind of good analysis when I enter the pits, a debrief or a catch-up if I'm racing"): coming into the pits after a stint, the side screen shows how it went: laps and clean laps, best, typical and spread, the mistakes that kept happening (same kind at the same corner on 2+ laps; else the stint's worst moments), what it did to the car (fuel per lap by distance driven and laps left, tyre wear, damage; read from the last moment on track, since "return to pits" resets the car) and one thing for the next stint. In a race, your position. It also writes the AI debrief so far (if the key's set and automatic debriefs are on). Gone when you drive out.
- **A drill can be stopped while paused or in the pits** (owner, 2026-11-05): that layout has no drill card, so a bar under the banner shows the running drill with Stop.
- **Conditions and what changed** (owner, 2026-11-05: "track all the variables: tyre wear, track temps, time of day, anything important"; "if I crash, or any change I should know about, the coach tells me"): Pitwall reads AC's tyre wear, tyre dirt, car damage, air and track temperature and track grip, and from the in-game app the time of day, weather, rain and CSP's track grip (fields as CSP's own apps read them). Each lap keeps its conditions (shown under the lap in the analysis, uploaded to the hub, given to the AI debrief); when the lap it's compared with was in different conditions, the analysis says so. The coach strip shows a one-line notice when something changes, before anything else: contact (where the car's damaged), dirty tyres after going off (and when they're clean), a crash or spin (stopped on track from speed, or side-on), tyres worn 3 / 6 / 10 points this stint, the track 4 degrees hotter or cooler, grip up or down two points, rain starting or stopping, dusk. AC's wear, dirt and damage numbers have no documented units: thresholds are cautious and to be checked on the rig.
- **What went wrong, by kind** (owner, 2026-11-05: "not just sections: if I messed up my gears, slightly spun, didn't accelerate as much as I should"): the lap review (and the coach strip's mistake after each lap) names going off, spins, **slides you caught** (the car over 8 degrees sideways for 0.3 s or more, from AC's heading against the direction of travel; over 90 degrees is a spin; a slide that put you off is named with the off), **wrong gear** (apex gear different from your usual, costing time), **slow on the power** (full throttle 15 m+ later than usual and slower on the exit), then plain slow corners. Slides are named even when they cost nothing. Checked on the rig recording: the 40-degree moment on lap 6 and the spin on lap 7.
- **Coaching, not lap comparison** (owner, 2026-11-04: "this isn't a lap comparison app, it's a coaching app"; "comparisons with my own better laps are fine, just not against worse"): a lap is never compared with a slower one. By default it's compared with your best lap when that's faster; on your best lap (or one quicker only by cutting), with the benchmark, the optimal run. The "vs" picker offers only your faster laps and the optimal run. PC and hub.
- **Coach strip on the side screen** (owner request, 2026-11-04): when no drill runs, the Coach card shows one thing at a time: **cold tyres** ("build up", until they're near the temperature this car's tyres usually work at, learnt from your laps; 55 °C until known) first; then for 25 s after each lap, **that lap's biggest mistake** (from its Good and bad), or "Clean"; otherwise the session's one **focus** corner: the most time to gain against its time to beat, its fix (from your last lap there), with Practise. The focus stays for the session until you've met its target twice.
- **Brake cue aims at the optimal run** (decided 2026-11-04, owner: "the goal isn't to compare myself to myself, it's to become better"): "brake in" (side screen and in-game overlay) and the corner's target speed come from the optimal run's braking points, still adjusted for your arrival speed; gears stay from your best lap (the optimal run has none). Your best lap until the optimal run is worked out. Setting: Settings → General → Braking points from.
- **Brake cue aims at the optimal run** (decided 2026-11-04, owner: "the goal isn't to compare myself to myself, it's to become better"): "brake in" (side screen and in-game overlay) and the corner's target speed come from the optimal run's braking points, still adjusted for your arrival speed; gears stay from your best lap (the optimal run has none). Your best lap until the optimal run is worked out. Setting: Settings → Coaching → Braking points from.
- **No pass targets** (decided 2026-11-04, owner: resetting when a run isn't close enough "ignores the whole point of a drill"): every run counts and nothing resets. The card shows the last run against your best, the best, how many runs, and the recent runs as bars.
- **Every lap gets its good and bad** (decided 2026-11-04, owner: "look at bad laps/invalid laps and blunders on normal laps to see where I went wrong, and the good and bad"): any lap can be opened in the analysis (cut, out and rewind laps too). A "Good and bad" panel compares it with your usual (the median of your recent clean laps through each corner): where it went wrong (going off, from a new wheels-off channel in the lap trace; spins; corners lost by more than your usual variation, with the likely cause) and what went well (quicker than usual or your best ever, with what helped). Worked out on the PC and uploaded with each lap for the hub.
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
- Gamification (streaks, corner greens, car/track XP): light, on by default, can be turned off.

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
  - FFB clipping meter from AC's `finalFF` (per lap, per car, with a gain suggestion) for the TS-PC — **done 2026-11-04** (Tools page: % of the time clipping over your last 10 clean laps, where, and how much to change the car's gain)
  - T-LCM pedal check: peak brake per stop vs 100 %, consistency, release smoothness; calibration advice — **done 2026-11-04** (Tools page)
  - "What's new" page (`#/news`, linked from Settings with a dot when there's something unread): each change in plain words plus anything you have to do yourself; add an entry at the top of `views/WhatsNew.tsx` when a change ships — **done 2026-11-04**
- **SF1000 wheel screen** (big feature): Pitwall drives the SF1000's built-in display with its own data, so key info sits on the wheel in your eyeline.
  - **Status (2026-11-04):** USB/Native mode isn't open to other programs (no public SDK; docs/research/sf1000-screen.md). Built the **Wi-Fi UDP** route: Pitwall sends F1 23 packets itself (rig `sf1000.py`), making the wheel's own pages work in AC; Settings → Controls → SF1000 wheel screen (IP, on/off, test pattern). Next: the owner's page checklist, then Pitwall's own values on the wheel.
  - Two possible routes:
    - **USB ("Native" mode)**: the wheel's screen and LEDs are driven through the wheelbase's USB link (Wi-Fi off). Games with Thrustmaster's SDK built in use this, and Thrustmaster's "SDK Test" PC app drives the screen this way, so a PC-side library exists. Preferred if it's usable by other apps (no Wi-Fi, no re-enabling after power-up), but no public documentation was found: research spike needed.
    - **Wi-Fi UDP** (known to work, fallback): in the F1 games' telemetry format (port 20777; F1 2020 or F1 23 format, chosen by firmware). Pitwall sends those packets itself, filling the fields with Pitwall data. Prior art: the community SimHub SF1000 UDP plugin feeds AC this way. On firmware v5 and older, UDP mode has to be switched on at the wheel after every power-up.
  - What to show (configurable, no code): gear/speed/RPM lights as normal, plus Pitwall's own: live delta to your reference, brake-in countdown and next corner grade, drill timer, last run and best, lap/sector times vs best, ABS/TC/BB once the CSP app reports real levels, flags/pit limiter.
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
| **2 Cloud hub** | Supabase sync, hosted hub, history, lap comparison, AI debrief, AI time to beat. Done: sync (laps, corner analysis, ~20 Hz telemetry, track layouts, car profiles) and the hub site (same analysis screens, read-only, compares laps in the browser; Vercel). Also done: AI debrief (Claude Opus 5.5 with the owner's API key on the PC; written when a session ends with 3+ clean laps, or on request; shown in the analysis on the PC and in the hub; the hub can also write one while the PC is off, through a Supabase Edge Function holding the key, limited to the owner's email), the hub's Progress page and the time to beat. Phase 2 is done; the recommended order for the rest is in docs/review-2026-11.md |
| **3 Coaching** | Live tips (audio+visual), blind-spot scan, electronics + pressure advisor, music, session timer |
| **— v1 = phases 0–3 —** | |
| 4 Content | Full Nordschleife/Spa/Hampton Downs packs, lesson library, setup unlock tree, quiz, pace notes, drive-along, famous times |
| 5 Car learning | Profiles, shakedown, transfer tips |
| 6 Racecraft | Lessons, pre-race briefing, incident review, AI scenario drills |
| 7 Settings tools | FOV, FFB, controls, graphics; more track packs |
| 8 Extras | SF1000 wheel screen (UDP), Discord RP, EVO + BeamNG adapters, iRacing + Garage61, Home Assistant, polished README + demo GIF, public repo |

---

## 15b. Notes for later

- **In-game CSP Lua app** (v0.1 built: `csp/Pitwall`, installed by start.bat; next corner + brake countdown overlay, instant drill retry via saved car state, "Go there" teleport to a drill (stopped, `physics.setCarPosition`), real ABS/TC/BB. In-game drill timer done 2026-11-04: run time counting through the section with the time to beat (or your best once you've beaten it), then the result for 4 s; game time, cancelled by a rewind/retry; Settings toggle. Still to do: coaching tips in game). Original plan: zero-latency overlays (brake countdown, next corner, drill), real ABS/TC levels (`car.absMode`, `car.tractionControlMode`), its own rewind using `ac.saveCarStateAsync` / `ac.loadCarState` (same approach as Time Shift), talking to the rig over `web.get/post`.
- A deeper AC/CSP **mod** is also an option if an app can't do something.
- Second-screen smoothness depends on GPU headroom: capping AC's frame rate leaves room for Chrome.

## 16. Open items

- **Drill teleport** (owner request, 2026-11-03; reworked 2026-11-04): built as "Go there" on each section/chapter in analysis. Teleport is only for getting to a drill; retries stay the rewind (saved run-up state, else Time Shift). The car is parked **stopped** on the racing line, far enough back that a flat-out standing start reaches the section start at reference speed. The distance comes from the reference lap's full-throttle acceleration per 10 km/h band at 85 %, lifting where the reference lap was slower. It is never closer than the Time Shift run-up + 50 m. Arriving at speed (owner, 2026-11-05, reversing the earlier stationary-start choice because CSP couldn't warm the tyres): as you drive, the in-game app saves a car state every 200 m of the lap, only when Pitwall says the car is fit (on track at speed, tyres warm, no damage or dirt, not mid-retry); "Go there" loads the one 150 to 1500 m before the drill's run-up, so you arrive at your normal speed with warm tyres. States belong to the car + track they were saved on. With none saved there yet this session, it parks you stopped as before. Teleporting resets the car; the tyres are then put back to working temperature with `physics.setTyresTemperature` (seen in CSP's CspDebug app; guarded, and says so if this CSP lacks it) (owner request, 2026-11-04). After the teleport the app keeps warming for two seconds and then reads the tyres back: it only reports warm if they are, else says in the game and on the side screen that this CSP couldn't warm them (2026-11-05: on the rig the call was accepted but the tyres stayed at 70 °C, and nothing said so). The target is the working temperature Pitwall learnt for the car on your laps, else the car's optimum, else 85 °C, never a cold reading: on the rig the car had been reset to the pits first, its tyres read 70 °C, and warming "back" to that did nothing (2026-11-05). The spot is far enough back to be at your usual speed by the run-up point (where retries start), not just by the section, with a wide margin: on the rig a standing start fell 25 km/h short (2026-11-05). The retry state is saved at the run-up point only at 95 % of your usual speed there; a slower pass is kept only until a quicker one, so retries never all start slow (2026-11-05).

- **Rewind mod**: name and whether it can be triggered from a CSP Lua app / externally. Affects only phase 1 retry implementation; teleport is the fallback.
- **AC EVO fields**: confirm BB/ABS/TC levels and tyre pressures exist before building EVO electronics features.
- **TTS voice**: audition 2–3 voices.
- **SF1000 screen** (USB answered 2026-11-04: not open to other programs, so Pitwall uses Wi-Fi UDP; see docs/research/sf1000-screen.md). Still open: which F1-format fields each wheel page shows, the user's firmware version, and whether the screen accepts a second sender alongside a game's own output. Could move earlier than phase 8 if wanted, since it's independent of the rest.

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

---

## 18. How the numbers are worked out (audit, 2026-11-16)

For whoever works on this next. Each line: where it lives, how it's worked out, how it was checked, and what's weak. "Rig lap" = the one full recorded lap (`rig/tests/fixtures/ac_spa_one_lap.pwrec`: Spa, RSS Mercer V8, 2:28.25).

**Facts about AC that the code depends on** (all seen in the rig recordings):
- AC resets the lap clock at the line one frame *before* it counts the lap. The recorder moves that sample to the next lap (`laps.next_lap_tail`); laps saved earlier are cleaned as they're read (`Store.trace`). Never work out a sample rate from a trace's first and last time.
- Lap progress wraps to 0 a few metres *before* the timing line, while the clock still runs. `LapView` drops those samples (progress must rise).
- Shared memory `abs` and `tc` are how hard the system is working right now (0 = not working), not the setting. The setting comes only from the in-game app (`car.absMode`, `car.tractionControlMode`).
- A lap is not a closed path: the car crosses the line in a different place each lap (3 m sideways on the rig lap). Anything that treats a lap's line as a loop has a kink at the seam.

| What | Where | How | Checked | Weak spots |
|---|---|---|---|---|
| Lap, valid, out lap, rewound | `laps.py` | Lap = AC's lap counter; valid = never more than 2 wheels off, driven line to line; a Time Shift rewind erases what it undid and flags the lap | Tests on the four recordings | A session restart on lap 0 is told from a rewind only by the jump detector |
| Sector times | `laps.py` | Clock at each change of AC's sector number | Rig lap: sums to the lap time | Laps with a different number of sectors from most are left out of the best sectors |
| Per-corner numbers (braking point, slowest point, full throttle, time) | `analysis.analyse_corner` | Braking point = start of the last braking phase before the apex (40 m off the brake starts a new one); time = entry to exit, interpolated | Unit tests, demo | Corner entry and exit come from the track's curvature (radius under 500 m), so "time through the corner" covers different lengths at different corners |
| Corner grades (green / amber / red) | `analysis.corner_mastery` | Spread and gap to best over the last 10 clean passes, fixed thresholds in seconds | Unit tests | The thresholds are absolute (0.08 s, 0.2 s): a long corner is graded harder than a short one. Scaling by the corner's time would be fairer; not changed, it would regrade every corner |
| Slides and spins | `laps.slip_deg`, `analysis.slide_runs` | Angle between heading and direction of travel: over 8° for 0.3 s is a slide, 90° a spin; ignored under 36 km/h | Rig recording (the 40° moment and the spin) | One car, one session |
| Section bests | `rig._record_sections` | Clean pass through the section on any lap without a rewind, no telemetry gap over 0.5 s | Unit tests | Sections that run over the start line are skipped |
| Optimal run | `optimal_run.py` | See §7 and the module's docstring. Hills, the top-of-data fit and local grip arrive with pull request 53 | **The real-line check** (below): on main the model is slower than the rig lap on 23 % of it, with pull request 53 on 8 % | Banking, kerbs, tyre state aren't modelled; needs 500 samples and the track's edges |
| Blind-spot scan | `scan.py` | A habit = 40 %+ of passes at a corner, 2+ corners, 6+ passes each | Demo; rig lap for brake release only (20 %, quiet) | Thresholds from one session; three of the six checks need the optimal run |
| Live tips | `tips.py` | Same mistake at the same corner on 2+ of the last 4 laps, else a trouble spot, else (with the advisor, pull request 54) a setting to change, else the focus | Unit tests, in-game harness | Not driven on the rig yet |
| Time to beat | `analysis.time_to_beat` | 35 to 60 % of the way from your usual to your best (or the optimal run), by grade | Unit tests | The stretch factors are a judgement, not fitted |
| Pedal and FFB checks | `tools.py` | Brake stops: peak, time to peak, time from the last 90 %-of-peak moment to off | Rig lap | "Abrupt" is under 0.15 s, fixed |

**The real-line check** (`test_the_model_can_drive_your_real_line_as_fast_as_you_did`, in `rig/tests/test_optimal_run.py` once pull request 53 is merged): learn the car from a real lap, then drive that lap's own line with the model. It should be as quick as the lap or quicker nearly everywhere; where it's much slower, the model is missing something the car really did. This is how the missing hills were found. Use it for any change to `optimal_run.py`. Ignore the first 3 % of the lap (the seam, above).

**The in-game app's CSP calls, checked 2026-11-16** against CSP's public sources (`ac-custom-shaders-patch/acc-lua-sdk` and `app-csp-defaults`; both can be cloned). Those don't list the functions built into CSP itself, so "not found" means not confirmed, not wrong. The full list is on the PC: `assettocorsa/extension/internal/lua-sdk/ac_apps/lib.lua`.
- **Confirmed in CSP's own apps:** `ui.pushDWriteFont`/`popDWriteFont`, `ui.drawRectFilled`, `ui.drawRect`, `ui.drawImage`, `ui.windowWidth`, `ui.text`, `ui.textWrapped`, `ui.textColored`, `ui.setCursor`, `ui.separator`, `ui.checkbox`, `os.preciseClock`, `ac.trackProgressToWorldCoordinate`, `ac.isCarResetAllowed`, `ac.saveCarStateAsync`, `ac.loadCarState`, `ac.onCarJumped`, `ac.getSim`, `ac.getCar`, `JSON.parse`/`stringify`, `web.get`; car fields `absMode(s)`, `tractionControlMode(s)`, `brakeBias`, `drs*`, `kers*`, `mguk*`, `fuelMap`, `currentEngineBrakeSetting`, `engineBrakeSettingsCount`, `speedKmh`, `splinePosition`, `look`, `wheels`; sim fields `isPaused`, `isReplayActive`, `trackLengthM`, `weatherType`, `rainIntensity`, `ambientTemperature`.
- **Confirmed in the SDK only:** `web.post`, `web.timeouts`, `ac.Wheel`, `ui.Alignment`.
- **Not found in either, but working on the rig:** `ui.dwriteTextAligned`, `ui.measureDWriteText` (the overlay draws), `physics.setCarPosition` (Go there works).
- **Not found, and not proven on the rig:** `physics.setTyresTemperature` (guarded; on the rig it was accepted but the tyres stayed cold), `sim.timeHours`, `sim.timeMinutes`, `sim.roadGrip`. These three are now read one at a time, so a missing one no longer loses the weather and rain with it. Check them in `lib.lua` on the PC.
