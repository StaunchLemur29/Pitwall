-- Pitwall in-game companion (CSP Lua app).
--
-- Talks to the Pitwall service on this PC (http://127.0.0.1:8765):
--   * every 0.1 s: POST /api/csp/sync with the real ABS / TC levels and brake
--     bias; gets back the current drill and any commands (e.g. "retry");
--   * when the track changes: GET /api/csp/track for corners, braking points
--     and the reference lap's speed, so the next corner and brake countdown
--     are worked out here every frame, with no lag.
-- Drill retry: when you pass the drill's run-up point the car's full state is
-- saved; "retry" loads it back, putting you there at speed.

local RIG = 'http://127.0.0.1:8765'
local SYNC_EVERY = 0.1
local SHOW_BRAKE_M = 300

local sim = ac.getSim()
local car = ac.getCar(0)

local track = nil -- { version, length_m, corners = {...}, ref_speed = {...} }
local drill = nil -- { key, name, start_p, end_p, run_up_p }
local launch = nil -- { key, data } car state saved at the run-up point
local connected = false
local syncBusy, trackBusy = false, false
local trackVersion = -1
local events = {}
local lastSpline = nil
local shift = { corner = nil, m = 0 } -- braking point shift for approach speed
local flash = { text = nil, untilT = 0 }

web.timeouts(500, 500, 1000, 1000)

local function say(text, seconds)
  flash.text, flash.untilT = text, os.preciseClock() + (seconds or 3)
end

-- -- talking to the Pitwall service -------------------------------------------

local function loadTrack(version)
  if trackBusy then return end
  trackBusy = true
  web.get(RIG .. '/api/csp/track', function (err, res)
    trackBusy = false
    if err or not res or res.status ~= 200 then return end
    local t = JSON.parse(res.body)
    if type(t) == 'table' and t.corners then
      track = t
      trackVersion = version
    else
      track = nil
    end
  end)
end

local function handle(cmd)
  if cmd.cmd == 'retry' then
    if not ac.isCarResetAllowed() then
      events[#events + 1] = { type = 'retry', ok = false, reason = 'not_allowed' }
      say('Retry only works in offline practice')
    elseif not launch or launch.key ~= cmd.key then
      events[#events + 1] = { type = 'retry', ok = false, reason = 'no_state' }
    elseif ac.loadCarState(launch.data, 30) then
      lastSpline = nil
      events[#events + 1] = { type = 'retry', ok = true }
      say('Go!', 2)
    else
      events[#events + 1] = { type = 'retry', ok = false, reason = 'load_failed' }
    end
  end
end

local function sync()
  if syncBusy then return end
  syncBusy = true
  local body = JSON.stringify({
    app_version = '0.1',
    abs = car.absMode, abs_modes = car.absModes,
    tc = car.tractionControlMode, tc_modes = car.tractionControlModes,
    bb = car.brakeBias,
    reset_allowed = ac.isCarResetAllowed(),
    has_launch = launch ~= nil and drill ~= nil and launch.key == drill.key,
    events = events,
  })
  events = {}
  web.post(RIG .. '/api/csp/sync', { ['Content-Type'] = 'application/json' }, body, function (err, res)
    syncBusy = false
    if err or not res or res.status ~= 200 then
      connected = false
      return
    end
    connected = true
    local d = JSON.parse(res.body)
    if type(d) ~= 'table' then return end
    drill = type(d.drill) == 'table' and d.drill or nil
    if launch and (not drill or launch.key ~= drill.key) then launch = nil end
    if d.track_version == -1 then
      track = nil
      trackVersion = -1
    elseif d.track_version ~= trackVersion then
      loadTrack(d.track_version)
    end
    for _, c in ipairs(d.commands or {}) do handle(c) end
  end)
end

setInterval(sync, SYNC_EVERY)

-- -- track maths (same as the Pitwall service, done locally every frame) ------

local function wrap(x) return x - math.floor(x) end

-- The corner you're in, or the next one; and how far away its entry is (m).
local function nextCorner(p)
  if not track or #track.corners == 0 then return nil, nil end
  local best, bestD = nil, math.huge
  for _, c in ipairs(track.corners) do
    local inside
    if c.entry <= c.exit then inside = p >= c.entry and p <= c.exit
    else inside = p >= c.entry or p <= c.exit end
    if inside then return c, 0 end
    local d = wrap(c.entry - p)
    if d < bestD then best, bestD = c, d end
  end
  return best, bestD * track.length_m
end

local function refSpeed(p)
  local s = track and track.ref_speed
  if not s or #s == 0 then return nil end
  return s[math.floor(wrap(p) * #s) + 1]
end

-- Metres to the braking point, moved earlier or later by how fast you're
-- arriving compared with your reference lap.
local function brakeIn(c, p, speedKmh)
  if not c.brake_p then return nil end
  local d = wrap(c.brake_p - p) * track.length_m
  if shift.corner ~= c.n then shift.corner, shift.m = c.n, 0 end
  local ve, vmin, mp, now = c.entry_kmh, c.min_kmh, c.min_p, refSpeed(p)
  if ve and vmin and mp and now and ve - vmin >= 15 then
    local dRef = wrap(mp - c.brake_p) * track.length_m
    if dRef > 5 and dRef < 600 then
      local vb = math.max(vmin + 1, ve + (speedKmh - now))
      local dYou = dRef * (vb * vb - vmin * vmin) / (ve * ve - vmin * vmin)
      local limit = math.min(80, 0.5 * dRef)
      local target = math.max(-limit, math.min(limit, dYou - dRef))
      shift.m = shift.m + (target - shift.m) * 0.2
    end
  end
  return d - shift.m
end

-- -- drill: save the car at the run-up point ------------------------------------

ac.onCarJumped(0, function () lastSpline = nil end)

local function crossed(a, b, x)
  -- moving forward from a to b (allowing for the line) passes x
  local span = wrap(b - a)
  return span > 0 and span < 0.05 and wrap(x - a) <= span
end

function script.update(dt)
  if sim.isReplayActive or sim.isPaused then return end
  local p = car.splinePosition
  if drill and lastSpline and car.speedKmh > 20 and crossed(lastSpline, p, drill.run_up_p) then
    local key = drill.key
    ac.saveCarStateAsync(function (err, data)
      if data and drill and drill.key == key then
        launch = { key = key, data = data }
      end
    end)
  end
  lastSpline = p
end

-- -- the window ----------------------------------------------------------------

local WHITE = rgbm(0.93, 0.94, 0.95, 1)
local GREY = rgbm(0.55, 0.58, 0.63, 1)
local RED = rgbm(1, 0.32, 0.32, 1)
local ORANGE = rgbm(1, 0.35, 0.21, 1)
local TRACK_BG = rgbm(1, 1, 1, 0.08)

function script.windowMain(dt)
  local w = ui.windowWidth()
  if not connected then
    ui.dwriteText('Pitwall isn’t running', 16, GREY)
    ui.dwriteText('Start it with scripts\\start.bat', 13, GREY)
    return
  end
  if not track then
    ui.dwriteText('Waiting for the track layout…', 15, GREY)
    return
  end

  local p = car.splinePosition
  local c, dist = nextCorner(p)
  if c then
    ui.pushDWriteFont('@System;Weight=Bold')
    ui.dwriteText(c.dir .. c.grade .. '  ' .. c.label, 24, WHITE)
    ui.popDWriteFont()
    local bits = {}
    if dist and dist > 0 then bits[#bits + 1] = string.format('%d m', math.floor(dist + 0.5)) else bits[#bits + 1] = 'in corner' end
    if c.gear then bits[#bits + 1] = 'gear ' .. c.gear end
    if c.min_kmh then bits[#bits + 1] = string.format('%d km/h', math.floor(c.min_kmh + 0.5)) end
    ui.dwriteText(table.concat(bits, '  ·  '), 15, GREY)

    local b = dist and dist > 0 and brakeIn(c, p, car.speedKmh) or nil
    if b and b > -5 and b < SHOW_BRAKE_M then
      local soon = b < 120
      ui.pushDWriteFont('@System;Weight=Bold')
      ui.dwriteText(string.format('Brake in %d m', math.max(0, math.floor(b + 0.5))), 20, soon and RED or WHITE)
      ui.popDWriteFont()
      local y = ui.getCursorY() + 2
      local frac = math.max(0, math.min(1, 1 - b / SHOW_BRAKE_M))
      ui.drawRectFilled(vec2(8, y), vec2(w - 8, y + 8), TRACK_BG, 4)
      ui.drawRectFilled(vec2(8, y), vec2(8 + (w - 16) * frac, y + 8), soon and RED or GREY, 4)
      ui.dummy(vec2(w - 16, 12))
    end
  end

  if drill then
    local ready = launch and launch.key == drill.key
    ui.dwriteText('Drill: ' .. drill.name .. (ready and '  ·  retry ready' or '  ·  drive through once'), 13,
      ready and ORANGE or GREY)
  end
  if flash.text and os.preciseClock() < flash.untilT then
    ui.dwriteText(flash.text, 15, ORANGE)
  end
end
