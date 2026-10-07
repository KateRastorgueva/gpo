import uuid
from types import SimpleNamespace

import pytest

from app.services import support_service as service
from app.services.support_service import RetrievalResult


def _row(title: str, content: str):
    source = SimpleNamespace(
        id=uuid.uuid4(), title=title, source_ref=None, is_active=True
    )
    chunk = SimpleNamespace(id=uuid.uuid4(), content=content)
    return chunk, source


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def exec(self, _statement):
        return SimpleNamespace(all=lambda: self._rows)


def _result(chunk_id: uuid.UUID, score: float = 0.5) -> RetrievalResult:
    return RetrievalResult(
        source_id=uuid.uuid4(),
        source_title="doc",
        source_ref=None,
        chunk_id=chunk_id,
        snippet="text",
        score=score,
    )


def test_bm25_tokens_drop_stopwords_and_stem() -> None:
    tokens = service._bm25_tokens("Сколько можно пересдавать экзамены?")
    assert "сколько" not in tokens
    assert any(t.startswith("пересда") for t in tokens)
    assert any(t.startswith("экзам") for t in tokens)


def test_bm25_ranks_matching_chunk_first_with_full_coverage() -> None:
    target = _row("Положение", "Комиссия на вторую пересдачу состоит из трех человек.")
    other = _row("Устав", "Университет расположен в городе Томске.")
    results, coverage = service.retrieve_lexical_bm25(
        _Session([other, target]), "комиссия на вторую пересдачу"
    )
    assert results[0].chunk_id == target[0].id
    assert coverage[target[0].id] == pytest.approx(1.0)


def test_bm25_unknown_words_lower_coverage_and_offtopic_is_empty() -> None:
    row = _row("Положение", "Комиссия на вторую пересдачу состоит из трех человек.")
    _, full = service.retrieve_lexical_bm25(_Session([row]), "комиссия пересдачу")
    _, partial = service.retrieve_lexical_bm25(_Session([row]), "комиссия пересдачу борщ")
    assert partial[row[0].id] < full[row[0].id]
    results, coverage = service.retrieve_lexical_bm25(_Session([row]), "как приготовить борщ")
    assert results == [] and coverage == {}


def test_bm25_empty_inputs() -> None:
    assert service.retrieve_lexical_bm25(_Session([]), "вопрос") == ([], {})
    row = _row("a", "b c")
    assert service.retrieve_lexical_bm25(_Session([row]), "и в на") == ([], {})


def test_rrf_merge_orders_by_rank_not_raw_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_embedding_backend", lambda: "hashed")
    sem_only = _result(uuid.uuid4(), score=0.52)
    both = _result(uuid.uuid4(), score=0.40)
    lex = _result(both.chunk_id, score=0.14)
    merged = service._rrf_merge([sem_only, both], [lex], {both.chunk_id: 0.8})
    assert merged[0].chunk_id == both.chunk_id
    assert merged[0].score == pytest.approx(0.8)
    assert merged[1].score == 0.0


def test_rrf_merge_keeps_blended_score_for_real_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "get_embedding_backend", lambda: "sentence-transformers")
    item = _result(uuid.uuid4(), score=0.8)
    merged = service._rrf_merge([item], [], {})
    assert merged[0].score == pytest.approx(0.8)
