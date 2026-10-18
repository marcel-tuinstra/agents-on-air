import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers.base import Provider, Registry, ProviderError
from providers.codex import CodexProvider, Rollout, MAX_INITIAL
from server import StudioServer


def record(kind, payload, ordinal=1):
    return {'type': kind, 'ordinal': ordinal, 'timestamp': datetime.now(timezone.utc).isoformat(), 'payload': payload}

def msg(identity, text, role='AgentMessage', ordinal=1):
    return record('event_msg', {'type':'item_completed','turn_id':'turn','item':{'type':role,'id':identity,'content':[{'type':'Text','text':text}],'phase':'commentary'}}, ordinal)

class StoreFixture:
    def __init__(self, base):
        self.home=Path(base);(self.home/'sessions').mkdir()
        self.db=sqlite3.connect(self.home/'state_5.sqlite')
        self.db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,thread_source TEXT,name TEXT,title TEXT,model TEXT,archived INTEGER,updated_at INTEGER,source TEXT,agent_nickname TEXT,agent_role TEXT)')
        self.db.execute('CREATE TABLE thread_spawn_edges(parent_thread_id TEXT,child_thread_id TEXT,status TEXT)')
    def add(self, id, source='user', events=None):
        path=self.home/'sessions'/f'{id}.jsonl'
        path.write_text(''.join(json.dumps(e)+'\n' for e in events or []))
        self.db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?)',(id,str(path),source,id,id,'test-model',0,int(time.time()),'vscode' if source=='user' else 'subagent',id,'Developer'))
        self.db.commit();return path
    def edge(self,parent,child):
        self.db.execute('INSERT INTO thread_spawn_edges VALUES (?,?,?)',(parent,child,'open'));self.db.commit()

