const assert=require('node:assert/strict');require('../static/voice-profiles.js');require('../static/speech.js');
global.atob=()=>{throw Error('Pocket must synthesize instead of decoding recordings');};
const context={createBuffer(c,l,rate){const data=new Float32Array(l);return {sampleRate:rate,data,getChannelData:()=>data};}};
for(let slot=0;slot<=10;slot++){
 const item={text:'Iedere figurant krijgt nieuwe klanken. Het is geen opname.',profile:'pocket-'+slot,messageId:'m'};
 const plan=StudioGarble.measuredVoicePlan(item),result=StudioGarble.makeGarble(context,item);
 assert.equal(plan.key,slot%2?'pocket-soft':'pocket-pixel');assert.equal(StudioGarble.voiceProfile(item.profile).source,'synthesized');
 assert.ok(plan.phonemes.every(p=>slot%2===0?p.pitch>600&&p.pitch<640:p.pitch>350&&p.pitch<450));
 assert.ok(Math.abs(plan.phonemes[1].start-plan.phonemes[0].start-.0475)<1e-9);
 assert.equal(result.duration,plan.duration);assert.equal(result.captions.at(-1).end,result.duration);
 assert.deepEqual(result.cues,plan.phonemes.map(({start,end,value})=>({start,end,value})));
 assert.ok(result.buffer.data.every(x=>Number.isFinite(x)&&Math.abs(x)<1));
 assert.notDeepEqual(result.buffer.data,StudioGarble.makeGarble(context,{...item,messageId:'n'}).buffer.data);
}
console.log('Pocket: two measured timbres across 11 fixed cast slots, fresh generated notes, safe output and synchronized mouth planning passed');
