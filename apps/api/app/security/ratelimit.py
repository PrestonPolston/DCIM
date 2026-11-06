"""In-process sliding-window rate limiter (R-2). One API process per install (SQLite/LAN),
so memory is enough; behind a reverse proxy run uvicorn with --forwarded-allow-ips so
request.client.host is the real client."""
import math
import threading
import time
from collections import OrderedDict, defaultdict, deque

# N-3: bound memory. Keys whose deque empties are dropped; above MAX_KEYS the oldest-touched keys are evicted.
# Limits are per process: run ONE API worker (documented in the README).
MAX_KEYS = 50_000


class SlidingWindow:
    def __init__(self, max_keys: int = MAX_KEYS) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self.max_keys = max_keys
        self._noted: OrderedDict[str, float] = OrderedDict()  # N-2: key -> window end of the last audited 429

    def _prune(self, q: deque, now: float, window: float) -> None:
        while q and q[0] <= now - window:
            q.popleft()

    def _gc(self, now: float, window: float) -> None:
        if len(self._hits) <= self.max_keys:
            return
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[k]
        while len(self._hits) > self.max_keys:  # still too many live keys: evict the oldest-touched
            oldest = min(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0)
            del self._hits[oldest]

    def __len__(self) -> int:
        return len(self._hits)

    def first_in_window(self, key: str, window: float) -> bool:
        """N-2: True once per key per window, so a 429 flood writes one audit row, not thousands."""
        now = time.monotonic()
        with self._lock:
            until = self._noted.get(key)
            if until is not None and until > now:
                return False
            self._noted[key] = now + window
            self._noted.move_to_end(key)
            while len(self._noted) > self.max_keys:
                self._noted.popitem(last=False)
            return True

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """0 if `key` may proceed (and counts the hit), else seconds to wait."""
        if limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            self._prune(q, now, window)
            if len(q) >= limit:
                return max(1, math.ceil(q[0] + window - now))
            q.append(now)
            self._gc(now, window)
            return 0

    def blocked(self, key: str, limit: int, window: float) -> int:
        """Like retry_after but does not count a hit (for failure counters)."""
        if limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                return 0  # don't create keys on a read
            self._prune(q, now, window)
            if not q:
                del self._hits[key]
                return 0
            return max(1, math.ceil(q[0] + window - now)) if len(q) >= limit else 0

    def hit(self, key: str) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._noted.clear()


login_limiter = SlidingWindow()
