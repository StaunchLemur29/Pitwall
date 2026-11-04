-- Just enough of CSP to run Pitwall.lua outside Assetto Corsa (used by harness.py).
--
-- The track is a pretend square (four straights), so a teleport has to turn
-- the car. Saved car states are plain tables. Where CSP's conventions are
-- unknown the fake picks the awkward one, so the app can't depend on them:
-- a saved state's matrix points backwards, and physics.setCarPosition takes
-- the direction reversed (as CSP's own apps call it).

NOW, TRACK_L, CAR_H, SAVE_OK = 0, 4000, 0.4, true
saved, loaded = 0, 0
os.preciseClock = function () return NOW end

local V = {}
V.__index = V
vec3 = function (x, y, z) return setmetatable({ x = x or 0, y = y or 0, z = z or 0 }, V) end
V.__add = function (a, b) return vec3(a.x + b.x, a.y + b.y, a.z + b.z) end
V.__sub = function (a, b) return vec3(a.x - b.x, a.y - b.y, a.z - b.z) end
V.__unm = function (a) return vec3(-a.x, -a.y, -a.z) end
V.__mul = function (a, k) return vec3(a.x * k, a.y * k, a.z * k) end
function V:length() return math.sqrt(self.x ^ 2 + self.y ^ 2 + self.z ^ 2) end
function V:normalize() local l = self:length(); return vec3(self.x / l, self.y / l, self.z / l) end
function V:dot(b) return self.x * b.x + self.y * b.y + self.z * b.z end
function V:clone() return vec3(self.x, self.y, self.z) end
function V:set(b) self.x, self.y, self.z = b.x, b.y, b.z; return self end
function V:cross(b) -- in place, like CSP's
  return self:set(vec3(self.y * b.z - self.z * b.y, self.z * b.x - self.x * b.z, self.x * b.y - self.y * b.x))
end
vec2 = function (x, y) return { x = x, y = y } end
rgbm = function (r, g, b, a) return { r = r, g = g, b = b, mult = a } end

-- Row-vector matrices like CSP's: point * A * B applies A, then B.
local M = {}
M.__index = M
local function mat(side, up, look, position)
  return setmetatable({ side = side, up = up, look = look, position = position }, M)
end
mat4x4 = {}
function mat4x4.translation(p) return mat(vec3(1, 0, 0), vec3(0, 1, 0), vec3(0, 0, 1), p:clone()) end
function M:transformVector(v) return self.side * v.x + self.up * v.y + self.look * v.z end
function M:transformPoint(v) return self:transformVector(v) + self.position end
function M:clone() return mat(self.side:clone(), self.up:clone(), self.look:clone(), self.position:clone()) end
function M:inverse() -- rigid transforms only
  local s, u, l, p = self.side, self.up, self.look, self.position
  return mat(vec3(s.x, u.x, l.x), vec3(s.y, u.y, l.y), vec3(s.z, u.z, l.z), vec3(-p:dot(s), -p:dot(u), -p:dot(l)))
end
M.__mul = function (a, b)
  return mat(b:transformVector(a.side), b:transformVector(a.up), b:transformVector(a.look), b:transformPoint(a.position))
end

-- The track: progress 0..1 round a square, starting at the origin.
local DIRS = { vec3(1, 0, 0), vec3(0, 0, 1), vec3(-1, 0, 0), vec3(0, 0, -1) }
local function sideOf(p)
  local s = TRACK_L / 4
  local d = (p - math.floor(p)) * TRACK_L
  local i = math.min(3, math.floor(d / s))
  return i, d - i * s, s
end
function line_at(p)
  local i, t, s = sideOf(p)
  local corner = ({ vec3(0, 0, 0), vec3(s, 0, 0), vec3(s, 0, s), vec3(0, 0, s) })[i + 1]
  return corner + DIRS[i + 1] * t
end
function line_dir(p) local i = sideOf(p); return DIRS[i + 1]:clone() end
local function progressOf(pos)
  local best, bestD = 0, math.huge
  for k = 0, 39999 do
    local q = k / 40000
    local d = (line_at(q) - vec3(pos.x, 0, pos.z)):length()
    if d < bestD then best, bestD = q, d end
  end
  return best
end

car = {
  splinePosition = 0, speedKmh = 180, gear = 4, absMode = 3, absModes = 12,
  tractionControlMode = 2, tractionControlModes = 8, brakeBias = 0.57,
  mgukDelivery = 1, mgukDeliveryCount = 4, mgukRecovery = 5, kersPresent = true,
  currentEngineBrakeSetting = 2, engineBrakeSettingsCount = 5,
  look = vec3(1, 0, 0), velocity = vec3(), position = vec3(0, CAR_H, 0),
}
local function syncCar()
  car.speedKmh = car.velocity:length() * 3.6
  local look = -car.look -- the awkward convention: see the top
  car.transform = mat(vec3(0, 1, 0):cross(look):normalize(), vec3(0, 1, 0), look, car.position:clone())
end
-- Drive: put the car at progress p, on the line, heading down the track.
function place(p, kmh, gear)
  NOW = NOW + 1 / 60
  car.splinePosition = p - math.floor(p)
  car.position = line_at(p) + vec3(0, CAR_H, 0)
  car.look = line_dir(p)
  car.velocity = car.look * ((kmh or 180) / 3.6)
  car.gear = gear or car.gear
  syncCar()
end
syncCar()

sim = { isReplayActive = false, isPaused = false }
local jumped = {}
local function jump(pos)
  car.position = pos:clone()
  car.splinePosition = progressOf(pos)
  syncCar()
  for _, fn in ipairs(jumped) do fn(0) end
end

ac = {
  getSim = function () return sim end,
  getCar = function () return car end,
  isCarResetAllowed = function () return true end,
  onCarJumped = function (i, fn) jumped[#jumped + 1] = fn end,
  trackProgressToWorldCoordinate = function (p) return line_at(p) end,
  storage = function (defaults) return defaults end,
  saveCarStateAsync = function (cb)
    saved = saved + 1
    if not SAVE_OK then return cb('not now', nil) end
    cb(nil, { tr = car.transform:clone(), vel = car.velocity:clone(), gear = car.gear })
  end,
  loadCarState = function (data, frames)
    loaded = loaded + 1
    car.look = -data.tr.look
    car.velocity = data.vel:clone()
    car.gear = data.gear
    jump(data.tr.position)
    return true
  end,
}

teleports = {}
physics = {
  setCarPosition = function (i, pos, dir)
    teleports[#teleports + 1] = { pos = pos, dir = dir }
    car.look = -dir
    car.velocity, car.gear = vec3(), 0 -- a plain move leaves you stopped in neutral
    jump(pos + vec3(0, CAR_H, 0))
  end,
}

local carsUtils = {
  getCarStateTransform = function (data) return data.tr:clone() end,
  alterCarStateTransform = function (data, t)
    return { tr = data.tr * t, vel = t:transformVector(data.vel), gear = data.gear }
  end,
  alterCarStateVelocity = function (data, v)
    return { tr = data.tr:clone(), vel = data.vel + v, gear = data.gear }
  end,
}
require = function (name) assert(name == 'shared/sim/cars', name); return carsUtils end

script = {}
