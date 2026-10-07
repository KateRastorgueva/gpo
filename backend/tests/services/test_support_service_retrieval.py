"""Юнит-тесты улучшений retrieval RAG.

Покрывают char-n-gram embedding, русский стемминг, TF-IDF лексический поиск
и определение конфликтов источников. Не требуют БД/Qdrant/LLM.
"""

import uuid

import pytest

from app.services import support_service as service
from app.services.support_service import RetrievalResult


def _cosine(a, b):
    import math

    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


def _result(source_id=None, snippet="", score=0.8):
    return RetrievalResult(
        source_id=source_id or uuid.uuid4(),
        source_title="Source",
        source_ref="https://example.edu",
        chunk_id=uuid.uuid4(),
        snippet=snippet,
        score=score,
    )


def test_russian_stem_collapses_inflections():
    assert service.russian_stem("оплаты") == service.russian_stem("оплата")
    assert service.russian_stem("стипендии") == service.russian_stem("стипендия")


def test_hashed_embedding_captures_lexical_similarity():
    a = service._hashed_embedding("оплата обучения договор")
    b = service._hashed_embedding("оплату обучения договора")
    c = service._hashed_embedding("расписание занятий пары")
    assert _cosine(a, b) > 0.5
    assert _cosine(a, c) < _cosine(a, b)


def test_tfidf_ranks_relevant_document_higher():
    idf = service._compute_idf(
        ["оплата обучения договор", "расписание занятий", "стипендии гранты"]
    )
    query = service._tfidf_vector("оплата договор", idf)
    relevant = service._tfidf_vector("оплата обучения договор", idf)
    irrelevant = service._tfidf_vector("расписание занятий", idf)
    assert service._tfidf_cosine(query, relevant) > service._tfidf_cosine(query, irrelevant)


def test_has_conflicting_sources_detects_opposite_polarity():
    first = _result(snippet="оплата договора обязательна", score=0.90)
    second = _result(snippet="оплата договора не обязательна", score=0.88)
    assert service.has_conflicting_sources([first, second]) is True


def test_has_conflicting_sources_ignores_agreeing_sources():
    first = _result(snippet="оплата договора обязательна", score=0.90)
    second = _result(snippet="оплата договора обязательна по регламенту", score=0.88)
    assert service.has_conflicting_sources([first, second]) is False
