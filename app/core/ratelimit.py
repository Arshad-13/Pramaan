"""A small in-memory sliding-window rate limiter (Spec Section 8.4).

Purpose: slow down password guessing, signup abuse and heavy verification use. Each key (an IP, an
         account, a user) may make `limit` attempts per `window` seconds; the next one is refused
         with HTTP 429 and a Retry-After header.
Why not slowapi: the login limit must count by the TARGET ACCOUNT (an email in the request body) as
         well as by IP, which a decorator cannot see, and this version is simple to test.
Limits: state lives in this process only. That is right for the single-process demo; running
         several workers would need a shared store (listed in the known limitations).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from app.config import get_settings
from app.errors import TooManyRequests

_PURGE_EVERY = 2048  # check for idle keys after this many calls


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        """Count one attempt for `key`; raise TooManyRequests when it exceeds the limit."""
        if not get_settings().rate_limit_enabled:
            return
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, math.ceil(hits[0] + window - now))
                raise TooManyRequests(retry_after=retry)
            hits.append(now)
            self._calls += 1
            if self._calls % _PURGE_EVERY == 0:
                self._purge(now, window)

    def _purge(self, now: float, window: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or h[-1] <= now - window]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
