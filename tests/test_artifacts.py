from contextlib import ExitStack
import json
import base64
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from test_viewer import StoreFixture, record, msg
from providers.codex import CodexProvider
from providers.claude import ClaudeCodeProvider
from providers.base import Registry, ProviderError
from providers.artifacts import RecentArtifacts
from server import StudioServer

PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*32

class ArtifactTests(unittest.TestCase):
    def test_artifact_selection_is_bounded_and_defers_file_reads(self):
        pending=RecentArtifacts(2)
        built=[]
        def build(identity):
            built.append(identity)
            return {'id':identity}
        pending.add('old-event',1,build,'old')
        pending.add('new-event',3,build,'new')
        pending.add('middle-event',2,build,'middle')
        self.assertEqual(built,[])
        self.assertEqual(len(pending.pending),2)
        artifacts,links=pending.collect()
        self.assertEqual(built,['new','middle'])
        self.assertEqual(artifacts,[{'id':'new'},{'id':'middle'}])
        self.assertEqual(links,{'new-event':['new'],'middle-event':['middle']})
    def test_before_after_roles_require_explicit_alt_labels_in_one_event(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            root=Path(tmp);cwd=root/'work';cwd.mkdir()
            for name in ('old.png','new.png','before-preview.png'):
                (cwd/name).write_bytes(PNG)
            store=root/'store';store.mkdir();f=StoreFixture(store);resources.callback(f.db.close)
            text='![Voor](old.png) ![After](new.png) ![Preview](before-preview.png)'
            f.add('main',events=[record('session_meta',{'cwd':str(cwd)},0),msg('m',text)])
            snap=CodexProvider(f.home).snapshot('main')
            images={a['label']:a for a in snap['artifacts']}
            self.assertEqual(images['Voor']['role'],'before')
            self.assertEqual(images['After']['role'],'after')
            self.assertNotIn('role',images['Preview'])
            self.assertEqual(set(snap['events'][0]['artifactIds']),{a['id'] for a in images.values()})
    def test_referenced_image_resolves_and_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            root=Path(tmp);cwd=root/'work';cwd.mkdir();image=cwd/'diagram.png';image.write_bytes(PNG)
            secret=root/'secret.png';secret.write_bytes(PNG)
            (root/'store').mkdir();f=StoreFixture(root/'store');resources.callback(f.db.close)
            e=msg('m','See ![diagram](diagram.png) and ![secret](../secret.png)')
            f.add('main',events=[record('session_meta',{'cwd':str(cwd)},0),e])
            reg=Registry([CodexProvider(f.home)]);snap=reg.snapshot('codex:main')
            images=[a for a in snap['artifacts'] if a['kind']=='image']
            self.assertEqual(len(images),1)
            self.assertEqual(images[0]['messageId'],'codex:main:m')
            self.assertEqual(reg.artifact(images[0]['id'])[0],PNG)
            with self.assertRaises(ProviderError):reg.artifact('guessed')
            image.unlink()
            with self.assertRaises(ProviderError):reg.artifact(images[0]['id'])
    def test_file_change_diff_attaches_to_work_event(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            change=record('event_msg',{'type':'item_completed','item':{'type':'FileChange','id':'patch1','changes':{'/work/main.py':{'type':'update','unified_diff':'@@ -1 +1 @@\n-old\n+new\n'}}}})
            f.add('main',events=[change]);snap=CodexProvider(f.home).snapshot('main')
            diffs=[a for a in snap['artifacts'] if a['kind']=='diff']
            self.assertEqual(len(diffs),1)
            self.assertIn('+new',diffs[0]['text'])
            self.assertIn(diffs[0]['id'],snap['events'][0]['artifactIds'])
    def test_completed_child_without_message_keeps_all_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            f.add('main',events=[record('event_msg',{'type':'task_started','turn_id':'parent'})])
            f.add('child','subagent',[
                record('turn_context',{'turn_id':'child-turn','root_turn_id':'parent'}),
                record('event_msg',{'type':'item_completed','item':{'type':'FileChange','id':'patch',
                    'changes':{name:{'unified_diff':'@@ -1 +1 @@\n-old\n+new\n'} for name in ('one.py','two.py')}}}),
                record('event_msg',{'type':'task_complete','turn_id':'child-turn'})])
            f.edge('main','child')
            snap=CodexProvider(f.home).snapshot('main')
            self.assertEqual({a['label'] for a in snap['artifacts']},{'Changed one.py','Changed two.py'})
            self.assertTrue(all(a['agentId']=='codex:child' for a in snap['artifacts']))
            self.assertIn('codex:child',{a['id'] for a in snap['agents']})
            change=next(e for e in snap['events'] if len(e['artifactIds'])==2)
            self.assertEqual(change['agentId'],'codex:child')
    def test_recent_child_diff_is_not_crowded_out_by_main_history(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            def change(identity, names):
                return record('event_msg',{'type':'item_completed','item':{'type':'FileChange','id':identity,
                    'changes':{name:{'unified_diff':'@@ -1 +1 @@\n-old\n+new\n'} for name in names}}})
            events=[record('event_msg',{'type':'task_started','turn_id':'parent'})]
            events += [change('batch'+str(i),[f'file-{i}-{j}.py' for j in range(20)]) for i in range(11)]
            f.add('main',events=events)
            f.add('child','subagent',[
                record('turn_context',{'turn_id':'child-turn','root_turn_id':'parent'}),
                change('child-patch',['latest.py'])])
            f.edge('main','child')
            snap=CodexProvider(f.home).snapshot('main')
            self.assertLessEqual(len(snap['artifacts']),200)
            self.assertIn('Changed latest.py',{a['label'] for a in snap['artifacts']})
    def test_claude_edit_uses_recorded_before_after_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            work=home/'work';work.mkdir()
            e={'type':'assistant','uuid':'a','timestamp':'2026-10-14T10:00:00Z','cwd':str(work),
               'message':{'content':[{'type':'tool_use','id':'edit-1','name':'Edit',
                 'input':{'file_path':str(work/'main.py'),'old_string':'old\n','new_string':'new\n'}}],
                 'stop_reason':'tool_use'}}
            (folder/'one.jsonl').write_text(json.dumps(e)+'\n')
            snap=ClaudeCodeProvider(home).snapshot('-work/one')
            self.assertEqual(len(snap['artifacts']),1)
            self.assertIn('+new',snap['artifacts'][0]['text'])
            self.assertTrue(snap['artifacts'][0]['label'].startswith('Proposed change'))
            self.assertIn(snap['artifacts'][0]['id'],snap['events'][0]['artifactIds'])
    def test_failed_claude_edit_is_still_only_a_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            request={'type':'assistant','uuid':'ask','timestamp':'2026-10-14T10:00:00Z','cwd':str(home),
                'message':{'content':[{'type':'tool_use','id':'edit-failed','name':'Edit',
                    'input':{'file_path':str(home/'main.py'),'old_string':'old','new_string':'new'}}],
                    'stop_reason':'tool_use'}}
            denial={'type':'user','uuid':'deny','timestamp':'2026-10-14T10:00:01Z','cwd':str(home),
                'message':{'content':[{'type':'tool_result','tool_use_id':'edit-failed','is_error':True,
                    'content':'Permission denied'}]}}
            (folder/'one.jsonl').write_text(json.dumps(request)+'\n'+json.dumps(denial)+'\n')
            snap=ClaudeCodeProvider(home).snapshot('-work/one')
            self.assertEqual(len(snap['artifacts']),1)
            self.assertTrue(snap['artifacts'][0]['label'].startswith('Proposed change'))
            self.assertIn('unverified',snap['artifacts'][0]['provenance'])
            self.assertNotIn('Permission denied',json.dumps(snap))
    def test_claude_inline_image_has_local_opaque_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            e={'type':'user','uuid':'image1','timestamp':'2026-10-14T10:00:00Z','cwd':str(home),
               'message':{'content':[{'type':'image','source':{'type':'base64','media_type':'image/png',
                  'data':base64.b64encode(PNG).decode()}}]}}
            (folder/'one.jsonl').write_text(json.dumps(e)+'\n')
            p=ClaudeCodeProvider(home);snap=p.snapshot('-work/one')
            self.assertEqual(len(snap['artifacts']),1)
            self.assertEqual(p.artifact_store.resolve(snap['artifacts'][0]['id'])[0],PNG)
            self.assertNotIn(base64.b64encode(PNG).decode(),json.dumps(snap))
    def test_codex_recorded_apply_patch_is_labeled(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            patch='*** Begin Patch\n*** Update File: main.py\n@@\n-old\n+new\n*** End Patch'
            e=record('response_item',{'type':'custom_tool_call','name':'apply_patch','call_id':'patch',
                                      'input':patch,'status':'completed'})
            f.add('main',events=[e]);snap=CodexProvider(f.home).snapshot('main')
            self.assertEqual(len(snap['artifacts']),1)
            self.assertIn('apply_patch',snap['artifacts'][0]['provenance'])
            self.assertIn(snap['artifacts'][0]['id'],snap['events'][0]['artifactIds'])
    def test_sensitive_patch_path_is_withheld(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            change=record('event_msg',{'type':'item_completed','item':{'type':'FileChange','id':'secret-change',
                'changes':{'/work/.env':{'unified_diff':'@@ -1 +1 @@\n-old\n+new\n'}}}})
            f.add('main',events=[change]);snap=CodexProvider(f.home).snapshot('main')
            self.assertEqual(snap['artifacts'],[])
            self.assertEqual(len(snap['events']),1)
    def test_sensitive_parent_folder_is_checked_before_shortening_filename(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as resources:
            f=StoreFixture(tmp);resources.callback(f.db.close)
            change=record('event_msg',{'type':'item_completed','item':{'type':'FileChange','id':'private-change',
                'changes':{'/work/secrets/config.py':{'unified_diff':'@@ -1 +1 @@\n-old\n+synthetic\n'}}}})
            f.add('main',events=[change])
            self.assertEqual(CodexProvider(f.home).snapshot('main')['artifacts'],[])
    def test_claude_sensitive_parent_folder_is_withheld(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'projects'/'-work';folder.mkdir(parents=True)
            entry={'type':'assistant','uuid':'edit','timestamp':'2026-10-14T10:00:00Z',
                'message':{'content':[{'type':'tool_use','id':'private-edit','name':'Edit',
                    'input':{'file_path':'C:\\work\\secrets\\config.py','old_string':'old\n','new_string':'synthetic\n'}}]}}
            (folder/'one.jsonl').write_text(json.dumps(entry)+'\n')
            self.assertEqual(ClaudeCodeProvider(home).snapshot('-work/one')['artifacts'],[])

class ArtifactHttpTests(unittest.TestCase):
    def test_authenticated_image_route_and_no_arbitrary_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cwd=root/'work';cwd.mkdir();(cwd/'diagram.png').write_bytes(PNG)
            store=root/'store';store.mkdir();f=StoreFixture(store)
            f.add('main',events=[record('session_meta',{'cwd':str(cwd)},0),msg('one','![diagram](diagram.png)')])
            server=StudioServer(('127.0.0.1',0),Registry([CodexProvider(f.home)]))
            class FakeNarration:
                def config(self): return {'enabled':True,'mode':'byok','provider':'test','model':'test','note':''}
                def summarize(self, snapshot):
                    self.assert_snapshot = snapshot
                    return {'text':'Summary','label':'AI-samenvatting','sourceMessageIds':[], 'createdAt':1}
            server.narration=FakeNarration()
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base='http://127.0.0.1:'+str(server.server_port)
                with urllib.request.urlopen(base+'/',timeout=5) as response:
                    cookie=response.headers['Set-Cookie'].split(';')[0]
                    html=response.read().decode()
                class Scripts(HTMLParser):
                    def __init__(self):
                        super().__init__();self.sources=[]
                    def handle_starttag(self,tag,attrs):
                        if tag == 'script':
                            source=dict(attrs).get('src')
                            if source:self.sources.append(source)
                parser=Scripts();parser.feed(html)
                self.assertIn('/stage-model.js',parser.sources)
                for source in parser.sources:
                    with urllib.request.urlopen(urllib.request.Request(urljoin(base+'/',source),headers={'Cookie':cookie}),timeout=5) as response:
                        self.assertEqual(response.status,200)
                        self.assertIn('javascript',response.headers['Content-Type'])
                with urllib.request.urlopen(urllib.request.Request(base+'/api/snapshot?chat=codex:main',headers={'Cookie':cookie}),timeout=5) as response:
                    artifact=json.load(response)['artifacts'][0]
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(base+artifact['url'],timeout=5)
                self.assertEqual(unauthorized.exception.code,401)
                with urllib.request.urlopen(urllib.request.Request(base+artifact['url'],headers={'Cookie':cookie}),timeout=5) as response:
                    self.assertEqual(response.read(),PNG)
                    self.assertEqual(response.headers['Content-Type'],'image/png')
                with self.assertRaises(urllib.error.HTTPError) as guessed:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/artifacts/'+'0'*32,headers={'Cookie':cookie}),timeout=5)
                self.assertEqual(guessed.exception.code,404)
                with self.assertRaises(urllib.error.HTTPError) as foreign:
                    urllib.request.urlopen(urllib.request.Request(base+artifact['url'],headers={'Cookie':cookie,'Origin':'https://evil.test'}),timeout=5)
                self.assertEqual(foreign.exception.code,403)
                with urllib.request.urlopen(urllib.request.Request(base+'/api/narration/config',headers={'Cookie':cookie}),timeout=5) as response:
                    self.assertTrue(json.load(response)['enabled'])
                request=urllib.request.Request(base+'/api/narration',data=b'{"chatId":"codex:main"}',
                    headers={'Cookie':cookie,'Content-Type':'application/json'},method='POST')
                with urllib.request.urlopen(request,timeout=5) as response:
                    self.assertEqual(json.load(response)['text'],'Summary')
                self.assertEqual(server.narration.assert_snapshot['chat']['id'],'codex:main')
            finally:
                server.shutdown();server.server_close();f.db.close()
if __name__=='__main__':unittest.main()
