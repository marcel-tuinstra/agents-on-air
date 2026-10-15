import json
import unittest
from unittest.mock import patch, Mock
from narration import NarrationService, NarrationError

SNAP={'messages':[{'id':'one','role':'assistant','speaker':'Test agent','text':'De knop is aangepast.'},
                  {'id':'secret','role':'user','text':'not forwarded'}]}
class NarrationTests(unittest.TestCase):
    def test_team_selection_keeps_quiet_agents_and_latest_corrections(self):
        messages = [
            {'id':'sam-fail','agentId':'sam','speaker':'Sam','role':'assistant','at':1,'text':'Mobile test failed.'},
            {'id':'sam-pass','agentId':'sam','speaker':'Sam','role':'assistant','at':2,'text':'Mobile test now passes.'},
            {'id':'noor','agentId':'noor','speaker':'Noor','role':'assistant','at':3,'text':'Menu issue remains open.'},
        ] + [dict(id=f'mira-{i}', agentId='mira', speaker='Mira', role='assistant', at=i+4,
                  text=f'Layout update {i}.') for i in range(10)]
        source, ids = NarrationService({}).source({'messages':messages})
        records = json.loads(source)
        self.assertEqual(len(records), 8)
        self.assertIn('sam-pass', ids)
        self.assertIn('noor', ids)
        self.assertIn('mira-9', ids)
        self.assertEqual([r['at'] for r in records], sorted(r['at'] for r in records))
        self.assertEqual(records[0]['agentId'], 'sam')
        self.assertEqual(records[0]['messageId'], 'sam-pass')

    def test_source_window_is_bounded_and_ignores_empty_or_private_records(self):
        messages = [dict(id=str(i), agentId=str(i), speaker='Same display name',
                         role='assistant', text=f'Record {i}', at=i) for i in range(40)]
        messages += [{'id':'empty','role':'assistant','text':'  '},
                     {'id':'user','role':'user','text':'private'},
                     {'id':'tool','role':'tool','text':'private'}]
        records, ids = NarrationService({}).source({'messages':messages})
        self.assertEqual(ids, [str(i) for i in range(32, 40)])
        self.assertNotIn('private', records)
        with self.assertRaises(NarrationError):
            NarrationService({}).source({'messages':messages[-3:]})
        # A quiet agent outside the recent window must not look like current work.
        repeated = [dict(id=f'busy-{i}', agentId='busy', role='assistant', text='Still checking.')
                    for i in range(32)]
        _, ids = NarrationService({}).source({'messages':[messages[0]] + repeated})
        self.assertEqual(ids, [f'busy-{i}' for i in range(24, 32)])

    def test_long_contribution_keeps_the_final_outcome_and_marks_omission(self):
        text = 'Started checking. ' + 'x'*4000 + ' Correction: the check failed.'
        records, _ = NarrationService({}).source({'messages':[
            {'id':'long','role':'assistant','speaker':'Mira','text':text}]})
        record = json.loads(records)[0]
        self.assertTrue(record['text'].startswith('Started checking.'))
        self.assertTrue(record['text'].endswith('Correction: the check failed.'))
        self.assertLessEqual(len(record['text']), 3000)
        self.assertTrue(record['textTruncated'])

    def test_settings_require_consent_and_do_not_run_a_provider(self):
        service=NarrationService({})
        payload={'mode':'byok','provider':'openai','model':'test-model','apiKey':'fake-test-key'}
        with self.assertRaises(ValueError):service.configure(payload)
        self.assertEqual(service.config()['mode'],'off')
        with patch('urllib.request.build_opener') as network, patch('subprocess.run') as cli:
            result=service.configure({**payload,'consent':True,'instructions':'Keep it brief.'})
            self.assertTrue(result['enabled']);self.assertTrue(result['hasKey'])
            self.assertNotIn('fake-test-key',json.dumps(result))
            self.assertEqual(result['instructions'],'Keep it brief.')
            network.assert_not_called();cli.assert_not_called()
        service.configure({**payload,'apiKey':'','consent':True})
        with self.assertRaises(ValueError):service.configure({**payload,'provider':'anthropic','apiKey':'','consent':True})
        self.assertEqual(service.config()['provider'],'openai')
        service.configure({'mode':'off'})
        self.assertFalse(service.config()['hasKey'])

    def test_config_is_read_under_request_lock_and_cannot_change_during_request(self):
        service=NarrationService({'STUDIO_NARRATION_MODE':'byok','STUDIO_NARRATION_PROVIDER':'openai','STUDIO_NARRATION_MODEL':'test','STUDIO_NARRATION_API_KEY':'fake-test-key'})
        original=service.config
        def locked_config():
            self.assertTrue(service._lock.locked())
            return original()
        def fake_request(source,cfg):
            with self.assertRaises(ValueError):service.configure({'mode':'off'})
            self.assertEqual(cfg['provider'],'openai')
            self.assertEqual(service.env['STUDIO_NARRATION_API_KEY'],'fake-test-key')
            return 'A test update.'
        with patch.object(service,'config',side_effect=locked_config),patch.object(service,'_byok',side_effect=fake_request):
            self.assertEqual(service.summarize(SNAP)['text'],'A test update.')
        self.assertFalse(service._lock.locked())

    def test_cli_rejects_missing_install_and_strips_api_credentials(self):
        service=NarrationService({'ANTHROPIC_API_KEY':'unused-secret','OPENAI_API_KEY':'unused-secret','PATH':'/usr/bin'})
        with patch('shutil.which',return_value=None):
            with self.assertRaises(ValueError):service.configure({'mode':'cli','provider':'claude','consent':True})
        with patch('shutil.which',return_value='/fake/claude'):
            service.configure({'mode':'cli','provider':'claude','consent':True})
            with patch('subprocess.run',return_value=Mock(returncode=0,stdout='{"result":"Test update"}')) as run:
                service.summarize(SNAP)
                env=run.call_args.kwargs['env']
                self.assertNotIn('ANTHROPIC_API_KEY',env);self.assertNotIn('OPENAI_API_KEY',env)
                self.assertEqual(env['PATH'],'/usr/bin')

    def test_invalid_settings_are_atomic(self):
        service=NarrationService({})
        for payload in ({'mode':'other'},{'mode':'off','apiKey':123},{'mode':'off','instructions':'x'*1201},{'mode':'off','command':'echo test'}):
            with self.assertRaises(ValueError):service.configure(payload)
            self.assertEqual(service.config()['mode'],'off')

    def test_off_even_with_unrelated_key(self):
        service=NarrationService({'OPENAI_API_KEY':'unused'})
        self.assertFalse(service.config()['enabled'])
        with patch('urllib.request.build_opener') as network, patch('subprocess.run') as cli:
            with self.assertRaises(NarrationError):service.summarize(SNAP)
            network.assert_not_called();cli.assert_not_called()
    def test_cli_approval_required_and_safe_flags(self):
        env={'STUDIO_NARRATION_MODE':'cli','STUDIO_NARRATION_PROVIDER':'claude'}
        with patch('shutil.which',return_value='/fake/claude'):
            service=NarrationService(env);self.assertFalse(service.config()['enabled'])
            service.env['STUDIO_NARRATION_CLI_APPROVED']='1'
            result=Mock(returncode=0,stdout=json.dumps({'result':'Agent paste de knop aan.'}))
            with patch('subprocess.run',return_value=result) as run:
                output=service.summarize(SNAP)
                self.assertEqual(output['sourceMessageIds'],['one'])
                args=run.call_args.args[0];self.assertIn('--no-session-persistence',args)
                self.assertEqual(args[args.index('--tools')+1],'')
                self.assertFalse(run.call_args.kwargs['shell'])
                self.assertNotIn('not forwarded',run.call_args.kwargs['input'])
    def test_byok_success_no_storage_and_redacted_failure(self):
        service=NarrationService({'STUDIO_NARRATION_MODE':'byok','STUDIO_NARRATION_PROVIDER':'openai',
                                  'STUDIO_NARRATION_MODEL':'chosen-model','STUDIO_NARRATION_API_KEY':'test-only'})
        response=Mock();response.read.return_value=json.dumps({'output':[{'type':'message','content':[{'type':'output_text','text':'Korte presentatie.'}]}]}).encode()
        cm=Mock();cm.__enter__=Mock(return_value=response);cm.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=cm
        with patch('urllib.request.build_opener',return_value=opener):
            self.assertEqual(service.summarize(SNAP)['label'],'AI studio update')
            payload=json.loads(opener.open.call_args.args[0].data);self.assertFalse(payload['store'])
            opener.open.side_effect=RuntimeError('test-only secret response')
            with self.assertRaises(NarrationError) as error:service.summarize(SNAP)
            self.assertNotIn('test-only',str(error.exception))
    def test_anthropic_request_and_response_contract(self):
        service=NarrationService({'STUDIO_NARRATION_MODE':'byok','STUDIO_NARRATION_PROVIDER':'anthropic',
                                  'STUDIO_NARRATION_MODEL':'chosen-model','STUDIO_NARRATION_API_KEY':'test-only'})
        response=Mock()
        response.read.return_value=json.dumps({'content':[{'type':'text','text':'An attributed update.'}]}).encode()
        cm=Mock();cm.__enter__=Mock(return_value=response);cm.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=cm
        with patch('urllib.request.build_opener',return_value=opener):
            result=service.summarize(SNAP)
        self.assertEqual(result['text'],'An attributed update.')
        self.assertEqual(result['sourceMessageIds'],['one'])
        request=opener.open.call_args.args[0]
        headers={name.lower():value for name,value in request.header_items()}
        self.assertEqual(request.full_url,'https://api.anthropic.com/v1/messages')
        self.assertEqual(headers['x-api-key'],'test-only')
        self.assertNotIn('authorization',headers)
        body=json.loads(request.data)
        self.assertEqual(body['model'],'chosen-model')
        self.assertEqual(body['max_tokens'],600)
        self.assertEqual(json.loads(body['messages'][0]['content']),
                         [{'messageId':'one','speaker':'Test agent','text':'De knop is aangepast.'}])

    def test_codex_cli_consumes_completed_messages_and_rejects_failed_exit(self):
        service=NarrationService({'STUDIO_NARRATION_MODE':'cli','STUDIO_NARRATION_PROVIDER':'codex',
                                  'STUDIO_NARRATION_CLI_APPROVED':'1'})
        stdout='\n'.join(json.dumps(event) for event in [
            {'type':'thread.started'}, {'type':'turn.started'},
            {'type':'item.completed','item':{'type':'agent_message','text':'A short update.'}},
            {'type':'turn.completed','usage':{}}])
        with patch('shutil.which',return_value='/fake/codex'):
            with patch('subprocess.run',return_value=Mock(returncode=0,stdout=stdout)) as run:
                self.assertEqual(service.summarize(SNAP)['text'],'A short update.')
                command=run.call_args.args[0]
                for flag in ('--ephemeral','--ignore-user-config','--json'):
                    self.assertIn(flag,command)
            with patch('subprocess.run',return_value=Mock(returncode=1,stdout=stdout)):
                with self.assertRaises(NarrationError):service.summarize(SNAP)

    def test_no_empty_or_concurrent_calls(self):
        service=NarrationService({'STUDIO_NARRATION_MODE':'byok','STUDIO_NARRATION_PROVIDER':'anthropic','STUDIO_NARRATION_MODEL':'chosen','STUDIO_NARRATION_API_KEY':'test'})
        with self.assertRaises(NarrationError):service.summarize({'messages':[]})
        service._lock.acquire()
        try:
            with self.assertRaises(NarrationError):service.summarize(SNAP)
        finally:service._lock.release()
if __name__=='__main__':unittest.main()
