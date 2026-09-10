// Drive the production pane key handlers; ordinary text is left to TextInput.
const fs = require('fs'), vm = require('vm'), assert = require('assert')
const qml = fs.readFileSync('plugin/ContentPane.qml', 'utf8')
const code = [...qml.matchAll(/^  function (\w+)\(/gm)].map(m => {
  const line = qml.indexOf('\n', m.index)
  return qml.slice(m.index, qml.slice(m.index, line).endsWith('}') ? line : qml.indexOf('\n  }', m.index) + 4)
}).join('\n')
const Qt = {ShiftModifier: 1, callLater: fn => fn()}
for (const key of ['Escape', 'Return', 'Enter', 'Up', 'Down', 'Left', 'Right', 'Tab', 'Delete', 'Question', 'Slash', '1', 'R', 'H', 'J', 'K', 'L']) Qt['Key_' + key] = key
const events = [], field = {text: '', visible: true, forceActiveFocus() {}, cursorPosition: 0}
const c = {Qt, searchField: field, ready: true, scenes: [{name:'work',valid:true},{name:'broken',valid:false,error:'Invalid layout'},{name:'home',valid:true}],
  selectedScene: '', deleting: '', appliedScene: '', scene: {}, hot: 0, matches: [{},{}],
  overlay: {busy: false, handleKey: e => {events.push(e.key); return true}, sceneAction: (...a) => events.push(a), deleteScene: name => events.push(['delete', name])},
  sceneCards: {itemAt: i => i + 1}, revealItem: i => events.push(['reveal', i])}
c.pane = c
Object.defineProperty(c, 'query', {get: () => field.text})
Object.defineProperty(c, 'searching', {get: () => field.text.trim() !== ''})
vm.createContext(c); vm.runInContext(code, c)
const key = name => ({key: Qt['Key_' + name], modifiers: 0})
c.handleSceneKey(key('Down')); assert.equal(c.selectedScene, 'work')
c.handleSceneKey(key('Return')); assert.deepEqual(events.pop(), ['apply', 'work'])
c.handleSceneKey(key('Down')); c.handleSceneKey(key('Return')); assert.equal(c.overlay.errorText, 'Invalid layout')
c.handleSceneKey(key('Down')); c.handleSceneKey(key('Down')); assert.equal(c.selectedScene, 'work')
c.handleSceneKey(key('Up')); assert.equal(c.selectedScene, 'home')
c.handleSceneKey(key('Delete')); assert.equal(c.deleting, 'home')
c.handleSceneKey(key('Escape')); assert.equal(c.deleting, '')
c.handleSceneKey(key('Delete')); c.handleSceneKey(key('Return')); assert.deepEqual(events.pop(), ['delete','home'])
for (const name of ['1', 'R', 'H', 'J', 'K', 'L']) assert.equal(c.handleSearchKey(key(name)), false)
field.text = '1Password'
c.handleSearchKey(key('Tab')); assert.equal(field.text, '1Password'); assert.equal(events.pop(), 'Tab')
c.focusSearch(); assert.equal(field.cursorPosition, 9)
c.handleSearchKey(key('Question')); assert.equal(events.pop(), 'Question'); assert.equal(field.text, '1Password')
c.handleSearchKey(key('Down')); assert.equal(c.hot, 1)
assert.equal(c.handleSearchKey(key('Left')), false)
c.handleSearchKey(key('Escape')); assert.equal(field.text, '')
c.handleSearchKey(key('Escape')); assert.equal(events.pop(), 'Escape')
console.log('scene and search keyboard behavior: all checks passed')
