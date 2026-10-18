"""Bounded, explicit local artifact references for the loopback viewer."""
import hashlib
import heapq
import hmac
import base64
import binascii
import re
import secrets
import tempfile
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .base import ProviderError

MAX_IMAGE = 8 * 1024 * 1024
MAX_DIFF = 64 * 1024
IMAGE_RE = re.compile(r'!\[([^\]]{0,120})\]\(([^)\n]{1,1024})\)')
SENSITIVE = {'.env', '.ssh', '.aws', 'credentials', 'secrets', 'id_rsa', 'id_ed25519', 'private'}
# The viewer is meant to be on screen; prefer hiding a harmless diff over showing a key.
SENSITIVE_NAME = re.compile(r'credential|secret|passw(or)?d|private[-_]?key|service[-_]?account|api[-_]?key'
                            r'|id_(rsa|dsa|ecdsa|ed25519)|kubeconfig|htpasswd|keystore|\.env$'
                            r'|\.(pem|key|p12|pfx|jks|ppk|asc|gpg|kdbx|keychain)$')
SECRET_TEXT = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}'
                         r'|\bgithub_pat_[A-Za-z0-9_]{22,}|\bsk-[A-Za-z0-9_-]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}'
                         r'|\bAIza[0-9A-Za-z_-]{35}|\b[rs]k_live_[0-9A-Za-z]{16,}|\bglpat-[0-9A-Za-z_-]{20,}'
                         r'|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')


class RecentArtifacts:
    """Select across the whole cast before reading image files or building diffs."""

    def __init__(self, limit):
        self.limit = limit
        self.pending = []
        self.sequence = 0

    def add(self, event_id, at, build, *args):
        self.sequence += 1
        candidate = (at, self.sequence, event_id, build, args)
        heapq.heappush(self.pending, candidate)
        if len(self.pending) > self.limit:
            heapq.heappop(self.pending)

    def collect(self):
        artifacts, links = [], {}
        for at, sequence, event_id, build, args in sorted(self.pending, reverse=True):
            artifact = build(*args)
            if artifact:
                artifacts.append(artifact)
                links.setdefault(event_id, []).append(artifact['id'])
        return artifacts, links


def image_references(text):
    for label, raw in IMAGE_RE.findall(text):
        raw = raw.strip().strip('<>')
        if raw:
            yield (label.strip() or 'Image', raw)


def mime_for(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


class ArtifactStore:
    def __init__(self, provider):
        self.provider = provider
        self.secret = secrets.token_bytes(32)
        self.entries = OrderedDict()
        self.attachment_roots = (Path(tempfile.gettempdir()).resolve(),)

    def image(self, raw, cwd, identity, agent_id, at, label='Image', message_id=None, attachment=False):
        if not isinstance(raw, str) or not isinstance(cwd, str) or not cwd:
            return None
        raw = raw.strip().strip('<>')
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return None
        path_text = unquote(parsed.path)
        if '\x00' in path_text or any(x in SENSITIVE or x.startswith('.') for x in Path(path_text).parts):
            return None
        root = Path(cwd).expanduser().resolve()
        if not root.is_dir() or root == Path('/'):
            return None
        candidate = Path(path_text).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_symlink():
            return None
        path = candidate.resolve()
        roots = (root, *self.attachment_roots) if attachment else (root,)
        if not any(path.is_relative_to(r) for r in roots):
            return None
        try:
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE:
                return None
            with path.open('rb') as f:
                data = f.read(MAX_IMAGE + 1)
            kind = mime_for(data)
            if not kind:
                return None
            if len(data) > MAX_IMAGE:
                return None
        except OSError:
            return None
        raw_id = self.provider + '\0' + identity + '\0' + str(path)
        token = hmac.new(self.secret, raw_id.encode(), hashlib.sha256).hexdigest()[:32]
        self.entries[token] = ('file', path, roots, kind, hashlib.sha256(data).digest())
        self.entries.move_to_end(token)
        while len(self.entries) > 1000:
            self.entries.popitem(last=False)
        result = {'id': token, 'agentId': agent_id, 'at': at, 'kind': 'image',
                  'label': label[:120], 'url': '/api/artifacts/' + token,
                  'provenance': self.provider + ' transcript reference'}
        explicit_role = {'before': 'before', 'voor': 'before',
                         'after': 'after', 'na': 'after'}.get(label.strip().casefold())
        if explicit_role:
            result['role'] = explicit_role
        if message_id:
            result['messageId'] = message_id
        return result

    def inline_image(self, encoded, declared_mime, identity, agent_id, at, message_id):
        if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE * 4 // 3 + 8):
            return None
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        kind = mime_for(data)
        if not kind or kind != declared_mime or not 0 < len(data) <= MAX_IMAGE:
            return None
        token = hmac.new(self.secret, (self.provider + '\0' + identity + '\0' + hashlib.sha256(data).hexdigest()).encode(),
                         hashlib.sha256).hexdigest()[:32]
        used = sum(len(e[1]) for e in self.entries.values() if e[0] == 'inline')
        while self.entries and used + len(data) > 32 * 1024 * 1024:
            _, old = self.entries.popitem(last=False)
            if old[0] == 'inline':
                used -= len(old[1])
        self.entries[token] = ('inline', data, kind)
        self.entries.move_to_end(token)
        while len(self.entries) > 1000:
            self.entries.popitem(last=False)
        return {'id': token, 'agentId': agent_id, 'at': at, 'kind': 'image', 'label': 'Image',
                'messageId': message_id, 'url': '/api/artifacts/' + token,
                'provenance': self.provider + ' transcript attachment'}

    def resolve(self, token):
        entry = self.entries.get(token)
        if not entry:
            raise ProviderError('This artifact is unavailable.')
        if entry[0] == 'inline':
            return entry[1], entry[2]
        _, path, roots, expected, expected_digest = entry
        try:
            if path.is_symlink() or not any(path.resolve().is_relative_to(r) for r in roots):
                raise ProviderError('This artifact is unavailable.')
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE:
                raise ProviderError('This artifact is unavailable.')
            with path.open('rb') as f:
                data = f.read(MAX_IMAGE + 1)
            if len(data) > MAX_IMAGE or mime_for(data) != expected or hashlib.sha256(data).digest() != expected_digest:
                raise ProviderError('This artifact is unavailable.')
            return data, expected
        except OSError:
            raise ProviderError('This artifact is unavailable.') from None


def sensitive_diff_path(path):
    parts = str(path).strip().replace('\\', '/').split('/')
    return any(part.lower() in SENSITIVE or part.startswith('.') or SENSITIVE_NAME.search(part.lower())
               for part in parts if part not in ('', '.', '..'))


def diff_artifact(text, identity, agent_id, at, label, provenance):
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_DIFF:
        return None
    # Explicit tool records can still contain credential-file patches. Keep those
    # out of the viewer even when the transcript stores the raw request.
    paths = [label, label.rsplit(' ', 1)[-1]]
    for line in text.splitlines():
        if line.startswith(('*** Update File: ', '*** Add File: ', '*** Delete File: ', '+++ ', '--- ')):
            paths.append(line.split(': ', 1)[-1] if ': ' in line else line[4:])
    if any(sensitive_diff_path(path) for path in paths) or SECRET_TEXT.search(text):
        return None
    token = hashlib.sha256((agent_id + '\0' + identity + '\0' + text).encode()).hexdigest()[:32]
    return {'id': token, 'agentId': agent_id, 'at': at, 'kind': 'diff', 'label': label[:120],
            'text': text, 'provenance': provenance}