class ParserTests(unittest.TestCase):
    def test_command_completion_counts_as_work_without_inventing_a_diff(self):
        r = Rollout(Path('unused'))
        r.consume(record('event_msg', {'type': 'item_completed', 'item': {
            'type': 'CommandExecution', 'id': 'shell-edit', 'status': 'completed',
            'command': 'private command', 'aggregated_output': 'private output'}}))
        self.assertEqual(r.events[-1]['label'], 'Ran a command')
        self.assertGreater(r.last_activity, 0)
        self.assertFalse(r.diff_refs)
        self.assertNotIn('private', json.dumps(list(r.events)))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'log.jsonl';self.path.touch()
    def append(self,e):
        with self.path.open('a') as f:f.write(json.dumps(e)+'\n')
    def test_append_partial_duplicate_and_private_content(self):
        r=Rollout(self.path);self.append(msg('one','Visible'))
        self.append(record('response_item',{'type':'reasoning','summary':'HIDDEN'}))
        self.append(record('event_msg',{'type':'item_completed','item':{'type':'Reasoning','raw_content':'HIDDEN'}}))
        self.append(record('response_item',{'type':'message','role':'system','content':'SECRET'}))
        self.append(msg('one','Visible'));r.refresh();self.assertEqual([m['text'] for m in r.messages],['Visible'])
        line=json.dumps(msg('two','Second'))
        with self.path.open('a') as f:f.write(line[:30])
        r.refresh();self.assertEqual(len(r.messages),1)
        with self.path.open('a') as f:f.write(line[30:]+'\n')
        r.refresh();self.assertEqual(len(r.messages),2)
    def test_final_answer_is_visible(self):
        e=msg('answer','Final answer');e['payload']['item']['phase']='final_answer';self.append(e);self.assertEqual(Rollout(self.path).refresh().messages[0]['text'],'Final answer')
    def test_rotation_and_truncation_reset(self):
        self.append(msg('one','Old'));r=Rollout(self.path).refresh();self.path.write_text(json.dumps(msg('two','New'))+'\n');r.refresh();self.assertEqual([m['text'] for m in r.messages],['New'])
    def test_inherited_child_history_is_excluded(self):
        self.append(record('session_meta',{'subagent_history_start_ordinal':10},0));self.append(msg('old','Inherited',ordinal=5));self.append(msg('new','New work',ordinal=11));self.assertEqual([m['text'] for m in Rollout(self.path).refresh().messages],['New work'])
    def test_status_turn_interleaving_and_stale(self):
        r=Rollout(self.path);r.consume(record('event_msg',{'type':'task_started','turn_id':'a'}));r.consume(record('event_msg',{'type':'task_complete','turn_id':'b'}));self.assertEqual(r.status(),'working');r.last_event=time.time()-301;self.assertEqual(r.status(),'unknown');r.consume(record('event_msg',{'type':'task_complete','turn_id':'a'}));self.assertEqual(r.status(),'idle')
    def test_history_bounded_and_initial_tail(self):
        for i in range(220):self.append(msg(str(i),'x'))
        r=Rollout(self.path).refresh();self.assertEqual(len(r.messages),200);self.assertTrue(r.truncated)
        self.path.write_text(json.dumps(record('response_item',{'type':'tool','output':'x'*(MAX_INITIAL+10)}))+'\n'+json.dumps(msg('last','Visible'))+'\n')
        r=Rollout(self.path).refresh();self.assertEqual(r.messages[-1]['text'],'Visible');self.assertTrue(r.truncated)

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.f=StoreFixture(self.tmp.name);self.addCleanup(self.f.db.close);self.p=CodexProvider(self.f.home)
    def test_roots_children_and_read_only(self):
        self.f.add('main',events=[record('event_msg',{'type':'task_started','turn_id':'turn','root_turn_id':'turn'}),msg('m','Main')]);self.f.add('sub','subagent',[record('turn_context',{'turn_id':'child-turn','root_turn_id':'turn'}),msg('s','Sub')]);self.f.add('guardian','guardian_review',[msg('g','Internal')]);self.f.edge('main','sub');self.f.edge('main','guardian')
        self.assertEqual(len(self.p.list_chats()),1)
        snap=self.p.snapshot('main');self.assertEqual({a['id'] for a in snap['agents']},{'codex:main','codex:sub'});self.assertNotIn('Internal',json.dumps(snap));self.assertEqual(len(snap['messages']),2)
        c=self.p.connect()
        with self.assertRaises(sqlite3.OperationalError):c.execute('DELETE FROM threads')
        c.close()
    def test_missing_and_path_escape(self):
        with self.assertRaises(ProviderError):self.p.snapshot('missing')
        self.f.add('main');self.f.db.execute("UPDATE threads SET rollout_path='/etc/passwd'");self.f.db.commit()
        with self.assertRaises(ProviderError):self.p.snapshot('main')
    def test_update_without_restarting(self):
        path=self.f.add('main',events=[msg('one','Initial')]);a=self.p.snapshot('main')
        with path.open('a') as f:f.write(json.dumps(msg('two','New message'))+'\n')
        b=self.p.snapshot('main');self.assertNotEqual(a['revision'],b['revision']);self.assertEqual(len(b['messages']),2)
    def test_provider_namespace(self):
        class Fake(Provider):
            id='claude';label='Anthropic · Claude Code'
            def list_chats(self):return [{'id':'claude:main','provider':'claude','updatedAt':'2026-10-14T09:00:00Z'}]
            def snapshot(self,key):return {'provider':'claude','nativeId':key}
        self.f.add('main');r=Registry([self.p,Fake()]);self.assertEqual({c['id'] for c in r.catalog()['chats']},{'claude:main','codex:main'});self.assertEqual(r.snapshot('claude:main')['provider'],'claude')

