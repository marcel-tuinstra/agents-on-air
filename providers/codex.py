"""Codex local-store adapter. Never starts/resumes an agent or writes Codex data."""
import json
import sqlite3
import time
from collections import OrderedDict, deque
from datetime import datetime
from pathlib import Path
from .base import Provider, ProviderError
from .schema import Snapshot, finalize_snapshot
from .grouping import codex_groups
from .presentation import clean_user_text
from .artifacts import ArtifactStore, RecentArtifacts, image_references, diff_artifact, sensitive_diff_path

MAX_INITIAL = 2 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024
MESSAGE_LIMIT = 200


def timestamp(value):
    if isinstance(value, (float, int)):
        return float(value) / (1000 if value > 10**11 else 1)
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def text_content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ''
    return '\n'.join(v.get('text', '') for v in value if isinstance(v, dict)
                     and v.get('type') in ('text', 'Text', 'input_text', 'output_text')
                     and isinstance(v.get('text'), str))


class Rollout:
    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.inode = None
        self.messages = deque(maxlen=MESSAGE_LIMIT)
        self.ids = set()
        self.events = deque(maxlen=MESSAGE_LIMIT)
        self.event_ids = set()
        self.last_activity = 0
        self.cwd = ''
        self.image_refs = {}
        self.diff_refs = {}
        self.tool_names = {}
        self.state = 'unknown'
        self.turn = None
        self.root_turn = None
        self.turn_started = 0
        self.last_event = 0
        self.model = None
        self.truncated = False
        self.minimum_ordinal = 0
        self.skip_line = False
        self.checkpoint = b''

    def consume(self, record):
        if not isinstance(record, dict):
            return
        kind, p = record.get('type'), record.get('payload', {})
        if not isinstance(p, dict):
            return
        if kind == 'session_meta':
            self.minimum_ordinal = p.get('subagent_history_start_ordinal') or 0
            if isinstance(p.get('cwd'), str):
                self.cwd = p['cwd']
        if (record.get('ordinal') or 0) < self.minimum_ordinal:
            return
        at = timestamp(record.get('timestamp'))
        self.last_event = max(self.last_event, at)
        if kind == 'response_item':
            subtype = p.get('type')
            if subtype in ('function_call', 'custom_tool_call'):
                name = p.get('name')
                call_id = p.get('call_id') or p.get('id')
                if isinstance(call_id, str) and isinstance(name, str):
                    self.tool_names[call_id] = name
                    if len(self.tool_names) > 1000:
                        self.tool_names.clear()
                    if name not in ('wait', 'wait_agent', 'list_agents'):
                        event_id = call_id + ':call'
                        self.activity(event_id, at, 'work', 'Started a tool')
                        patch = p.get('input')
                        if name == 'apply_patch' and isinstance(patch, str) and len(patch) <= 64000 \
                                and patch.startswith('*** Begin Patch') and patch.rstrip().endswith('*** End Patch'):
                            self.diff_refs[event_id] = [('patch', patch)]
            elif subtype in ('function_call_output', 'custom_tool_call_output'):
                call_id = p.get('call_id')
                if isinstance(call_id, str) and call_id in self.tool_names \
                        and self.tool_names[call_id] not in ('wait', 'wait_agent', 'list_agents'):
                    self.activity(call_id + ':output', at, 'work', 'Tool finished')
            return
        if kind == 'turn_context':
            self.model = p.get('model') or self.model
            self.root_turn = p.get('root_turn_id') or self.root_turn
            if not self.turn:
                self.turn = p.get('turn_id')
        if kind == 'event_msg':
            event = p.get('type')
            if event == 'task_started':
                self.activity(str(p.get('turn_id') or record.get('ordinal')) + ':start', at, 'lifecycle', 'Started working')
                self.state, self.turn = 'working', p.get('turn_id')
                self.root_turn = p.get('root_turn_id') or self.turn
                self.turn_started = timestamp(p.get('started_at')) or at
            elif event in ('task_complete', 'turn_aborted', 'task_failed'):
                self.activity(str(p.get('turn_id') or record.get('ordinal')) + ':' + event, at, 'lifecycle',
                              {'task_complete': 'Finished working', 'turn_aborted': 'Work interrupted', 'task_failed': 'Work failed'}[event])
                if not self.turn or not p.get('turn_id') or p.get('turn_id') == self.turn:
                    self.turn = p.get('turn_id') or self.turn
                    self.root_turn = p.get('root_turn_id') or self.root_turn
                    self.state = {'task_complete': 'idle', 'turn_aborted': 'interrupted', 'task_failed': 'error'}[event]
            # Only explicit user-facing message items are admitted. Never reasoning,
            # tool arguments/results, system prompts, or arbitrary response_item records.
            if event == 'item_completed':
                item = p.get('item', {})
                if isinstance(item, dict) and item.get('type') == 'CommandExecution':
                    self.activity(str(item.get('id') or record.get('ordinal')) + ':work',
                                  at, 'work', 'Ran a command')
                if isinstance(item, dict) and item.get('type') in ('McpToolCall', 'FileChange', 'WebSearch'):
                    self.activity(str(item.get('id') or record.get('ordinal')) + ':work', at, 'work',
                                  ('Changed files' if item.get('status') in (None, 'completed') else 'Attempted file change')
                                  if item['type'] == 'FileChange' else 'Used a tool')
                    if item['type'] == 'FileChange' and item.get('status') in (None, 'completed') \
                            and isinstance(item.get('changes'), dict):
                        patches = []
                        for path, change in list(item['changes'].items())[:20]:
                            if sensitive_diff_path(path):
                                continue
                            if isinstance(change, dict) and isinstance(change.get('unified_diff'), str) \
                                    and len(change['unified_diff']) <= 64000:
                                patches.append((Path(str(path)).name, change['unified_diff']))
                        self.diff_refs[str(item.get('id') or record.get('ordinal')) + ':work'] = patches
                if not self.turn and p.get('turn_id'):
                    self.turn = p['turn_id']
                if not isinstance(item, dict) or item.get('type') not in ('UserMessage', 'AgentMessage'):
                    return
                if item.get('type') == 'AgentMessage' and item.get('phase') not in (None, 'final', 'final_answer', 'commentary'):
                    return
                text = text_content(item.get('content'))
                images = [(v.get('path'), True) for v in item.get('content', [])
                          if isinstance(v, dict) and v.get('type') == 'local_image' and isinstance(v.get('path'), str)] if isinstance(item.get('content'), list) else []
                if not text.strip() and not images:
                    return
                if not text.strip():
                    text = '[Image]'
                role = 'user' if item['type'] == 'UserMessage' else 'assistant'
                if role == 'user': text = clean_user_text(text)
                identity = item.get('id') or str(record.get('ordinal')) + ':' + role
                if identity in self.ids:
                    return
                if len(self.messages) == MESSAGE_LIMIT:
                    self.truncated = True
                    self.ids.discard(self.messages[0]['nativeId'])
                    self.image_refs.pop(self.messages[0]['nativeId'], None)
                self.ids.add(identity)
                self.messages.append({'nativeId': identity, 'role': role, 'text': text,
                                      'at': at, 'turnId': p.get('turn_id'), 'phase': item.get('phase')})
                self.image_refs[identity] = images
                self.activity(str(identity) + ':message', at, 'message', 'Sent a message' if role == 'assistant' else 'Received a message')

    def activity(self, identity, at, kind, label):
        if not at or identity in self.event_ids:
            return
        if len(self.events) == MESSAGE_LIMIT:
            self.event_ids.discard(self.events[0]['id'])
            self.diff_refs.pop(self.events[0]['id'], None)
        self.event_ids.add(identity)
        self.events.append({'id': identity, 'at': at, 'kind': kind, 'label': label, 'artifactIds': []})
        self.last_activity = max(self.last_activity, at)

    def refresh(self):
        stat = self.path.stat()
        rewritten = False
        if self.offset and self.checkpoint and stat.st_size >= self.offset:
            with self.path.open('rb') as check:
                check.seek(self.offset - len(self.checkpoint))
                rewritten = check.read(len(self.checkpoint)) != self.checkpoint
        if self.inode != stat.st_ino or stat.st_size < self.offset or rewritten:
            self.__init__(self.path)
            self.inode = stat.st_ino
            with self.path.open('rb') as f:
                first = f.readline(MAX_LINE)
                try:
                    meta = json.loads(first)
                    if meta.get('type') == 'session_meta':
                        self.consume(meta)
                except (ValueError, UnicodeError):
                    pass
            if stat.st_size > MAX_INITIAL:
                with self.path.open('rb') as f:
                    f.seek(stat.st_size - MAX_INITIAL)
                    f.readline(MAX_LINE)
                    self.offset = f.tell()
                self.truncated = True
        with self.path.open('rb') as f:
            f.seek(self.offset)
            # Bounded batches keep the viewer responsive even for huge tool outputs.
            budget = MAX_INITIAL
            while budget > 0:
                start = f.tell()
                line = f.readline(MAX_LINE)
                if not line:
                    break
                budget -= len(line)
                if not line.endswith(b'\n'):
                    if len(line) == MAX_LINE:
                        self.skip_line = True
                        self.offset = f.tell()
                        continue
                    break  # Incomplete JSON waits for the writer's next append.
                self.offset = f.tell()
                if self.skip_line:
                    self.skip_line = False
                    continue
                try:
                    self.consume(json.loads(line))
                except (ValueError, UnicodeError):
                    continue
        with self.path.open('rb') as check:
            check.seek(max(0, self.offset - 256))
            self.checkpoint = check.read(min(self.offset, 256))
        return self

    def status(self):
        # Disk logs cannot prove an old process is still alive.
        return 'unknown' if self.state == 'working' and time.time() - self.last_event > 300 else self.state


