"""Read the Codex desktop's saved organization without modifying its preferences."""
import json
from pathlib import Path


def codex_groups(home, rows, connection):
    try:
        state = json.loads((home / '.codex-global-state.json').read_text())
    except (OSError, ValueError):
        state = {}
    atoms = state.get('electron-persisted-atom-state', {})
    projects = state.get('local-projects', {})
    order = state.get('project-order', list(projects))
    assignments = state.get('thread-project-assignments', {})
    projectless = set(state.get('projectless-thread-ids', []))
    manual = atoms.get('flat-project-sidebar-preferences-v1', {}).get('chatSortMode') == 'manual'
    definitions, groups = {}, []
    for pid in dict.fromkeys([*order, *projects]):
        project = projects.get(pid)
        if not isinstance(project, dict):
            continue
        group = {'id': 'codex:project:' + pid, 'label': project.get('name') or 'Project',
                 'provider': 'codex', 'kind': 'project', 'order': len(groups),
                 'collapsed': not atoms.get('sidebar-project-expanded-v1-codex:' + pid, True)}
        definitions[pid] = group
        groups.append(group)
    # Current app-server project IDs may differ from the legacy desktop IDs.
    aliases = {}
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'projects', 'project_roots'} <= tables:
        roots = {}
        for row in connection.execute('SELECT project_id,path FROM project_roots'):
            roots.setdefault(row[0], set()).add(row[1])
        for pid, name in connection.execute('SELECT id,name FROM projects ORDER BY position'):
            matches = [old for old, p in projects.items() if roots.get(pid, set()) & set(p.get('rootPaths', []))]
            if len(matches) == 1:
                aliases[pid] = matches[0]
            elif pid not in definitions:
                group = {'id': 'codex:project:' + pid, 'label': name, 'provider': 'codex',
                         'kind': 'project', 'order': len(groups), 'collapsed': False}
                definitions[pid] = group
                groups.append(group)
    sections, section_threads = {}, {}
    # Only local thread keys are relevant; no cross-account transcript data is read.
    for saved in atoms.get('sidebar-custom-sections-v3', {}).values():
        for section in saved.get('sections', []):
            local_ids = [key[len('codex:thread:local:'):] for key in section.get('itemKeys', [])
                         if key.startswith('codex:thread:local:')]
            if not local_ids:
                continue
            sid = section['id']
            group = {'id': 'codex:section:' + sid, 'label': section['name'], 'provider': 'codex',
                     'kind': 'section', 'order': -500 + len(sections),
                     'collapsed': sid in saved.get('collapsedSectionIds', [])}
            sections[sid] = group
            for i, tid in enumerate(local_ids):
                section_threads[tid] = (group, i)
    if 'thread_sections' in tables:
        for sid, name in connection.execute('SELECT id,name FROM thread_sections'):
            existing = next((g for g in sections.values() if g['label'] == name), None)
            sections[sid] = existing or {'id': 'codex:section:' + sid, 'label': name,
                'provider': 'codex', 'kind': 'section', 'order': -1000 if name == 'Pinned' else -400 + len(sections), 'collapsed': False}
    pinned = state.get('pinned-thread-ids', [])
    recent = {'id': 'codex:recent', 'label': 'Recent', 'provider': 'codex', 'kind': 'recent', 'order': 1000, 'collapsed': False}
    result = {}
    for r in rows:
        tid = r['id']; keys = r.keys(); group = None; chat_order = 0
        sid = r['thread_section_id'] if 'thread_section_id' in keys else None
        if sid in sections:
            group = sections[sid]; chat_order = r['section_position'] or 0
        elif tid in pinned:
            group = {'id': 'codex:pinned', 'label': 'Vastgezet', 'provider': 'codex', 'kind': 'section', 'order': -1000, 'collapsed': False}
            chat_order = pinned.index(tid)
        elif tid in section_threads:
            group, chat_order = section_threads[tid]
        if not group:
            pid = r['project_id'] if 'project_id' in keys else None
            pid = aliases.get(pid, pid)
            if not pid and tid not in projectless:
                pid = assignments.get(tid, {}).get('projectId')
            group = definitions.get(pid, recent)
            if manual and pid:
                ids = state.get('sidebar-project-thread-orders', {}).get(pid, {}).get('threadIds', [])
                chat_order = ids.index(tid) if tid in ids else len(ids)
        result[tid] = {'groupId': group['id'], 'groupLabel': group['label'], 'groupKind': group['kind'],
                       'chatOrder': chat_order if manual or group['kind'] == 'section' else -r['updated_at']}
        if group['id'] not in {g['id'] for g in groups}:
            groups.append(group)
    return result, sorted(groups, key=lambda g: g['order'])
