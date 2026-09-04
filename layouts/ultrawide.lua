-- hypertile layout "ultrawide". Plain Lua, edit freely.
-- 20/60/20 columns. Fill order: 1 center, 2 right, 3 left, then
-- right, left, center repeating (stacked vertically within a column).
-- `empty = "keep"` and `single = "slot"` keep a lone window in the center.

local hypertile = require("hypr.hypertile")

hypertile.layout("ultrawide", {
  columns = {
    { name = "left", w = 0.2 },
    { name = "center", w = 0.6 },
    { name = "right", w = 0.2 },
  },
  fill = { "center", "right", "left" },
  cycle = { "right", "left", "center" },
  empty = "keep",
  single = "slot",
})
