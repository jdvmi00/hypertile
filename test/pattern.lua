package.path = "./?.lua;" .. package.path
local matcher = require("hypertile-pattern")
local checked = 0
local function compare(pattern, subject)
  local expected = string.find(subject, pattern) ~= nil
  local actual, limited = matcher.matches(matcher.compile(pattern), subject)
  assert(not limited and actual == expected, string.format("pattern %q subject %q: expected %s, got %s (limited=%s)",
    pattern, subject, tostring(expected), tostring(actual), tostring(limited)))
  checked = checked + 1
end

local subjects = { "", "a", "b", "ab", "aab", "aaa", "aaaa", "abcd", "12 aa!", "C++ [IDE]", "()", "(a(b)c)",
  "<a><b>", "[[]]", "é", "\0a\255", "a?+-*$^", "a\na", "]-a" }
local patterns = { "", "^", "$", "^$", "abc", "^a", "a$", "^a$", "a.a", "a.-a", "a?a?b", "a**", "[a-z]+",
  "[^a]*b", "[]a]+", "[^]a]+", "[a%-z]", "[a-z%d]+", "^C%+%+ %[IDE%]$", "%z", "%Z", "%A", "%q",
  "%f[%a]%a+", "%f[%z]$", "%f[^%a]", "%f[\0]", "%b()", "%b[]", "%b<>%b<>", "%bxx", "%b()?", "%f[%a]*",
  "(a*)%1", "((a?)b)%1%2", "(a-)(a*)%2%1", "a*(a)%1", "()(a)%2", "()%1", "(a?)a%1", "(%a+)%s+%1", "(.*)%1$" }
for _, pattern in ipairs(patterns) do for _, subject in ipairs(subjects) do compare(pattern, subject) end end

-- Compare all bytes with native Lua's character classes, ranges and escapes.
for _, class in ipairs({ "%a", "%c", "%d", "%g", "%l", "%p", "%s", "%u", "%w", "%x", "%z",
  "%A", "%C", "%D", "%G", "%L", "%P", "%S", "%U", "%W", "%X", "%Z", "[%a%d_]", "[^%s]", "[\0-\255]" }) do
  for byte = 0, 255 do compare(class, string.char(byte)) end
end

-- Small randomized patterns have a cheap native oracle; adversarial inputs
-- below are deliberately never passed to the unbounded native matcher.
math.randomseed(537)
local atoms, suffixes = { "a", "b", ".", "%d", "[ab]", "[^b]", "%a" }, { "", "?", "*", "+", "-" }
for _ = 1, 1500 do
  local pattern = math.random(2) == 1 and "^" or ""
  for _ = 1, math.random(1, 4) do pattern = pattern .. atoms[math.random(#atoms)] .. suffixes[math.random(#suffixes)] end
  if math.random(2) == 1 then pattern = pattern .. "$" end
  local subject = ""
  for _ = 1, math.random(0, 8) do local i = math.random(3); subject = subject .. (i == 1 and "a" or i == 2 and "b" or "1") end
  compare(pattern, subject)
end

-- Nested captures and alternatives created by greedy/lazy repetition must
-- restore the capture state when a later backreference fails.
for _ = 1, 1500 do
  local a = atoms[math.random(#atoms)] .. suffixes[math.random(#suffixes)]
  local b = atoms[math.random(#atoms)] .. suffixes[math.random(#suffixes)]
  local pattern = "((" .. a .. ")" .. b .. ")%" .. math.random(1, 2) .. "$"
  local subject = ""
  for _ = 1, math.random(0, 8) do subject = subject .. (math.random(2) == 1 and "a" or "b") end
  compare(pattern, subject)
end

for _, pattern in ipairs({ "a*a*a*a*b", "a?a?a?a?a?a?a?a?a?a?aaaaaaaaaab", "%b()x", "(a*)%1b" }) do
  local budget = { remaining = 50 }
  local _, limited = matcher.matches(matcher.compile(pattern), string.rep("a", 128), budget)
  assert(limited and budget.remaining == 0, "budget bounds " .. pattern)
end
local budget = { remaining = 4 }
assert(matcher.matches(matcher.compile("^ab$"), "ab", budget))
assert(matcher.matches(matcher.compile("^ab$"), "ab", budget))
local found, limited = matcher.matches(matcher.compile("^ab$"), "ab", budget)
assert(not found and limited and budget.remaining == 0, "multiple matches share one total budget")
found, limited = matcher.matches(matcher.compile("^a$"), string.rep("a", matcher.MAX_SUBJECT + 1))
assert(not found and limited, "oversized subjects have a bounded failure")
assert(not pcall(matcher.compile, string.rep("a", matcher.MAX_PATTERN + 1)), "oversized patterns rejected during compilation")
assert(matcher.matches(matcher.compile("^ab$"), "ab"), "a later calculation gets a fresh budget")
print("bounded patterns: " .. checked .. " native-oracle comparisons and budget checks passed")
