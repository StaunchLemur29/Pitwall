# Can Pitwall drive the SF1000 screen and LEDs?

Research spike, 2026-11-04. Nothing here was tested on hardware.

## VERDICT (read this first)

- **USB / Native mode: no, not in practice.** Thrustmaster has no public SDK, documentation, download or licence for its telemetry SDK. Games get it from Thrustmaster directly; how they get it isn't public (probably a partner deal, but that's a guess). Nobody has published how the SF1000 screen works over USB. The only USB work published covers the 488 Challenge rim's rev LEDs, not the SF1000. Doing it ourselves would mean capturing USB traffic from a game that supports the screen and reverse-engineering it. That's a research project with no guarantee it works.
- **Wi-Fi UDP mode: yes. This is the recommended route.** The wheel joins the home Wi-Fi and listens on UDP port 20777 for packets in the F1 game format (F1 2020 or F1 23). Any program can send them. An open-source MIT SimHub plugin already does this for Assetto Corsa, so we know it works. Pitwall's Python service can send the same packets itself with `socket` + `struct`, with no SimHub and no Thrustmaster software.
- **Catch:** the wheel only shows what F1 cars have: gear, RPM/rev lights, speed, lap and sector times, fuel, tyre temps and wear, ERS/DRS, position, flags. It runs Thrustmaster's own fixed screen layouts. We can't draw our own screens or text. "Pitwall data" means putting Pitwall values into F1 fields, e.g. Pitwall's live delta in the delta field.
- **LEDs:** in UDP mode the rev LEDs appear to follow `m_revLightsPercent` and the flag LEDs `m_vehicleFiaFlags`. This comes from the SimHub plugin, which fills those fields for that reason. It is **not documented by Thrustmaster**, so check it on the rig.

### Recommended next steps

1. Owner runs the checklist below, mainly to get the firmware version and confirm the wheel shows `UDP: 20777` plus an IP.
2. Quick proof on the rig, no Pitwall code needed: install the SimHub SF1000 UDP plugin, drive AC, and confirm the screen and LEDs come alive. This proves the wheel, Wi-Fi and firewall all work.
3. Build a small `sf1000` output module in the Pitwall service. It takes AC data Pitwall already has and sends F1 23 packets (IDs 1, 2, 6, 7, 10, 4) to the wheel's IP:20777. Use the same rates as the plugin, with an F1 2020 fallback setting for old firmware. Model it on the plugin's field mapping (table below).
4. Turn off SimHub's SF1000 plugin when Pitwall is sending. Two senders would fight. AC itself sends no F1 UDP, so nothing else clashes.
5. Optional later: send Pitwall's own values in fields the wheel shows, e.g. Pitwall's live delta, predicted lap, or fuel laps.

## 1. USB / Native mode

**How it works.** Thrustmaster describes Native mode as the game talking to the SF1000 directly through the wheelbase's USB link. The SF1000's Wi-Fi must be **off** for Native mode. It is supported on PC (Win 10/11), PS5 and PS4; on Xbox it needs a T598 base on firmware v1.60+. Source: Thrustmaster KB 1784, "Ferrari SF1000 – Using LCD screen display and telemetry modes (Native / UDP)", https://support.thrustmaster.com/en/kb/1784-en/. I read this only through search snippets, because support.thrustmaster.com is blocked from this session.

