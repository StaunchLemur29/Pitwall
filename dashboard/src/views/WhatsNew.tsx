/** What changed in Pitwall, newest first, in plain words: what it does and
 * anything you need to do. Add an entry at the top when a change ships. */
import { useEffect } from "react";

interface Entry {
  id: string; // unique, newest first; the newest one marks the page as read
  date: string;
  title: string;
  what: string[];
  todo?: string; // something you have to do yourself
}

export const NEWS: Entry[] = [
  {
    id: "2026-11-06-tips",
    date: "6 Nov 2026",
    title: "Live tips and blind spots",
    what: [
      "One short tip a lap on the straight before a corner: something that keeps going wrong this session, or your focus corner, always as something to do (\"Brake 12 m later\").",
      "Blind spots (analysis window): habits across your recent laps, like coasting or braking early, each with where it shows most and a drill.",
    ],
    todo: "Settings → Coaching → Live tips: on the side screen and in the game, side screen only, or off.",
  },
  {
    id: "2026-11-06-hub",
    date: "6 Nov 2026",
    title: "The hub catches up",
    what: [
      "The website compares your best lap with the optimal run and colours the map against it, like the PC.",
      "Section bests count drill runs and every lap, and older laps are filled in.",
      "Fixed: the website wasn't showing each lap's conditions or section bests.",
    ],
  },
  {
    id: "2026-11-05-goto",
    date: "5 Nov 2026",
    title: "Go there at speed, pit report",
    what: [
      "Go there now drops you in at your normal speed with warm tyres, from a pass earlier in the session (drive one normal lap first).",
      "Coming into the pits: a report on the stint (times, what kept going wrong, fuel per lap, wear, damage, what to work on next), and the AI debrief so far.",
      "A drill can be stopped while paused or in the pits.",
    ],
  },
  {
    id: "2026-11-05-coach",
    date: "5 Nov 2026",
    title: "The coach names the mistake",
    what: [
      "Slides you caught, spins, wrong gear and slow on the power, not just slow corners.",
      "Conditions with every lap (track and air temperature, grip, tyre wear, damage, time of day), and a notice when they change: a crash and what it damaged, dirty or worn tyres, the track, rain, dusk.",
      "Your best lap always has something faster to compare with, and a section's best counts from any lap, crashes and out laps included.",
    ],
  },
  {
    id: "2026-11-sf1000",
    date: "Nov 2026",
    title: "SF1000 wheel screen",
    what: ["The wheel's own F1 pages now work in AC: gear, rev lights, lap times, fuel, tyres, brake bias, ABS / TC, DRS."],
    todo: "Wheel firmware 6.27 or later, join Wi-Fi, UDP mode on. Then Settings → Controls → SF1000 wheel screen: IP, then Test.",
  },
  {
    id: "2026-11-tools",
    date: "Nov 2026",
    title: "Tools: force feedback and brake pedal",
    what: [
      "How often your force feedback clips, and at which corners.",
      "How you use the brake pedal: how hard you press, how often you hit full, how you release.",
    ],
    todo: "Open Tools (top of Settings) after a few clean laps.",
  },
  {
    id: "2026-11-coach",
    date: "Nov 2026",
    title: "Coach strip on the side screen",
    what: [
      "One thing to work on this session. It stays until you've got it right twice.",
      "After each lap: that lap's biggest mistake, briefly.",
      "A warning while the tyres are still cold.",
    ],
  },
  {
    id: "2026-11-compare",
    date: "Nov 2026",
    title: "Only compared with faster laps",
    what: [
      "Analysis never compares you with a slower lap. On your best lap it compares with the optimal run (the benchmark).",
      "Unfinished laps count too: the corners you drove well on a lap you didn't finish (the Nordschleife) are kept.",
      "Invalid laps are in the lap list, so you can see where they went wrong.",
    ],
  },
  {
    id: "2026-11-drills",
    date: "Nov 2026",
    title: "Drills: timer in the game, warm tyres",
    what: [
      "The in-game app shows the drill time as you go, the time to beat, then the result.",
      "After teleporting to a drill the tyres are put back to working temperature.",
      "DRS and battery only show up on cars that have them.",
    ],
  },
  {
    id: "2026-11-misc",
    date: "Nov 2026",
    title: "Smaller things",
    what: [
      "Fullscreen button (or F) on every page, on the PC and on the hub.",
      "Settings has one Coaching tab for everything about how you're coached.",
      "No stall crossing the line on long tracks; analysis is faster.",
    ],
  },
];

const SEEN_KEY = "pitwall.news.seen";

/** True when there's news you haven't opened yet. */
export function hasUnseenNews(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) !== NEWS[0]?.id;
  } catch {
    return false;
  }
}

export function WhatsNew() {
  useEffect(() => {
    try {
      localStorage.setItem(SEEN_KEY, NEWS[0]?.id ?? "");
    } catch {
      /* private window: nothing to remember */
    }
  }, []);
  return (
    <div className="settings news">
      <header className="settings__head">
        <a href="#/settings" className="settings__back">
          ← Settings
        </a>
        <h1>What's new</h1>
      </header>
      <div className="news__list">
        {NEWS.map((e) => (
          <section key={e.id} className="settings__card">
            <div className="news__date muted">{e.date}</div>
            <h3 className="news__title">{e.title}</h3>
            <ul>
              {e.what.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            {e.todo && (
              <p className="news__todo">
                <b>You:</b> {e.todo}
              </p>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
