"""Shared, bounded latest-value cache for local source polling.

Clients keep only their last revision. A slow reader never accumulates a queue
of snapshots, and opening another tab does not start another source scan.
"""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

from providers.base import ProviderError


@dataclass
class Slot:
    value: Any = None
    error: Optional[str] = None
    refreshed: float = float('-inf')
    loading: bool = False
    ready: threading.Event = field(default_factory=threading.Event)


class LiveFeed:
    def __init__(self, interval=2, capacity=128, clock=time.monotonic):
        self.interval = interval
        self.capacity = capacity
        self.clock = clock
        self.slots = OrderedDict()
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.generation = 0
        self.closed = False

    def read(self, key, loader):
        with self.lock:
            if self.closed:
                raise ProviderError('The local viewer has stopped.')
            slot = self.slots.get(key)
            if slot is None:
                if len(self.slots) >= self.capacity:
                    victim = next((k for k, item in self.slots.items() if not item.loading), None)
                    if victim is None:
                        raise ProviderError('The viewer is busy. Try again shortly.')
                    del self.slots[victim]
                slot = self.slots[key] = Slot()
            self.slots.move_to_end(key)
            if not slot.loading and self.clock() - slot.refreshed >= self.interval:
                slot.loading = True
                slot.refreshed = self.clock()
                threading.Thread(target=self._refresh, args=(slot, loader), daemon=True).start()
            warm = slot.ready.is_set()
        # Warm readers receive the last revision while the shared refresh runs.
        if not warm and not slot.ready.wait(timeout=10):
            raise ProviderError('The chat source is taking too long. Reconnecting…')
        with self.lock:
            if slot.error:
                raise ProviderError(slot.error)
            return slot.value

    def _refresh(self, slot, loader):
        try:
            value, error = loader(), None
        except ProviderError as failure:
            value, error = None, str(failure)
        except Exception:
            # Local paths or transcript content must not escape in tracebacks.
            value, error = None, 'The local chat source could not be read.'
        with self.lock:
            slot.value = value
            slot.error = error
            slot.loading = False
            slot.ready.set()
            self.generation += 1
            self.changed.notify_all()

    def wait(self, generation, timeout=2):
        with self.changed:
            self.changed.wait_for(lambda: self.closed or self.generation != generation, timeout)

    def close(self):
        with self.lock:
            self.closed = True
            self.slots.clear()
            self.changed.notify_all()
