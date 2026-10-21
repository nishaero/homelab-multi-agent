"""One model call at a time, highest priority first.

A home lab usually has a single GPU. Several agents thinking at once slow each other and
the voice assistant. The gate hands out one slot at a time and orders waiters by priority
(lower number first), then by arrival.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time
from contextlib import contextmanager

VOICE, INTERACTIVE, BACKGROUND = 0, 1, 2


class GateTimeout(Exception):
    pass


class ModelGate:
    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._heap: list[tuple[int, int]] = []
        self._busy = False
        self._seq = itertools.count()
        self.waited_s = 0.0          # total time spent waiting, for measuring contention
        self.calls = 0

    @contextmanager
    def slot(self, priority: int = BACKGROUND, timeout: float | None = None):
        ticket = (priority, next(self._seq))
        start = time.monotonic()
        with self._cv:
            heapq.heappush(self._heap, ticket)
            while not (self._heap[0] == ticket and not self._busy):
                remaining = None if timeout is None else timeout - (time.monotonic() - start)
                if remaining is not None and remaining <= 0:
                    self._heap.remove(ticket)
                    heapq.heapify(self._heap)
                    self._cv.notify_all()
                    raise GateTimeout(f"no model slot within {timeout}s")
                self._cv.wait(remaining)
            heapq.heappop(self._heap)
            self._busy = True
            self.waited_s += time.monotonic() - start
            self.calls += 1
        try:
            yield
        finally:
            with self._cv:
                self._busy = False
                self._cv.notify_all()
