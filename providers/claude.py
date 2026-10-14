"""Read-only Claude Code project transcripts; no hooks, credentials or model calls."""
import json
import time
import difflib
from collections import OrderedDict
from pathlib import Path
from .base import Provider, ProviderError
from .schema import Snapshot, finalize_snapshot
from .presentation import clean_user_text
from .codex import Rollout, timestamp, text_content, MESSAGE_LIMIT
from .artifacts import ArtifactStore, RecentArtifacts, image_references, diff_artifact, sensitive_diff_path


def visible_user(record):
    if record.get('isMeta') or record.get('isCompactSummary'):
        return ''
    text = text_content(record.get('message', {}).get('content'))
    # Claude's command/harness records use the user role too.
    if text.lstrip().startswith(('<local-command', '<command-name>', '<system-reminder>', '<task-notification>')):
        return ''
    return clean_user_text(text)


class ClaudeRollout(Rollout):
    def __init__(self, path):
        super().__init__(path)
        self.cwd = ''
        self.title = ''
        self.custom_title = ''
        self.session_id = path.stem
        self.sidechain = False
        self.inline_refs = {}
        # Metadata can sit outside the bounded transcript tail.
        try:
            with path.open('rb') as f:
                for line in f.read(512 * 1024).splitlines():
                    try:
                        r = json.loads(line)
                        if isinstance(r, dict):
                            self.metadata(r)
                    except (ValueError, TypeError):
                        continue
        except OSError:
            pass

    def metadata(self, r):
        self.cwd = r.get('cwd') or self.cwd
        self.session_id = r.get('sessionId') or self.session_id
        self.sidechain = r.get('isSidechain', self.sidechain)
        if r.get('type') == 'custom-title' and isinstance(r.get('customTitle'), str):
            self.custom_title = r['customTitle'][:180]
        if r.get('type') == 'user' and isinstance(r.get('message'), dict) and not self.title:
            self.title = ' '.join(visible_user(r).split())[:140]

    def consume(self, r):
        if not isinstance(r, dict):
            return
        self.metadata(r)
        kind = r.get('type')
        if kind not in ('user', 'assistant', 'system', 'progress'):
            return
        at = timestamp(r.get('timestamp'))
        self.last_event = max(self.last_event, at)
        if kind == 'system':
            if r.get('subtype') == 'turn_duration':
                self.state = 'idle'
                self.activity(str(r.get('uuid') or r.get('timestamp')) + ':complete', at,
                              'lifecycle', 'Finished working')
            return
        if kind == 'progress':
            return
        m = r.get('message', {})
        if not isinstance(m, dict):
            return
        role = kind
        blocks = m.get('content') if isinstance(m.get('content'), list) else []
        inline = [(b['source'].get('data'), b['source'].get('media_type'))
                  for b in blocks if isinstance(b, dict) and b.get('type') == 'image'
                  and isinstance(b.get('source'), dict) and b['source'].get('type') == 'base64']
        if kind == 'assistant':
            self.model = m.get('model') or self.model
            text = text_content(m.get('content'))
            for block in m.get('content', []) if isinstance(m.get('content'), list) else []:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    tool_id = str(block.get('id') or r.get('uuid')) + ':tool'
                    self.activity(tool_id, at,
                                  'work', 'Requested a tool')
                    tool_input = block.get('input')
                    if isinstance(tool_input, dict):
                        name = block.get('name')
                        source_path = str(tool_input.get('file_path') or tool_input.get('path') or 'file')
                        if sensitive_diff_path(source_path):
                            continue
                        filename = source_path.replace('\\', '/').rsplit('/', 1)[-1]
                        old, new = None, None
                        if name == 'Edit':
                            old, new = tool_input.get('old_string'), tool_input.get('new_string')
                        elif name == 'Write':
                            old, new = '', tool_input.get('content')
                        if isinstance(old, str) and isinstance(new, str) and len(old) + len(new) <= 64000:
                            diff = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                               fromfile='before/' + filename, tofile='after/' + filename))
                            self.diff_refs[tool_id] = [(filename, diff)]
                        elif name in ('apply_patch', 'ApplyPatch') and isinstance(tool_input.get('patch'), str):
                            self.diff_refs[tool_id] = [(filename, tool_input['patch'])]
            stop = m.get('stop_reason')
            self.state = 'error' if r.get('isApiErrorMessage') else ('idle' if stop in ('end_turn', 'stop_sequence') else 'working')
        else:
            text = visible_user(r)
            if text or inline:
                self.turn = r.get('uuid')
                self.turn_started = at
                self.state = 'working'
                self.activity(str(r.get('uuid')) + ':start', at, 'lifecycle', 'Started working')
        if not text.strip() and inline:
            text = '[Image]'
        if not text.strip():
            return
        identity = r.get('uuid')
        if not isinstance(identity, str):
            return
        if identity in self.ids:
            # Some writers update the same message rather than assigning a new UUID.
            for old in self.messages:
                if old['nativeId'] == identity:
                    changed = old['text'] != text or self.inline_refs.get(identity) != inline
                    if changed:
                        old.update(text=text, at=at)
                        self.inline_refs[identity] = inline
                        event_id = identity + ':message'
                        event = next((e for e in self.events if e['id'] == event_id), None)
                        if event:
                            event['at'] = max(event['at'], at)
                            event['label'] = 'Updated a message'
                            self.last_activity = max(self.last_activity, at)
                        else:
                            self.activity(event_id, at, 'message', 'Updated a message')
            return
        if len(self.messages) == MESSAGE_LIMIT:
            self.truncated = True
            self.ids.discard(self.messages[0]['nativeId'])
            self.inline_refs.pop(self.messages[0]['nativeId'], None)
        self.ids.add(identity)
        self.messages.append({'nativeId': identity, 'role': role, 'text': text,
                              'at': at, 'turnId': self.turn, 'phase': 'final' if self.state == 'idle' else 'commentary'})
        self.inline_refs[identity] = inline
        self.activity(identity + ':message', at, 'message', 'Sent a message' if role == 'assistant' else 'Received a message')


