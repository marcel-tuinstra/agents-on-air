const assert = require('node:assert/strict');
const { StudioBoot, LatestRequest } = require('../static/controllers.js');

function boot(reduce = false) {
  const nodes = new Map(), timers = [];
  const media = { matches: reduce, addEventListener: (_, fn) => media.change = fn };
  const q = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: false, textContent: '', classList: { remove() {} },
      addEventListener: (name, fn) => nodes.get(selector)[name] = fn,
    });
    return nodes.get(selector);
  };
  const controller = new StudioBoot(q, media, (fn, ms) => timers.push({ fn, ms }));
  return { q, timers, media, set: value => controller.setTarget(value) };
}
let b = boot();
b.set('ready');
assert.equal(b.q('[data-ready]').hidden, true);
assert.equal(b.timers[0].ms, 5000);
b.timers[0].fn();
assert.equal(b.q('[data-ready]').hidden, false);
b.set('loading');
assert.equal(b.q('.load').hidden, false);
assert.equal(b.q('[data-skip-intro]').hidden, true);
b.set('ready');
assert.equal(b.q('.load').hidden, true);
b = boot(); b.set('empty'); b.q('[data-skip-intro]').click();
assert.equal(b.q('[data-no-selection]').hidden, false);
b = boot(); b.timers[0].fn();
assert.equal(b.q('.load').hidden, false);
b = boot(true); b.set('ready');
assert.equal(b.q('[data-ready]').hidden, false);
assert.equal(b.timers[0].ms, 0);
b = boot(); b.set('ready'); b.media.matches = true; b.media.change();
assert.equal(b.q('[data-ready]').hidden, false);

(async () => {
  const pending = [], controller = new LatestRequest();
  let applied;
  const load = () => new Promise(resolve => pending.push(resolve));
  const initial = controller.run(load, value => applied = value);
  const saved = controller.run(load, value => applied = value);
  pending[1]('new'); await saved;
  pending[0]('old'); await initial;
  assert.equal(applied, 'new');
  console.log('Boot and settings controllers: timing, skipping, reduced motion and stale request isolation passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
