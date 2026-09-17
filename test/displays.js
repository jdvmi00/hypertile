const fs = require('fs'), vm = require('vm'), assert = require('assert')
const D = {}
vm.runInNewContext(fs.readFileSync('plugin/Displays.js', 'utf8'), D)
const plain = value => JSON.parse(JSON.stringify(value))
const a = {connected:true, enabled:true, width:3840, height:2160, scale:1.5, transform:0, x:0, y:0}
const b = {connected:true, enabled:true, width:1920, height:1080, scale:1.25, transform:1, x:-864, y:0}
assert.deepStrictEqual(plain(D.bounds(a)), {x:0,y:0,w:2560,h:1440})
assert.deepStrictEqual(plain(D.bounds(b)), {x:-864,y:0,w:864,h:1536})
assert.deepStrictEqual(plain(D.extent([a,b])), {x:-864,y:0,w:3424,h:1536})
assert.deepStrictEqual(plain(D.snap([a,b],1,-870,8,20)), {x:-864,y:0})
assert.deepStrictEqual(plain(D.snap([a,b],1,-900,40,20)), {x:-900,y:40})
assert.deepStrictEqual(plain(D.extent([a,{...b,enabled:false}])), {x:0,y:0,w:2560,h:1440})
assert.deepStrictEqual(plain(D.extent([{...a,connected:false}])), {x:0,y:0,w:1920,h:1080})
for(const transform of [1,3,5,7]) assert.strictEqual(D.bounds({...b,transform}).w,864)
for(const transform of [0,2,4,6]) assert.strictEqual(D.bounds({...b,transform}).w,1536)
assert.deepStrictEqual(plain(D.parseMode('3840x2160@59.94Hz')), {width:3840,height:2160,refresh:59.94})
assert.strictEqual(D.parseMode('unavailable'),null)
console.log('Display diagram geometry, snapping, scaling, rotation and modes passed')
// Exercise the pane's pure action helpers without a graphical session.
const qml = fs.readFileSync('plugin/DisplaysPane.qml', 'utf8')
function helper(name) {
    const start = qml.indexOf('    function ' + name + '(')
    const ends = [qml.indexOf('    function ', start + 5), qml.indexOf('    Component.onCompleted', start + 5)].filter(i => i > start)
    const end = ends.length ? Math.min(...ends) : -1
    assert(start >= 0 && end > start, 'helper must remain extractable: ' + name)
    return qml.slice(start, end)
}
const pane = {
    Displays: D,
    selectedDisplay: {id: 'portrait'},
    draft: {workspaces: {'2': {monitor: 'wide', layout: 'lua:quad'}}},
    dirty: false,
}
vm.runInNewContext(helper('setAssignment'), pane)
pane.setAssignment('2', null, true)
assert.deepStrictEqual(plain(pane.draft.workspaces['2']), {monitor:'portrait', layout:'lua:quad'})
pane.setAssignment('2', null, false)
assert.deepStrictEqual(plain(pane.draft.workspaces['2']), {monitor:'portrait', layout:null})
pane.setAssignment('writing', 'master', true)
assert.deepStrictEqual(plain(pane.draft.workspaces['name:writing']), {monitor:'portrait', layout:'master'})
vm.runInNewContext(helper('serviceError'), pane)
assert.strictEqual(pane.serviceError('{"error":"Last display cannot be disabled"}', '', 'fallback'), 'Last display cannot be disabled')
assert.strictEqual(pane.serviceError('not json', ' adapter unavailable \n', 'fallback'), 'adapter unavailable')
assert.strictEqual(pane.serviceError('', '', 'fallback'), 'fallback')
console.log('Display workspace provenance and actionable service errors passed')
// Power controls follow the compositor, not the unsaved draft.
const power = {
    catalog: {displays: [
        {id:'a', connector:'HDMI-A-1', connected:true, enabled:true, awake:true},
        {id:'b', connector:'DP-1', connected:true, enabled:true, awake:false},
        {id:'c', connector:'DP-2', connected:true, enabled:false, awake:false},
    ]},
}
vm.runInNewContext(helper('liveFor') + helper('isAsleep'), power)
assert.strictEqual(power.liveFor({connector:'DP-1', connected:true}).id, 'b')
assert.strictEqual(power.liveFor({connector:'DP-1', connected:false}), null, 'a saved, disconnected entry has no live power state')
assert.strictEqual(power.liveFor({connector:'DP-9', connected:true}), null)
assert.strictEqual(power.liveFor(null), null)
assert.strictEqual(power.isAsleep({connector:'HDMI-A-1', connected:true}), false)
assert.strictEqual(power.isAsleep({connector:'DP-1', connected:true, enabled:false}), true, 'draft edits never change the live power state')
assert.strictEqual(power.isAsleep({connector:'DP-2', connected:true}), false, 'a disabled output is off, not asleep')
power.catalog = null
assert.strictEqual(power.isAsleep({connector:'DP-1', connected:true}), false)
console.log('Display power state reads the compositor catalog passed')
// Closing never drops unsaved edits silently; a pending preview reverts first.
function closing(state) {
    const ctx = Object.assign({closed: 0, reverted: 0, refreshed: 0, notice: '', closeAfterRevert: false, confirmingDiscard: false, pending: null, dirty: false}, state)
    ctx.closeRequested = () => ctx.closed++
    ctx.run = () => ctx.reverted++
    ctx.refresh = () => ctx.refreshed++
    ctx.Qt = {Key_Escape: 1, Key_Return: 2, Key_Enter: 3, Key_D: 4, ControlModifier: 8, AltModifier: 16, MetaModifier: 32}
    vm.runInNewContext(['requestClose', 'discardAndClose', 'keepEditing', 'handleKey', 'revert'].map(helper).join(''), ctx)
    return ctx
}
let close = closing({})
close.requestClose()
assert.deepStrictEqual([close.closed, close.confirmingDiscard], [1, false], 'a clean pane closes at once')
close = closing({dirty: true})
close.requestClose()
assert.deepStrictEqual([close.closed, close.confirmingDiscard, close.dirty], [0, true, true], 'a dirty pane asks first')
assert.strictEqual(close.handleKey({key: 1, modifiers: 0}), true)
assert.deepStrictEqual([close.closed, close.confirmingDiscard, close.dirty], [0, false, true], 'Escape keeps editing')
close.requestClose()
assert.strictEqual(close.handleKey({key: 4, modifiers: 8}), true)
assert.strictEqual(close.closed, 0, 'Ctrl+D is not a discard')
assert.strictEqual(close.handleKey({key: 4, modifiers: 0}), true)
assert.deepStrictEqual([close.closed, close.confirmingDiscard, close.dirty], [1, false, false], 'D discards and closes')
close = closing({dirty: true, pending: {token: 't'}})
close.requestClose()
assert.deepStrictEqual([close.reverted, close.closeAfterRevert, close.confirmingDiscard], [1, true, false], 'a preview reverts instead of asking')
close = closing({dirty: true, confirmingDiscard: true})
close.revert()
assert.deepStrictEqual([close.confirmingDiscard, close.dirty, close.refreshed], [false, false, 1], 'Reset clears the confirmation')
console.log('Display close confirmation, keys and preview revert passed')

