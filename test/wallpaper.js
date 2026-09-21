const fs = require('fs'), vm = require('vm'), assert = require('assert');
const W = {};
vm.runInNewContext(fs.readFileSync('plugin/Wallpaper.js', 'utf8'), W);
const plain = x => JSON.parse(JSON.stringify(x));
const screens = [
    {name:'left', x:-1920,y:0,width:1920,height:1080},
    {name:'middle', x:0,y:0,width:1920,height:1080},
    {name:'right', x:1920,y:-200,width:1280,height:1440}
];
const span = {version:1, groups:[{outputs:['left','middle'],mode:'span',image:null,fit:'crop'},
    {outputs:['right'],mode:'repeat',image:'/fixed.png',fit:'fit'}]};
assert.deepStrictEqual(plain(W.frame(span,'left',screens)), {x:0,y:0,width:3840,height:1080});
assert.deepStrictEqual(plain(W.frame(span,'middle',screens)), {x:-1920,y:0,width:3840,height:1080});
assert.deepStrictEqual(plain(W.frame(span,'right',screens)), {x:0,y:0,width:1280,height:1440});
assert.deepStrictEqual(plain(W.frame(span,'middle',screens.slice(1))), {x:0,y:0,width:1920,height:1080});
assert.strictEqual(W.groupFor(span,'right').image,'/fixed.png');
let next = W.setGroup(span, 'middle', {outputs:['middle','right'],mode:'span',image:null,fit:'crop'});
assert.deepStrictEqual(plain(W.groupFor(next,'left').outputs), ['left']);
assert.strictEqual(W.groupFor(next,'left').mode, 'repeat');
assert.deepStrictEqual(plain(W.frame(next,'middle',screens)), {x:0,y:-200,width:3200,height:1440});
assert.strictEqual(span.groups[1].image, '/fixed.png', 'edits do not mutate saved config');
next = W.setGroup(next,'right',{outputs:['right'],mode:'repeat',image:'/fixed.png',fit:'fit'});
assert.deepStrictEqual(plain(W.groupFor(next,'middle').outputs), ['middle']);
assert.strictEqual(W.groupFor(next,'middle').mode,'repeat');
assert.strictEqual(W.groupFor({groups:[]},'new').image,null);
console.log('Wallpaper groups: two-screen span, independent third, mixed geometry, disconnect and regrouping pass');
