"""Unit tests for BM25RankingBackend."""

from __future__ import annotations

from swarmmesh_cli.store import BM25RankingBackend, MemoryEntry


def _entry(entry_id: str, text: str) -> MemoryEntry:
    return MemoryEntry(
        namespace="ns", id=entry_id, text=text, metadata={}, created_by="a1", created_at="now"
    )


def test_score_empty_entries_returns_empty_list():
    backend = BM25RankingBackend()
    assert backend.score("query", []) == []


def test_score_empty_query_returns_zero_for_all():
    backend = BM25RankingBackend()
    entries = [_entry("1", "some text"), _entry("2", "other text")]
    results = backend.score("", entries)
    assert all(score == 0.0 for _, score in results)


def test_score_ranks_more_frequent_term_higher():
    backend = BM25RankingBackend()
    entries = [
        _entry("low", "cats are nice"),
        _entry("high", "cats cats cats are wonderful animals"),
        _entry("none", "dogs are also nice"),
    ]
    results = backend.score("cats", entries)
    ordered_ids = [entry.id for entry, _ in results]
    assert ordered_ids[0] == "high"
    assert ordered_ids[-1] == "none"

    scores = {entry.id: score for entry, score in results}
    assert scores["none"] == 0.0
    assert scores["high"] > scores["low"] > scores["none"]


def test_score_is_case_insensitive():
    backend = BM25RankingBackend()
    entries = [_entry("1", "Python is great")]
    results = backend.score("python", entries)
    assert results[0][1] > 0.0


def test_score_multi_term_query():
    backend = BM25RankingBackend()
    entries = [
        _entry("both", "race condition bug"),
        _entry("one", "race across the finish line"),
        _entry("neither", "completely unrelated text"),
    ]
    results = backend.score("race condition", entries)
    scores = {entry.id: score for entry, score in results}
    assert scores["both"] > scores["one"] > scores["neither"]
    assert scores["neither"] == 0.0