const matching = {
    version:1,
    displays:[
        {id:'new-connector',identity:'dell:serial',connector:'DP-3',connected:true,enabled:false,width:1920,height:1080,refresh:60,scale:1,transform:0,x:0,y:0,modes:['2560x1440@59.95Hz'],awake:true,ambiguous:true},
        {id:'other-identical',identity:'dell:serial',connector:'DP-4',connected:true,enabled:true,width:1920,height:1080,refresh:60,scale:1,transform:0,x:0,y:0,modes:['1920x1080@60.00Hz']},
        {id:'saved-stable',identity:'dell:serial',connector:'DP-1',connected:false,enabled:true,width:2560,height:1440,refresh:59.95,scale:1.25,transform:1,x:-1152,y:80,default_layout:'lua:columns',initial_workspace:'name:work',modes:[]},
        {id:'unrelated',identity:'other:serial',connector:'HDMI-A-1',connected:true,enabled:true,modes:[]}
    ],
    workspaces:{'2':{monitor:'saved-stable',layout:'lua:quad'},'name:work':{monitor:'new-connector',layout:null},'3':{monitor:'other-identical',layout:'master'}}
}
const originalMatching = JSON.stringify(matching)
assert.deepStrictEqual(plain(D.matchCandidates(matching,2)).map(d=>d.connector), ['DP-3','DP-4'])
assert.deepStrictEqual(plain(D.matchCandidates(matching,0)), [])
assert.throws(()=>D.matchSavedDisplay(matching,2,''), /Choose one connected display/)
assert.throws(()=>D.matchSavedDisplay(matching,2,'HDMI-A-1'), /same identity/)
assert.throws(()=>D.matchSavedDisplay(matching,0,'DP-4'), /same identity/)
const matched = plain(D.matchSavedDisplay(matching,2,'DP-3'))
assert.strictEqual(JSON.stringify(matching), originalMatching, 'matching must not mutate confirmed/draft input')
assert.strictEqual(matched.displays.length,3)
assert(!matched.displays.some(d=>d.id==='new-connector'))
const savedMatched = matched.displays.find(d=>d.id==='saved-stable')
for(const key of ['id','identity','enabled','width','height','refresh','scale','transform','x','y','default_layout','initial_workspace'])
    assert.strictEqual(savedMatched[key],matching.displays[2][key], 'retain saved '+key)
