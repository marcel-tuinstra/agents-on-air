const assert=require('node:assert/strict');require('../static/voice-profiles.js');require('../static/speech.js');
global.atob=()=>{throw Error('Midnight must not decode recorded audio');};
const ctx={createBuffer(c,l,rate){const data=new Float32Array(l);return {sampleRate:rate,data,getChannelData:()=>data};}};
const text='Hallo vanuit Midnight. Een nieuwe bijdrage met een eigen klank.';
for(let slot=0;slot<=10;slot++){
 const item={text,profile:'midnight-'+slot,messageId:'a'},plan=StudioGarble.measuredVoicePlan(item);
 assert.equal(plan.key,'midnight','use the new reference-derived synthesis, not another channel');
 assert.ok(plan.voice.interval>.10&&plan.voice.interval<.115,'preserve the slower reference cadence');
 assert.ok(plan.phonemes.every(p=>p.template.partials?.length>=4),'retain the reference’s non-harmonic timbre');
 const result=StudioGarble.makeGarble(ctx,item),again=StudioGarble.makeGarble(ctx,{...item,messageId:'b'});
 assert.equal(result.duration,plan.duration);assert.deepEqual(result.cues,plan.phonemes.map(({start,end,value})=>({start,end,value})));
 assert.equal(result.captions.at(-1).end,result.duration);assert.ok(result.captions.every(c=>c.text.length<=80));
 assert.ok(result.buffer.data.every(v=>Number.isFinite(v)&&Math.abs(v)<1));assert.ok(result.buffer.data.some(v=>Math.abs(v)>.01));
 assert.notDeepEqual(result.buffer.data,again.buffer.data,'messages generate fresh notes instead of replaying a sample');
}
console.log('Midnight: measured timbre and cadence, 11 cast slots, fresh synthesis, bounded output, synchronized captions and mouths passed');
