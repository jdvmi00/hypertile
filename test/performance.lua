-- Repeatable CPU benchmark, separate from correctness tests (no timing gates).
-- Run: lua test/performance.lua [source-directory]
-- The optional directory lets the same workload measure another revision.
local source = arg[1] or "."
package.path = source .. "/?.lua;" .. package.path
local engine = require("hypertile")

local function benchmark(name, spec, windows, iterations)
  local provider = engine.provider(name, spec)
  local ctx = { area = { x = 0, y = 40, w = 4608, h = 1880 }, targets = {} }
  for i = 1, windows do
    ctx.targets[i] = {
      window = { address = tostring(i), workspace = { id = 1 } },
      box = {}, place = function(self, box) self.box = box end,
    }
  end
  provider.recalculate(ctx)
  local samples = {}
  for sample = 1, 5 do
    collectgarbage("collect")
    local start = os.clock()
    for _ = 1, iterations do provider.recalculate(ctx) end
    samples[sample] = (os.clock() - start) * 1e6 / iterations
  end
  table.sort(samples)
  print(string.format("%s,%d,%.2f", name, windows, samples[3]))
end

print("case,windows,median_us_per_recalculate")
for _, name in ipairs({ "welcome", "ultrawide", "quad" }) do
  local spec
  local recorder = { layout = function(_, value) spec = value end }
  local env = setmetatable({ require = function() return recorder end }, { __index = _G })
  assert(loadfile(source .. "/layouts/" .. name .. ".lua", "t", env))()
  for _, windows in ipairs({ 1, 4, 16, 64 }) do
    benchmark(name, spec, windows, 1000)
  end
end

-- A valid adversarial layout: all occupancy is at the bottom of a comb tree.
-- Its ancestors must not repeatedly rescan the same empty descendants.
local tree = { name = "last" }
for i = 1, 150 do tree = { columns = { { name = "s" .. i }, tree } } end
tree.single, tree.fill, tree.cycle = "slot", { "last" }, { "last" }
benchmark("deep-collapse", tree, 1, 200)