assert.strictEqual(savedMatched.connector,'DP-3')
assert.strictEqual(savedMatched.connected,true)
assert.strictEqual(savedMatched.explicit_match,true)
assert.strictEqual(savedMatched.mode_available,true)
assert.deepStrictEqual(savedMatched.modes,['2560x1440@59.95Hz'])
assert.deepStrictEqual(matched.workspaces['2'],{monitor:'saved-stable',layout:'lua:quad'})
assert.deepStrictEqual(matched.workspaces['name:work'],{monitor:'saved-stable',layout:null})
assert.deepStrictEqual(matched.workspaces['3'],matching.workspaces['3'])
assert.strictEqual(D.matchSavedDisplay(matching,2,'DP-4').displays.find(d=>d.id==='saved-stable').mode_available,false)
const duplicateConnector = plain(matching)
duplicateConnector.displays.push({...duplicateConnector.displays[0],id:'duplicate'})
assert.throws(()=>D.matchSavedDisplay(duplicateConnector,2,'DP-3'),/Choose one connected display/)
console.log('Explicit reconnect matching, preserved preferences, candidate isolation and duplicate rejection passed')
const matchingPane = {
    Displays:D, busy:false, pending:null,
    selectedDisplay:matching.displays[2], selectedIndex:2,
    matchingConnector:'DP-3', draft:matching, dirty:false, error:'', notice:''
}
vm.runInNewContext(helper('matchSelectedDisplay'), matchingPane)
matchingPane.matchSelectedDisplay()
assert.strictEqual(matchingPane.selectedIndex,1, 'selection follows retained saved id after candidate removal')
assert.strictEqual(matchingPane.draft.displays[matchingPane.selectedIndex].id,'saved-stable')
assert.strictEqual(matchingPane.matchingConnector,'')
assert.strictEqual(matchingPane.dirty,true)
assert.strictEqual(matchingPane.error,'')
const failedMatchPane = {...matchingPane,draft:matching,selectedIndex:2,matchingConnector:'',dirty:false}
vm.runInNewContext(helper('matchSelectedDisplay'), failedMatchPane)
failedMatchPane.matchSelectedDisplay()
assert.strictEqual(failedMatchPane.draft,matching)
assert.strictEqual(failedMatchPane.dirty,false)
assert(failedMatchPane.error.includes('Choose one connected display'))
console.log('Reconnect pane selection and validation feedback passed')
const untouchedDisplay = {id:'screen',x:0,y:0,scale:1.3333334}
const untouchedPane = {Displays:D,selectedDisplay:untouchedDisplay,selectedIndex:0,draft:{displays:[untouchedDisplay]},dirty:false,pending:null,busy:false}
vm.runInNewContext(helper('setDisplay'),untouchedPane)
const untouchedDraft = untouchedPane.draft
untouchedPane.setDisplay('initial_workspace',null)
untouchedPane.setDisplay('x',0)
untouchedPane.setDisplay('y',0)
untouchedPane.setDisplay('scale',1.3333334)
assert.strictEqual(untouchedPane.draft,untouchedDraft)
assert.strictEqual(untouchedPane.dirty,false,'tabbing through unchanged fields must not stage settings')
assert(!Object.hasOwn(untouchedPane.draft.displays[0],'initial_workspace'))
untouchedPane.setDisplay('initial_workspace','name:writing')
assert.strictEqual(untouchedPane.dirty,true)
assert.strictEqual(untouchedPane.draft.displays[0].initial_workspace,'name:writing')
assert.strictEqual(untouchedPane.draft.displays[0].scale,1.3333334)
console.log('Untouched fields preserve clean draft and exact fractional scale')
const inspectorSettings = {parent:{parent:null}}
const focusReview = {settings:inspectorSettings,revealed:[]}
// QML resolves reveal() through the enclosing component, rather than binding
// JavaScript's receiver; use an explicit closure in this isolated test.
focusReview.reveal = item => focusReview.revealed.push(item)
vm.runInNewContext(helper('revealInspectorControl'),focusReview)
const nestedButton = {parent:{parent:inspectorSettings}}
focusReview.revealInspectorControl(nestedButton)
focusReview.revealInspectorControl({parent:{parent:null}})
assert.deepStrictEqual(focusReview.revealed,[nestedButton])
console.log('Inspector keyboard actions scroll into view without moving toolbar focus')

