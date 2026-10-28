const assert = require('node:assert/strict');
const { attachCodeBoxes } = require('../static/unlock/unlock.js');

function setup() {
  const form = { submitted: 0, submit() { this.submitted++; } };
  const state = { focused: null };
  const boxes = Array.from({ length: 6 }, () => {
    const box = { value: '', handlers: {} };
    box.addEventListener = (name, fn) => box.handlers[name] = fn;
    box.focus = () => state.focused = box;
    box.select = () => {};
    return box;
  });
  attachCodeBoxes(form, boxes);
  const type = (index, text) => { boxes[index].value = text; boxes[index].handlers.input(); };
  const key = (index, name) => {
    const event = { key: name, prevented: false, preventDefault() { this.prevented = true; } };
    boxes[index].handlers.keydown(event);
    return event;
  };
  const paste = (index, text) => boxes[index].handlers.paste({ preventDefault() {}, clipboardData: { getData: () => text } });
  const code = () => boxes.map(box => box.value || '_').join('');
  const at = () => boxes.indexOf(state.focused);
  return { form, type, key, paste, code, at };
}

let s = setup();
s.type(0, '4');
assert.equal(s.code(), '4_____');
assert.equal(s.at(), 1);
s.type(1, 'x');
assert.equal(s.code(), '4_____', 'non-digits are dropped');
assert.equal(s.at(), 1);
s.type(1, '82');
assert.equal(s.code(), '482___', 'several digits at once fill the next boxes');
assert.equal(s.at(), 3);
assert.ok(s.key(3, 'Backspace').prevented);
assert.equal(s.code(), '48____', 'backspace in an empty box clears the previous one');
assert.equal(s.at(), 2);
s.key(2, 'ArrowLeft');
assert.equal(s.at(), 1);
s.key(1, 'ArrowRight');
assert.equal(s.at(), 2);
assert.equal(s.form.submitted, 0);
s.type(2, '2913');
assert.equal(s.code(), '482913');
assert.equal(s.form.submitted, 1, 'a full code submits once');
s.type(5, '7');
assert.equal(s.form.submitted, 1);

s = setup();
s.paste(0, ' 48 29-13 extra 99');
assert.equal(s.code(), '482913', 'a pasted code spreads over the boxes');
assert.equal(s.at(), 5);
assert.equal(s.form.submitted, 1);

s = setup();
s.key(0, 'Backspace');
assert.equal(s.at(), -1, 'backspace in the first box stays put');
console.log('Unlock code boxes: typing, paste, backspace, arrows and single submit passed');