class CodexProvider(Provider):
    id, label = 'codex', 'OpenAI · Codex'
    def __init__(self, home):
        self.home = Path(home).expanduser().resolve()
        self.cache = OrderedDict()
        self.group_memberships = {}
        self._groups = []
        self.group_warning = None
        self.artifact_store = ArtifactStore(self.id)
        self.activity_cache = {}

    def activity_for(self, row):
        path = Path(row['rollout_path']).resolve()
        if not any(path.is_relative_to(self.home / folder) for folder in ('sessions', 'archived_sessions')):
            raise ProviderError('The chat points to an unexpected storage location.')
        try:
            stat = path.stat()
        except OSError:
            raise ProviderError('The transcript is unavailable on this computer.') from None
        stamp = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        cached = self.activity_cache.get(row['id'])
        if cached and cached[:4] == stamp:
            return cached[4]
        reader = self.read(row)
        self.activity_cache[row['id']] = (*stamp, reader.last_activity, reader.state, reader.last_event)
        if len(self.activity_cache) > 10000:
            self.activity_cache.clear()
        return reader.last_activity

    def connect(self):
        files = list(self.home.glob('state_*.sqlite'))
        if not files:
            raise ProviderError('No local Codex chat storage found.')
        database = max(files, key=lambda p: int(p.stem.split('_')[-1]))
        try:
            c = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
            c.execute('PRAGMA query_only=ON')
            c.row_factory = sqlite3.Row
            columns = {x[1] for x in c.execute('PRAGMA table_info(threads)')}
            if not {'id', 'rollout_path', 'thread_source', 'name', 'model', 'archived', 'title', 'source', 'updated_at', 'agent_role', 'agent_nickname'} <= columns:
                c.close()
                raise ProviderError('This Codex storage format is not supported yet.')
            edge_columns = {x[1] for x in c.execute('PRAGMA table_info(thread_spawn_edges)')}
            if not {'parent_thread_id', 'child_thread_id'} <= edge_columns:
                c.close()
                raise ProviderError('This Codex storage format is missing agent relationships.')
            return c
        except sqlite3.Error:
            raise ProviderError('Local Codex storage is temporarily unreadable.') from None

    def chat(self, r):
        cached = self.cache.get(r['id'])
        activity = self.activity_cache.get(r['id'])
        state = cached.state if cached else activity[5] if activity else 'unknown'
        last_event = cached.last_event if cached else activity[6] if activity else 0
        status = 'unknown' if state == 'working' and time.time() - last_event > 300 else state
        return {'id': 'codex:' + r['id'], 'provider': 'codex', 'providerLabel': self.label,
                'title': (r['name'] or r['title'] or 'Untitled chat')[:180],
                'model': r['model'] or 'Codex', 'updatedAt': r['updated_at'],
                'status': status,
                'lastActivityAt': activity[4] if activity else cached.last_activity if cached else 0,
                **self.group_memberships.get(r['id'], {})}

    def groups(self):
        return self._groups

    def list_chats(self):
        c = self.connect()
        try:
            rows = c.execute("""SELECT * FROM threads WHERE archived=0
                AND (thread_source IS NULL OR thread_source IN ('user','automation','agent_created_thread','agent_forked_thread'))
                AND source NOT LIKE '%subagent%'
                ORDER BY updated_at DESC LIMIT 500""").fetchall()
            try:
                self.group_memberships, self._groups = codex_groups(self.home, rows, c)
                self.group_warning = None
            except (AttributeError, KeyError, TypeError, ValueError, sqlite3.Error):
                self.group_warning = 'Project groups are temporarily unreadable; chats appear under Recent.'
                self._groups = [{'id':'codex:recent','label':'Recent','provider':'codex','kind':'recent','order':1000}]
                self.group_memberships = {r['id']:{'groupId':'codex:recent','groupLabel':'Recent','groupKind':'recent'} for r in rows}
            chats = {}
            for r in rows:
                try:
                    self.activity_for(r)
                except ProviderError:
                    self.cache.pop(r['id'], None)
                chats[r['id']] = self.chat(r)
            # A descendant can continue after its parent log goes quiet. Read its
            # own transcript; database updated_at is metadata, not activity.
            for root_id, child_id in c.execute("""WITH RECURSIVE family(root_id,child_id) AS (
                SELECT parent_thread_id,child_thread_id FROM thread_spawn_edges
                UNION SELECT f.root_id,e.child_thread_id FROM thread_spawn_edges e
                  JOIN family f ON e.parent_thread_id=f.child_id
            ) SELECT f.root_id,t.id FROM family f JOIN threads t ON t.id=f.child_id
              WHERE t.thread_source='subagent'"""):
                if root_id not in chats:
                    continue
                try:
                    child = c.execute('SELECT * FROM threads WHERE id=?', (child_id,)).fetchone()
                    if child:
                        chats[root_id]['lastActivityAt'] = max(chats[root_id]['lastActivityAt'], self.activity_for(child))
                except ProviderError:
                    pass
            return list(chats.values())
        except sqlite3.Error:
            raise ProviderError('The Codex chat list could not be read.') from None
        finally:
            c.close()

    def read(self, r):
        path = Path(r['rollout_path']).resolve()
        if not any(path.is_relative_to(self.home / folder) for folder in ('sessions', 'archived_sessions')):
            raise ProviderError('The chat points to an unexpected storage location.')
        if not path.is_file():
            raise ProviderError('The transcript is unavailable on this computer.')
        reader = self.cache.get(r['id'])
        if reader is None or reader.path != path:
            reader = Rollout(path)
            self.cache[r['id']] = reader
        self.cache.move_to_end(r['id'])
        while len(self.cache) > 120:
            self.cache.popitem(last=False)
        try:
            return reader.refresh()
        except OSError:
            raise ProviderError('The transcript could not be read temporarily.') from None

    def snapshot(self, native_id) -> Snapshot:
        c = self.connect()
        try:
            row = c.execute('SELECT * FROM threads WHERE id=? AND archived=0', (native_id,)).fetchone()
            if row is None or row['thread_source'] in ('subagent', 'guardian_review'):
                raise ProviderError('This chat is unavailable.')
            # Recursive descendants include agents spawned by agents, never guardian runs.
            descendants = c.execute("""WITH RECURSIVE family(id) AS (
                SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?
                UNION SELECT e.child_thread_id FROM thread_spawn_edges e JOIN family f ON e.parent_thread_id=f.id
            ) SELECT t.* FROM threads t JOIN family f ON t.id=f.id
              WHERE t.thread_source='subagent' ORDER BY t.updated_at DESC LIMIT 100""", (native_id,)).fetchall()
        except sqlite3.Error:
            raise ProviderError('Codex agent relationships could not be read.') from None
        finally:
            c.close()
        main = self.read(row)
        agents, messages, events, artifacts, errors = [], [], [], [], [self.group_warning] if self.group_warning else []
        pending_artifacts = RecentArtifacts(MESSAGE_LIMIT)
        def add_agent(r, reader, main_agent=False):
            key = 'codex:' + r['id']
            label = 'Lead agent' if main_agent else r['agent_nickname'] or r['agent_role'] or 'Subagent'
            agents.append({'id': key, 'name': label, 'role': r['agent_role'] or ('Director' if main_agent else 'Subagent'),
                           'model': reader.model or r['model'] or 'Codex', 'status': reader.status(),
                           'isMain': main_agent, 'lastEventAt': reader.last_event, 'lastKnownStatus': reader.state})
            for m in reader.messages:
                # A child's inherited history and earlier runs do not pollute this turn.
                if not main_agent and (m['at'] < main.turn_started or m['role'] != 'assistant'):
                    continue
                messages.append({**m, 'id': key + ':' + m['nativeId'], 'agentId': key,
                                 'speaker': 'You' if m['role'] == 'user' else label})
            events.extend({**event, 'id': key + ':' + event['id'], 'agentId': key} for event in reader.events)
            for m in reader.messages:
                if not main_agent and (m['role'] != 'assistant' or m['at'] < main.turn_started):
                    continue
                message_id = key + ':' + m['nativeId']
                refs = [(label, raw, False) for label, raw in image_references(m['text'])]
                refs += [('Image', raw, attachment) for raw, attachment in reader.image_refs.get(m['nativeId'], [])]
                for label, raw, attachment in refs[:20]:
                    pending_artifacts.add(message_id + ':message', m['at'],
                        self.artifact_store.image, raw, reader.cwd, message_id + ':' + raw,
                        key, m['at'], label, message_id, attachment)
            for event in reader.events:
                for label, diff in reader.diff_refs.get(event['id'], []):
                    proposed = label == 'patch' and event['id'].endswith(':call')
                    pending_artifacts.add(key + ':' + event['id'], event['at'],
                        diff_artifact, diff, event['id'] + ':' + label, key,
                        event['at'], 'Recorded patch' if proposed else 'Changed ' + label,
                        'Codex apply_patch input; application unverified' if proposed else 'Codex FileChange record')
        add_agent(row, main, True)
        for child in descendants:
            try:
                reader = self.read(child)
                same_turn = reader.root_turn == main.turn if main.turn and reader.root_turn else (main.turn_started > 0 and reader.last_event >= main.turn_started)
                if same_turn and (reader.messages or reader.diff_refs or reader.state == 'working'):
                    add_agent(child, reader)
                else:
                    key = 'codex:' + child['id']
                    events.extend({**event, 'id': key + ':' + event['id'], 'agentId': key} for event in reader.events)
            except ProviderError:
                errors.append('A subagent transcript is unavailable.')
        artifacts, event_artifacts = pending_artifacts.collect()
        return finalize_snapshot(
            chat=self.chat(row), agents=agents, messages=messages, events=events,
            artifacts=artifacts, links=event_artifacts, truncated=main.truncated,
            agent_limit=len(descendants) == 100, warnings=errors,
            status_note='Local Codex updates · every 2 seconds')
