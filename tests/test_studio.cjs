const assert=require('node:assert/strict');
const model=require('../static/stage-model.js');

const now=1_900_000_000;
assert.equal(model.recent({lastActivityAt:now-24*3600},now),true);
assert.equal(model.recent({lastActivityAt:now-24*3600-1,status:'working'},now),false);
assert.equal(model.recent({updatedAt:now,status:'working'},now),false);
assert.equal(model.waiting({lastActivityAt:now-3600},now),true);
assert.equal(model.waiting({lastActivityAt:now-3599},now),false);
assert.equal(model.recent({lastActivityAt:now-23*3600},now),true);
assert.equal(model.waiting({lastActivityAt:now-1800},now),false);
assert.equal(model.roomState({lastActivityAt:now-3601},true,now),'waiting');
assert.equal(model.roomState({lastActivityAt:now-3601},false,now),'offline');
assert.equal(model.roomState({lastActivityAt:now},true,now),'active');
const active=[{id:'codex:selected',lastActivityAt:now-5}];
assert.equal(model.selectionDecision(active,'codex:selected',[{id:'codex',connected:true}],now),'keep');
assert.equal(model.selectionDecision([], 'codex:selected',[{id:'codex',connected:true}],now),'expired');
assert.equal(model.selectionDecision([], 'codex:selected',[{id:'codex',connected:false}],now),'unavailable');
assert.equal(model.selectionDecision(active,'codex:selected',[{id:'codex',connected:false}],now),'unavailable');

const long='Eerste zin is kort. Daarna volgt een heel lang stuk tekst met voldoende woorden om over meerdere captions te verdelen zonder op een willekeurige plek te beginnen of te eindigen.';
const chunks=model.captionParts(long);
assert.ok(chunks.length>1);
assert.equal(chunks.join(' '),long);
assert.ok(chunks.every(chunk=>chunk.length<=58));
assert.deepEqual(model.captionParts(' \n '),[]);
const first={items:[{text:'old'}],index:0,paused:true};
const held=model.appendCaptionParts(first,['new first','new second'],{speaker:'Sol'});
assert.equal(held.index,0);
assert.equal(held.items.length,3);
const live=model.appendCaptionParts({...first,paused:false},['new first','new second'],{speaker:'Sol'});
assert.equal(live.index,1);

const message={id:'m2',agentId:'a',at:200};
const snapshot={events:[{id:'e1',agentId:'a',at:199,artifactIds:['old','correct','before','after']}],artifacts:[
 {id:'old',agentId:'b',at:198,kind:'diff',text:'wrong'},
 {id:'correct',agentId:'a',at:199,kind:'diff',text:'right'},
 {id:'newer-unrelated',agentId:'a',at:201,kind:'diff',text:'future'},
 {id:'before',agentId:'a',at:199,kind:'image',url:'/api/artifacts/before',role:'before'},
 {id:'after',agentId:'a',at:199,kind:'image',url:'/api/artifacts/after',role:'after'}
]};
assert.equal(model.selectArtifact(snapshot,message).id,'correct');
assert.equal(model.selectWorkArtifact(snapshot,message).event.agentId,'a');
assert.deepEqual(model.pairImages(snapshot,snapshot.artifacts[4]),{before:snapshot.artifacts[3],after:snapshot.artifacts[4]});
assert.equal(model.pairImages({...snapshot,artifacts:snapshot.artifacts.filter(a=>a.id!=='before')},snapshot.artifacts[4]),null);
assert.equal(model.pairImages({...snapshot,artifacts:snapshot.artifacts.map(a=>({...a,role:undefined,provenance:a.role}))},snapshot.artifacts[4]),null);
const standalone={events:[{id:'later',agentId:'b',at:240,artifactIds:['later-diff']}],artifacts:[{id:'later-diff',agentId:'b',at:240,kind:'diff',text:'new change'}]};
assert.equal(model.selectWorkArtifact(standalone,message).artifact.id,'later-diff');
assert.equal(model.selectWorkArtifact(standalone,message).event.agentId,'b');
// Every file in a multi-file change must be reachable, with its own attribution.
assert.deepEqual(model.workArtifacts(snapshot,message).map(item=>item.artifact.id),['correct','before','after']);
const combined={events:[...snapshot.events,...standalone.events],artifacts:[...snapshot.artifacts,...standalone.artifacts]};
assert.deepEqual(model.workArtifacts(combined,message).map(item=>item.artifact.id),['later-diff','correct','before','after']);
assert.deepEqual(model.workArtifacts({},null),[]);
assert.equal(model.workArtifacts({artifacts:[{id:'direct',agentId:'a',messageId:'m2',kind:'diff',at:200}]},message)[0].artifact.id,'direct');
console.log('Studio model: recency, waiting, captions, artifact provenance passed');
