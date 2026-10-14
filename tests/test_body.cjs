const assert=require('node:assert/strict');const {pose,draw}=require('../static/body.js');
const a=pose({time:1000,id:0,talking:true}),b=pose({time:1200,id:0,talking:true});assert.notEqual(a.left,b.left);assert.notEqual(a.rh,b.rh);
assert.ok(Math.abs(pose({time:1000,pointing:true}).right)>.05);
assert.ok(Array.from({length:20},(_,i)=>pose({time:i*80,waiting:true}).tap).some(n=>n>.4));
assert.ok(Object.values(pose({time:1234,waiting:true,talking:true,reduced:true})).every(v=>v===0));
assert.ok(pose({time:10000,waiting:true}).sleep>.95,'long closed-eye rest');
assert.equal(pose({time:19000,waiting:true}).sleep,0,'brief wake-up between naps');
assert.ok(pose({time:10000,waiting:true}).head>.08,'visible head droop');
for(const theme of ['midnight','paper','pocket'])for(let id=0;id<=10;id++){
 let faces=0,depth=0;const c=new Proxy({}, {get:(_,key)=> key==='save'?()=>depth++:key==='restore'?()=>depth--:()=>{}});
 draw(c,{frame:{},id,theme,time:3100,talking:true,drawFace:()=>faces++});assert.equal(faces,1);assert.equal(depth,0);
}
console.log('Body rig: independent arm/hand poses, tap, pointing, all cast slots, reduced motion and balanced layers passed');
