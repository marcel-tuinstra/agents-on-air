import json
import unittest
from test_viewer import record, msg
from providers.codex import Rollout

class PresentationTests(unittest.TestCase):
    def read(self, text):
        reader=Rollout(None);reader.consume(msg('reply',text,role='UserMessage'))
        return reader.messages[0]['text']

    def test_question_reply_keeps_human_content_without_transport_metadata(self):
        payload=[{'questionItemId':'private-call-id','question':'Kun je de telefoon aansluiten?','answer':'Aangesloten en ontgrendeld.'}]
        result=self.read('<send_user_message_question_reply>\n'+json.dumps(payload)+'\n</send_user_message_question_reply>')
        self.assertIn('Kun je de telefoon aansluiten?',result)
        self.assertIn('Aangesloten en ontgrendeld',result)
        self.assertNotIn('questionItemId',result)
        self.assertNotIn('send_user_message_question_reply',result)

    def test_multiple_answers_and_malformed_payload(self):
        payload=[{'question':'Eerste?','answer':'Ja'},{'question':'Tweede?','answer':'Nee'}]
        result=self.read('<send_user_message_question_reply>'+json.dumps(payload)+'</send_user_message_question_reply>')
        self.assertIn('Eerste?',result);self.assertIn('Tweede?',result)
        self.assertEqual(self.read('<send_user_message_question_reply>{broken}</send_user_message_question_reply>'),'Reply received; its contents could not be read.')

    def test_code_examples_and_normal_messages_unchanged(self):
        for text in ['Gewone **Markdown** blijft staan.','```xml\n<send_user_message_question_reply>[]</send_user_message_question_reply>\n```']:
            self.assertEqual(self.read(text),text)
