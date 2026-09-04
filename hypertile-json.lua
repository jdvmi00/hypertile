-- Minimal JSON encoder/decoder for hypertile (pure Lua, 5.1+).
-- Encoding is deterministic: object keys are sorted, output is pretty
-- printed with two-space indent. Tables with a positive sequence length are
-- arrays; other tables are objects. Mark an empty table as an array with
-- json.array({}) so it encodes as [] instead of {}.

local M = {}

local array_mt = { __jsontype = "array" }

function M.array(t)
  return setmetatable(t or {}, array_mt)
end

local function is_array(t)
  local mt = getmetatable(t)
  if mt and mt.__jsontype == "array" then
    return true
  end
  if mt and mt.__jsontype == "object" then
    return false
  end
  return #t > 0
end

local escapes = {
  ['"'] = '\\"',
  ["\\"] = "\\\\",
  ["\b"] = "\\b",
  ["\f"] = "\\f",
  ["\n"] = "\\n",
  ["\r"] = "\\r",
  ["\t"] = "\\t",
}

local function encode_string(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    return escapes[c] or string.format("\\u%04x", c:byte())
  end) .. '"'
end

local function encode_number(n)
  if n ~= n or n == math.huge or n == -math.huge then
    error("json: cannot encode " .. tostring(n))
  end
  if math.floor(n) == n and math.abs(n) < 1e15 then
    return string.format("%d", n)
  end
  return string.format("%.14g", n)
end

local function encode(v, indent, out)
  local t = type(v)
  if t == "nil" then
    out[#out + 1] = "null"
  elseif t == "boolean" then
    out[#out + 1] = v and "true" or "false"
  elseif t == "number" then
    out[#out + 1] = encode_number(v)
  elseif t == "string" then
    out[#out + 1] = encode_string(v)
  elseif t == "table" then
    local inner = indent .. "  "
    if is_array(v) then
      if #v == 0 then
        out[#out + 1] = "[]"
        return
      end
      out[#out + 1] = "[\n"
      for i = 1, #v do
        out[#out + 1] = inner
        encode(v[i], inner, out)
        out[#out + 1] = (i < #v) and ",\n" or "\n"
      end
      out[#out + 1] = indent .. "]"
    else
      local keys = {}
      for k in pairs(v) do
        if type(k) ~= "string" then
          error("json: object keys must be strings, got " .. type(k))
        end
        keys[#keys + 1] = k
      end
      if #keys == 0 then
        out[#out + 1] = "{}"
        return
      end
      table.sort(keys)
      out[#out + 1] = "{\n"
      for i, k in ipairs(keys) do
        out[#out + 1] = inner .. encode_string(k) .. ": "
        encode(v[k], inner, out)
        out[#out + 1] = (i < #keys) and ",\n" or "\n"
      end
      out[#out + 1] = indent .. "}"
    end
  else
    error("json: cannot encode " .. t)
  end
end

function M.encode(v)
  local out = {}
  encode(v, "", out)
  return table.concat(out)
end

---------------------------------------------------------------------------
-- Decoder
---------------------------------------------------------------------------

local function decode_error(s, i, msg)
  local line, col = 1, 1
  for k = 1, i - 1 do
    if s:sub(k, k) == "\n" then
      line, col = line + 1, 1
    else
      col = col + 1
    end
  end
  error(string.format("json: %s at line %d col %d", msg, line, col), 0)
end

local function skip_ws(s, i)
  local _, e = s:find("^[ \t\r\n]*", i)
  return e + 1
end

local decode_value

local function decode_string(s, i)
  local out = {}
  local j = i + 1
  while true do
    local c = s:sub(j, j)
    if c == "" then
      decode_error(s, j, "unterminated string")
    elseif c == '"' then
      return table.concat(out), j + 1
    elseif c == "\\" then
      local n = s:sub(j + 1, j + 1)
      local map = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }
      if map[n] then
        out[#out + 1] = map[n]
        j = j + 2
      elseif n == "u" then
        local hex = s:sub(j + 2, j + 5)
        local code = tonumber(hex, 16)
        if not code then
          decode_error(s, j, "bad unicode escape")
        end
        if code < 0x80 then
          out[#out + 1] = string.char(code)
        elseif code < 0x800 then
          out[#out + 1] = string.char(0xC0 + math.floor(code / 0x40), 0x80 + code % 0x40)
        else
          out[#out + 1] = string.char(0xE0 + math.floor(code / 0x1000), 0x80 + math.floor(code / 0x40) % 0x40, 0x80 + code % 0x40)
        end
        j = j + 6
      else
        decode_error(s, j, "bad escape")
      end
    else
      out[#out + 1] = c
      j = j + 1
    end
  end
end

local function decode_number(s, i)
  local num = s:match("^-?%d+%.?%d*[eE]?[-+]?%d*", i)
  local v = tonumber(num)
  if not v then
    decode_error(s, i, "bad number")
  end
  return v, i + #num
end

local function decode_array(s, i)
  local arr = M.array({})
  i = skip_ws(s, i + 1)
  if s:sub(i, i) == "]" then
    return arr, i + 1
  end
  while true do
    local v
    v, i = decode_value(s, i)
    arr[#arr + 1] = v
    i = skip_ws(s, i)
    local c = s:sub(i, i)
    if c == "]" then
      return arr, i + 1
    elseif c ~= "," then
      decode_error(s, i, "expected , or ]")
    end
    i = skip_ws(s, i + 1)
  end
end

local function decode_object(s, i)
  local obj = setmetatable({}, { __jsontype = "object" })
  i = skip_ws(s, i + 1)
  if s:sub(i, i) == "}" then
    return obj, i + 1
  end
  while true do
    if s:sub(i, i) ~= '"' then
      decode_error(s, i, "expected string key")
    end
    local k
    k, i = decode_string(s, i)
    i = skip_ws(s, i)
    if s:sub(i, i) ~= ":" then
      decode_error(s, i, "expected :")
    end
    i = skip_ws(s, i + 1)
    local v
    v, i = decode_value(s, i)
    obj[k] = v
    i = skip_ws(s, i)
    local c = s:sub(i, i)
    if c == "}" then
      return obj, i + 1
    elseif c ~= "," then
      decode_error(s, i, "expected , or }")
    end
    i = skip_ws(s, i + 1)
  end
end

decode_value = function(s, i)
  i = skip_ws(s, i)
  local c = s:sub(i, i)
  if c == "{" then
    return decode_object(s, i)
  elseif c == "[" then
    return decode_array(s, i)
  elseif c == '"' then
    return decode_string(s, i)
  elseif c == "-" or c:match("%d") then
    return decode_number(s, i)
  elseif s:sub(i, i + 3) == "true" then
    return true, i + 4
  elseif s:sub(i, i + 4) == "false" then
    return false, i + 5
  elseif s:sub(i, i + 3) == "null" then
    return nil, i + 4
  end
  decode_error(s, i, "unexpected character '" .. c .. "'")
end

function M.decode(s)
  if type(s) ~= "string" then
    error("json: decode expects a string", 0)
  end
  local v, i = decode_value(s, 1)
  i = skip_ws(s, i)
  if i <= #s then
    decode_error(s, i, "trailing garbage")
  end
  return v
end

return M
