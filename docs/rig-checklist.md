# Rig checklist

What still has to be tried on the real rig. None of this can be checked without Assetto Corsa. Work down the list; each line says what to do and what you should see. If something's wrong, tell Claude which line.

Written 2026-11-16. Remove a line once it's confirmed.

## First: already on main

Pull the latest, run `scripts\start.bat`, pick a car and track you know. Drive 4 clean laps.

1. **The optimal run shows up at all.** Open the analysis window and click a corner. You should see a dotted "Optimal run" line in the speed chart and an "Optimal run" column in the table.
   - Before 16 November it could not work on real laps (pull request 52). If it's still missing after 4 clean laps, that's a bug.
2. **The optimal run has gears.** In the corner table, "Gear at the apex" has a number in the optimal column.
3. **Live tips.** Make the same mistake at the same corner on two laps (brake too early is easy). On the next lap, a tip should show on the straight before that corner, on the side screen and in the game. One a lap at most.
   - Turn it off or to side screen only: Settings → Coaching → Live tips.
4. **Blind spots.** After 6 laps, the analysis window has a "Blind spots" panel. Either it lists habits with a Practise button, or it says nothing is a habit.
5. **Section bests from older laps.** A track you drove before November: section bests should now include those laps.
6. **The hub.** Open the website. Your best lap compares with the optimal run, and the map colours against it.
7. **Weather.** If the side screen never mentions rain or the time of day when it should, the in-game app can't read them on your CSP version. Say so and Claude will check the names on your PC.

## Then: one pull request at a time

Merge one, try it, then the next. They don't depend on each other.

### 53: Optimal run models hills
- Drive Spa (or anywhere hilly) for 4 clean laps.
- **Eau Rouge:** the optimal run should no longer brake or lift where you're flat.
- **Braking points:** look at three corners. The optimal run's braking point should look reachable, not absurd.
- **Lap time:** the optimal run's lap time should be a few seconds quicker than your best, not level with it and not 10 seconds off.
- If any corner looks wrong, note the corner and what it asked for.

### 54: Advisor (brake bias, ABS, TC, tyre pressures)
- Drive 4 laps. Open Settings → Tools. The "Car setup" card is at the top.
- **Lock a front wheel on purpose** at the same corner on two laps. It should suggest more ABS, or brake bias to the rear.
- **Spin the rears on exit** on two laps. It should suggest more TC, or gentler throttle.
- **Change the brake bias.** The card should start again ("From your last 1 lap…").
- **False alarms:** if it reports lock-ups or wheelspin you didn't feel, say which corner. The thresholds have never seen your car.
- **Pit report:** come into the pits after the laps above. "Settings to try" should list the top two.
- Optional: type the car's ideal hot pressure on the card (Content Manager shows it in the setup's tyre tab).

### 55: Session timer
- The side screen's bottom line shows **Stint** counting up, and resets when you leave the pits.
- **In a race:** it shows your position and laps left (or time left). Check the laps-left number against the game's.
- **Break reminder** (off unless you turn it on): set Settings → Break reminder to 1 minute, drive 2 minutes. "Take a break" should show on straights only. Sit in the pits 5 minutes: it should be gone when you drive out.

### 58: DRS and battery tips
- In a car with DRS, leave it shut down the same straight on two laps. On the next lap a tip should show on that straight: "Open the DRS on the way to …".
- In a hybrid, run the battery flat before the same corner on two laps. The tip should say to save some earlier.

### 56: Blind spots on the hub
- Merge, drive a few laps so the PC uploads, then open the website on the MacBook.
- The analysis page has a "Blind spots" panel matching the PC's, without Practise buttons.
- On a phone it's under the corner list.
