"""Shared presentation records; parsing remains provider-specific."""
import hashlib
import json
from typing import List, Optional, TypedDict

MESSAGE_LIMIT = 200
EVENT_LIMIT = 500


class Chat(TypedDict, total=False):
    id: str
    title: str
    provider: str
    providerLabel: str
    model: str
    lastActivityAt: float


class Agent(TypedDict, total=False):
    id: str
    name: str
    model: str
    isMain: bool
    status: str
    role: str


class Message(TypedDict, total=False):
    id: str
    agentId: str
    role: str
    text: str
    speaker: str
    at: float


class WorkEvent(TypedDict, total=False):
    id: str
    agentId: str
    at: float
    kind: str
    label: str
    artifactIds: List[str]


class Artifact(TypedDict, total=False):
    id: str
    agentId: str
    at: float
    kind: str
    label: str
    messageId: Optional[str]
    text: str
    url: str
    provenance: str
    role: str


class Snapshot(TypedDict):
    chat: Chat
    agents: List[Agent]
    messages: List[Message]
    events: List[WorkEvent]
    artifacts: List[Artifact]
    lastActivityAt: float
    historyLimited: bool
    agentLimitReached: bool
    warnings: List[str]
    transport: str
    statusNote: str
    revision: str


def finalize_snapshot(*, chat: Chat, agents: List[Agent], messages: List[Message],
                      events: List[WorkEvent], artifacts: List[Artifact], links,
                      truncated=False, agent_limit=False, warnings=(), status_note='') -> Snapshot:
    """Apply one ordering, history limit and attribution policy to both sources."""
    ordered_events = sorted(events, key=lambda event: (event['at'], event['id']))
    last_activity = max((event['at'] for event in ordered_events), default=0)
    by_id = {artifact['id']: artifact for artifact in artifacts}
    visible_events = []
    for event in ordered_events[-EVENT_LIMIT:]:
        ids = [identity for identity in links.get(event['id'], [])
               if identity in by_id and by_id[identity]['agentId'] == event['agentId']]
        visible_events.append({**event, 'artifactIds': ids})
    visible_ids = {identity for event in visible_events for identity in event['artifactIds']}
    result = {
        'chat': {**chat, 'lastActivityAt': last_activity},
        'agents': agents,
        'messages': sorted(messages, key=lambda message: message['at'])[-MESSAGE_LIMIT:],
        'events': visible_events,
        'artifacts': [artifact for artifact in artifacts if artifact['id'] in visible_ids],
        'lastActivityAt': last_activity,
        'historyLimited': truncated or len(messages) > MESSAGE_LIMIT,
        'agentLimitReached': agent_limit,
        'warnings': sorted(set(warnings)),
        'transport': 'local-store',
        'statusNote': status_note,
    }
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:20]
    return result
