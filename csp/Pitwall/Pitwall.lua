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
settings = nil -- overlay settings from Pitwall (see the window section)

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
    -- the car's other systems (whatever it has)
    drs_present = car.drsPresent, drs_available = car.drsAvailable, drs_active = car.drsActive,
    kers_present = car.kersPresent, kers_charge = car.kersCharge,
    mguk_delivery = car.mgukDelivery, mguk_delivery_count = car.mgukDeliveryCount, mguk_recovery = car.mgukRecovery,
    engine_brake = car.currentEngineBrakeSetting, engine_brake_count = car.engineBrakeSettingsCount,
    fuel_map = car.fuelMap,
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
    local o = d.overlay
    if type(o) == 'table' then
      settings = {
        showTurn = o.show_turn ~= false, showTurnName = o.show_turn_name ~= false,
        showBrake = o.show_brake ~= false, showFromM = tonumber(o.show_from_m) or 250,
      }
    end
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
local function signed(x) return wrap(x + 0.5) - 0.5 end

-- Positive before the braking point, negative just after it (so "BRAKE" can
-- hold for a moment); nil once past the apex or well past the point.
local BRAKE_HOLD_M = 40
local function brakeIn(c, p, speedKmh)
  if not c.brake_p then return nil end
  local d = signed(c.brake_p - p) * track.length_m
  if d < -BRAKE_HOLD_M or signed(c.apex - p) <= 0 then return nil end
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
-- A small centred pill, empty most of the time. Approaching a braking point it
-- fades in with the turn ahead and a countdown bar; at the braking point it
-- flashes BRAKE; once you're past, it fades away. Nothing else.

-- What to show is set in Pitwall's Settings (General > In-game overlay) and
-- arrives with each sync; these are the defaults until then.
settings = settings or { showTurn = true, showTurnName = true, showBrake = true, showFromM = 250 }
local preview = false -- settings: sample content, to position the window

local WHITE = rgbm(0.96, 0.97, 0.98, 1)
local DIM = rgbm(0.62, 0.66, 0.71, 1)
local RED = rgbm(1, 0.27, 0.23, 1)
local PANEL = rgbm(0.03, 0.035, 0.045, 0.72)
local alpha = 0
local held = { c = nil, b = nil } -- last thing shown, kept while fading out
local cueUntil = 0 -- BRAKE flash

local function fade(c, a) return rgbm(c.r, c.g, c.b, c.mult * a) end

local function ordinal(n)
  local suffix = ({ 'st', 'nd', 'rd' })[n] or 'th'
  return n .. suffix
end

function script.windowMain(dt)
  local W = ui.windowWidth()
  local now = os.preciseClock()
  local show, c, b = false, nil, nil
  if preview then
    show, c, b = true, { dir = 'R', grade = 2, label = 'Chicane 1', gear = 2 }, 112
  elseif connected and track then
    local p = car.splinePosition
    local cc, dist = nextCorner(p)
    if cc and dist then
      local bb = brakeIn(cc, p, car.speedKmh)
      if bb and bb < settings.showFromM then
        if bb <= 0 and (held.b or 1) > 0 then cueUntil = now + 0.8 end -- just reached it
        show, c, b = true, cc, bb
      end
    end
  end
  if show then held.c, held.b = c, b end
  alpha = math.max(0, math.min(1, alpha + (show and 8 or -4) * dt))
  if alpha <= 0 or not held.c or not (settings.showBrake or settings.showTurn) then return end
  c, b = held.c, held.b

  local PW = math.min(W - 8, 300)
  local x0 = (W - PW) / 2
  local rows = (settings.showTurn and 30 or 0) + (settings.showBrake and 26 or 0)
  ui.drawRectFilled(vec2(x0, 4), vec2(x0 + PW, 4 + rows + 12), fade(PANEL, alpha), 6)
  local y = 10

  if settings.showTurn then
    -- Rally style, centred as one group: [R2]  2nd  Chicane 1
    local tag = c.dir .. c.grade
    local gear = c.gear and ordinal(c.gear) or nil
    local name = settings.showTurnName and c.label or nil
    ui.pushDWriteFont('@System;Weight=Bold')
    local tw = ui.measureDWriteText(tag, 15).x + 10
    local gw = gear and ui.measureDWriteText(gear, 17).x or 0
    ui.popDWriteFont()
    local nw = name and ui.measureDWriteText(name, 17).x or 0
    local total = tw + (gear and 10 + gw or 0) + (name and 10 + nw or 0)
    local gx = (W - total) / 2
    ui.drawRectFilled(vec2(gx, y + 3), vec2(gx + tw, y + 23), fade(WHITE, alpha), 3)
    ui.setCursor(vec2(gx, y + 3))
    ui.pushDWriteFont('@System;Weight=Bold')
    ui.dwriteTextAligned(tag, 15, ui.Alignment.Center, ui.Alignment.Center, vec2(tw, 20), false, rgbm(0, 0, 0, alpha))
    local x = gx + tw + 10
    if gear then
      ui.setCursor(vec2(x, y + 1))
      ui.dwriteText(gear, 17, fade(WHITE, alpha))
      x = x + gw + 10
    end
    ui.popDWriteFont()
    if name then
      ui.setCursor(vec2(x, y + 1))
      ui.dwriteText(name, 17, fade(DIM, alpha))
    end
    y = y + 30
  end

  if settings.showBrake and b then
    if now < cueUntil or b <= 0 then
      ui.setCursor(vec2(x0, y - 4))
      ui.pushDWriteFont('@System;Weight=Bold')
      ui.dwriteTextAligned('BRAKE', 22, ui.Alignment.Center, ui.Alignment.Center, vec2(PW, 26), false, fade(RED, alpha))
      ui.popDWriteFont()
    else
      local close = b < 100
      local frac = math.max(0, math.min(1, 1 - b / settings.showFromM))
      local bx0, bx1 = x0 + 14, x0 + PW - 56
      ui.drawRectFilled(vec2(bx0, y + 8), vec2(bx1, y + 13), fade(rgbm(1, 1, 1, 0.14), alpha), 3)
      ui.drawRectFilled(vec2(bx0, y + 8), vec2(bx0 + (bx1 - bx0) * frac, y + 13), fade(close and RED or WHITE, alpha), 3)
      ui.setCursor(vec2(bx1 + 6, y))
      ui.dwriteTextAligned(string.format('%d', math.floor(b + 0.5)), 15, ui.Alignment.End, ui.Alignment.Center,
        vec2(PW - (bx1 - x0) - 20, 22), false, fade(close and RED or DIM, alpha))
    end
  end
end

function script.windowSettings(dt)
  if connected then
    ui.textColored('Connected to Pitwall', rgbm(0.24, 0.86, 0.52, 1))
  else
    ui.textColored('Pitwall isn\'t running: start scripts\\start.bat', RED)
  end
  if track == nil and connected then ui.text('Waiting for the track layout...') end
  ui.separator()
  ui.textWrapped('Choose what the overlay shows in Pitwall: Settings > General > In-game overlay.')
  ui.textWrapped('Keep this window open: it stays invisible until a braking point is coming up.')
  ui.separator()
  if ui.checkbox('Preview (to position the window)', preview) then preview = not preview end
end
