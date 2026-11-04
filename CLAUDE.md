# Pitwall

A sim-racing coach and racing hub for one driver (the owner). `SPEC.md` is the plan and the record of decisions: read it before changing behaviour, and keep it current when a decision changes. `README.md` has setup, run and test commands.

## The owner

- Self-taught, ~600 h in Assetto Corsa (Content Manager + CSP + Pure, heavily modded, many RSS cars). Rig: Thrustmaster TS-PC with an SF1000 rim, T-LCM pedals, a 1080×1920 portrait second monitor. Uses a Windows PC for driving and a MacBook when the PC is off.
- Has ADHD: answers in plain language, short, most important first. Lead with what changed and what they need to do.
- Never give time estimates.
- Wants to be asked only when a decision is genuinely theirs; otherwise pick the sensible default and say so.
- Tests on the real rig; this environment can't run Assetto Corsa. Say plainly what was and wasn't verified.

## Working conventions

- One branch per piece of work, from the latest `main`; the owner merges pull requests. Before pushing to a branch, check whether its pull request is still open: once merged, follow-up work goes on a fresh branch and a new pull request.
- Verify before reporting: `rig` tests (`uv run pytest`), dashboard type-check, tests and build, and for the in-game app `csp/harness.py` (runs the Lua app outside AC against a live service). For UI changes, screenshot with Playwright and look.
- The in-game CSP app (`csp/Pitwall`) uses only CSP Lua APIs confirmed in CSP's own app sources; check there before using a new call.
- Things the owner turned down stay out: car-system controls from Pitwall (AC binds them itself), copying third-party HUD styles.
