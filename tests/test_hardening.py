from contextlib import ExitStack
import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from test_viewer import StoreFixture, record, msg
from live_feed import LiveFeed
from providers.artifacts import diff_artifact, sensitive_diff_path
from providers.base import Registry
from providers.claude import ClaudeCodeProvider
from providers.codex import CodexProvider, MESSAGE_TEXT, TEXT_BUDGET
from server import Handler, StudioServer
from theme_packs import load_packs

ROOT=Path(__file__).resolve().parents[1]
DIFF='@@ -1 +1 @@\n-old\n+new\n'


class SensitiveDiffTests(unittest.TestCase):
    def test_credential_file_variants_are_withheld(self):
        for path in ('credentials.json','config/service-account.json','gcp_service_account.json','certs/server.pem',
                     'tls/site.KEY','deploy/id_rsa.pub','id_ed25519_work','.env.local','prod.env','secrets.yaml',
                     'client_secret.json','keystore.jks','bundle.p12','db_password.txt','kubeconfig','api_key.txt'):
            self.assertTrue(sensitive_diff_path(path),path)
        for path in ('src/app.py','README.md','theme_tokens.json','frontend/keyboard.js','docs/monkey.md'):
            self.assertFalse(sensitive_diff_path(path),path)
    def test_secret_content_withholds_an_innocent_path(self):
        key='-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n'
        for secret in (key,'token = "ghp_'+'a1B2'*9+'"','AWS_ACCESS_KEY_ID=AKIA'+'ABCDEFGHIJKLMNOP',
                       'OPENAI_API_KEY=sk-proj-'+'x9'*16,'slack: xoxb-1234567890-abcdefghij',
                       'google = "AIza'+'S'*35+'"','stripe: sk_live_'+'4eC39HqLyjWDarjtT1zdp7dc'):
            self.assertIsNone(diff_artifact('@@ -1 +1 @@\n-old\n+'+secret+'\n','id','agent',1,'Changed app.py','test'),secret)
        self.assertIsNotNone(diff_artifact('@@ -1 +1 @@\n-old\n+key = load_key(path)  # sk-short\n','id','agent',1,'Changed app.py','test'))
    def test_codex_and_claude_credential_files_are_withheld(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            change=record('event_msg',{'type':'item_completed','item':{'type':'FileChange','id':'c',
                'changes':{'/work/credentials.json':{'unified_diff':DIFF},'/work/certs/site.pem':{'unified_diff':DIFF}}}})
            f.add('main',events=[change])
            self.assertEqual(CodexProvider(f.home).snapshot('main')['artifacts'],[])
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            entry={'type':'assistant','uuid':'edit','timestamp':'2026-10-14T10:00:00Z',
                'message':{'content':[{'type':'tool_use','id':'e','name':'Write',
                    'input':{'file_path':'/work/service-account.json','content':'{"type": "service_account"}\n'}}]}}
            (folder/'one.jsonl').write_text(json.dumps(entry)+'\n')
            self.assertEqual(ClaudeCodeProvider(home).snapshot('-work/one')['artifacts'],[])


class StalledRefreshTests(unittest.TestCase):
    def test_hanging_loader_is_superseded_and_cannot_overwrite_newer_value(self):
        now=[0];feed=LiveFeed(clock=lambda:now[0],stall=30);self.addCleanup(feed.close)
        entered,release,returned=threading.Event(),threading.Event(),threading.Event()
        self.addCleanup(release.set)
        def hang():
            entered.set();release.wait(5);returned.set();return 'late'
        self.assertEqual(feed.read('chat',lambda:'first'),'first')
        now[0]=3;self.assertEqual(feed.read('chat',hang),'first');self.assertTrue(entered.wait(1))
        now[0]=10;self.assertEqual(feed.read('chat',lambda:'unused'),'first')
        now[0]=40;generation=feed.generation
        self.assertEqual(feed.read('chat',lambda:'fresh'),'first')
        feed.wait(generation,2);self.assertEqual(feed.read('chat',lambda:'unused'),'fresh')
        generation=feed.generation;release.set();self.assertTrue(returned.wait(1));feed.wait(generation,.3)
        self.assertEqual(feed.generation,generation)
        self.assertEqual(feed.read('chat',lambda:'unused'),'fresh')
    def test_stalled_slot_can_be_evicted(self):
        now=[0];feed=LiveFeed(clock=lambda:now[0],capacity=1,stall=30);self.addCleanup(feed.close)
        release=threading.Event();self.addCleanup(release.set)
        self.assertEqual(feed.read('chat',lambda:'first'),'first')
        now[0]=3;feed.read('chat',lambda:release.wait(5))
        now[0]=40;self.assertEqual(feed.read('other',lambda:'other'),'other')


class MalformedTranscriptTests(unittest.TestCase):
    def test_claude_wrong_field_types_only_affect_that_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            good={'type':'user','uuid':'u','timestamp':'2026-10-14T10:00:00Z','cwd':'/work','message':{'content':'Hello'}}
            bad={**good,'cwd':42,'sessionId':['x'],'isSidechain':'no',
                 'message':{'content':'Odd','model':{'name':'x'}}}
            (folder/'good.jsonl').write_text(json.dumps(good)+'\n')
            (folder/'bad.jsonl').write_text(json.dumps(bad)+'\n'+json.dumps({**good,'uuid':'v','type':'assistant','message':{'content':'Hi','model':7}})+'\n')
            catalog=Registry([ClaudeCodeProvider(home)]).catalog()
            self.assertTrue(catalog['providers'][0]['connected'])
            self.assertEqual({c['id'] for c in catalog['chats']},{'claude:-work/good','claude:-work/bad'})
            snap=ClaudeCodeProvider(home).snapshot('-work/bad')
            self.assertEqual(snap['agents'][0]['model'],'Claude Code')
    def test_codex_string_ordinals_do_not_disconnect_the_provider(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            f.add('good',events=[msg('one','Fine')])
            f.add('bad',events=[record('session_meta',{'subagent_history_start_ordinal':'5','cwd':7},0),
                                {**msg('two','Still visible'),'ordinal':'9'},msg('three','After')])
            catalog=Registry([CodexProvider(f.home)]).catalog()
            self.assertTrue(catalog['providers'][0]['connected'])
            self.assertEqual({c['id'] for c in catalog['chats']},{'codex:good','codex:bad'})
            self.assertIn('After',[m['text'] for m in CodexProvider(f.home).snapshot('bad')['messages']])


class RetainedTextTests(unittest.TestCase):
    def test_messages_are_capped_per_message_and_per_reader(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            f.add('main',events=[msg('m'+str(i),str(i)+'x'*(MESSAGE_TEXT*2)) for i in range(60)])
            p=CodexProvider(f.home);snap=p.snapshot('main');reader=p.cache['main']
            self.assertTrue(all(len(m['text'])<=MESSAGE_TEXT+80 for m in snap['messages']))
            self.assertLessEqual(sum(len(m['text']) for m in reader.messages),TEXT_BUDGET)
            self.assertEqual(snap['messages'][-1]['text'][:2],'59')
            self.assertTrue(snap['historyLimited'])
    def test_claude_messages_and_revisions_are_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            base={'type':'assistant','uuid':'a','timestamp':'2026-10-14T10:00:00Z','message':{'content':'short'}}
            (folder/'one.jsonl').write_text(json.dumps(base)+'\n'+json.dumps({**base,'message':{'content':'y'*(MESSAGE_TEXT*3)}})+'\n')
            p=ClaudeCodeProvider(home);snap=p.snapshot('-work/one')
            self.assertLessEqual(len(snap['messages'][0]['text']),MESSAGE_TEXT+80)
            reader=next(iter(p.cache.values()))
            self.assertEqual(reader.text_size,sum(len(m['text']) for m in reader.messages))


class ThemeShapeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.source=Path(temp.name);shutil.copytree(ROOT/'themes/paper',self.source/'custom-fox')
        self.manifest=self.source/'custom-fox/theme.json';self.change(id='custom-fox')
    def change(self,**values):
        data=json.loads(self.manifest.read_text());data.update(values);self.manifest.write_text(json.dumps(data))
    def test_wrongly_typed_manifest_fields_raise_validation_errors(self):
        original=self.manifest.read_text()
        for values in ({'tokens':['--ink']},{'tokens':None},{'fonts':3},{'portrait':7},{'cast':5}):
            self.change(**values)
            with self.assertRaises(ValueError,msg=values):load_packs(self.source)
            self.manifest.write_text(original)
        load_packs(self.source)
        manifest=json.loads(self.manifest.read_text());del manifest['tokens'];self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'tokens'):load_packs(self.source)
    def test_wrongly_typed_audio_raises_validation_error(self):
        audio=self.source/'custom-fox/audio.json';data=json.loads(audio.read_text())
        data['voices']['paper']['templates']=4;audio.write_text(json.dumps(data))
        with self.assertRaises(ValueError):load_packs(self.source)


class ConnectionTests(unittest.TestCase):
    def start(self,server_class=StudioServer):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        f=StoreFixture(tmp.name);self.addCleanup(f.db.close);f.add('main',events=[msg('one','Hi')])
        server=server_class(('127.0.0.1',0),Registry([CodexProvider(f.home)]))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server,f'http://127.0.0.1:{server.server_port}'
    def session(self,url):
        with urllib.request.urlopen(url+'/',timeout=5) as response:
            return response.headers['Set-Cookie'].split(';')[0]
    def test_non_ascii_cookie_is_unauthorized_not_dropped(self):
        server,url=self.start()
        for cookie in ('studio_session="é"','other=1; studio_session="éé"','studio_session=é'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(url+'/api/catalog',headers={'Cookie':cookie}),timeout=5)
            self.assertEqual(caught.exception.code,401)
    def test_partial_post_body_times_out(self):
        with patch.object(Handler,'timeout',.5):
            server,url=self.start();cookie=self.session(url)
            with socket.create_connection(('127.0.0.1',server.server_port),timeout=5) as client:
                client.sendall(('POST /api/narration HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nCookie: %s\r\n'
                                'Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{"chat'%(server.server_port,cookie)).encode())
                started=time.monotonic()
                self.assertEqual(client.recv(1024),b'')
                self.assertLess(time.monotonic()-started,4)
    def test_concurrent_connections_are_bounded(self):
        class Small(StudioServer):
            connection_limit=1
        with patch.object(Handler,'timeout',3):
            server,url=self.start(Small)
            with socket.create_connection(('127.0.0.1',server.server_port),timeout=5) as idle:
                idle.sendall(b'GET / HTTP/1.1\r\n')
                time.sleep(.2)
                with self.assertRaises((urllib.error.URLError,ConnectionError)):
                    urllib.request.urlopen(url+'/',timeout=5)
            deadline=time.monotonic()+5
            while True:
                try:
                    with urllib.request.urlopen(url+'/',timeout=5) as response:
                        self.assertEqual(response.status,200);break
                except (urllib.error.URLError,ConnectionError):
                    if time.monotonic()>deadline:raise
                    time.sleep(.1)
    def test_event_stream_survives_the_request_timeout(self):
        with patch.object(Handler,'timeout',.5):
            server,url=self.start();cookie=self.session(url)
            request=urllib.request.Request(url+'/api/events?chat=codex:main',headers={'Cookie':cookie})
            with urllib.request.urlopen(request,timeout=5) as stream:
                started=time.monotonic();beats=0
                while time.monotonic()-started<2.5:
                    line=stream.readline()
                    beats+=line.startswith(b'event: heartbeat')
                self.assertGreaterEqual(beats,2)


if __name__ == '__main__':
    unittest.main()
