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
-- Getting to a drill: "teleport" parks the car, stopped, on the racing line at
-- the point the service picked (far enough back to be up to speed by the
-- section). Only to get there; retries are the rewind above. Teleporting resets
-- the car, so the tyres are put back to working temperature straight after.

local RIG = 'http://127.0.0.1:8765'
local SYNC_EVERY = 0.1
local SHOW_BRAKE_M = 300

local sim = ac.getSim()
local car = ac.getCar(0)

local track = nil -- { version, length_m, corners = {...}, ref_speed = {...} }
local drill = nil -- { key, name, start_p, end_p, run_up_p }
local launch = nil -- { key, data } car state saved at the run-up point
local settle = nil -- just teleported: { pos, dir, frames, flipped, tyreTemp }
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

-- -- teleport to a drill -------------------------------------------------------

local function wrap01(x) return x - math.floor(x) end

-- A point on the racing line (the track's AI spline) and the way along it.
local function lineAt(p)
  local len = track and track.length_m or sim.trackLengthM or 5000
  local pos = ac.trackProgressToWorldCoordinate(wrap01(p))
  local dir = ac.trackProgressToWorldCoordinate(wrap01(p + 5 / len)) - pos
  if dir:length() < 0.01 then return nil end
  return pos, dir:normalize()
end

-- The tyre temperature to arrive with: the car's optimum if CSP says, else what
-- they're at now (warmed by driving). Read defensively: not every CSP has these.
local function arrivalTyreTemp()
  local ok, t = pcall(function ()
    local sum, n = 0, 0
    for i = 0, 3 do
      local w = car.wheels[i]
      local v = w.tyreOptimumTemperature
      if not v or v < 40 then v = w.tyreCoreTemperature end
      if v and v >= 40 then sum, n = sum + v, n + 1 end
    end
    return n > 0 and sum / n or nil
  end)
  return ok and t or nil
end

-- Teleporting resets the car, tyres stone cold: put them back to temperature.
-- physics.setTyresTemperature is in CSP's own debug app (CspDebug); guarded in
-- case this CSP doesn't have it. Returns 'warm', 'no_temp' or 'unsupported'.
local function warmTyres(temp)
  if not temp then return 'no_temp' end
  if not (physics.setTyresTemperature and ac.Wheel and ac.Wheel.All) then return 'unsupported' end
  local ok = pcall(physics.setTyresTemperature, 0, ac.Wheel.All, temp)
  return ok and 'warm' or 'unsupported'
end

local function teleport(p)
  if not (physics and physics.setCarPosition and ac.trackProgressToWorldCoordinate) then return 'unsupported' end
  local pos, dir = lineAt(p)
  if not pos then return 'no_line' end
  local temp = arrivalTyreTemp() -- before the reset cools them
  -- CSP's own debug app passes the direction reversed; if the car still comes
  -- out facing backwards it's turned round on the next frame (see settleStep)
  physics.setCarPosition(0, pos, -dir)
  settle = { pos = pos, dir = dir, frames = 3, flipped = false, tyreTemp = temp }
  settle.tyres = warmTyres(temp)
  lastSpline = nil
  return nil
end

local function settleStep()
  local st = settle
  if not st.flipped and car.look:dot(st.dir) < 0 then
    physics.setCarPosition(0, st.pos, st.dir)
    st.flipped = true
  end
  warmTyres(st.tyreTemp) -- again for a few frames: the reset can land after the first go
  st.frames = st.frames - 1
  if st.frames <= 0 then settle = nil end
end

local function handle(cmd)
  if cmd.cmd == 'teleport' then
    if not ac.isCarResetAllowed() then
      events[#events + 1] = { type = 'teleport', ok = false, reason = 'not_allowed' }
      say('Teleport only works in offline practice')
    else
      local why = teleport(tonumber(cmd.p) or 0)
      events[#events + 1] = { type = 'teleport', ok = why == nil, reason = why, tyres = settle and settle.tyres or nil }
      if settle and settle.tyres ~= 'warm' then say('Teleported: tyres are cold, this CSP can\'t warm them') end
    end
  end
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
  if settle then
    settleStep()
    lastSpline = nil
    return
  end
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

local WHITE = rgbm(0.933, 0.941, 0.953, 1) -- dashboard --text
local DIM = rgbm(0.62, 0.66, 0.71, 1)
local RED = rgbm(1, 0.322, 0.322, 1) -- dashboard --bad
local PANEL = rgbm(0.03, 0.035, 0.045, 0.72)
local alpha = 0
local held = { c = nil, b = nil } -- last thing shown, kept while fading out
local cueUntil = 0 -- BRAKE flash

local function fade(c, a) return rgbm(c.r, c.g, c.b, c.mult * a) end


-- Looks like the dashboard: its card colours, its font (Inter, bundled in
-- ./fonts) and its exact turn arrows (rendered from the dashboard to ./icons,
-- one per direction and severity: tighter bends for sharper corners).
local FONT_MEDIUM = 'Inter:./fonts;Weight=Medium'
local FONT_BOLD = 'Inter:./fonts;Weight=Bold'
local FONT_HEAVY = 'Inter:./fonts;Weight=ExtraBold'
local CARD = rgbm(0.055, 0.067, 0.082, 0.86)
local EDGE = rgbm(0.12, 0.145, 0.173, 1)
local TRACK = rgbm(0.114, 0.137, 0.169, 1)
local MUTED = rgbm(0.545, 0.58, 0.63, 1)

local function icon(dir, grade)
  return string.format('icons/turn_%s%d.png', dir == 'L' and 'L' or 'R', math.max(1, math.min(6, grade or 4)))
end

local function text(str, font, size, x, y, w, h, align, colour)
  ui.pushDWriteFont(font)
  ui.setCursor(vec2(x, y))
  ui.dwriteTextAligned(str, size, align, ui.Alignment.Center, vec2(w, h), false, colour)
  ui.popDWriteFont()
end

function script.windowMain(dt)
  local W = ui.windowWidth()
  local now = os.preciseClock()
  local show, c, b = false, nil, nil
  if preview then
    show, c, b = true, { dir = 'R', grade = 2, label = 'Chicane 1', gear = 2 }, 160
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

  -- card
  local PW, PAD = 200, 16
  local x0 = (W - PW) / 2
  local turnH = settings.showTurn and (75 + (settings.showTurnName and 22 or 0)) or 0
  local brakeH = settings.showBrake and (settings.showTurn and 34 or 26) or 0
  local H = 14 + turnH + brakeH + 12
  ui.drawRectFilled(vec2(x0, 1), vec2(x0 + PW, 1 + H), fade(CARD, alpha), 8)
  ui.drawRect(vec2(x0, 1), vec2(x0 + PW, 1 + H), fade(EDGE, alpha), 8)
  local y = 15

  if settings.showTurn then
    -- arrow, gear beside it, centred as a pair
    local IW, IH = 84, 75
    ui.pushDWriteFont(FONT_HEAVY)
    local gw = c.gear and ui.measureDWriteText(tostring(c.gear), 54).x or 0
    ui.popDWriteFont()
    local gx = (W - (IW + (c.gear and 14 + gw or 0))) / 2
    ui.drawImage(icon(c.dir, c.grade), vec2(gx, y), vec2(gx + IW, y + IH), fade(WHITE, alpha))
    if c.gear then text(tostring(c.gear), FONT_HEAVY, 54, gx + IW + 14, y, gw + 4, IH, ui.Alignment.Start, fade(WHITE, alpha)) end
    y = y + IH
    if settings.showTurnName then
      text(string.upper(c.label), FONT_BOLD, 12, x0, y + 2, PW, 18, ui.Alignment.Center, fade(MUTED, alpha))
      y = y + 22
    end
    y = y + 8
  end

  if settings.showBrake and b then
    if now < cueUntil or b <= 0 then
      text('BRAKE', FONT_HEAVY, 24, x0, y, PW, 26, ui.Alignment.Center, fade(RED, alpha))
    else
      local close = b < 100
      local accent = close and RED or WHITE
      local frac = math.max(0, math.min(1, 1 - b / settings.showFromM))
      local bx0, bx1 = x0 + PAD, x0 + PW - PAD - 42
      ui.drawRectFilled(vec2(bx0, y + 10), vec2(bx1, y + 16), fade(TRACK, alpha), 3)
      ui.drawRectFilled(vec2(bx0, y + 10), vec2(bx0 + (bx1 - bx0) * frac, y + 16), fade(accent, alpha), 3)
      text(string.format('%d', math.floor(b + 0.5)), FONT_BOLD, 15, bx1, y, 42, 26, ui.Alignment.End,
        fade(close and RED or MUTED, alpha))
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
