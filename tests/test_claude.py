from contextlib import ExitStack
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from test_viewer import record, StoreFixture
from providers.claude import ClaudeCodeProvider, ClaudeRollout
from providers.codex import CodexProvider
from providers.base import ProviderError, Registry


def event(role, identity, text=None, **extra):
    content = [{'type':'text','text':text}] if text else []
    return {'type':role,'uuid':identity,'timestamp':'2026-10-14T10:00:00Z',
            'cwd':'/projects/demo','sessionId':'session',
            'message':{'role':role,'content':content,'model':'claude-test','stop_reason':'end_turn' if role=='assistant' else None},**extra}

class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.folder=self.home/'projects'/'-projects-demo';self.folder.mkdir(parents=True)
        self.path=self.folder/'session.jsonl';self.path.touch();self.p=ClaudeCodeProvider(self.home)
    def append(self, e, path=None):
        with (path or self.path).open('a') as f:f.write(json.dumps(e)+'\n')
    def test_messages_exclude_thinking_tools_and_harness(self):
        self.append(event('user','u','Hello'))
        e=event('assistant','a','**Answer**');e['message']['content'] += [{'type':'thinking','thinking':'HIDDEN'},{'type':'tool_use','input':{'secret':'SECRET'}}];self.append(e)
        self.append(event('user','tool',message={'content':[{'type':'tool_result','content':'SECRET'}]}))
        self.append(event('user','h','<task-notification>PRIVATE</task-notification>'))
        self.append(event('user','meta','INTERNAL',isMeta=True))
        self.append({'type':'system','subtype':'turn_duration','content':'PRIVATE'})
        self.append({'type':'custom-title','customTitle':'Named session'})
        chats=self.p.list_chats();self.assertEqual(chats[0]['title'],'Named session');self.assertEqual(chats[0]['groupLabel'],'demo')
        snap=self.p.snapshot('-projects-demo/session');self.assertEqual([m['text'] for m in snap['messages']],['Hello','**Answer**']);self.assertEqual(snap['agents'][0]['status'],'idle')
        self.assertNotIn('SECRET',json.dumps(snap));self.assertNotIn('HIDDEN',json.dumps(snap))
    def test_partial_append_and_same_size_rewrite(self):
        self.append(event('assistant','one','First'));r=ClaudeRollout(self.path).refresh()
        line=json.dumps(event('assistant','two','Second'))
        with self.path.open('a') as f:f.write(line[:40])
        r.refresh();self.assertEqual(len(r.messages),1)
        with self.path.open('a') as f:f.write(line[40:]+'\n')
        r.refresh();self.assertEqual(len(r.messages),2)
        self.path.write_text(json.dumps(event('assistant','one','Other'))+'\n');r.refresh();self.assertEqual([m['text'] for m in r.messages],['Other'])
    def test_same_id_text_revision_is_preserved(self):
        self.append(event('assistant','a','Short'));a=self.p.snapshot('-projects-demo/session')
        self.append(event('assistant','a','Much longer answer'));b=self.p.snapshot('-projects-demo/session')
        self.assertEqual(len(b['messages']),1);self.assertEqual(b['messages'][0]['text'],'Much longer answer');self.assertNotEqual(a['revision'],b['revision'])
    def test_long_unknown_turn_does_not_admit_historical_children(self):
        self.path.write_text(json.dumps({'type':'progress','data':'x'*(3*1024*1024)})+'\n'+json.dumps(event('assistant','a','Tail'))+'\n')
        folder=self.folder/'session'/'subagents';folder.mkdir(parents=True);self.append(event('assistant','old','Old child'),folder/'agent-old.jsonl')
        snap=self.p.snapshot('-projects-demo/session');self.assertEqual(len(snap['agents']),1);self.assertTrue(snap['warnings'])
    def test_new_chat_and_live_revision(self):
        self.append(event('user','u','Hello'));self.p.list_chats();a=self.p.snapshot('-projects-demo/session')
        self.append(event('assistant','a','Reply'));b=self.p.snapshot('-projects-demo/session');self.assertNotEqual(a['revision'],b['revision'])
        self.append(event('user','u','Other'),self.folder/'other.jsonl');self.p.scanned_at=None;self.assertEqual(len(self.p.list_chats()),2)
    def test_subagent_lifecycle_namespace_and_history(self):
        self.append(event('user','u','Task'));d=self.folder/'session'/'subagents';d.mkdir(parents=True);child=d/'agent-abc.jsonl'
        self.append(event('user','prompt','PRIVATE PROMPT',isSidechain=True),child)
        e=event('assistant','a','Working',isSidechain=True,timestamp='2026-10-14T10:00:01Z');e['message']['stop_reason']='tool_use';self.append(e,child)
        snap=self.p.snapshot('-projects-demo/session');self.assertEqual(len(snap['agents']),2);self.assertEqual(snap['agents'][1]['lastKnownStatus'],'working');self.assertNotIn('PRIVATE PROMPT',json.dumps(snap))
        self.append(event('assistant','done','Finished',isSidechain=True,timestamp='2026-10-14T10:00:02Z'),child)
        snap=self.p.snapshot('-projects-demo/session');self.assertEqual(snap['agents'][1]['status'],'idle');self.assertTrue(all(m['id'].startswith('claude:') for m in snap['messages']))
        self.append(event('user','new','Next task',timestamp='2026-10-14T10:01:00Z'));self.assertEqual(len(self.p.snapshot('-projects-demo/session')['agents']),1)
    def test_paths_are_confined_and_unknown_id_rejected(self):
        with self.assertRaises(ProviderError):self.p.snapshot('../../outside')
        outside=self.home/'outside.jsonl';outside.write_text(json.dumps(event('user','x','SECRET'))+'\n');(self.folder/'escape.jsonl').symlink_to(outside)
        self.assertTrue(all('escape' not in c['id'] for c in self.p.list_chats()))
    def test_multi_provider_ids_and_read_only_source(self):
        self.append(event('user','u','Hello'));before=self.path.read_bytes();stamp=self.path.stat().st_mtime_ns
        with tempfile.TemporaryDirectory() as tmp:
            fixture=StoreFixture(tmp);fixture.add('session');r=Registry([CodexProvider(fixture.home),self.p]);catalog=r.catalog();self.assertEqual({c['provider'] for c in catalog['chats']},{'codex','claude'});fixture.db.close()
        self.p.snapshot('-projects-demo/session');self.assertEqual(self.path.read_bytes(),before);self.assertEqual(self.path.stat().st_mtime_ns,stamp)

