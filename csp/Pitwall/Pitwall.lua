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
-- Transparent and empty most of the time: the brake point (and the corner it's
-- for) fade in as you approach, then disappear once you're past it.

local settings = ac.storage({
  showBrake = true, -- the brake countdown
  showCorner = true, -- the upcoming turn
  showDrill = true, -- short drill messages ("retry ready", "Go!")
  showFromM = 300, -- how far before the braking point it appears
})
local preview = false -- settings: show sample content to position the window

local WHITE = rgbm(0.95, 0.96, 0.97, 1)
local GREY = rgbm(0.75, 0.78, 0.82, 1)
local RED = rgbm(1, 0.32, 0.32, 1)
local ORANGE = rgbm(1, 0.35, 0.21, 1)
local alpha = 0 -- fades in and out
local lastShown = { corner = nil, brake = nil }
local wasReady = false

local function withAlpha(c, a) return rgbm(c.r, c.g, c.b, c.mult * a) end

local function outlined(text, size, colour, bold)
  if bold then ui.pushDWriteFont('@System;Weight=Bold') end
  ui.beginOutline()
  ui.dwriteText(text, size, colour)
  ui.endOutline(rgbm(0, 0, 0, 0.85 * alpha))
  if bold then ui.popDWriteFont() end
end

local function cornerLine(c)
  local bits = { c.dir .. c.grade .. '  ' .. c.label }
  if c.gear then bits[#bits + 1] = 'gear ' .. c.gear end
  if c.min_kmh then bits[#bits + 1] = string.format('%d km/h', math.floor(c.min_kmh + 0.5)) end
  return table.concat(bits, '  ·  ')
end

function script.windowMain(dt)
  local w = ui.windowWidth()
  local show, c, b = false, nil, nil
  if preview then
    show, c, b = true, { dir = 'R', grade = 3, label = 'Pouhon', gear = 3, min_kmh = 165 }, 140
  elseif connected and track then
    local p = car.splinePosition
    local cc, dist = nextCorner(p)
    if cc and dist and dist > 0 then
      local bb = brakeIn(cc, p, car.speedKmh)
      if bb and bb > -5 and bb < settings.showFromM then show, c, b = true, cc, bb end
    end
  end
  if show then lastShown.corner, lastShown.brake = c, b end
  alpha = math.max(0, math.min(1, alpha + (show and 6 or -3) * dt))

  -- Drill: say once when the run-up is saved, then keep quiet.
  local ready = drill and launch and launch.key == drill.key or false
  if ready and not wasReady and settings.showDrill then say('Retry ready: ' .. drill.name, 2.5) end
  wasReady = ready

  if alpha > 0 and lastShown.corner then
    local cc, bb = lastShown.corner, lastShown.brake
    if settings.showCorner then outlined(cornerLine(cc), 18, withAlpha(GREY, alpha), false) end
    if settings.showBrake and bb then
      local soon = bb < 120
      outlined(string.format('Brake  %d m', math.max(0, math.floor(bb + 0.5))), 30,
        withAlpha(soon and RED or WHITE, alpha), true)
      local y = ui.getCursorY() + 2
      local frac = math.max(0, math.min(1, 1 - bb / settings.showFromM))
      ui.drawRectFilled(vec2(8, y), vec2(w - 8, y + 6), rgbm(0, 0, 0, 0.45 * alpha), 3)
      ui.drawRectFilled(vec2(8, y), vec2(8 + (w - 16) * frac, y + 6), withAlpha(soon and RED or WHITE, alpha), 3)
      ui.dummy(vec2(w - 16, 10))
    end
  end
  if settings.showDrill and flash.text and os.preciseClock() < flash.untilT then
    local a0 = alpha
    alpha = 1
    outlined(flash.text, 16, ORANGE, true)
    alpha = a0
  end
end

function script.windowSettings(dt)
  if connected then
    ui.textColored('Connected to Pitwall', rgbm(0.24, 0.86, 0.52, 1))
  else
    ui.textColored('Pitwall isn\'t running: start scripts\\start.bat', RED)
  end
  if track == nil and connected then ui.text('Waiting for the track layout…') end
  ui.separator()
  if ui.checkbox('Show the brake point', settings.showBrake) then settings.showBrake = not settings.showBrake end
  if ui.checkbox('Show the upcoming turn', settings.showCorner) then settings.showCorner = not settings.showCorner end
  if ui.checkbox('Show drill messages', settings.showDrill) then settings.showDrill = not settings.showDrill end
  settings.showFromM = ui.slider('##from', settings.showFromM, 100, 600, 'Appear %.0f m before braking', 1)
  ui.separator()
  if ui.checkbox('Preview (to position the window)', preview) then preview = not preview end
end
