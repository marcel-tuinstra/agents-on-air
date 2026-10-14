"""Provider-neutral, read-only contract. IDs are namespaced at this boundary."""
from abc import ABC, abstractmethod
from datetime import datetime
import math
import threading
from .schema import Snapshot

class ProviderError(Exception):
    pass

class Provider(ABC):
    id: str
    label: str
    @abstractmethod
    def list_chats(self) -> list[dict]: ...
    def groups(self):
        return []
    @abstractmethod
    def snapshot(self, native_id: str) -> Snapshot: ...

class Registry:
    def __init__(self, providers):
        self.providers = {p.id: p for p in providers}
        self.locks = {p.id: threading.RLock() for p in self.providers.values()}
    def catalog(self):
        chats, sources, groups = [], [], []
        for p in self.providers.values():
            try:
                with self.locks[p.id]:
                    incoming = p.list_chats()
                    provider_groups = p.groups()
                for chat in incoming:
                    if not chat['id'].startswith(p.id + ':') or chat['provider'] != p.id:
                        raise ProviderError('The source returned an invalid chat ID.')
                    value = chat['updatedAt']
                    if isinstance(value, str):
                        value = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
                    chat['updatedAt'] = float(value)
                    if not math.isfinite(chat['updatedAt']):
                        raise ProviderError('The source returned an invalid date.')
                    activity = chat.get('lastActivityAt', 0)
                    if isinstance(activity, str):
                        activity = datetime.fromisoformat(activity.replace('Z', '+00:00')).timestamp()
                    chat['lastActivityAt'] = float(activity)
                    if not math.isfinite(chat['lastActivityAt']) or chat['lastActivityAt'] < 0:
                        raise ProviderError('The source returned an invalid activity date.')
                chats.extend(incoming)
                groups.extend(provider_groups)
                sources.append({'id': p.id, 'label': p.label, 'connected': True})
            except (ProviderError, KeyError, ValueError, TypeError) as e:
                sources.append({'id': p.id, 'label': p.label, 'connected': False, 'error': str(e) if isinstance(e, ProviderError) else 'The source returned an invalid format.'})
        return {'chats': sorted(chats, key=lambda x: x['updatedAt'], reverse=True), 'providers': sources, 'groups': groups}
    def snapshot(self, key):
        provider, sep, native_id = key.partition(':')
        if not sep or provider not in self.providers:
            raise ProviderError('This source is not connected.')
        with self.locks[provider]:
            return self.providers[provider].snapshot(native_id)
    def artifact(self, opaque_id):
        if not isinstance(opaque_id, str) or len(opaque_id) != 32 or any(c not in '0123456789abcdef' for c in opaque_id):
            raise ProviderError('This artifact is unavailable.')
        for provider in self.providers.values():
            store = getattr(provider, 'artifact_store', None)
            with self.locks[provider.id]:
                if store and opaque_id in store.entries:
                    return store.resolve(opaque_id)
        raise ProviderError('This artifact is unavailable.')