class ClaudeCodeProvider(Provider):
    id, label = 'claude', 'Anthropic · Claude Code'

    def __init__(self, home):
        self.home = Path(home).expanduser().resolve()
        self.cache = OrderedDict()
        self.paths = {}
        self._groups = []
        self.scanned_at = None
        self.artifact_store = ArtifactStore(self.id)

    def confined(self, path):
        path = path.resolve()
        if not path.is_relative_to(self.home / 'projects'):
            raise ProviderError('The Claude transcript is outside project storage.')
        return path

    def read(self, path):
        path = self.confined(path)
        try:
            reader = self.cache.get(path)
            if reader is None:
                reader = ClaudeRollout(path)
                self.cache[path] = reader
            self.cache.move_to_end(path)
            while len(self.cache) > 600:
                self.cache.popitem(last=False)
            return reader.refresh()
        except OSError:
            raise ProviderError('The Claude transcript is temporarily unreadable.') from None

    def scan(self):
        project_dir = self.home / 'projects'
        if not project_dir.is_dir():
            raise ProviderError('No local Claude Code project storage found.')
        if self.scanned_at is not None and time.monotonic() - self.scanned_at < 2:
            return
        try:
            paths = sorted(project_dir.glob('*/*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:500]
            self.paths = {p.parent.name + '/' + p.stem: p for p in paths if not p.name.startswith('agent-')}
            self.scanned_at = time.monotonic()
        except OSError:
            raise ProviderError('The Claude project list is temporarily unreadable.') from None

    def chat(self, key, path, reader):
        group = 'claude:project:' + path.parent.name
        folder = Path(reader.cwd).name if reader.cwd else path.parent.name
        return {'id': 'claude:' + key, 'provider': self.id, 'providerLabel': self.label,
                'title': reader.custom_title or reader.title or 'Claude-chat ' + path.stem[:8],
                'model': reader.model or 'Claude Code', 'updatedAt': path.stat().st_mtime,
                'lastActivityAt': reader.last_activity,
                'status': reader.status(), 'groupId': group, 'groupLabel': folder or 'Claude-project',
                'groupKind': 'project'}

    def list_chats(self):
        self.scan()
        chats, groups = [], {}
        for key, path in self.paths.items():
            try:
                reader = self.read(path)
                if reader.sidechain:
                    continue
                chat = self.chat(key, path, reader)
                children = (path.parent / path.stem / 'subagents').glob('agent-*.jsonl')
                for child in children:
                    try:
                        chat['lastActivityAt'] = max(chat['lastActivityAt'], self.read(child).last_activity)
                    except ProviderError:
                        continue
                chats.append(chat)
                groups.setdefault(chat['groupId'], {'id': chat['groupId'], 'label': chat['groupLabel'],
                    'provider': self.id, 'kind': 'project', 'order': len(groups), 'collapsed': False})
            except (ProviderError, OSError):
                continue
        self._groups = list(groups.values())
        return chats

    def groups(self):
        return self._groups

    def snapshot(self, native_id) -> Snapshot:
        self.scan()
        path = self.paths.get(native_id)
        if path is None:
            raise ProviderError('This Claude chat is unavailable.')
        main = self.read(path)
        if main.sidechain:
            raise ProviderError('This Claude chat is a subagent.')
        chat = self.chat(native_id, path, main)
        agents, messages, events, artifacts, warnings = [], [], [], [], []
        pending_artifacts = RecentArtifacts(MESSAGE_LIMIT)

        def add(reader, identity, name, is_main):
            agents.append({'id': identity, 'name': name, 'model': reader.model or 'Claude Code',
                           'role': 'Director' if is_main else 'Subagent', 'status': reader.status(),
                           'isMain': is_main, 'lastKnownStatus': reader.state, 'lastEventAt': reader.last_event})
            for m in reader.messages:
                if not is_main and (m['role'] != 'assistant' or m['at'] < main.turn_started):
                    continue
                messages.append({**m, 'id': identity + ':' + m['nativeId'], 'agentId': identity,
                                 'speaker': 'You' if m['role'] == 'user' else name})
            events.extend({**e, 'id': identity + ':' + e['id'], 'agentId': identity} for e in reader.events)
            for m in reader.messages:
                if not is_main and (m['role'] != 'assistant' or m['at'] < main.turn_started):
                    continue
                message_id = identity + ':' + m['nativeId']
                for label, raw in list(image_references(m['text']))[:20]:
                    pending_artifacts.add(message_id + ':message', m['at'],
                        self.artifact_store.image, raw, reader.cwd, message_id + ':' + raw,
                        identity, m['at'], label, message_id)
                for index, (encoded, mime) in enumerate(reader.inline_refs.get(m['nativeId'], [])[:10]):
                    pending_artifacts.add(message_id + ':message', m['at'],
                        self.artifact_store.inline_image, encoded, mime,
                        message_id + ':' + str(index), identity, m['at'], message_id)
            for e in reader.events:
                for label, diff in reader.diff_refs.get(e['id'], []):
                    pending_artifacts.add(identity + ':' + e['id'], e['at'],
                                             diff_artifact, diff, e['id'] + ':' + label, identity, e['at'],
                                             'Proposed change · ' + label,
                                             'Claude tool_use input; application unverified')

        add(main, chat['id'], 'Lead agent', True)
        if main.truncated and not main.turn_started:
            warnings.append('The start of this turn is outside the loaded transcript; subagent links are unknown.')
        children = sorted((path.parent / path.stem / 'subagents').glob('agent-*.jsonl'),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:100]
        for child in children:
            try:
                reader = self.read(child)
                if not main.turn_started:
                    events.extend({**e, 'id': chat['id'] + ':' + child.stem + ':' + e['id'],
                                   'agentId': chat['id'] + ':' + child.stem} for e in reader.events)
                    continue
                if reader.last_event < main.turn_started:
                    events.extend({**e, 'id': chat['id'] + ':' + child.stem + ':' + e['id'],
                                   'agentId': chat['id'] + ':' + child.stem} for e in reader.events)
                    continue
                name = 'Agent ' + child.stem.removeprefix('agent-')[:12]
                meta = self.confined(child.with_suffix('.meta.json'))
                if meta.is_file():
                    try:
                        data = json.loads(meta.read_text())
                        name = str(data.get('name') or data.get('agentType') or name)[:80]
                    except (ValueError, OSError, AttributeError):
                        pass
                add(reader, chat['id'] + ':' + child.stem, name, False)
            except ProviderError:
                warnings.append('A Claude subagent transcript is unavailable.')
        artifacts, event_artifacts = pending_artifacts.collect()
        return finalize_snapshot(
            chat=chat, agents=agents, messages=messages, events=events,
            artifacts=artifacts, links=event_artifacts, truncated=main.truncated,
            agent_limit=len(children) == 100, warnings=warnings,
            status_note='Local Claude Code updates · every 2 seconds')
