const fs = require('fs'), vm = require('vm'), assert = require('assert')
const Picker = {}
vm.runInNewContext(fs.readFileSync('plugin/TilePicker.js', 'utf8'), Picker)
const qml = fs.readFileSync('plugin/TilePicker.qml', 'utf8')
const functions = [...qml.matchAll(/^  function (\w+)\(/gm)].map(match => {
  const end = qml.indexOf('\n  }', match.index) + 4
  const lineEnd = qml.indexOf('\n', match.index)
  return qml.slice(match.index, qml.slice(match.index, lineEnd).endsWith('}') ? lineEnd : end)
}).join('\n')
const slots = [{zone:'one', numbers:[1]}, {zone:'two', numbers:[2, 3]},
  {zone:'ten', numbers:[10]}, {zone:'unnumbered', numbers:[]}]
const Qt = {Key_0:48, Key_9:57, Key_Escape:27, Key_Backspace:8, Key_Return:13, Key_Enter:14}
function fixture() {
  const chosen = []
  const root = {request:{slots}, digits:'', busy:false, opened:true, errorText:'',
    choose(slot) {chosen.push(slot.zone)}, finished() {chosen.push('cancel')}}
  const context = {root, Picker, Qt}
  vm.createContext(context)
  vm.runInContext(functions, context)
  root.chooseNumber = context.chooseNumber
  return {root, chosen, key(value, repeat=false) {context.handleKey({key:value, isAutoRepeat:repeat})}}
}
{
  const f = fixture()
  f.key(49)
  assert.deepEqual(f.chosen, [], 'ambiguous 1 waits')
  f.key(48)
  assert.deepEqual(f.chosen, ['ten'], '10 commits immediately')
}
{
  const f = fixture()
  f.key(49); f.key(Qt.Key_Return)
  assert.deepEqual(f.chosen, ['one'], 'Enter chooses shorter exact number')
}
{
  const f = fixture()
  f.key(49); f.key(Qt.Key_Backspace); f.key(51)
  assert.deepEqual(f.chosen, ['two'], 'stack aliases select the same zone')
}
{
  const f = fixture()
  f.key(57)
  assert.deepEqual(f.chosen, [])
  assert.match(f.root.errorText, /No available tile/)
  assert.equal(f.root.digits, '')
  f.key(50)
  assert.deepEqual(f.chosen, ['two'], 'invalid entry can be corrected immediately')
}
{
  const f = fixture()
  f.key(50, true)
  assert.deepEqual(f.chosen, [], 'ignore auto-repeat')
  f.key(Qt.Key_Escape)
  assert.deepEqual(f.chosen, ['cancel'], 'Escape never moves a window')
  f.root.busy = true
  f.key(50)
  assert.deepEqual(f.chosen, ['cancel'], 'only one command can run')
}
console.log('numbered tile picker: all checks passed')

{
  const f = fixture()
  f.root.dragging = true
  f.root.request.dragToken = 'current'
  const context = {root:f.root, Picker, Qt}
  vm.createContext(context)
  vm.runInContext(functions, context)
  context.choose(slots[1])
  assert.equal(f.root.busy, false, 'drag overlay cannot dispatch a move from clicks')
  context.readDrag('{"token":"old","active":false}')
  assert.deepEqual(f.chosen, [], 'stale drag cannot close current overlay')
  context.readDrag('{"token":"current","active":true,"zone":"two"}')
  assert.equal(f.root.dragZone, 'two')
  context.readDrag('{"token":"current","active":true,"zone":""}')
  assert.equal(f.root.dragZone, '', 'leaving valid drop area clears the highlight')
  context.readDrag('{"token":"current","active":false}')
  assert.deepEqual(f.chosen, ['cancel'], 'release before overlay opens still closes it')
}
