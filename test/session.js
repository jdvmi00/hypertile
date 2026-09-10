const fs = require('fs'), vm = require('vm'), assert = require('assert')
const S = {}
vm.runInNewContext(fs.readFileSync('plugin/Session.js', 'utf8'), S)
for (const input of ['', '{', 'null', '[]', '{}', '{"mode":"unknown"}']) assert.equal(S.parse(input), null)
assert.equal(S.parse('{"mode":"watching"}').mode, 'watching')
assert.equal(S.attention(null, false, false), false)
assert.equal(S.attention(null, false, true), true)
assert.match(S.summary(null, false, true), /unavailable/)
assert.equal(S.attention({mode:'disabled'}, true, true), false)
assert.match(S.summary({mode:'disabled'}, true, true), /disabled/)
const partial = {mode:'partial', matched:5, total:10, saving:{paused:true, can_resume:true}}
assert.equal(S.attention(partial, true, true), true)
assert.equal(S.canResume(partial), true)
assert.match(S.summary(partial, true, true), /Saving paused: 5 of 10 windows restored/)
assert.equal(S.canResume({mode:'restoring', saving:{can_resume:false}}), false)
assert.equal(S.attention({mode:'watching'}, true, true), false)
const waiting = {mode:'watching', scene_delivery:{pending:2}}
assert.equal(S.attention(waiting, true, true), true)
assert.match(S.summary(waiting, true, true), /Saving continues; 2 scene/)
const preview = {mode:'watching', error:'A layout preview is active', saving:{can_resume:false}}
assert.equal(S.attention(preview, true, true), true)
assert.match(S.summary(preview, true, true), /Saving paused.*preview/)
assert.equal(S.canResume(preview), false)
const expired = {mode:'watching', saving:{warning:'A layout preview expired; saving its committed layout'}}
assert.equal(S.attention(expired, true, true), true)
assert.match(S.summary(expired, true, true), /committed layout/)
console.log('session saving feedback: all checks passed')
