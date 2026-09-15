// Match configured fill numbers, including aliases for stacked zones.
// A prefix such as 1 waits for another digit or Enter when 10 also exists.
function match(slots, digits) {
  var exact = null, longer = false, found = false
  for (var i = 0; i < slots.length; i++) {
    for (var j = 0; j < slots[i].numbers.length; j++) {
      var number = String(slots[i].numbers[j])
      if (number.indexOf(digits) !== 0) continue
      found = true
      if (number === digits) exact = slots[i]
      else longer = true
    }
  }
  return { exact: exact, longer: longer, found: found }
}
