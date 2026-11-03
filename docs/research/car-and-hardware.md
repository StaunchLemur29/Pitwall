# Research: RSS cars, TS-PC Racer, T-LCM pedals (2026-11)

What the owner's cars and hardware offer, and features Pitwall could add.

## Race Sim Studio (RSS) cars

Advanced RSS cars (Formula RSS hybrids, GT/prototype cars) carry the systems
a real car's wheel controls: brake bias and brake migration, ABS / TC
levels, diff settings, engine maps, DRS, and for hybrids ERS (MGU-K deploy
and recovery modes, battery charge, MGU-H mode). RSS's own buyer's guide
expects these on button boxes and rotaries ("MGU, brake bias, diff, and MFD
pages"). Brake migration shifts the brake bias as the pedal is pressed (peak
shift plus a "ramp" for where along the pedal travel it starts).

What Pitwall can read and change (confirmed in CSP's Lua API, used by CSP's
own apps):

- read: `car.drsPresent / drsAvailable / drsActive`, `car.kersPresent /
  kersCharge`, `car.mgukDelivery / mgukDeliveryCount / mgukRecovery`,
  `car.mguhChargingBatteries`, `car.currentEngineBrakeSetting /
  engineBrakeSettingsCount`, `car.fuelMap`, `car.absMode / tractionControlMode`,
  `car.brakeBias`
- change: `ac.setABS`, `ac.setTC`, `ac.setBrakeBias`,
  `ac.setEngineBrakeSetting`, `ac.setMGUKDelivery`, `ac.setMGUKRecovery`
- AC shared memory (no app needed) also has `drs`, `drsAvailable`,
  `drsEnabled`, `kersCharge`, `kersInput`, `ersRecoveryLevel`,
  `ersPowerLevel`, `ersIsCharging`, `engineBrake`.

Feature ideas:

1. **Car systems strip** (done, v0.3 app): the status line shows DRS
   (ready / open), battery %, deploy mode and engine-brake map for cars that
   have them.
2. **Energy and DRS in the lap analysis**: battery charge and DRS open/closed
   along the lap; "where you ran out of battery", "DRS available but not
   opened".
3. ~~Car systems on wheel buttons through Pitwall~~: dropped, AC's own
   controls already bind these directly.
4. **Car profile auto-detect**: which systems a car has (from the fields
   above), so lessons and the electronics advisor only talk about what exists.
5. **Brake migration / engine braking advice** per corner (phase 3+), once
   real data on them is recorded.

## Thrustmaster TS-PC Racer (wheelbase)

FFB is mostly tuned in game; in the Thrustmaster Control Panel, guides
consistently say BOOST off, and set overall strength around 75-100 % with
in-game gain tuned to avoid clipping. Rotation is left at max (AC sets each
car's steering lock). These figures come mostly from guides for other
Thrustmaster bases; TS-PC-specific numbers weren't confirmed.

Feature ideas:

1. **FFB clipping meter** (no app needed): AC shared memory has `finalFF`,
   the force sent to the wheel. Pitwall can show the % of each lap spent
   clipping, per car, and suggest a gain change ("clipping 9 % of the lap,
   mostly in Eau Rouge: lower gain to ~85 %"). Per-car gain matters with
   a heavily modded car list.
2. **TS-PC walkthrough** in Settings tools: Control Panel values, AC FFB
   settings, CSP FFB tweaks, with the clipping meter as the check.

## Thrustmaster T-LCM (load-cell pedals)

The brake is a load cell (force, not travel). Owners tune it with springs,
washers (preload) and the max brake force in Thrustmaster's calibration
software. The trade-off: heavier springs feel more like a real load-cell
pedal but are harder to modulate; lighter springs are easier but less
realistic. A common problem: the calibration force set too high, so 100 %
brake is rarely reached (or too low, so it's hit with every stomp).

Feature ideas:

1. **Pedal check from telemetry** (part of the blind-spot scan): peak brake
   per stop across a session. If you rarely reach ~95-100 %, suggest lowering
   the max force in the T-LCM software; if you sit at 100 % for long
   stretches, suggest raising it. Also braking consistency (spread of peak
   pressure at the same corner) and how smoothly you release.
2. **Trail-braking shape** in the corner breakdown: pressure over distance
   versus your best lap (the brake chart exists; add release-rate notes).
3. **T-LCM walkthrough** in Settings tools: springs, preload, calibration,
   then the pedal check to confirm.

## Sources

- RSS buyer's guide: https://store.racesimstudio.com/buyers-guide/
- Brake migration (CM guide): https://www.scribd.com/document/729800768/Manual
- AC EVO ERS / EBB guide (for how these systems behave): https://traxion.gg/assetto-corsa-evos-ferrari-sf-25-ers-guide/
- TS-PC AC settings: https://boxthislap.org/thrustmaster-ts-pc-ts-xw-assetto-corsa-settings/
- Thrustmaster FFB in AC: https://simracingsetup.com/assetto-corsa/assetto-corsa-thrustmaster-wheel-settings/
- TS-PC FFB thread: https://www.overtake.gg/threads/ffb-settings-for-thrustmaster-ts-pc-racer.216123/
- T-LCM owners' thread: https://www.gtplanet.net/forum/threads/thrustmaster-t-lcm-pedals.391822/
- CSP Lua (fields/setters as used by CSP's own apps): https://github.com/ac-custom-shaders-patch/acc-lua-internal
