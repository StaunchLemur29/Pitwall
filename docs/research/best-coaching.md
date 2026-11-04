# The best coaching Pitwall could give

*Synthesis of [coaching.md](coaching.md) (coaching and motor-learning science), [learning-a-long-track.md](learning-a-long-track.md) (Nordschleife, measuring improvement), [coaching-apps.md](coaching-apps.md) (what Trophi, VRS, Track Titan, Delta, Garage 61 and others do) and [sim-racing.md](sim-racing.md) (AC, hardware). November 2026.*

**Caveat:** the research sessions couldn't open most web pages directly, so claims rest on search extracts and paper abstracts; each file says which. The ideas below don't depend on any single uncertain claim.

## The three big findings

1. **Pitwall's edge is real and specific.** No competitor has **drills** (section practice with retry and teleport), and every competitor measures you against **other people's laps**. Coaching for the original AC is thin and none of it suits a heavily modded install. Pitwall's optimal run (your car's learnt grip, any mod) and drills are things nobody else does. Lean into them.
2. **Less live feedback teaches more.** Feedback during or instantly after every lap helps in the moment and hurts lasting learning (Schmidt & Wulf 1997; Swinnen 1990). Best pattern: **one focus**, quiet while you're inside your usual range, a short summary after a few laps, and cues that **fade** as a corner is learnt.
3. **Measure the usual, not the PB.** Progress shows in your rolling median and spread through each section, not in the occasional best lap. Count every clean pass of a section, including laps you didn't finish. Plateaus are normal; the fix is to change *what* you practise, not do more laps.

## Ranked roadmap

Effort: S (small), M, L. Status as of tonight's pull requests.

| # | Idea | Why | Effort | Status |
|---|------|-----|--------|--------|
| 1 | **One focus per session**, shared by the side screen, drills and debrief | ADHD-friendly; the strongest common thread across coaching, apps and science | S | **Built** (#23 coach strip: session focus with Practise). Next: the debrief and drill card name the same focus. |
| 2 | **Drill straight from the focus**, never resetting, counting across sessions | Pitwall's unique edge; varied practice later | M | Drills never reset (#15), Practise on the focus (#23). Next: drill stats that carry across days. |
| 3 | **Count good sections of every lap** | One spin shouldn't erase 15 good sections (Nordschleife) | M | **Built** (#21 unfinished laps, per-corner clean/driven). |
| 4 | **Section medians + spread in the hub**, PB as a faint marker | Honest progress; detects plateaus | M | Not yet. Hub Progress shows laps; add per-section rolling median. |
| 5 | **Bandwidth feedback**: say nothing while a corner is within your usual | Less clutter, better learning | S | Partly (Good and bad ignores normal variation). Next: the brake cue/coach strip stay quiet inside the band. |
| 6 | **Fade the brake countdown** once a corner is learnt (a few clean laps in tolerance) | Guidance hypothesis: cues become a crutch | S | Not yet. Needs a setting; start conservative. |
| 7 | **Nordschleife named sections** (Hatzenbach, Flugplatz, Adenauer Forst, Fuchsröhre, Bergwerk, Karussell, Brünnchen…) as the unit for drills, stats and debriefs | How people actually learn the Ring | M | Chapters exist (pack); corner names need real track data to match AC's corners. |
| 8 | **Crest/blind-corner safety** on brake cues and targets | The optimal run doesn't know crests; brake before or after, never on it | M | Not yet. Needs crest detection from track height or the pack. |
| 9 | **Guess first**: one tap "which corner felt worst?" before the review | Error estimation trains self-coaching | S | Not yet. |
| 10 | **Positives first** in reviews and debriefs; keep "bad" to one item | Motivation without nagging | S | Partly (Good and bad shows both). Next: debrief prompt order. |
| 11 | **Corner phases** (braking, entry, apex, exit): show only the worst phase | Readable, actionable | M | Partly (notes name the cause). |
| 12 | **Opt-in spoken cue** for the focus corner only | Eyes stay on the road in dense sections | M | Not yet. Windows TTS for instant cues. |
| 13 | **Tyre pressure helper** (hot pressures vs window, one instruction) | Biggest easy setup win | M | Not yet; Pitwall has pressures and temps. |
| 14 | **Hardware checks**: FFB clipping, brake pedal | TS-PC / T-LCM tuning | S | **Built** (#29 Tools page). |
| 15 | **Mixed drills** once sections are learnt; a full "stitch" lap now and then | Varied practice retains better | M | Not yet. |
| 16 | **Show what practice earned** ("Flugplatz: −0.18 s since Tuesday", vs yourself) | Real, personal result | S | Partly (hub Progress). |
| 17 | **Effect-worded cues** ("carry speed to the exit kerb") in the debrief prompt | Free, may help a little | S | Prompt tweak. |
| 18 | **Manual external target** (paste a friend's / leaderboard time) | No usable leaderboard APIs for AC | S | Not yet; low priority. |

**Leave out** (from the research and your earlier decisions): leaderboards and community ghosts, setup marketplaces, widget-heavy overlays, copying any product's HUD style, car-system controls.

## Suggested next three

1. **Quiet by default** (#5 + #6): bandwidth + fading cues. Small, directly from the science, and it makes the side screen calmer.
2. **Section progress in the hub** (#4): rolling median + spread per section, the honest "am I getting better" view.
3. **Nordschleife sections done properly** (#7 + #8), ideally after a real recording from the rig so the names and crests line up with AC's track.
