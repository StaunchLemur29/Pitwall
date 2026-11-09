// Makes the README / portfolio screenshots (2560×1600, 16:10) from the demo car.
//
//   cd dashboard && npm run build      (the script serves dashboard/dist)
//   node docs/screenshots/make.js
//
// Needs uv (for the rig service) and Playwright with Chromium on this machine.
// It starts its own Pitwall service on port 8799 with a throwaway data folder,
// lets the demo car drive a dozen laps at 8× speed, takes raw screenshots and
// lays them out on a dark background. Images land next to this file.
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const OUT = __dirname;
const PORT = 8799;
const URL = `http://localhost:${PORT}`;
const LAPS = 10; // valid laps before shooting: enough for the optimal run
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pitwall-shots-"));
const raw = (n) => path.join(tmp, n);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForLaps(n) {
  for (let i = 0; i < 600; i++) {
    try {
      const laps = await (await fetch(`${URL}/api/laps`)).json();
      const valid = laps.filter((l) => l.valid).length;
      if (valid >= n) return;
      if (i % 10 === 0) console.log(`  ${valid}/${n} clean laps`);
    } catch {}
    await sleep(1000);
  }
  throw new Error("the demo car never finished enough laps");
}

// Wait for a live moment whose page text matches `want` (and not `avoid`).
async function waitForMoment(page, want, avoid = /CRASH/) {
  for (let i = 0; i < 400; i++) {
    const t = await page.evaluate(() => document.body.innerText);
    if (want(t) && !avoid.test(t)) return;
    await sleep(100);
  }
  console.warn("  didn't catch the moment; using whatever is on screen");
}

async function capture(browser) {
  const ctx = (w, h) => browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });

  // Live page 1: a brake countdown going into a corner.
  const live = await ctx(1080, 1920);
  await live.goto(URL);
  await sleep(2500);
  await waitForMoment(live, (t) => {
    const m = t.match(/Brake in\s*(\d+)\s*m/);
    return m && +m[1] > 50 && +m[1] < 110;
  });
  await live.screenshot({ path: raw("live1.png") });
  // Live page 2: lap timer, delta and tyres, mid-lap with a real delta.
  await live.keyboard.press("Control+Alt+ArrowRight");
  await sleep(1500);
  await waitForMoment(live, (t) => /LAP \d+\s*\n?\s*vs best/.test(t) && /0:[2-5]\d\./.test(t));
  await live.screenshot({ path: raw("live2.png") });

  // Analysis window (landscape), latest lap against your best.
  const ana = await ctx(1920, 1200);
  await ana.goto(`${URL}/#/analysis`);
  await sleep(4000);
  await ana.screenshot({ path: raw("analysis.png") });
  // Same with the optimal line on the lap map.
  await ana.getByText("+ Optimal line").click().catch(() => {});
  await sleep(1000);
  await ana.screenshot({ path: raw("analysis_line.png") });
  // Corner detail: the corner column (header, notes, close-up, charts).
  await ana.screenshot({ path: raw("corner.png"), clip: { x: 745, y: 110, width: 775, height: 1080 } });

  // Tools page: the two rig checks.
  const tools = await ctx(1920, 1200);
  await tools.goto(`${URL}/#/tools`);
  await sleep(2500);
  await tools.screenshot({ path: raw("tools.png"), clip: { x: 470, y: 10, width: 980, height: 372 } });
}

const CSS = `
html,body{margin:0;width:2560px;height:1600px;overflow:hidden}
body{background:radial-gradient(ellipse at 30% 20%,#1d2230 0%,#0b0d12 60%);
  font-family:Inter,system-ui,sans-serif;color:#fff;position:relative}
.title{position:absolute;left:110px;top:92px}
.title h1{margin:0;font-size:84px;letter-spacing:.18em;font-weight:800;display:flex;align-items:center;gap:28px}
.title h1 i{width:30px;height:30px;background:#ff4d2e;border-radius:6px;display:inline-block}
.title h2{margin:0;font-size:72px;font-weight:750;letter-spacing:-.01em}
.title p{margin:16px 0 0;font-size:38px;color:#a8adb9;max-width:820px;line-height:1.35}
.kicker{font-size:28px;letter-spacing:.2em;color:#ff4d2e;font-weight:700;margin-bottom:18px}
.shot{position:absolute;border-radius:22px;overflow:hidden;
  box-shadow:0 40px 120px rgba(0,0,0,.65),0 0 0 2px rgba(255,255,255,.08)}
.shot img{display:block;width:100%}`;

