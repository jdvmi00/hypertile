-- Boolean Lua-pattern matching with bounded work. Native string.find cannot
-- be interrupted by a Lua instruction hook while its C matcher backtracks.
-- Syntax/semantics: https://www.lua.org/manual/5.5/manual.html#6.5.1
-- Captures are retained only for backreferences; callers need a boolean.
local M = { MAX_PATTERN = 1024, MAX_SUBJECT = 8192, MATCH_LIMIT = 8192, TOTAL_LIMIT = 32768 }
local LIMIT = {}

function M.compile(pattern)
  assert(type(pattern) == "string", "expected a Lua pattern string")
  assert(#pattern <= M.MAX_PATTERN, "pattern exceeds " .. M.MAX_PATTERN .. " bytes")
  local tokens, captures, open = {}, {}, {}
  local anchored = pattern:sub(1, 1) == "^"
  local i = anchored and 2 or 1
  local function bracket()
    local start = i
    assert(pattern:sub(i, i) == "[", "missing '[' after '%f'")
    i = i + 1
    if pattern:sub(i, i) == "^" then i = i + 1 end
    repeat
      assert(i <= #pattern, "missing ']'")
      if pattern:sub(i, i) == "%" then i = i + 1 end
      i = i + 1
    until pattern:sub(i, i) == "]"
    i = i + 1
    return pattern:sub(start, i - 1)
  end
  local function charset(atom)
    local set = {}
    -- A single character class against one byte never backtracks. Let Lua
    -- define locale-dependent classes and bracket-range edge cases.
    for byte = 0, 255 do set[byte] = string.find(string.char(byte), "^" .. atom .. "$") ~= nil end
    return set
  end
  while i <= #pattern do
    local c, token = pattern:sub(i, i), nil
    if c == "(" then
      assert(#captures < 32, "too many captures")
      local id = #captures + 1
      if pattern:sub(i + 1, i + 1) == ")" then
        captures[id], token, i = "closed", { kind = "position", id = id }, i + 2
      else
        captures[id], token, i = "open", { kind = "open", id = id }, i + 1
        open[#open + 1] = id
      end
    elseif c == ")" then
      assert(#open > 0, "invalid pattern capture")
      local id = table.remove(open)
      captures[id], token, i = "closed", { kind = "close", id = id }, i + 1
    elseif c == "$" and i == #pattern then
      token, i = { kind = "finish" }, i + 1
    elseif c == "%" then
      local escape = pattern:sub(i + 1, i + 1)
      assert(escape ~= "", "pattern ends with '%'")
      i = i + 2
      if escape == "b" then
        assert(i + 1 <= #pattern, "missing arguments to '%b'")
        token = { kind = "balance", left = pattern:byte(i), right = pattern:byte(i + 1) }
        i = i + 2
      elseif escape == "f" then
        token = { kind = "frontier", set = charset(bracket()) }
      elseif escape:match("%d") then
        local id = tonumber(escape)
        assert(captures[id] == "closed", "invalid capture index %" .. escape)
        token = { kind = "reference", id = id }
      elseif escape:match("[aAcCdDgGlLpPsSuUwWxXzZ]") then
        token = { kind = "byte", set = charset("%" .. escape) }
      else
        token = { kind = "byte", value = escape:byte() }
      end
    elseif c == "[" then
      token = { kind = "byte", set = charset(bracket()) }
    else
      token = { kind = "byte", value = c ~= "." and c:byte() or nil }
      i = i + 1
    end
    if token.kind == "byte" then
      local suffix = pattern:sub(i, i)
      if suffix ~= "" and (suffix == "*" or suffix == "+" or suffix == "-" or suffix == "?") then
        token.repeat_kind, i = suffix, i + 1
      end
    end
    tokens[#tokens + 1] = token
  end
  assert(#open == 0, "unfinished capture")
  local literal, ending = {}, false
  for _, token in ipairs(tokens) do
    if token.kind == "finish" then ending = true
    elseif token.kind == "byte" and token.value and not token.repeat_kind then
      literal[#literal + 1] = string.char(token.value)
    else literal = nil; break end
  end
  return { tokens = tokens, anchored = anchored, ending = ending, literal = literal and table.concat(literal) }
end

function M.matches(compiled, subject, budget)
  budget = budget or { remaining = M.TOTAL_LIMIT }
  if budget.remaining <= 0 then return false, true end
  if #subject > M.MAX_SUBJECT then return false, true end
  local initial = math.min(M.MATCH_LIMIT, budget.remaining)
  local remaining = initial
  local function spend(n)
    remaining = remaining - (n or 1)
    if remaining < 0 then error(LIMIT, 0) end
  end
  local function run()
    local literal = compiled.literal
    if literal then
      -- Common exact/substring rules use bounded native string operations,
      -- never the native pattern matcher. Charge their scanned byte count.
      spend(math.max(1, #subject))
      if compiled.anchored and compiled.ending then return subject == literal end
      if compiled.anchored then return subject:sub(1, #literal) == literal end
      if compiled.ending then return #subject >= #literal and subject:sub(#subject - #literal + 1) == literal end
      return subject:find(literal, 1, true) ~= nil
    end
    local tokens, length = compiled.tokens, #subject
    local function byte_matches(token, pos)
      spend()
      local byte = subject:byte(pos)
      return byte ~= nil and (token.set and token.set[byte] or not token.set and (not token.value or token.value == byte))
    end
    local function capture(caps, id)
      while caps do
        spend()
        if caps.id == id then return caps end
        caps = caps.parent
      end
    end
    for start = 1, compiled.anchored and 1 or length + 1 do
      local pc, pos, caps, stack = 1, start, nil, {}
      while true do
        spend()
        local token = tokens[pc]
        if not token then return true end
        local kind, matched = token.kind, true
        if kind == "byte" then
          local repeat_kind = token.repeat_kind
          if repeat_kind == "-" then
            stack[#stack + 1] = { pc = pc + 1, pos = pos, caps = caps, grow = token }
          elseif repeat_kind then
            local first, last = pos, pos
            while byte_matches(token, last) do
              last = last + 1
              if repeat_kind == "?" then break end
            end
            local minimum = first + (repeat_kind == "+" and 1 or 0)
            matched = last >= minimum
            if matched then
              if last > minimum then stack[#stack + 1] = { pc = pc + 1, pos = last - 1, minimum = minimum, caps = caps } end
              pos = last
            end
          else
            matched = byte_matches(token, pos)
            if matched then pos = pos + 1 end
          end
        elseif kind == "finish" then
          matched = pos == length + 1
        elseif kind == "frontier" then
          matched = not token.set[subject:byte(pos - 1) or 0] and token.set[subject:byte(pos) or 0]
        elseif kind == "balance" then
          matched = subject:byte(pos) == token.left
          if matched then
            local depth = 1
            pos = pos + 1
            while pos <= length do
              spend()
              local byte = subject:byte(pos)
              if byte == token.right then depth = depth - 1
              elseif byte == token.left then depth = depth + 1 end
              pos = pos + 1
              if depth == 0 then break end
            end
            matched = depth == 0
          end
        elseif kind == "reference" then
          local ref = capture(caps, token.id)
          matched = ref and ref.length and ref.length >= 0 and pos + ref.length <= length + 1
          if matched then
            spend(ref.length)
            matched = subject:sub(pos, pos + ref.length - 1) == subject:sub(ref.start, ref.start + ref.length - 1)
            if matched then pos = pos + ref.length end
          end
        else
          local ref = kind == "close" and capture(caps, token.id)
          caps = { id = token.id, start = ref and ref.start or pos,
            length = ref and pos - ref.start or kind == "position" and -1 or nil, parent = caps }
        end
        if matched then pc = pc + 1
        else
          local retry
          repeat
            spend()
            retry = table.remove(stack)
            if retry and retry.grow then
              if byte_matches(retry.grow, retry.pos) then
                retry.pos = retry.pos + 1
                stack[#stack + 1] = { pc = retry.pc, pos = retry.pos, caps = retry.caps, grow = retry.grow }
              else retry = nil end
            elseif retry and retry.pos > retry.minimum then
              stack[#stack + 1] = { pc = retry.pc, pos = retry.pos - 1, minimum = retry.minimum, caps = retry.caps }
            end
          until retry or #stack == 0
          if not retry then break end
          pc, pos, caps = retry.pc, retry.pos, retry.caps
        end
      end
    end
    return false
  end
  local ok, result = pcall(run)
  budget.remaining = budget.remaining - (initial - math.max(0, remaining))
  if not ok and result ~= LIMIT then error(result, 0) end
  return ok and result or false, not ok
end

return M