const mirrorDoc = {displays: [{...a, id:'a'}, {...b, id:'b'}], workspaces:{'1':{monitor:'b'}}}
const mirrorDraft = D.setUsage(mirrorDoc, 1, 'a')
assert.strictEqual(mirrorDraft.displays[1].mirror_of, 'a')
assert.deepStrictEqual(plain(D.extent(mirrorDraft.displays)), plain(D.extent([a])))
assert.strictEqual(D.groupLabel(mirrorDraft.displays, 0), '1 + 2')
assert.strictEqual(mirrorDraft.workspaces['1'].monitor, 'b')
const extendedDraft = D.setUsage(mirrorDraft, 1, 'extended')
assert.strictEqual(extendedDraft.displays[1].mirror_of, null)
assert.strictEqual(extendedDraft.displays[1].x, b.x)
assert.strictEqual(extendedDraft.displays[1].y, b.y)
assert.strictEqual(D.usageOptions(mirrorDraft.displays, mirrorDraft.displays[0]).length, 2)
assert.strictEqual(D.setUsage(mirrorDoc, 1, 'disabled').displays[1].enabled, false)
console.log('Mirror groups, source selection, retained preferences and Extended restoration passed')

// A lone desktop rectangle has no relative arrangement, including a mirror group.
for (const others of [[], [{...b, enabled:false}], [{...b, connected:false}], [{...b, mirror_of:'a'}]]) {
    const displays = [{...a, id:'a', x:177, y:374}, ...others]
    assert.strictEqual(D.canArrange(displays), false)
    const ctx = {Displays:D, draft:{displays}, dirty:false, busy:false, pending:null}
    vm.runInNewContext(helper('setPosition'), ctx)
    const original = ctx.draft
    ctx.setPosition(0, 2077, 367)
    assert.strictEqual(ctx.draft, original, 'single-display dragging must preserve coordinates and draft identity')
    assert.strictEqual(ctx.dirty, false, 'single-display dragging must not prompt to discard changes')
}
assert.strictEqual(D.canArrange([a,b]), true)
const movement = {Displays:D, draft:{displays:[{...a},{...b}]}, dirty:false, busy:false, pending:null}
vm.runInNewContext(helper('setPosition'), movement)
const originalMovement = movement.draft
movement.setPosition(0, 0.1, 0.2)
assert.strictEqual(movement.draft, originalMovement, 'unchanged rounded coordinates leave draft clean')
assert.strictEqual(movement.dirty, false)
movement.setPosition(1, -900.4, 40.2)
assert.deepStrictEqual(plain(movement.draft.displays[1]), {...b,x:-900,y:40})
assert.strictEqual(movement.dirty, true)
console.log('Single-display arrangement is inert; multiple displays still move and unchanged positions stay clean')

const ultrawideScales = plain(D.scaleOptions({width:6144,height:2560}))
assert.deepStrictEqual(ultrawideScales.map(s=>s.label), ['1x','1.33x','1.6x','2x','3.2x','4x'])
assert.strictEqual(ultrawideScales[1].value, 4/3, 'display labels must not round the scale sent to Hyprland')
for (const [width,height] of [[6144,2560],[1920,1080],[3840,2160],[2560,1440],[1080,1920]]) {
    const options = plain(D.scaleOptions({width,height}))
    assert.strictEqual(new Set(options.map(s=>s.value)).size, options.length)
    for (const {value} of options) {
        assert(Math.abs(width / value - Math.round(width / value)) < 0.00001)
        assert(Math.abs(height / value - Math.round(height / value)) < 0.00001)
    }
}
assert.deepStrictEqual(plain(D.scaleOptions(null)), [])
const textPane = {textSizeStops:[9,10,11,12,14,16,20], pendingTextSize:-1, textSizeProcess:{running:false}, draft:untouchedDraft, dirty:false}
vm.runInNewContext(helper('setTextSize'), textPane)
assert.strictEqual(D.nearestStop(textPane.textSizeStops,13),3)
textPane.setTextSize(4)
assert.deepStrictEqual(plain(textPane.textSizeProcess.command), ['omarchy','display','text','size','14'])
assert.strictEqual(textPane.pendingTextSize,14)
assert.strictEqual(textPane.dirty,false,'global text sizing must not stage a display preview')
textPane.setTextSize(6)
assert.strictEqual(textPane.pendingTextSize,14,'an in-flight text-size command must not be overwritten')
console.log('Resolution-compatible scale presets and global text-size actions passed')
