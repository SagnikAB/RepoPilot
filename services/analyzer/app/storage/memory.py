"""Bounded, thread-safe in-memory analysis store (MVP; no persistence)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.graph.builder import CallGraph
from app.models.analysis import AnalysisSummary, RepositoryInfo
from app.models.common import Language
from app.models.findings import Finding


@dataclass(frozen=True, slots=True)
class StoredSource:
    """An analyzed file's text, retained for evidence retrieval.

    Only files that passed ingestion filtering (no secrets, keys, env files,
    binaries or dependency directories; size-limited) *and* were parsed are kept.
    """

    path: str
    language: Language
    text: str
    size_bytes: int
    redactions: tuple[tuple[int, int], ...] = ()  # code-point spans of credential-like values


@dataclass(frozen=True, slots=True)
class StoredAnalysis:
    """Everything served for one analysis run, built once from a single checkout."""

    analysis_id: str
    summary: AnalysisSummary  # status, revision, timestamps, stats, diagnostics
    graph: CallGraph | None  # None when the analysis failed
    findings: tuple[Finding, ...] = ()  # ordered by (path, line, column, rule)
    sources: Mapping[str, StoredSource] = field(default_factory=dict)

    @property
    def repository(self) -> RepositoryInfo:
        return self.summary.repository

    @property
    def source_bytes(self) -> int:
        return sum(source.size_bytes for source in self.sources.values())


class AnalysisStore(Protocol):
    def save(self, analysis: StoredAnalysis) -> None: ...

    def get(self, analysis_id: str) -> StoredAnalysis | None: ...


class InMemoryAnalysisStore:
    """LRU store bounded by analysis count and by total retained source bytes.

    The most recently saved analysis is never evicted by the byte budget, so a
    single large analysis is still served (ingestion limits bound its size).
    """

    def __init__(self, capacity: int, max_source_bytes: int | None = None) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        if max_source_bytes is not None and max_source_bytes < 1:
            raise ValueError("max_source_bytes must be positive")
        self._capacity = capacity
        self._max_source_bytes = max_source_bytes
        self._items: OrderedDict[str, StoredAnalysis] = OrderedDict()
        self._source_bytes = 0
        self._lock = threading.Lock()

    def save(self, analysis: StoredAnalysis) -> None:
        with self._lock:
            previous = self._items.pop(analysis.analysis_id, None)
            if previous is not None:
                self._source_bytes -= previous.source_bytes
            self._items[analysis.analysis_id] = analysis
            self._source_bytes += analysis.source_bytes
            while len(self._items) > self._capacity or self._over_budget():
                _, evicted = self._items.popitem(last=False)
                self._source_bytes -= evicted.source_bytes

    def _over_budget(self) -> bool:
        return (
            self._max_source_bytes is not None
            and self._source_bytes > self._max_source_bytes
            and len(self._items) > 1
        )

    def get(self, analysis_id: str) -> StoredAnalysis | None:
        with self._lock:
            analysis = self._items.get(analysis_id)
            if analysis is not None:
                self._items.move_to_end(analysis_id)
            return analysis

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def source_bytes(self) -> int:
        with self._lock:
            return self._source_bytes
