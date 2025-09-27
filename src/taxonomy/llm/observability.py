"""Observability utilities for the LLM subsystem."""

from __future__ import annotations

import statistics
import threading
from collections import Counter, deque
from dataclasses import dataclass
from typing import Deque, Dict


@dataclass
class MetricsSnapshot:
    """Immutable snapshot of collected metrics."""

    counters: Dict[str, int]
    latency_p50_ms: float
    latency_p95_ms: float
    tokens_in: int
    tokens_out: int


class MetricsCollector:
    """Thread safe collector for LLM level metrics."""

    def __init__(self, window_size: int = 200) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._latencies: Deque[float] = deque(maxlen=window_size)
        self._prompt_tokens: Deque[int] = deque(maxlen=window_size)
        self._completion_tokens: Deque[int] = deque(maxlen=window_size)

    def incr(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def record_latency(self, value_ms: float) -> None:
        with self._lock:
            self._latencies.append(float(value_ms))

    def record_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            self._prompt_tokens.append(int(prompt_tokens))
            self._completion_tokens.append(int(completion_tokens))

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            latencies = list(self._latencies)
            prompt_tokens = list(self._prompt_tokens)
            completion_tokens = list(self._completion_tokens)
            counters = dict(self._counters)

        latency_p50 = statistics.median(latencies) if latencies else 0.0
        latency_p95 = 0.0
        if latencies:
            sorted_latencies = sorted(latencies)
            index = max(int(0.95 * (len(sorted_latencies) - 1)), 0)
            latency_p95 = sorted_latencies[index]

        return MetricsSnapshot(
            counters=counters,
            latency_p50_ms=latency_p50,
            latency_p95_ms=latency_p95,
            tokens_in=sum(prompt_tokens),
            tokens_out=sum(completion_tokens),
        )


__all__ = ["MetricsCollector", "MetricsSnapshot"]
