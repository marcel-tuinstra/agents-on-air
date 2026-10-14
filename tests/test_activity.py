import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from test_viewer import StoreFixture, record, msg
from test_claude import event
from providers.codex import CodexProvider, Rollout
from providers.claude import ClaudeCodeProvider

class ActivityTests(unittest.TestCase):
    def test_codex_tool_and_lifecycle_count_but_metadata_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'log.jsonl'; r=Rollout(path)
            records=[record('session_meta', {'cwd':tmp}), record('event_msg',{'type':'task_started','turn_id':'t'}),
                record('event_msg',{'type':'item_completed','item':{'type':'McpToolCall','id':'tool','tool':'read','arguments':{'secret':'HIDDEN'},'result':'HIDDEN'}}),
                record('event_msg',{'type':'item_completed','item':{'type':'McpToolCall','id':'tool','tool':'read'}}),
                record('event_msg',{'type':'task_complete','turn_id':'t'})]
            path.write_text(''.join(json.dumps(x)+'\n' for x in records));r.refresh()
            self.assertEqual(len(r.events),3)
            self.assertEqual({e['kind'] for e in r.events},{'lifecycle','work'})
            self.assertNotIn('HIDDEN',json.dumps(list(r.events)))
            at=r.last_activity
            r.consume(record('turn_context',{'model':'renamed'}))
            self.assertEqual(r.last_activity,at)
    def test_codex_response_item_tool_progress_is_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'log.jsonl'
            records=[record('response_item',{'type':'function_call','name':'exec_command','call_id':'one','arguments':'SECRET ARG'}),
                record('response_item',{'type':'function_call_output','call_id':'one','output':'SECRET OUTPUT'}),
                record('response_item',{'type':'function_call','name':'wait','call_id':'poll','arguments':'POLL'}),
                record('response_item',{'type':'reasoning','content':'PRIVATE'})]
            path.write_text(''.join(json.dumps(x)+'\n' for x in records))
            r=Rollout(path).refresh()
            self.assertEqual(len(r.events),2)
            self.assertTrue(all(e['kind']=='work' for e in r.events))
            self.assertNotIn('SECRET',json.dumps(list(r.events)))
    def test_descendant_activity_reaches_catalog_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=StoreFixture(tmp);self.addCleanup(f.db.close)
            parent=msg('m','Parent');parent['timestamp']='2026-10-13T00:00:00Z'
            child=msg('c','Child');child['timestamp']='2026-10-14T00:00:00Z'
            f.add('main',events=[parent]);f.add('child','subagent',[child]);f.edge('main','child')
            p=CodexProvider(f.home)
            self.assertEqual(p.list_chats()[0]['lastActivityAt'],p.snapshot('main')['lastActivityAt'])
            self.assertGreater(p.list_chats()[0]['lastActivityAt'],p.cache['main'].last_activity)
            self.assertEqual(p.snapshot('main')['chat']['lastActivityAt'],p.snapshot('main')['lastActivityAt'])
            self.assertTrue(any(e['agentId']=='codex:child' for e in p.snapshot('main')['events']))
    def test_claude_tool_activity_without_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-demo';folder.mkdir(parents=True)
            path=folder/'one.jsonl'; e=event('assistant','a');e['message']['content']=[{'type':'tool_use','id':'t','name':'Read','input':{'file_path':'/secret'}}]
            path.write_text(json.dumps(e)+'\n');p=ClaudeCodeProvider(home)
            snap=p.snapshot('-demo/one')
            self.assertTrue(snap['lastActivityAt'])
            self.assertEqual(snap['events'][0]['kind'],'work')
            self.assertNotIn('/secret',json.dumps(snap))
    def test_claude_same_uuid_revision_updates_activity_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-demo';folder.mkdir(parents=True)
            path=folder/'one.jsonl'
            first=event('assistant','same','Draft',timestamp='2026-10-14T10:00:00Z')
            revised=event('assistant','same','Final',timestamp='2026-10-14T10:01:00Z')
            duplicate=event('assistant','same','Final',timestamp='2026-10-14T10:02:00Z')
            path.write_text(''.join(json.dumps(x)+'\n' for x in (first,revised,duplicate)))
            snap=ClaudeCodeProvider(home).snapshot('-demo/one')
            self.assertEqual(len(snap['events']),1)
            self.assertEqual(snap['events'][0]['label'],'Updated a message')
            self.assertEqual(snap['lastActivityAt'],snap['events'][0]['at'])
            self.assertEqual(snap['lastActivityAt'],datetime.fromisoformat('2026-10-14T10:01:00+00:00').timestamp())
if __name__=='__main__':unittest.main()
