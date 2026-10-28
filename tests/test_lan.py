import http.client
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from urllib.parse import urlencode
from test_viewer import StoreFixture, msg
from lan_access import LanAccess, MAX_FAILURES, host_name, is_ip_literal
from providers.base import Registry
from providers.codex import CodexProvider
from server import Handler, StudioServer

CODE = '482913'


class HostTests(unittest.TestCase):
    def test_host_names_need_the_port_and_ignore_case(self):
        self.assertEqual(host_name('Studio.LOCAL:8878', 8878), 'studio.local')
        self.assertEqual(host_name('[::1]:8878', 8878), '[::1]')
        self.assertIsNone(host_name('studio.local:9000', 8878))
        self.assertIsNone(host_name('studio.local', 8878))
        self.assertIsNone(host_name(None, 8878))

    def test_lan_allows_this_computer_and_address_literals_only(self):
        lan = LanAccess(names={'Studio.local'}, code=CODE)
        for name in ('studio.local', 'localhost', '127.0.0.1', '192.168.1.20', '[fe80::1]'):
            self.assertTrue(lan.host_allowed(name), name)
        for name in ('evil.test', 'studio.local.evil.test', '192.168.1.20.nip.io'):
            self.assertFalse(lan.host_allowed(name), name)
        self.assertTrue(is_ip_literal('10.0.0.5'))
        self.assertFalse(is_ip_literal('10.0.0.5.example'))

    def test_wrong_codes_lock_out_the_right_one(self):
        lan = LanAccess(names=set(), code=CODE)
        self.assertTrue(lan.check(CODE))
        with redirect_stdout(StringIO()) as output:
            for _ in range(MAX_FAILURES):
                self.assertFalse(lan.check('000000'))
        self.assertIn('locked out', output.getvalue())
        self.assertTrue(lan.locked())
        self.assertFalse(lan.check(CODE))

    def test_random_codes_have_six_digits(self):
        for _ in range(20):
            code = LanAccess(names=set()).code
            self.assertRegex(code, r'^[0-9]{6}$')


class LanHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.f = StoreFixture(self.tmp.name); self.addCleanup(self.f.db.close)
        self.f.add('main', events=[msg('one', 'Public user-facing text')])
        self.lan = LanAccess(names={'studio.local'}, code=CODE)
        self.server = StudioServer(('127.0.0.1', 0), Registry([CodexProvider(self.f.home)]), self.lan)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        self.host = f'studio.local:{self.port}'

    def request(self, method, path, body=None, headers=None, host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        self.addCleanup(connection.close)
        sent = {'Host': host or self.host, **(headers or {})}
        if body is not None:
            sent.setdefault('Content-Type', 'application/x-www-form-urlencoded')
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        return response, response.read().decode('utf-8', 'replace')

    def unlock(self, code, next_path='/'):
        digits = [('d', digit) for digit in code]
        return self.request('POST', '/unlock', urlencode([('next', next_path), *digits]),
                            {'Origin': 'http://' + self.host})

    def test_this_computer_skips_the_code(self):
        response, page = self.request('GET', '/', host=f'127.0.0.1:{self.port}')
        self.assertEqual(response.status, 200)
        self.assertIn('Agents on Air · Live', page)
        self.assertIn('studio_session=', response.getheader('Set-Cookie'))

    def test_other_devices_enter_the_code_before_the_studio(self):
        with patch.object(Handler, 'remote', return_value=True):
            response, page = self.request('GET', '/')
            self.assertEqual(response.status, 200)
            self.assertIn('action="/unlock"', page)
            self.assertEqual(page.count('class="digit"'), 6)
            self.assertNotIn('{{', page)
            self.assertIsNone(response.getheader('Set-Cookie'))
            self.assertIn("form-action 'self'", response.getheader('Content-Security-Policy'))
            self.assertEqual(response.getheader('Referrer-Policy'), 'same-origin')
            for path in ('/unlock/unlock.js', '/unlock/unlock.css', '/fonts/Lora.ttf', '/favicon.svg'):
                self.assertEqual(self.request('GET', path)[0].status, 200, path)
            self.assertEqual(self.request('GET', '/api/catalog')[0].status, 401)

            response, page = self.unlock('111111')
            self.assertEqual(response.status, 403)
            self.assertIn('not right', page)
            self.assertIn('class="wrong"', page)

            response, _ = self.unlock(CODE, '/voice-lab')
            self.assertEqual(response.status, 303)
            self.assertEqual(response.getheader('Location'), '/voice-lab')
            cookie = response.getheader('Set-Cookie').split(';')[0]
            response, page = self.request('GET', '/', headers={'Cookie': cookie})
            self.assertIn('Agents on Air · Live', page)
            self.assertEqual(self.request('GET', '/api/catalog', headers={'Cookie': cookie})[0].status, 200)

    def test_unlock_rejects_foreign_pages_hosts_and_origins(self):
        with patch.object(Handler, 'remote', return_value=True):
            response, _ = self.unlock(CODE, '//evil.test/')
            self.assertEqual(response.getheader('Location'), '/')
            self.assertEqual(self.request('GET', '/', host=f'evil.test:{self.port}')[0].status, 403)
            response, _ = self.request('POST', '/unlock', urlencode({'code': CODE}),
                                       {'Origin': 'http://evil.test'})
            self.assertEqual(response.status, 403)
            response, _ = self.request('POST', '/unlock', urlencode({'code': CODE}), {'Origin': 'null'})
            self.assertEqual(response.status, 403)
            self.assertEqual(self.request('GET', '/', host=f'STUDIO.local:{self.port}')[0].status, 200)
            self.assertEqual(self.request('GET', '/', host=f'192.168.1.20:{self.port}')[0].status, 200)

    def test_lockout_disables_the_form(self):
        with patch.object(Handler, 'remote', return_value=True), redirect_stdout(StringIO()):
            for _ in range(MAX_FAILURES):
                self.unlock('000000')
            response, page = self.unlock(CODE)
            self.assertEqual(response.status, 403)
            self.assertIn('Too many wrong codes', page)
            self.assertIn('disabled', page)

    def test_settings_stay_on_this_computer(self):
        response, _ = self.request('GET', '/', host=f'127.0.0.1:{self.port}')
        cookie = response.getheader('Set-Cookie').split(';')[0]
        with patch.object(Handler, 'remote', return_value=True):
            response, _ = self.request('POST', '/api/narration/config', '{"mode": "off"}',
                                       {'Cookie': cookie, 'Content-Type': 'application/json'})
            self.assertEqual(response.status, 403)
        response, _ = self.request('POST', '/api/narration/config', '{"mode": "off"}',
                                   {'Cookie': cookie, 'Content-Type': 'application/json'},
                                   host=f'127.0.0.1:{self.port}')
        self.assertEqual(response.status, 200)

    def test_without_lan_other_hosts_and_unlock_stay_closed(self):
        server = StudioServer(('127.0.0.1', 0), Registry([]))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.port = server.server_port
        self.assertEqual(self.request('GET', '/', host=f'192.168.1.20:{self.port}')[0].status, 403)
        self.assertEqual(self.request('GET', '/', host=f'studio.local:{self.port}')[0].status, 403)
        response, _ = self.request('POST', '/unlock', urlencode({'code': CODE}), host=f'127.0.0.1:{self.port}')
        self.assertEqual(response.status, 405)


if __name__ == '__main__':
    unittest.main()
