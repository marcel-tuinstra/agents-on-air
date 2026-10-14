const assert=require('node:assert/strict');
const {speechDuration,isRecent,safeLink,plainText}=require('../static/markdown.js');
assert.equal(speechDuration('kort'),6000);
assert.ok(speechDuration('woord '.repeat(180))>=60000);
assert.ok(speechDuration('woord '.repeat(500))>speechDuration('woord '.repeat(180)));
assert.equal(speechDuration('woord '.repeat(5000)),300000);
for(const url of ['javascript:alert(1)','data:text/html,x','file:///etc/passwd','/Users/private','//evil.test'])assert.equal(safeLink(url),null);
assert.equal(safeLink('https://example.com/path'),'https://example.com/path');
assert.equal(plainText('**Sterk** en [link](https://example.com)'),'Sterk en link');
console.log('Text helpers: duration scaling/bounds, safe URLs and preview text passed');

assert.equal(isRecent({updatedAt:1000,status:'idle'},7,1000+7*86400),true);
assert.equal(isRecent({updatedAt:1000,status:'idle'},7,1001+7*86400),false);
assert.equal(isRecent({updatedAt:1000,status:'working'},3,1001+7*86400),true);
assert.equal(isRecent({updatedAt:1000,status:'idle'},3,1001+3*86400),false);
console.log('Recency filters: 72h/7d boundaries and working chats passed');
