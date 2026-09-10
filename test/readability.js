const fs = require('fs'), vm = require('vm'), assert = require('assert')
const R = {}
vm.runInNewContext(fs.readFileSync('plugin/Readability.js', 'utf8'), R)
const rgb = value => ({r: parseInt(value.slice(1, 3), 16) / 255, g: parseInt(value.slice(3, 5), 16) / 255, b: parseInt(value.slice(5, 7), 16) / 255})
const backgrounds = ['#000000','#ffffff','#202424','#888888','#ff00ff','#074167','#fff2c7']
for (const bg of backgrounds) for (const fg of ['#ffffff','#000000','#909090','#ee6677',bg]) for (const amount of [0,0.62,0.72,1]) {
  const result = R.textColor(rgb(fg), rgb(bg), amount)
  assert(R.contrast(rgb(result), rgb(bg)) >= 4.5, `${fg} on ${bg} at ${amount}: ${result}`)
}
assert.equal(R.textColor(rgb('#eeeeee'), rgb('#111111'), 1), '#eeeeee', 'readable theme colors stay intact')
assert.notEqual(R.textColor(rgb('#eeeeee'), rgb('#111111'), 0.72), '#eeeeee', 'secondary text remains distinct when contrast allows')
console.log('overlay text contrast: all checks passed')