class GroupingTests(unittest.TestCase):
    def test_malformed_grouping_keeps_chats_available(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close);f.add('main');p=CodexProvider(f.home)
            for data in [[], {'electron-persisted-atom-state':None}, {'local-projects':['bad']}]:
                (f.home/'.codex-global-state.json').write_text(json.dumps(data))
                self.assertEqual(p.list_chats()[0]['groupLabel'],'Recent')

    def test_saved_membership_order_custom_sections_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            for id in ['a','b','c']:f.add(id)
            state={'local-projects':{'p':{'name':'My project','rootPaths':['/projects/demo']},'empty':{'name':'Empty'}},'project-order':['empty','p'], 'thread-project-assignments':{'a':{'projectId':'p'}},'electron-persisted-atom-state':{'sidebar-project-expanded-v1-codex:p':False,'sidebar-custom-sections-v3':{'account':{'sections':[{'id':'s','name':'Games','itemKeys':['codex:thread:local:b']} ]}}}}
            path=f.home/'.codex-global-state.json';path.write_text(json.dumps(state));p=CodexProvider(f.home);chats={c['id']:c for c in p.list_chats()}
            self.assertEqual(chats['codex:a']['groupLabel'],'My project');self.assertEqual(chats['codex:b']['groupLabel'],'Games');self.assertEqual(chats['codex:c']['groupLabel'],'Recent');self.assertTrue(next(g for g in p.groups() if g['label']=='My project')['collapsed'])
            state['local-projects']['p']['name']='Renamed';path.write_text(json.dumps(state));self.assertEqual(next(c for c in p.list_chats() if c['id']=='codex:a')['groupLabel'],'Renamed')

if __name__=='__main__':unittest.main()
