-- Generic pinned swaps preserve identities and validate both sides atomically.
package.path = './?.lua;' .. package.path
local engine = require('hypertile')
engine.provider('test', {columns={{name='left', id='a'}, {name='right', id='b'}}})
local ws = {id=1, name='1', tiled_layout='lua:test'}
local windows = {
  {address='a', stable_id=1, pid=11, mapped=true, workspace=ws, class='editor'},
  {address='b', stable_id=2, pid=22, mapped=true, workspace=ws, class='com.moonlight_stream.Moonlight'}
}
local calls = {}
hl = {get_windows=function() return windows end, get_workspaces=function() return {ws} end,
  dsp={window={resize=function(a) return a end}}, dispatch=function(a) calls[#calls+1]=a end}
local session = require('hypertile-session')
local live = engine.live.test
live.orders['1'] = {'a','b'}
live.state.pins.a = 'left'
live.state.exclusive_pins = {a=true}
local plan = session.swap_plan({windows=windows})
windows[2].pid = 99
assert(not pcall(session.swap_apply, plan))
assert(live.state.pins.a == 'left' and not live.state.pins.b, 'stale identity cannot partially swap')
windows[2].pid = 22
session.swap_apply(plan)
assert(live.state.pins.a == 'right' and live.state.pins.b == 'left')
session.swap_apply(plan)
assert(live.state.pins.a == 'right' and live.state.pins.b == 'left', 'replay is absolute')
assert(live.state.exclusive_pins.a and live.state.exclusive_pins.b)
live.state.scene_empty = {['1']={right=true}}
assert(not pcall(session.swap_apply, plan), 'cannot occupy an Empty zone')
assert(not session.stream_assign and not session.stream_launch, 'compositor owns no remote lifecycle')
print('generic pinned swaps: all checks passed')