class StartupTests(unittest.TestCase):
    def test_loopback_startup_does_not_wait_for_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=RuntimeError('Resolver unavailable')) as lookup:
            server = StudioServer(('127.0.0.1', 0), Registry([]))
            self.addCleanup(server.server_close)
            self.assertGreater(server.server_port, 0)
            self.assertEqual(server.server_name, 'localhost')
            lookup.assert_not_called()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.f=StoreFixture(self.tmp.name);self.addCleanup(self.f.db.close);self.path=self.f.add('main',events=[msg('one','Public user-facing text')]);self.server=StudioServer(('127.0.0.1',0),Registry([CodexProvider(self.f.home)]));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown);self.url=f'http://127.0.0.1:{self.server.server_port}'
    def get(self,path,headers=None):return urllib.request.urlopen(urllib.request.Request(self.url+path,headers=headers or {}),timeout=5)
    def test_access_guards_and_no_mutation_routes(self):
        for path,headers,code in [('/api/catalog',{},401),('/',{'Host':'evil.test'},403),('/',{'Origin':'https://evil.test'},403),('/',{'Sec-Fetch-Site':'cross-site'},403)]:
            with self.assertRaises(urllib.error.HTTPError) as e:self.get(path,headers)
            self.assertEqual(e.exception.code,code)
        with self.get('/') as root:cookie=root.headers['Set-Cookie'].split(';')[0]
        headers={'Cookie':cookie}
        with self.get('/api/catalog',headers) as r:self.assertEqual(len(json.load(r)['chats']),1)
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(urllib.request.Request(self.url+'/api/turn',data=b'{}',headers=headers))
        self.assertEqual(e.exception.code,405)
    def test_language_speech_removed(self):
        with self.get('/') as page:
            cookie=page.headers['Set-Cookie'].split(';')[0]
            html=page.read()
        self.assertIn(b'data-audio-mute',html)
        self.assertIn(b'lang="en"',html)
        self.assertIn(b'data-open-settings',html)
        self.assertNotIn(b'data-audio-mode',html)
        headers={'Cookie':cookie}
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/api/speech/voices',headers)
        self.assertEqual(e.exception.code,404)
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(urllib.request.Request(self.url+'/api/speech',data=b'{}',headers=headers))
        self.assertEqual(e.exception.code,405)
        self.assertFalse(hasattr(self.server,'speech'))
        with self.get('/voice-profiles.js',headers) as voice:
            self.assertIn(b'StudioVoiceProfiles',voice.read())
        for name in ['Silkscreen-Regular','Lora','Nunito','PixelifySans']:
            with self.get('/fonts/'+name+'.ttf',headers) as font:
                self.assertEqual(font.headers['Content-Type'],'font/ttf')
                self.assertEqual(font.read()[:4],b'\x00\x01\x00\x00')
        for route in ['/paper-voice.js','/pocket-voices.js']:
            with self.assertRaises(urllib.error.HTTPError) as old:self.get(route,headers)
            self.assertEqual(old.exception.code,404)
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/voice-profiles.js')
        self.assertEqual(e.exception.code,401)

    def test_settings_api_is_local_authenticated_explicit_and_redacted(self):
        from narration import NarrationService
        self.server.narration=NarrationService({})
        with self.get('/') as page:cookie=page.headers['Set-Cookie'].split(';')[0]
        payload={'mode':'byok','provider':'openai','model':'test','apiKey':'fake-test-key','consent':True}
        def post(headers,data=payload):
            return urllib.request.urlopen(urllib.request.Request(self.url+'/api/narration/config',data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**headers}),timeout=5)
        for headers,code in [({},401),({'Cookie':cookie,'Origin':'https://evil.test'},403)]:
            with self.assertRaises(urllib.error.HTTPError) as e:post(headers)
            self.assertEqual(e.exception.code,code)
        with self.assertRaises(urllib.error.HTTPError) as e:post({'Cookie':cookie},{**payload,'consent':False})
        self.assertEqual(e.exception.code,400)
        with post({'Cookie':cookie}) as result:
            body=result.read();self.assertNotIn(b'fake-test-key',body);self.assertTrue(json.loads(body)['enabled'])
        with self.get('/api/narration/config',{'Cookie':cookie}) as result:self.assertNotIn(b'fake-test-key',result.read())
        with post({'Cookie':cookie},{'mode':'off'}) as result:self.assertFalse(json.load(result)['hasKey'])

    def test_voice_lab_assets_keep_access_guards(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/voice-lab/lab.js')
        self.assertEqual(e.exception.code,401)
        with self.get('/voice-lab') as page:
            cookie=page.headers['Set-Cookie'].split(';')[0]
            self.assertIn(b'Voice lab',page.read())
        headers={'Cookie':cookie}
        for asset in ['lab.js','lab.css','rig.js']:
            with self.get('/voice-lab/'+asset,headers) as response:
                self.assertEqual(response.status,200)
        with self.get('/voice-lab/lab.js',headers) as response:
            script=response.read()
            self.assertIn(b'new StudioSpeech',script)
            self.assertNotIn(b'decodeAudioData',script)
            self.assertNotIn(b'fetch(',script)
        for path in ['/voice-lab/../../server.py','/voice-lab/manifest.json','/voice-lab/CREDITS.txt',
                     '/voice-lab/vocal.wav','/voice-lab/synth.wav','/voice-lab/rodent.wav',
                     '/voice-lab/blips.wav','/voice-lab/robot.wav','/voice-lab/unknown.wav']:
            with self.assertRaises(urllib.error.HTTPError) as e:self.get(path,headers)
            self.assertEqual(e.exception.code,404)
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/voice-lab',{'Origin':'https://evil.test'})
        self.assertEqual(e.exception.code,403)

    def test_brand_icons_are_linked_and_served_without_a_session(self):
        page=self.get('/').read().decode()
        for path,kind in (('/favicon.svg','image/svg+xml'),('/favicon-32.png','image/png'),('/apple-touch-icon.png','image/png')):
            self.assertIn('href="'+path+'"',page)
            with self.get(path) as response:
                self.assertEqual(response.headers['Content-Type'],kind);self.assertTrue(response.read())
        with self.assertRaises(urllib.error.HTTPError):self.get('/favicon.svg',{'Host':'evil.test'})
    def test_theme_assets_require_session_and_allowlisted_paths(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.get('/themes/paper/cast.webp')
        self.assertEqual(error.exception.code,401)
        with self.get('/') as page:cookie=page.headers['Set-Cookie'].split(';')[0]
        headers={'Cookie':cookie}
        for path in ['/themes.js','/themes.css','/themes/paper/cast.webp']:
            with self.get(path,headers) as response:self.assertEqual(response.status,200)
        for path in ['/themes/paper/theme.json','/themes/paper/../../server.py','/themes/qa-radio/cast.webp']:
            with self.assertRaises(urllib.error.HTTPError) as error:self.get(path,headers)
            self.assertEqual(error.exception.code,404)

    def test_event_stream_receives_new_messages(self):
        with self.get('/') as root:cookie=root.headers['Set-Cookie'].split(';')[0]
        stream=self.get('/api/events?chat=codex:main',{'Cookie':cookie});self.addCleanup(stream.close)
        def read_snapshot():
            for _ in range(40):
                line=stream.readline().decode()
                if line.strip()=='event: snapshot':return json.loads(stream.readline().decode()[6:])
            self.fail('No snapshot')
        self.assertEqual(len(read_snapshot()['messages']),1)
        with self.path.open('a') as f:f.write(json.dumps(msg('two','Appended live'))+'\n')
        self.assertEqual(len(read_snapshot()['messages']),2)
    def test_unavailable_other_provider_does_not_break_selected_chat(self):
        class Offline(Provider):
            id='claude';label='Claude'
            def list_chats(self):raise ProviderError('Offline')
            def snapshot(self,key):raise ProviderError('Offline')
        self.server.registry.providers['claude']=Offline()
        with self.get('/') as root:cookie=root.headers['Set-Cookie'].split(';')[0]
        with self.get('/api/events?chat=codex:main',{'Cookie':cookie}) as stream:
            for _ in range(20):
                if stream.readline().decode().strip()=='event: heartbeat':
                    self.assertTrue(json.loads(stream.readline().decode()[6:])['sourceHealthy'])
                    return
        self.fail('No heartbeat')

if __name__=='__main__':unittest.main()
