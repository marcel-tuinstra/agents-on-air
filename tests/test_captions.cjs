const assert = require('node:assert/strict');
require('../frontend/captions.js');

const metric = (text) => Array.from(text).reduce((width, char) =>
  width + (char === 'W' ? 12 : char === 'i' ? 3 : char === ' ' ? 4 : 7), 0);
const fit = (text, width = 38) => StudioCaptionFit(text, width, metric);

for (const source of [
  'Wide WWW and thin iii letters flow across the scene.',
  'WWWWWWWWWWWWWWWWWWWW',
  'A😀 B😀 C😀 with punctuation! And another phrase.',
  'Line one.\nLine two still has every character.',
]) {
  const parts = fit(source);
  assert.equal(parts.join(''), source, 'layout must never lose source characters');
  assert.ok(parts.length > 0);
  for (const part of parts) {
    assert.ok(StudioCaptionFit(part, 38, metric, 1).length <= 2,
      'explicit measured lines must fit within a two-line segment');
    let lines = 1, line = '';
    for (const char of Array.from(part)) {
      if (line && metric(line + char) > 38) { lines++; line = ''; }
      line += char;
    }
    assert.ok(lines <= 2, `${JSON.stringify(part)} exceeds two measured lines`);
  }
}
assert.ok(fit('WWWWWWWWWWWW').length > fit('iiiiiiiiiiii').length,
  'glyph width, rather than character count, controls fitting');

const model = new StudioCaptionModel((text) => fit(text, 55));
model.append('First agent speaks in several fitting segments.', {messageId:'one', speaker:'One', agentId:'a'}, 0);
model.append('Second agent follows in sequence.', {messageId:'two', speaker:'Two', agentId:'b'}, 100);
assert.equal(model.current.messageId, 'one');
let observed = [model.current.text];
for (let time = 8000; time < 100000 && model.visible; time += 8000) {
  model.tick(time, false);
  if (model.visible) observed.push(model.current.text);
}
assert.equal(observed.join(''), model.records.map(record => record.text).join(''));
assert.equal(model.visible, false, 'final caption expires');

model.append('Fresh activity revives the bubble.', {messageId:'three', speaker:'Three'}, 101000);
assert.equal(model.visible, true);
assert.equal(model.current.messageId, 'three', 'new activity starts at its first segment after expiry');
const beforeResize = model.current.offset;
model.segment = (text) => fit(text, 85);
model.reflow(101001);
assert.equal(model.current.messageId, 'three');
assert.ok(model.current.offset <= beforeResize, 'resize preserves the selected source offset');
assert.equal(model.items.map(item => item.text).join(''), model.records.map(record => record.text).join(''));
model.step(-1);
const selected = model.current;
assert.equal(model.resolve({playing:true, caption:'Stale audio', speaker:'Old'}), selected,
  'history selection must win over a stale audio event');
model.tick(200000, true);
assert.equal(model.current, selected, 'history selection remains held');
model.reflow(200001);
assert.equal(model.current.messageId, selected.messageId, 'reflow preserves selected source');
model.setPaused(false, 200002);
assert.equal(model.history, false);
assert.equal(model.resolve({playing:true, caption:'Audio cue', agentId:'a'}), model.current,
  'the shared selected entry remains the displayed audio caption');
const aligned = new StudioCaptionModel((text) => fit(text, 38));
const recordId = aligned.append('One two three four five six seven eight nine.', {messageId:'live'}, 0);
aligned.alignAudio({playing:true, captionRecordId:recordId, sourceStart:0,
  captionIndex:0, captionProgress:0.95,
  captionCues:[{sourceStart:0, sourceEnd:aligned.records[0].text.length}]});
assert.ok(aligned.index > 0, 'audio cue progress updates the shared navigation index');
aligned.step(-1);
const audioHeld = aligned.current;
aligned.alignAudio({playing:true, captionRecordId:recordId, sourceStart:0,
  captionIndex:0, captionProgress:1,
  captionCues:[{sourceStart:0, sourceEnd:aligned.records[0].text.length}]});
assert.equal(aligned.current, audioHeld, 'history selection resists late audio progress');
model.setPaused(true, 200003);
assert.notEqual(model.resolve({playing:true, caption:'Stale audio'}).text, 'Stale audio');
model.reset();
assert.equal(model.current, null);
assert.equal(model.visible, false);
console.log('Caption fitting, sequential stream, expiry, history and stale audio: passed');

// A second-screen session must retain the selected passage without growing forever.
let fitted = 0;
const bounded = new StudioCaptionModel(text => { fitted++; return [text]; });
bounded.append('A passage held for rereading.', {messageId:'held'}, 0);
bounded.setPaused(true, 0);
for (let i = 0; i < 10000; i++)
  bounded.append('Live update '+i, {messageId:'live-'+i}, i);
assert.ok(bounded.records.length <= 200, 'caption history has a fixed record budget');
assert.equal(bounded.current.messageId, 'held', 'overflow must preserve held reading');
assert.equal(bounded.records.at(-1).meta.messageId, 'live-9999');
assert.equal(fitted, 10001, 'arrival only fits the new message, not the entire history');
assert.ok(bounded.trimmed > 0, 'overflow is disclosed to the viewer');
assert.equal(bounded.items.map(x=>x.text).join(''), bounded.records.map(x=>x.text).join(''));
bounded.setPaused(false, 10001);
bounded.tick(20000);
assert.equal(bounded.current.messageId, 'live-9801', 'resume visits the retained queue in order');
bounded.reflow(20001);
assert.equal(bounded.current.messageId, 'live-9801');
bounded.reset();
assert.equal(bounded.trimmed, 0);
assert.equal(bounded.records.length, 0);
const expired = new StudioCaptionModel(text => [text]);
for (let i=0;i<1000;i++) { expired.append('Update '+i,{messageId:String(i)},i*5000); expired.tick(i*5000+4001); }
assert.equal(expired.current.messageId,'999');
assert.equal(expired.visible,false);
console.log('Long session: bounded history, held reading, incremental fitting and expiry passed');
