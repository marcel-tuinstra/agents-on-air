const assert = require('node:assert/strict');
const {StudioStream} = require('../static/stream.js');
const sources=[],timers=new Map();let next=0;
const stream=new StudioStream({
 create(url){const source={url,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},close(){this.closed=true;}};sources.push(source);return source;},
 schedule(fn){timers.set(++next,fn);return next;},cancel(id){timers.delete(id);}
});
const received=[],handlers={snapshot:data=>received.push(data.id)};
stream.connect('codex:first',handlers);
const first=sources[0];first.listeners.snapshot({data:'{"id":"one"}'});
stream.connect('claude:second',handlers);
assert.equal(first.closed,true);
first.listeners.snapshot({data:'{"id":"stale"}'});
first.onerror();assert.equal(timers.size,0);
sources[1].onerror();assert.equal(timers.size,1);
const reconnect=[...timers.values()][0];reconnect();
assert.equal(sources[2].url,'/api/events?chat=claude%3Asecond');
sources[2].listeners.snapshot({data:'{"id":"two"}'});
sources[2].listeners.snapshot({data:'invalid json'});
assert.equal(sources[2].closed,true);
stream.stop();const count=sources.length;reconnect();
assert.equal(sources.length,count);
assert.deepEqual(received,['one','two']);
console.log('Stream: chat switches, stale events, reconnects, invalid JSON and cancellation passed');
// Browser timer functions reject a controller instance as their receiver.
const vm=require('node:vm'),fs=require('node:fs');
const nativeLike={module:{exports:{}},setTimeout:function(){'use strict';assert.equal(this,undefined);return 1;},clearTimeout:function(){'use strict';assert.equal(this,undefined);}};
vm.runInNewContext(fs.readFileSync(require.resolve('../static/stream.js'),'utf8'),nativeLike);
const nativeStream=new nativeLike.module.exports.StudioStream({create:()=>({addEventListener(){},close(){}})});
nativeStream.connect('test',{});nativeStream.source.onerror();nativeStream.stop();
