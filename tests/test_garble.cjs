const assert=require('node:assert/strict');
global.StudioText=require('../static/markdown.js');
global.localStorage={getItem:()=>null,setItem:()=>{}};
require('../static/voice-profiles.js');require('../static/speech.js');

function bufferContext(){
 const sources=[];
 return {sources,currentTime:0,state:'running',async resume(){this.state='running';},async suspend(){this.state='suspended';},getOutputTimestamp(){return {contextTime:this.currentTime};},
  createGain(){return {gain:{value:1,setTargetAtTime(value){this.value=value;}},connect(){}};},
  createBuffer(_channels,length,sampleRate){const data=new Float32Array(length);return {duration:length/sampleRate,sampleRate,getChannelData:()=>data,data};},
  createBufferSource(){const node={connect(){},disconnect(){},start(){},stop(){this.stopped=true;this.onended?.();}};sources.push(node);return node;},destination:{}};
}
const item=(text='A quiet test message with a few words.',profile='midnight-0')=>({text,profile,messageId:'msg-1'});

(async()=>{
 const context=bufferContext(),text='A gentle little syllable, then another one!';
 const one=StudioGarble.makeGarble(context,item(text)),two=StudioGarble.makeGarble(context,item(text));
 assert.equal(one.duration,two.duration);assert.deepEqual(one.cues,two.cues);assert.deepEqual(one.buffer.data,two.buffer.data,'same message and cast must synthesize the same buffer');
 assert.ok(one.duration>=text.match(/\w+/g).length/3,'reading time should be close to 180 words per minute');
 assert.ok(one.duration<8,'short text must stay within the slower Midnight reading budget');
 assert.ok(one.cues.length>0);assert.equal(one.cues[0].start,0);assert.ok(one.cues.at(-1).end<one.duration,'punctuation and word gaps remain audible pauses');
 assert.ok(one.cues.every(c=>c.end>c.start&&'ABCDEFGH'.includes(c.value)));
 const mouthMap=Object.fromEntries(StudioGarble.phones.map(p=>[p.s,p.v]));assert.deepEqual(mouthMap,{a:'D',e:'C',i:'B',o:'E',u:'F',ae:'C',sh:'B',ya:'C'});
 const longPlan=StudioGarble.readingPlan('a'.repeat(190));assert.ok(longPlan.captions.length>=3);assert.ok(longPlan.captions[0].end<longPlan.captions[1].end,'long-word caption chunks must map to different word fractions');assert.ok(longPlan.captions.every(c=>c.sourceEnd>c.sourceStart));
 assert.ok(one.buffer.data.some(n=>Math.abs(n)>.001),'synthesis must contain audible formant energy');
 assert.ok(Math.max(...one.buffer.data.slice(0,Math.min(10000,one.buffer.data.length)))<1,'output stays bounded');
 const other=StudioGarble.makeGarble(context,item(text,'pocket-10'));assert.notDeepEqual(one.buffer.data,other.buffer.data,'cast profile changes the generated voice');
 const levels=['midnight-0','paper-5','pocket-10'].map(profile=>{const samples=StudioGarble.makeGarble(context,item('A short four second audio anchor to check voice balance and safe peaks.',profile)).buffer.data;let square=0,peak=0;for(const v of samples){square+=v*v;peak=Math.max(peak,Math.abs(v));}return {rms:Math.sqrt(square/samples.length),peak};});
 assert.ok(levels.every(x=>x.rms>=.025&&x.peak<.75&&x.peak>.1),'garble voice anchors must be audible and peak-limited');// Measured profiles retain their reference loudness targets.

 let requests=0;global.fetch=async()=>{requests++;throw Error('Piper must not be used in garble mode');};
 const s=new StudioSpeech(()=>{},()=>({channel:'midnight',slot:0}));s.context=context;s.init();assert.equal(s.enabled,true);assert.equal(s.mode,'garble');assert.equal(s.muted,false);assert.equal(s.setMode,undefined,'spoken language mode is no longer exposed');
 s.offer({id:'msg-1',agentId:'a',speaker:'Agent A',text});
 await new Promise(r=>setImmediate(r));assert.equal(requests,0);assert.equal(s.current.playing,true);assert.equal(s.current.messageId,'msg-1');
 const caption=s.current.caption;assert.ok(caption.length>0&&caption.length<=80);assert.equal(s.current.captionIndex,0);assert.equal(s.current.captionProgress,0);
 context.currentTime=s.current.startedAt+s.current.captionCues[0].end*.7;assert.ok(s.current.captionProgress>.65&&s.current.captionProgress<.75);
 const firstCue=s.current.cues[0];context.currentTime=s.current.startedAt+firstCue.start+.08;assert.equal(s.mouth('a').code,firstCue.value,'mouth cue uses the synchronized audio clock');
 await s.pause();assert.equal(s.paused,true);const frozen=s.current.captionProgress,pausedAt=context.currentTime;assert.equal(s.current.captionProgress,frozen,'suspended AudioContext time freezes captions');assert.equal(context.currentTime,pausedAt);await s.pause();
 const playing=s.current,node=s.node;
 s.setMuted(true);assert.equal(s.output.gain.value,0);assert.equal(s.current,playing);assert.equal(node.stopped,undefined,'mute preserves caption and phoneme clock');
 s.setMuted(false);assert.equal(s.output.gain.value,1);assert.equal(s.current,playing);
 s.reset();assert.equal(context.sources[0].stopped,true);assert.equal(s.current,null);assert.equal(s.queue.length,0);
 await new Promise(r=>setImmediate(r));assert.equal(s.failed,false,'cancelled playback cannot overwrite reset state');
 const locked=new StudioSpeech(()=>{});locked.context=bufferContext();locked.context.state='suspended';locked.init();
 locked.offer({id:'old',agentId:'a',speaker:'A',text:'Old message'});locked.offer({id:'new',agentId:'a',speaker:'A',text:'New message'});
 assert.equal(locked.current,null);assert.equal(locked.queue.length,1,'autoplay lock must not build stale backlog');assert.equal(locked.needsGesture,true);
 await locked.unlock();assert.equal(locked.current.messageId,'new');assert.equal(locked.needsGesture,false);locked.disable();
 global.localStorage={getItem:()=> 'true',setItem(){}};const remembered=new StudioSpeech(()=>{});assert.equal(remembered.muted,true);
 assert.equal(requests,0,'neither init nor playback calls a voice API');
 const profiles=['midnight-0','paper-0','pocket-0'].map(StudioGarble.voiceProfile);assert.deepEqual(profiles.map(p=>p.channel),['midnight','paper','pocket']);assert.ok(profiles.every(p=>p.source==='synthesized'));
 console.log('Gibberish only: cast synthesis, loudness, deterministic phonemes, captions, autoplay, mute, pause and cancellation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