const title = (kicker, h, p) =>
  `<div class="title"><div class="kicker">${kicker}</div><h2>${h}</h2><p>${p}</p></div>`;
const shot = (img, style) => `<div class="shot" style="${style}"><img src="file://${raw(img)}"></div>`;

const LAYOUTS = {
  "hero.png": `
    <div class="title"><h1><i></i>PITWALL</h1><p>Live sim-racing coach for Assetto Corsa</p></div>
    ${shot("analysis.png", "left:110px;top:330px;width:1700px")}
    ${shot("live1.png", "right:110px;top:90px;width:760px")}`,
  "live.png": `
    ${title("WHILE YOU DRIVE", "The side screen", "On a portrait monitor next to the game: the next corner, a brake countdown and the road ahead, with your lap delta and tyres one button away.")}
    ${shot("live1.png", "left:1010px;top:110px;width:710px")}
    ${shot("live2.png", "left:1780px;top:110px;width:710px")}`,
  "analysis.png": `
    ${title("AFTER THE LAP", "Lap analysis", "Where the time went, corner by corner, against your best lap and the optimal line.")}
    ${shot("analysis_line.png", "left:420px;top:420px;width:2030px")}`,
  "corner.png": `
    ${title("EVERY CORNER", "Against the optimal run", "The racing line worked out from the track's edges, driven at your car's grip. Speed, brake and throttle side by side, and what to change.")}
    ${shot("corner.png", "right:110px;top:90px;width:1050px")}`,
  "tools.png": `
    ${title("RIG TOOLS", "Wheel and pedal checks", "Force-feedback clipping and brake-pedal habits, read from your recent laps.")}
    ${shot("tools.png", "left:110px;top:640px;width:2340px")}`,
};

async function compose(browser) {
  const page = await browser.newPage({ viewport: { width: 2560, height: 1600 } });
  for (const [name, body] of Object.entries(LAYOUTS)) {
    // A file:// page, so it may load the raw screenshots from disk.
    const html = path.join(tmp, "layout.html");
    fs.writeFileSync(html, `<!doctype html><meta charset="utf-8"><style>${CSS}</style>${body}`);
    await page.goto(`file://${html}`);
    await sleep(300);
    await page.screenshot({ path: path.join(OUT, name) });
    console.log(`  wrote docs/screenshots/${name}`);
  }
}

(async () => {
  const dist = path.join(ROOT, "dashboard/dist");
  if (!fs.existsSync(path.join(dist, "index.html"))) throw new Error("build the dashboard first: cd dashboard && npm run build");
  // Don't pop a dashboard window on this machine's monitors.
  fs.mkdirSync(path.join(tmp, "data"));
  fs.writeFileSync(path.join(tmp, "data/config.json"), JSON.stringify({ display: { open_browser: false } }));
  console.log("starting the demo car…");
  const rig = spawn(
    "uv",
    ["run", "pitwall-rig", "run", "--game", "demo", "--time-scale", "8", "--seed", "1",
     "--data-dir", path.join(tmp, "data"), "--port", String(PORT), "--static", dist],
    { cwd: path.join(ROOT, "rig"), stdio: "ignore" },
  );
  const browser = await chromium.launch();
  try {
    await waitForLaps(LAPS);
    console.log("taking screenshots…");
    await capture(browser);
    await compose(browser);
  } finally {
    await browser.close();
    rig.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
})().catch((e) => { console.error(e); process.exit(1); });
