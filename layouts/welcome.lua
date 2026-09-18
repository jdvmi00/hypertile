-- hypertile layout "welcome". Written by hypertile-ctl; plain Lua, edit freely.
-- Select it with a workspace rule or SUPER+L: layout = "lua:welcome".

local hypertile = require("hypr.hypertile")

hypertile.layout("welcome", {
  rows = {
    {
      columns = {
        { name = "tl", stack = "h", id = "z-mu6bqqtw-jhyhw6fah5g7d6sa2z64v36fvyx65qqiz" },
        { name = "tr", stack = "h", id = "z-mu6bqqtw-65qa1a9fbrlhv4nar8u1ppd4h4evhz9pp118uvlv2g2v" },
      },
    },
    {
      columns = {
        { name = "bl", never_split = true, id = "z-mu6bqqtw-d39oj5lwxuocm16ufirouzy" },
        { name = "br", never_split = true, id = "z-mu6bqqtw-mh2sxy16u3wmhykx91g5bddalh0ifh3e" },
      },
    },
  },
  fill = { "tl", "tr", "bl", "br" },
  rounding = 20,
  empty = "keep",
  single = "slot",
  layout_id = "z-mu6bqqtw-d0ywy8ykb358a6xry7prmbmqxj3c8pczn",
})
