# Sim racing research for Pitwall (Nov 2026)

**Method and limits.** This was web search only. Page fetches were blocked in this environment for acstuff.club, overtake.gg, coachdaveacademy.com, support.thrustmaster.com, boxthislap.org and thesimgrid.com, so most facts below come from search snippets of those pages, not full reads. Anything marked *(opinion)* is community advice. Anything marked *(unverified)* came from a single weak source or from background knowledge. Check those before building on them.

---

## 1. Assetto Corsa (original) today

**Content Manager (CM).** CM is the standard launcher. It installs and updates CSP itself, and it has a local "Lap times" results view (personal stats, lap times, replays) ([CM page](https://acstuff.club/app)). Those are *your* local times, filterable per car/track ([RaceDepartment](https://www.racedepartment.com/threads/local-track-times.135551/)). One user reports CM shows only the top 10 per track ([Overtake](https://www.overtake.gg/threads/where-can-i-see-all-of-my-best-lap-times.223669/)). Older CM builds also showed online times from RSR, SRS and World Sim Series ([listing](https://www.sourceforge.net/projects/contant-manger)). AC's own best laps also live in `Documents\Assetto Corsa\personalbest.ini` *(unverified, from memory)*.

**Custom Shaders Patch (CSP).**
- **Version line:** I couldn't confirm the current build. The latest public build I found listed is 0.2.11 ([modland](https://www.modland.net/assetto-corsa-mods/other/custom-shaders-patch.html)). Previews come first through x4fab's Patreon. A 0.2.10 preview listed "physics extensions by mclarenf1papa" and scriptable WeatherFX ([assettolab](https://assettolab.ru/other/csp-0-2-10-preview1-custom-shaders-patch/)). Check acstuff.club/patch for the current build.
- **Time Shift (rewind):** A CSP app called "Time Shift" on the App Shelf lets you rewind offline. That comes from one anonymous forum post ([Steam](https://steamcommunity.com/app/3058630/discussions/0/4406291166505519890)), so it needs checking in game *(unverified)*. Hotlappers use it to re-run a single corner without driving the whole Nordschleife again.
- **Extended physics:** Car mods can opt into extra physics. RSS cars list a minimum CSP for it, for example FH2022 needs 0.1.77+, FH2023/24 need 0.2.3+ and the Alpine 2025 needs 0.2.7+ ([RSS store](https://store.racesimstudio.com/p/fh23)).
- **Lua apps:** Available since CSP 0.1.76 (LuaJIT). An app lives in `apps/lua/<name>` with a `manifest.ini`. The SDK definitions ship in `extension/internal/lua-sdk` ([SDK wiki](https://github.com/ac-custom-shaders-patch/acc-lua-sdk/wiki/Lua-apps), [SDK](https://www.github.com/ac-custom-shaders-patch/acc-lua-sdk)). Source for CSP's own apps is in [app-csp-defaults](https://www.github.com/ac-custom-shaders-patch/app-csp-defaults) and [acc-lua-internal](https://github.com/ac-custom-shaders-patch/acc-lua-internal), which is the reference Pitwall's CLAUDE.md requires.

**Pure (Peter Boese).** Pure is a weather and lighting add-on on top of CSP. It is Patreon-only, v3.10 as of Dec 2025, and some versions need a minimum CSP ([install guide](https://creacher4.github.io/assetto-corsa-arc/guides/setup/installing-pure.html)). Some Pure updates have broken third-party post-processing filters ([GTPlanet](https://www.gtplanet.net/forum/threads/assetto-corsa-pc-mods-general-discussion.307899/page-4980)). Practical tip *(opinion)*: if lap times move after a Pure or CSP update, check the grip and temperature settings in Pure's planner before blaming your driving.

**RSS cars (Race Sim Studio).** RSS makes paid, high-quality mod cars, mostly fictional "Formula" versions of real cars (Formula Hybrid 2019–2026, Formula RSS 2/3/4, GT-M). Their systems:
- **Hybrid cars:** model ERS, with MGU-K delivery and recovery, MGU-H mode and an overtake button, all shown on the steering-wheel display pages ([display mod](https://www.overtake.gg/downloads/rss-formula-hybrids-display.56397/)).
- **DRS:** carried even by non-hybrid cars such as the Formula RSS 2, which needs no energy management ([RSS](https://store.racesimstudio.com/p/formula-rss-supreme/)).
- **Newest releases:** a 2026-spec Formula Hybrid ([Traxion](https://traxion.gg/race-sim-studio-releases-2026-spec-formula-1-style-mod-for-assetto-corsa/)) and a Formula RSS 3 2026 with an NA V6.
- **Engine maps:** where you change them is unclear even to users ([GTPlanet](https://www.gtplanet.net/forum/threads/assetto-corsa-pc-mods-general-discussion.307899/page-4515)). Read each car's PDF manual.
- **Controls:** base AC hotkeys cover ERS/KERS, engine brake and brake bias ([Wikipedia](https://Www.wikipedia.org/wiki/Assetto_Corsa)). CSP extended controls add torque and pedal maps.
- Per the owner's decision, Pitwall can *show* these systems but not control them.

**Nordschleife.**
- **Official:** Kunos `ks_nordschleife` from Dream Pack 1, with layouts Nordschleife, Tourist and Endurance (24h) ([Steam](https://store.steampowered.com/app/347990)).
- **Popular community add-ons:**
  - [Nordschleife pack](https://overtake.gg/downloads/nordschleife-pack.9409): 24h, Tourist, Tourist Short, VLN and VLN 2005 layouts.
  - [Tourist Enhanced](https://www.modland.net/assetto-corsa-mods/tracks/nordschleife-tourist-enhanced-mod.html): needs DP1, CM and CSP.
  - [Tourist Full](https://www.assettohub.com/track/nordschleife-tourist-full/): 20.8 km, needs CSP.
  - [Tourist Freeroam](https://www.overtake.gg/downloads/nordschleife-tourist-freeroam-mod.74624/).
  - [400,000 3D Trees rework](https://www.overtake.gg/downloads/reworked-400-000-3d-trees-nordschleife.68447/): visual, CSP 0.1.79+.
  - [Nürburgring 24H](https://www.assettoworld.com/track/nuerburgring-24h) on AssettoWorld.
- **"LS" layout:** I couldn't identify a mod called "LS". Ask the owner which one they mean.
- **For Pitwall:** each variant has a different track folder or layout ID and length. Times must be keyed by track *and* layout, or a Tourist lap ends up compared with a 24h lap.

**Learning cars and tracks** *(opinion)*. For cars, the usual picks are the Mazda MX-5 Cup (ND) ([Asetek](https://www.asetek.com/simsports/?p=6560)), the Toyota GT86 and BMW M3 E30 ([ProGameGuides](https://progameguides.com/assetto-corsa/best-cars-in-assetto-corsa/)), and the Lotus Exos 125 for fun. Common advice is to stick to one car and one track for a while ([Overtake](https://www.overtake.gg/threads/path-for-begginers-in-sim-racing.199483/)). Short tracks such as Magione, Brands Hatch Indy and Silverstone National give many laps per hour. I couldn't source that last point; it's general community practice.

## 2. Assetto Corsa EVO

- **Status:** Early Access since January 2025. The fall-2025 target for 1.0 was dropped. Kunos's publisher, Digital Bros, now points investors at January–June 2027 ([BoxThisLap](https://boxthislap.org/assetto-corsa-evo-rally-full-release-2027/)).
- **Recent updates:**
  - [0.4](https://worthplaying.com/article/2025/12/4/news/148398-assetto-corsa-evo-early-access-update-add-10-new-cars-5-new-tracks-daily-racing-portal-and-much-more-screens-trailer) (Dec 2025) added a laser-scanned Nordschleife in three layouts, later updated to the 2026 track changes ([Traxion](https://traxion.gg/why-assetto-corsa-evo-has-sim-racings-most-accurate-nurburgring-nordschleife/)).
  - 0.6 (April 2026) brought major physics and FFB changes and MoTeC telemetry.
  - [0.7](https://traxion.gg/assetto-corsa-evos-latest-update-marks-the-beginning-of-modding/) (June 2026) shipped the first car SDK.
  - [0.8](https://traxion.gg/assetto-corsa-evos-version-0-8-update-released-adding-more-content-and-multiplayer-mods/) (July 2026) allowed mod cars online.
  - **0.9 (26 Aug 2026)** added worldwide **Hotlap and Hotstint leaderboards**: pick a nearby rival and the delta bar switches to their lap. It also brought a new GT slick tyre model ([505 patch notes](https://support.505games.com/support/solutions/articles/150000232714-assetto-corsa-evo-0-9-patch-notes), [BoxThisLap](https://boxthislap.org/assetto-corsa-evo-update-0-9/)), followed by a 0.9.1 hotfix ([505](https://support.505games.com/support/solutions/articles/150000233185-assetto-corsa-evo-0-9-1-hotfix-1st-sept-2026-)).
- **Track modding:** promised but not out yet ([simracingcockpit](https://simracingcockpit.gg/assetto-corsa-evo-mods/)).
- **Telemetry:** EVO has its own shared memory, three named segments with different names from AC's ([acevo-shared-memory](https://docs.rs/acevo-shared-memory), [live-telemetry-evo](https://github.com/albertowd/live-telemetry-evo)). Pitwall would need a separate reader. There is no CSP and no Lua in EVO.
- **Worth moving?** *(opinion)* Not as the main sim yet. FFB reviews are split ([BoxThisLap](https://boxthislap.org/assetto-corsa-evo-a-deep-dive-into-its-force-feedback-system/), [Steam](https://steamcommunity.com/app/3058630/discussions/0/595140510531755302)), and performance complaints continue ([DG-Edge](https://www.dg-edge.com/articles/news/assetto-corsa-evo-early-access-review/451)). There's no RSS car library and no track mods. It is worth owning for its laser-scanned Nordschleife and its built-in hotlap leaderboard. Revisit at 1.0.

## 3. Hotlap communities and leaderboards for AC

- **RSR Live Timing:** This used to be *the* AC hotlap board. You logged in through Steam, a plugin recorded valid laps, and the site ranked them, with anti-cheat on top ([VirtualR](https://virtualr.racesimcentral.net/assetto-corsa-rsr-live-timing-plugin-released.html), [Steam](https://steamcommunity.com/app/244210/discussions/0/627457481700038914)). A RaceDepartment thread reports it shutting down ([thread](https://www.racedepartment.com/threads/rsr-rehab-suggestions.146957/)). Treat it as gone *(date unverified)*.
- **Sim Racing System (SRS):** ranked, automated hourly races for AC, AMS and rF2 ([review](https://bsimracing.com/?p=63178)). It is racing-focused, not a hotlap board.
- **TheSimGrid:** has AC leaderboards and ratings ([SimGrid AC](https://www.thesimgrid.com/games/assetto-corsa-pc/leaderboards?page=2)). I found no documented public API.
- **Track Titan:** a telemetry coaching platform that supports AC. It offers reference laps (pro, community and "personalised"), leaderboards and coaching flows. There is a free tier, and pro references are paid ([Track Titan](https://www.tracktitan.io/post/cw-37-weekly-track-titan-update), [site](https://tracktitan.io)). I found no public API.
- **Server-side tools:**
  - stracker records every lap and sector into a database, and its ptracker client shows in-game boards ([guide](https://assettohosting.com/en/article/stracker-assetto-corsa-complete-guide), [example](https://opengt3.assettocorsaservers.com/stracker/)).
  - [acss](https://pypi.org/project/acss) exposes best laps per track over HTTP.
  - Emperor's AC Server Manager has a read-only web API, rate-limited to 5 requests per 20 s with no stability promise ([wiki](https://wiki.emperorservers.com/assetto-corsa-server-manager/web-api)).
- **Can lap times be fetched as targets?** No clean, official source exists for the original AC. Realistic options:
  1. **The owner's own personal bests** from CM and AC files. This is the best option, and it's free.
  2. A public stracker or Server Manager hotlap server, scraped politely.
  3. Times the owner types in by hand from Track Titan, SimGrid or YouTube onboards.
  4. For EVO only, its in-game boards. They have no public API.

## 4. Hardware: TS-PC, SF1000, T-LCM

**TS-PC Racer.**
- **Firmware:** Thrustmaster lists firmware **v13** as the latest. Update with the "Firmware Update" app on Windows 10/11 ([product page](https://support.thrustmaster.com/en/product/ts-pc-racer), [how-to](https://support.thrustmaster.com/en/kb/1826-en/)). Don't use "My Thrustmaster Panel" with FFB bases. Thrustmaster says it doesn't support them and recommends updating on a PC without it installed ([TM](https://support.thrustmaster.com/en/kb/1799-en/)).
- **Control Panel:** The common advice *(opinion)* is to leave the Control Panel near default and tune in game ([Coach Dave](https://coachdaveacademy.com/tutorials/how-to-set-up-your-thrustmaster-tspc-for-acc/)). One AC guide uses 1080° rotation and 85% overall strength ([BoxThisLap](https://boxthislap.org/thrustmaster-ts-pc-ts-xw-assetto-corsa-settings/)). In AC, let the car set the steering lock. CM/CSP handle that per car *(general knowledge)*.
- **Common mistakes** *(opinion)*:
  - Running AC gain so high the FFB clips. Users lower it step by step until the clip meter stops going red ([Overtake](https://www.overtake.gg/threads/ffb-settings-for-thrustmaster-ts-pc-racer.216123/)).
  - Stacking damper in the Control Panel *and* in game.
  - The driver auto-loading a "TS-PC profile" over your own ([Overtake](https://www.overtake.gg/threads/thrustmaster-ts-pc-racer-setup-ac.155635/)).
  - In EVO, some TS-PC users had to invert the brake axis ([Steam](https://steamcommunity.com/app/244210/discussions/0/3184615258413665084)).

**SF1000 rim.**
- **Native mode:** telemetry runs through the base. Wi-Fi must be off. Firmware on both the rim and the base matters, and turn Quick Resume off ([TM KB](https://support.thrustmaster.com/en/kb/1784-en/)).
- **UDP mode:** the rim listens over Wi-Fi in F1-game format. AC isn't natively supported, so people use the [SimHub-SF1000-UDP](https://github.com/ducng99/SimHub-SF1000-UDP) plugin:
  - It speaks F1 23 format, which needs rim firmware v6.27+. On older firmware, switch the plugin to F1 2020 format.
  - On v6.27+, UDP is always on; the Wi-Fi screen shows "UDP: 20777".
  - Enter the wheel's IP in SimHub.
  - Don't mix Native and UDP.
- **Button mapping** *(general knowledge)*: map the encoders and dials in AC/CM controls. CSP extended controls can bind more functions, such as pit limiter, wipers, and ERS/brake-bias steps for RSS cars.

**T-LCM pedals.**
- **Calibration:** update the firmware, then calibrate in the T-LCM software. Recalibrate after any spring change. The software shows "raw" and "final" brake force, and the brake-force slider scales the final value ([Coach Dave](https://coachdaveacademy.com/tutorials/how-to-set-up-the-thrustmaster-t-lcm-pedals-for-acc/)).
- **Gamma:** keep the device gamma at **1.0** (linear) unless you want more sensitivity. Forum users run the force slider around 68–85, which is personal taste. Setting it too high means only a stamp reaches 100% ([GTPlanet](https://www.gtplanet.net/forum/threads/brake-calibration-in-gt-sport-yet-again-and-brake-mod-questions-for-t-lcm.392877/latest)).
- **Common mistake** *(opinion)*: adding a curve in the T-LCM software *and* in AC's brake gamma. Pick one place.
- **Consistency:** set full brake to a pressure you can hit again and again, not your hardest stamp. That suits a load cell, which works on muscle memory of pressure.

## 5. Setup basics for a hotlapper (plain language)

1. **Tyre pressures and temperatures first.** In AC the pressure you set is *cold*. What matters is the *hot* pressure after a few laps. Aim for the car's ideal window: the tyre app turning green, or the car's stated optimum ([EVO wiki on the concept](https://assettocorsaevo.wiki.gg/wiki/Setups), [guide](https://assetto-drift-tuning.pages.dev/)). Too high gives less grip and a skittish car. Too low makes it lazy and the tyres overheat.
2. **Brake bias.** More to the front is stable but locks the fronts sooner. More to the rear rotates the car but can spin it ([guide](https://godidier.github.io/car-setup-guide.html)). Move it in small steps until the fronts *just* lock before the rears.
3. **Differential.** Power lock gives more drive out of slow corners, but the car pushes wide on throttle. Coast lock gives more stability on turn-in and braking, but less rotation. Preload sets how locked it is at all times ([guide](https://godidier.github.io/car-setup-guide.html)).
4. **Wings and aero.** More wing means more grip in fast corners but a lower top speed. On the Nordschleife, a common choice *(opinion)* is a little more than at Monza, because stability through the Flugplatz, Schwedenkreuz and Pflanzgarten matters more than a few km/h.
5. **Change one thing at a time.** Drive about three laps and compare. This matters most for this driver's attention style.

---

## What this means for Pitwall

Ranked, most useful first:

1. **Personal-best targets from the owner's own data.** Read AC/CM personal bests, key them by car + track + **layout** (Nordschleife variants must not mix), and show "target = PB" on the portrait screen. It's reliable and free, and nothing to scrape.
2. **Tyre pressure helper.** After an out-lap and two laps, show hot pressure per corner against the car's ideal window, then give one plain instruction ("drop front-left 0.5 psi"). This is the biggest, easiest setup win.
3. **One-corner practice loop for the Nordschleife.** Split the lap into named sections (Hatzenbach, Flugplatz, Adenauer Forst, Karussell…). Show a delta per section against PB and pick *one* weakest section to work on next. If CSP Time Shift is confirmed in game, suggest rewinding into that section.
4. **Brake trace check for the T-LCM.** Show peak brake % and how consistent it is per corner, and flag "never reaching 100%" or "always slamming 100%". The latter suggests the T-LCM force slider or calibration needs changing.
5. **FFB clipping indicator.** Show the percentage of time clipped per lap and per car. If it's high, say "lower gain in AC" (a setting, not a control).
6. **Read-only display of RSS car state.** Show ERS state of charge, deploy mode, DRS available and engine map on screen, with no controls (respecting the owner's decision). Needs the CSP car-state fields confirmed in CSP's app sources.
7. **Manual "external target" entry.** Let the owner paste a lap time from Track Titan, SimGrid or a friend as a second target, since none of these offer a usable API.
8. **Later: an EVO reader.** Its shared memory differs from AC's. Only worth it if the owner moves to EVO after 1.0 (expected Jan–Jun 2027).
9. **Skip:** SF1000 screen output. SimHub already covers it well over UDP, and duplicating it adds little.