**Is there an SDK?**
- Thrustmaster calls it a telemetry SDK built into games. The manual says "the SDK of the wheel is already included in the game" ([manual excerpt, manualslib](https://manualslib.mx/manual/536965/Thrustmaster-Ferrari-Sf1000-Wheel-Add-On.html?page=11)). Thrustmaster's T818/T598 pages refer to "games compatible with the telemetry SDK" ([T818](https://support.thrustmaster.com/en/product/t818-en/), [T598](https://support.thrustmaster.com/en/product/t598x-en/)). A driver package note says it "restored PC telemetry support on games using latest SDK" ([SF1000 product page](https://support.thrustmaster.com/en/product/ferrarisf1000addon-en/), snippet only).
- **"SDK Test"** is a Thrustmaster end-user diagnostic for Windows. Open it and press F5; the screen shows telemetry animations and the LEDs flash ([Help Center KB 1899](https://support.thrustmaster.com/en/kb/1899-en/), snippet). It's a test tool, not a developer kit.
- **No public developer SDK.** Several searches found no public download, docs, licence, partner programme or NDA terms. This is **uncertain**: it could exist privately. Studios clearly get it somehow, since ACC added native SF1000 display support in v1.8 ([Traxion](https://traxion.gg/thrustmaster-sf1000-display-support-coming-soon-to-assetto-corsa-competizione/)). Original Assetto Corsa has no native support that I could find.
- **Can a third-party app use it?** Not without Thrustmaster giving it out. Even if we had it, the terms are unknown.

**Community reverse-engineering over USB.**
- [Kimplul/hid-tmff2](https://github.com/Kimplul/hid-tmff2) is the Linux force-feedback driver; TS-PC support is experimental. It has nothing for SF1000, rim screens or LEDs, and says outright "There is currently no support for the built-in screen" (that note is about the T248).
- [Prodigal.Knight's SimHub LED plugin](https://gitlab.com/prodigal.knight/simhub-thrustmaster-wheel-led-controller) (MIT) controls rev LEDs over USB HID, but only on the **Ferrari 488 Challenge Edition**. The author asks for USB captures to add other rims. Packets are 64-byte reports starting `0x60 0x00 0x41 <cmd>`; the code itself calls the magic bytes "Meaning unknown". Last commit Dec 2023.
- [wKoja/thrustmaster-led-linux](https://github.com/wKoja/thrustmaster-led-linux) (GPL-3.0) is a Linux daemon built on the same protocol: LED bitmask command `0x02`, brightness `0x10`. It was tested on a **TS-PC + 488 rim** and says "the LED protocol is a property of the rim, not the base", so we can't assume the SF1000 uses the same packets. Its `documentation/DRIVER_ANALYSIS.md` is a Ghidra read of Thrustmaster's 2024 driver. It found screen functions in `tmHidUsb.sys` (`SetDisplayData`, `IsScreenForStreamingPresent`, `BandwidthScreenBytesPerSecond`) and rates the display "High difficulty". **Uncertain:** the doc reads machine-generated and only lists symbol names; it doesn't describe the packet format.
- An Arduino forum thread on emulating the SF1000 rim found nothing that worked ([forum.arduino.cc](https://forum.arduino.cc/t/emulating-thrustmaster-sf1000-rim/1173488)).
- **Bottom line:** nobody has published the SF1000 screen or LED protocol over USB.

**Which firmware supports Native mode.** Native mode has been available on PC since launch for supported games. Firmware V5.51 improved some F1 2020/2021 native info. V6.27 added F1 23 native screens. The latest is **V9.15** (V9.18 for Xbox Wi-Fi with driver package 2026.TTRS.2). Sources: [SF1000 product page](https://support.thrustmaster.com/en/product/ferrarisf1000addon-en/) and [ORD on v6.27](https://www.onlineracedriver.com/2023/09/21/thrustmaster-sf1000-firmware-update-v6-27-released/). Snippets only; not opened.

## 2. Wi-Fi UDP mode

**How it works.**
- The SF1000 has its own Wi-Fi and joins the home network. Its Wi-Fi screen shows `IP: x.x.x.x` and `UDP: 20777`. The sender sends F1-format UDP packets to **that IP, port 20777**. The wheel is the listener, so nothing needs to listen on the PC.
- The port can't be changed on the wheel ([overtake.gg user report](https://overtake.gg/threads/telemetry-tool-for-acc.187592/page-9)).
- Thrustmaster's Xbox guide lists port 20777 and UDP formats 2020 / 2023 / 2026, which must match the wheel ([KB 1786](https://support.thrustmaster.com/en/kb/1786-en/), snippet).
- Thrustmaster says UDP mode shows less telemetry than Native mode, and that latency depends on your home Wi-Fi ([KB 1784](https://support.thrustmaster.com/en/kb/1784-en/), snippet).
- Wi-Fi setup is in Thrustmaster's connection tutorial PDF ([ts.thrustmaster.com](https://ts.thrustmaster.com/download/accessories/Manuals/SF1000/iOS_FWheel_Add-On_Ferrari_SF1000Edition_Connection_Tutorial_EN.pdf); not opened).

**Firmware.** All of this is from the [SimHub-SF1000-UDP README](https://github.com/ducng99/SimHub-SF1000-UDP).
- Firmware **v5 and below**: UDP has to be turned on at the wheel after **every power-up**.
- Firmware **v6.27+**: UDP is always on, and the "UDP GAMES" menu was removed.
- The F1 23 format needs **v6.27+**. Older firmware has to use the F1 2020 format.
- A newer "2026" format is listed by Thrustmaster for F1 25 on Xbox (fw 9.18). We have no spec for how the wheel handles it, so **stay on F1 23**.

**Prior art: [ducng99/SimHub-SF1000-UDP](https://github.com/ducng99/SimHub-SF1000-UDP)** (MIT, C#; cloned and read, last commit 2026-10-24).
- It's a SimHub plugin built for games like Assetto Corsa. The author no longer maintains it: "Issues and PRs will be closed". Releases rebuild automatically.
- It doesn't start when the game is an F1 game (regex `^F120\d{2}$`), so it never clashes with a real F1 game's output.
- Defaults: wheel IP from settings, port 20777, send rate 120 Hz, F1 23 format, sends only while a game is running.
- Packet loops in `UDPServer.cs`:
  - Session (id 1): every 500 ms
  - LapData (2), CarTelemetry (6), CarStatus (7): every frame at the send rate
  - Participants (4): every 5 s
  - CarDamage (10, F1 23 only): every 100 ms
- Only car index 0 is filled; `m_playerCarIndex = 0`. Header: `packetFormat 2023, gameYear 23, major 1, minor 18, packetVersion 1, sessionUID 0`, and frameIdentifier counts up.
- Known wheel firmware bug: the **ERS bar** doesn't display properly. The plugin fixes `m_ersHarvestedThisLapMGUK=100, MGUH=1` because the wheel computes harvest % as MGUK/MGUH.
- The README doesn't say whether it can run next to other UDP output. As above, only one sender should talk to the wheel at a time.

Another SF1000 sender: wKoja's repo has a design note for one (`tm-led-daemon/TODO/sf1000-display.md`), but it's only a plan. It has errors too: it targets `127.0.0.1` and says the wheel listens "via Wi-Fi or USB", which disagrees with Thrustmaster (UDP is Wi-Fi only). Don't rely on it.

**What each display page shows.** I couldn't reach Thrustmaster's manuals, so there's no official list of pages. Reviews say:
- One dial switches between the basic dash and pages for tyres, fuel and ERS ([Traxion review](https://traxion.gg/thrustmaster-ferrari-sf1000-wheel-add-on-review/), [The Race](https://www.the-race.com/gaming/more-than-a-collectors-item-thrustmaster-f1-wheel-reviewed/)).
- The screen covers gear, rev lights, speed, lap/sector times and delta, tyre temps/wear, fuel, ERS/DRS, position/laps and flags.
- **The owner should note what each page shows on his wheel** (checklist).

**Alongside a game.** AC doesn't send F1 UDP, so the only possible clash is with another sender to the wheel (SimHub's plugin). Native mode needs Wi-Fi off, so Native and UDP can't both run at once ([KB 1784](https://support.thrustmaster.com/en/kb/1784-en/)). AC has no Native support anyway.

## 3. Other routes

- **SimHub.** I found no SF1000 support built into SimHub itself. The usual route is the community UDP plugin above ([Steam thread](https://steamcommunity.com/app/2440510/discussions/0/3881597531959365370/)).
- **Pitwall feeding SimHub.** This works: the [SimHubUDPConnector](https://github.com/markhannon/OfficialSimHubUDPConnector) plugin accepts JSON key/value data over UDP. But the SF1000 plugin reads SimHub's standard game data, not custom properties, so we'd still have to fork the C# plugin to show Pitwall values. That's more pieces, Windows-only C#, and a dependency on SimHub. **Not worth it.** Sending F1 packets straight from Pitwall is simpler.
- **SimHub on its own, as a stopgap.** It needs no Pitwall work and gives a working AC dash on the wheel today. Good for step 2 above.

## Packets Pitwall would send (F1 23 format, little-endian, packed)

- Spec: [EA F1 23 UDP Specification](https://answers.ea.com/t5/General-Discussion/F1-23-UDP-Specification/td-p/12632888).
- F1 2020 spec (archived): https://web.archive.org/web/20221127112921/https://forums.codemasters.com/topic/50942-f1-2020-udp-specification/
- Every packet is a 29-byte header plus arrays of **22 cars**. Fill car 0 and zero the rest.
- Byte sizes from memory of the spec, **verify against the spec or the plugin's structs**: Session 644, Lap 1131, Participants 1306, Telemetry 1352, Status 1239, Damage 953.

Header: `u16 packetFormat=2023, u8 gameYear=23, u8 major=1, u8 minor=18, u8 packetVersion=1, u8 packetId, u64 sessionUID, f32 sessionTime, u32 frameIdentifier, u32 overallFrameIdentifier, u8 playerCarIndex=0, u8 secondaryPlayerCarIndex=255`.

| Packet (id, rate) | Fields that matter (plugin's AC mapping) |
|---|---|
| **CarTelemetry (6), ~60–120 Hz** | `m_speed` (u16 km/h), `m_throttle`/`m_brake` (f32 0–1), `m_gear` (i8, N=0, R=-1), `m_engineRPM` (u16), `m_drs`, **`m_revLightsPercent` (u8 0–100, drives rev LEDs, inferred)**, `m_brakesTemperature[4]`, `m_tyresSurfaceTemperature[4]`, `m_tyresInnerTemperature[4]`, `m_engineTemperature`, `m_tyresPressure[4]` (wheel order RL, RR, FL, FR), trailer `m_mfdPanelIndex=255, m_mfdPanelIndexSecondaryPlayer=255, m_suggestedGear=0` |
| **CarStatus (7), ~60 Hz** | `m_tractionControl`, `m_antiLockBrakes`, `m_frontBrakeBias`, `m_pitLimiterStatus`, `m_fuelInTank`, `m_fuelCapacity`, `m_fuelRemainingLaps`, `m_maxRPM`, `m_idleRPM`, `m_maxGears`, `m_drsAllowed`, **`m_vehicleFiaFlags` (0 none, 1 green, 2 blue, 3 yellow; flag LEDs, inferred)**, `m_ersStoreEnergy`, `m_ersDeployMode`, `m_ersHarvestedThisLapMGUK=100`, `MGUH=1` (firmware workaround), `m_actualTyreCompound=16` |
| **LapData (2), ~60 Hz** | `m_lastLapTimeInMS`, `m_currentLapTimeInMS`, `m_sector1TimeInMS`/`Minutes`, `m_sector2TimeInMS`/`Minutes`, `m_deltaToCarInFrontInMS`, `m_lapDistance`, `m_totalDistance`, `m_carPosition`, `m_currentLapNum`, `m_pitStatus`, `m_sector`, `m_currentLapInvalid`, `m_driverStatus=4`, `m_resultStatus=2`, pit-lane timers |
| **Session (1), 2 Hz** | `m_trackTemperature`, `m_airTemperature`, `m_totalLaps`, `m_trackLength`, `m_sessionTimeLeft`, `m_gamePaused`, `m_pitSpeedLimit`; the plugin fixes the rest (`m_trackId=-1`, `m_gameMode=7`, `m_ruleSet=1`, units 1/0) |
| **CarDamage (10), 10 Hz** | `m_tyresWear[4]` (percent worn, f32), `m_tyresDamage[4]` (u8); everything else 0 |
| **Participants (4), 0.2 Hz** | `m_numActiveCars` only |

The plugin's AC-specific bits: rev % = (shift-light-1 + shift-light-2 + redline fraction)/3; ERS stored = ERSMax − stored; ERS mode from `KersInput`/`ErsPowerLevel`. Pitwall can compute rev % itself from AC's RPM and max RPM.

## Checklist for the owner (on the wheel and PC)

1. **Firmware.** Write down the SF1000 firmware number. It's on the wheel's info screen or in the Thrustmaster Control Panel. Below 6.27 means F1 2020 format and turning UDP on after each power-up. Updating to the latest (9.15) is the easy fix.
2. **Wi-Fi.** In the wheel menu, connect to your home Wi-Fi. The Wi-Fi screen should then show `IP: …` and `UDP: 20777`. Write down the IP. It's best to give it a fixed (reserved) address in your router.
3. **Modes offered.** Note which options the menu lists (Native / UDP / UDP GAMES / format choices like 2020/2023/2026).
4. **Pages.** With SimHub plus the SF1000 UDP plugin running in AC, turn the screen dial through every page. For each page, note what it shows, e.g. "page 2: tyre temps + wear, fuel laps". Photos of each page are ideal.
5. **LEDs.** Check that the rev LEDs light up through the rev range and that the side flag LEDs light under yellow or blue flags.
6. **Native check (optional).** In a game with native support (e.g. ACC), Wi-Fi off, confirm the screen works over USB. This just confirms Native mode works on your setup; Pitwall can't use it.
7. **Firewall.** Nothing should block outgoing UDP to the wheel. If nothing shows, check the PC and wheel are on the same network.

## Not verified

- Every hardware behaviour. Nothing was run against a wheel.
- Thrustmaster pages (support.thrustmaster.com, thrustmaster.com) and manuals.plus are blocked from this session. Claims sourced there come from search snippets only.
- What the LED fields do is inferred from the plugin's code.
- Packet byte sizes are from memory of the F1 23 spec.

---

## Built (2026-11-04)

Pitwall now sends the F1 23 packets itself (`rig/src/pitwall_rig/sf1000.py`): session (2 Hz), lap data, telemetry and status (every frame), damage (10 Hz) and participants (every 5 s), car 0 only. The packet layouts were checked against the SimHub plugin's structures (all six sizes match the spec: 644 / 1131 / 1306 / 1352 / 1239 / 953 bytes) and against a local listener standing in for the wheel. Settings → Controls → SF1000 wheel screen: switch on, enter the wheel's IP, "Send a test pattern" sweeps the rev lights, gears and speed.

**Not yet:** Pitwall's own values (live delta, time to beat, brake cue) on the wheel. That needs the page checklist above first: which F1 field each page shows, so we pick fields that can carry them (most F1 delta fields can't go negative).
