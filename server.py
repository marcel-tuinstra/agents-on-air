#!/usr/bin/env python3
"""Local chat viewer with opt-in provider summaries."""
import re
import argparse
import json
import os
import secrets
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlsplit
from providers.base import Registry, ProviderError
from providers.codex import CodexProvider
from providers.claude import ClaudeCodeProvider
from narration import NarrationService, NarrationError
from live_feed import LiveFeed

STATIC = Path(__file__).parent / 'static'

class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    connection_limit = 64
    def __init__(self, address, registry):
        self.connections = threading.BoundedSemaphore(self.connection_limit)
        self.registry = registry
        self.narration = NarrationService()
        self.token = secrets.token_urlsafe(32)
        self.feed = LiveFeed()
        super().__init__(address, Handler)

    def server_bind(self):
        # This loopback viewer does not need HTTPServer's reverse DNS lookup.
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]

    def process_request(self, request, client_address):
        # Each connection holds a thread; refuse extras instead of growing without bound.
        if not self.connections.acquire(blocking=False):
            return self.shutdown_request(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def catalog(self):
        return self.feed.read('catalog', self.registry.catalog)

    def snapshot(self, key):
        return self.feed.read(('chat', key), lambda: self.registry.snapshot(key))

    def server_close(self):
        self.feed.close()
        super().server_close()

class Handler(BaseHTTPRequestHandler):
    # Bounds stalled reads and writes; event streams write a heartbeat every two seconds.
    timeout = 20
    def log_message(self, *args):
        pass  # Never log chat identifiers or content.
    def origin_allowed(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        origin = self.headers.get('Origin')
        return (self.headers.get('Host') in hosts and
                (not origin or origin in {f'http://{h}' for h in hosts}) and
                self.headers.get('Sec-Fetch-Site', '') in ('', 'same-origin', 'none'))
    def authorized(self):
        try:
            jar = cookies.SimpleCookie(self.headers.get('Cookie', ''))
            return secrets.compare_digest(jar['studio_session'].value.encode(), self.server.token.encode())
        except (KeyError, cookies.CookieError, UnicodeError):
            return False
    def respond(self, status, body, kind='application/json; charset=utf-8', bootstrap=False, language=None):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if bootstrap:
            self.send_header('Set-Cookie', f'studio_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/')
        if language:
            self.send_header('Content-Language',language)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if not self.origin_allowed():
            return self.respond(403, {'error': 'Only local access from this app is allowed.'})
        route = urlsplit(self.path)
        if route.path == '/voice-lab':
            return self.respond(200, (STATIC/'voice-lab/index.html').read_bytes(), 'text/html; charset=utf-8', True)
        if route.path == '/':
            return self.respond(200, (STATIC/'index.html').read_bytes(), 'text/html; charset=utf-8', True)
        if not self.authorized():
            return self.respond(401, {'error': 'Reopen the studio to connect.'})
        if route.path == '/api/narration/config':
            return self.respond(200, self.server.narration.config())
        if route.path == '/api/catalog':
            try:
                return self.respond(200, self.server.catalog())
            except ProviderError as error:
                return self.respond(503, {'error': str(error)})
        if route.path == '/api/snapshot':
            key = parse_qs(route.query).get('chat', [''])[0]
            try:
                result = self.server.snapshot(key)
                return self.respond(200, result)
            except ProviderError as e:
                return self.respond(404, {'error': str(e)})
        if route.path.startswith('/api/artifacts/'):
            artifact_id = route.path.removeprefix('/api/artifacts/')
            try:
                data, mime = self.server.registry.artifact(artifact_id)
                return self.respond(200, data, mime)
            except ProviderError as e:
                return self.respond(404, {'error': str(e)})
        if route.path == '/api/events':
            return self.events(parse_qs(route.query).get('chat', [''])[0])
        assets = {'/fonts/Silkscreen-Regular.ttf': ('fonts/Silkscreen-Regular.ttf', 'font/ttf'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/settings.js': ('settings.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'),
                  '/marked.js': ('marked.js', 'text/javascript; charset=utf-8'), '/purify.js': ('purify.js', 'text/javascript; charset=utf-8'),
                  '/markdown.js': ('markdown.js', 'text/javascript; charset=utf-8'),
                  '/speech.js': ('speech.js', 'text/javascript; charset=utf-8'),
                  '/voice-profiles.js': ('voice-profiles.js', 'text/javascript; charset=utf-8'),
                  '/body.js': ('body.js', 'text/javascript; charset=utf-8'),
                  '/stage-model.js': ('stage-model.js', 'text/javascript; charset=utf-8'),
                  '/openai.svg': ('openai.svg', 'image/svg+xml'), '/anthropic.svg': ('anthropic.svg', 'image/svg+xml')}
        for font in ('Lora', 'Nunito', 'PixelifySans'):
            assets['/fonts/'+font+'.ttf'] = ('fonts/'+font+'.ttf', 'font/ttf')
        for module in ('rig', 'controllers', 'stream', 'work-view', 'captions'):
            assets['/'+module+'.js'] = (module+'.js', 'text/javascript; charset=utf-8')
        for name, kind in {'lab.js':'text/javascript', 'rig.js':'text/javascript', 'lab.css':'text/css'}.items():
            assets['/voice-lab/'+name] = ('voice-lab/'+name, kind)
        for name,kind in {'themes.js':'text/javascript; charset=utf-8','themes.css':'text/css; charset=utf-8'}.items():
            assets['/'+name]=(name,kind)
        theme_assets=json.loads((STATIC/'themes.json').read_text())['assets']
        for asset in theme_assets:
            if re.fullmatch(r'/themes/[a-z][a-z0-9-]{0,39}/[A-Za-z0-9_-]+\.(webp|png|ttf|woff2)',asset):
                kind={'.webp':'image/webp','.png':'image/png','.ttf':'font/ttf','.woff2':'font/woff2'}[Path(asset).suffix]
                assets[asset]=(asset.lstrip('/'),kind)
        if route.path in assets:
            name, kind = assets[route.path]
            return self.respond(200, (STATIC/name).read_bytes(), kind)
        return self.respond(404, {'error': 'Not found.'})
    def events(self, key):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        last_catalog, last_snapshot = None, None
        def emit(event, payload):
            self.wfile.write(('event: '+event+'\ndata: '+json.dumps(payload, ensure_ascii=False)+'\n\n').encode())
            self.wfile.flush()
        try:
            while not self.server.feed.closed:
                generation = self.server.feed.generation
                catalog = self.server.catalog()
                snap, error = None, None
                if key:
                    try:
                        snap = self.server.snapshot(key)
                    except ProviderError as e:
                        error = str(e)
                encoded = json.dumps(catalog, sort_keys=True)
                if encoded != last_catalog:
                    emit('catalog', catalog)
                    last_catalog = encoded
                if error:
                    emit('source-error', {'error': error})
                elif snap and snap['revision'] != last_snapshot:
                    emit('snapshot', snap)
                    last_snapshot = snap['revision']
                selected_provider = key.partition(':')[0]
                relevant_sources = [p for p in catalog['providers'] if not key or p['id'] == selected_provider]
                healthy = not error and bool(relevant_sources) and all(p['connected'] for p in relevant_sources)
                emit('heartbeat', {'at': time.time(), 'sourceHealthy': healthy})
                self.server.feed.wait(generation)
        except ProviderError as error:
            if not self.server.feed.closed:
                emit('source-error', {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ('/api/narration', '/api/narration/config'):
            return self.respond(405, {'error': 'This studio is read-only.'})
        if not self.origin_allowed():
            return self.respond(403, {'error':'Only local access is allowed.'})
        if not self.authorized():
            return self.respond(401, {'error':'Reopen the studio to connect.'})
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            return self.respond(415, {'error':'JSON required.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= (8192 if route == '/api/narration/config' else 4096):
                return self.respond(413, {'error':'Request too large.'})
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):
                raise ValueError()
            if route == '/api/narration/config':
                try:
                    return self.respond(200, self.server.narration.configure(payload))
                except ValueError as error:
                    return self.respond(400, {'error': str(error)})
            if set(payload) != {'chatId'} or not isinstance(payload['chatId'], str) or len(payload['chatId']) > 256:
                raise ValueError()
            snapshot = self.server.registry.snapshot(payload['chatId'])
            result = self.server.narration.summarize(snapshot)
            self.respond(200,result)
        except (ValueError,UnicodeError):
            self.respond(400,{'error':'Invalid request.'})
        except ProviderError as e:
            self.respond(404,{'error':str(e)})
        except NarrationError:
            self.respond(503,{'error':'Studio updates are currently unavailable.'})
        except (BrokenPipeError,ConnectionResetError):
            pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Agents on Air · local viewer')
    parser.add_argument('--open-browser', action='store_true', help='Open the studio in your default browser')
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home()/'.claude')))
    parser.add_argument('--port', type=int, default=8878)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')))
    args = parser.parse_args()
    server = StudioServer(('127.0.0.1', args.port), Registry([CodexProvider(args.codex_home), ClaudeCodeProvider(args.claude_home)]))
    print(f'Agents on Air: http://127.0.0.1:{server.server_port}', flush=True)
    print('Local Codex + Claude Code viewer · Ctrl+C to stop', flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
