-- hypertile layout "quad". Plain Lua, edit freely.
-- 20/60/20 columns; the center is four fixed quadrants.
-- Fill order: 1 top-left, 2 top-right, 3 bottom-left, 4 bottom-right,
-- 5 right, 6 right (stacked), 7 left, 8 left (stacked); 9+ cycle from 1.
-- Every slot keeps its place when empty.

local hypertile = require("hypr.hypertile")

hypertile.layout("quad", {
  columns = {
    { name = "left", w = 0.2 },
    {
      w = 0.6,
      rows = {
        { columns = { { name = "tl" }, { name = "tr" } } },
        { columns = { { name = "bl" }, { name = "br" } } },
      },
    },
    { name = "right", w = 0.2 },
  },
  fill = { "tl", "tr", "bl", "br", "right", "right", "left", "left" },
  empty = "keep",
  single = "slot",
})
