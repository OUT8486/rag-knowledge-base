"""Small, bounded public budgets for the existing single-process deployment."""

from threading import BoundedSemaphore, Lock
from time import monotonic


class PublicBudget:
    _limits = {"ask": (12, 120), "create": (3, 50), "lookup": (30, 300)}

    def __init__(self):
        self._lock = Lock()
        self._minute = -1
        self._counts = {}
        self._totals = {}
        self.inference = BoundedSemaphore(2)

    def admit(self, action, peer):
        minute = int(monotonic() // 60)
        per_peer, total = self._limits[action]
        with self._lock:
            if self._minute != minute:
                self._minute = minute
                self._counts.clear()
                self._totals.clear()
            key = (action, peer)
            if self._totals.get(action, 0) >= total or self._counts.get(key, 0) >= per_peer:
                return False
            self._counts[key] = self._counts.get(key, 0) + 1
            self._totals[action] = self._totals.get(action, 0) + 1
            return True
