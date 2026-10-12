from __future__ import annotations

import dataclasses

import pytest

from app.models.common import Language
from app.models.ids import new_analysis_id
from app.storage.memory import InMemoryAnalysisStore, StoredAnalysis, StoredSource
from tests.helpers.fakes import FAKE_SHA, analyze_fixture, require_graph


@pytest.fixture(scope="module")
def analysis() -> StoredAnalysis:
    return analyze_fixture()


def _copy(analysis: StoredAnalysis) -> StoredAnalysis:
    return dataclasses.replace(analysis, analysis_id=new_analysis_id())


def test_build_analysis_records_revision_and_graph(analysis: StoredAnalysis) -> None:
    assert analysis.repository.commit_sha == FAKE_SHA
    assert analysis.repository.url == "https://github.com/acme/shop-api"
    graph = require_graph(analysis)
    assert len(graph.nodes) == 9 and len(graph.edges) == 5


def test_store_roundtrip_and_lru_eviction(analysis: StoredAnalysis) -> None:
    store = InMemoryAnalysisStore(capacity=2)
    first, second, third = _copy(analysis), _copy(analysis), _copy(analysis)

    store.save(first)
    store.save(second)
    assert store.get(first.analysis_id) is first  # touch: second is now least recent
    store.save(third)

    assert store.get(second.analysis_id) is None
    assert store.get(first.analysis_id) is first and store.get(third.analysis_id) is third
    assert len(store) == 2


def test_store_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        InMemoryAnalysisStore(capacity=0)


def _with_sources(analysis: StoredAnalysis, size: int) -> StoredAnalysis:
    source = StoredSource("src/a.js", Language.JAVASCRIPT, "x" * size, size)
    sources = {"src/a.js": source}
    return dataclasses.replace(analysis, analysis_id=new_analysis_id(), sources=sources)


def test_store_evicts_by_retained_source_bytes(analysis: StoredAnalysis) -> None:
    store = InMemoryAnalysisStore(capacity=10, max_source_bytes=250)
    first, second, third = (_with_sources(analysis, 100) for _ in range(3))

    store.save(first)
    store.save(second)
    store.save(third)  # 300 bytes > 250: the least recently used goes

    assert store.get(first.analysis_id) is None
    assert store.get(second.analysis_id) is second and store.get(third.analysis_id) is third
    assert store.source_bytes == 200


def test_store_keeps_the_newest_analysis_even_if_it_alone_exceeds_the_budget(
    analysis: StoredAnalysis,
) -> None:
    store = InMemoryAnalysisStore(capacity=10, max_source_bytes=50)
    small, huge = _with_sources(analysis, 10), _with_sources(analysis, 500)

    store.save(small)
    store.save(huge)

    assert store.get(small.analysis_id) is None
    assert store.get(huge.analysis_id) is huge and len(store) == 1


def test_resaving_does_not_double_count(analysis: StoredAnalysis) -> None:
    store = InMemoryAnalysisStore(capacity=10, max_source_bytes=1_000)
    item = _with_sources(analysis, 100)

    store.save(item)
    store.save(item)

    assert store.source_bytes == 100 and len(store) == 1


def test_retained_sources_are_exactly_the_parsed_files(analysis: StoredAnalysis) -> None:
    assert sorted(analysis.sources) == ["src/auth/session.ts", "src/db.ts", "src/server.ts"]
    assert analysis.source_bytes == sum(s.size_bytes for s in analysis.sources.values())
