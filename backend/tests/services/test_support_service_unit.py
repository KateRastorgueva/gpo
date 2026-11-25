import uuid
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import support_service as service
from app.services.support_service import RetrievalResult


def _result(
    *,
    source_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    snippet: str = "Student support portal answers requests.",
    score: float = 0.8,
    source_ref: str = "https://example.edu/support",
) -> RetrievalResult:
    return RetrievalResult(
        source_id=source_id or uuid.uuid4(),
        source_title="Support source",
        source_ref=source_ref,
        chunk_id=chunk_id or uuid.uuid4(),
        snippet=snippet,
        score=score,
    )


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("  Где расписание занятий?!  ", "где расписание занятий"),
        ("Support\tPortal\nFAQ", "support portal faq"),
        ("Оплата-договора №42", "оплата-договора 42"),
    ],
)
def test_normalize_text_prepares_queries_for_matching(
    raw_text: str, expected: str
) -> None:
    assert service.normalize_text(raw_text) == expected


@pytest.mark.parametrize(
    ("question", "faq_question", "meets_threshold"),
    [
        ("расписание тусур пары", "Где посмотреть расписание занятий ТУСУР?", True),
        ("контакты приемной комиссии", "Где контакты приемной комиссии ТУСУР?", True),
        (
            "Где информация по оплате обучения в ТУСУР?",
            "Где информация по оплате обучения в ТУСУР?",
            True,
        ),
        ("личный приказ об отчислении", "Где смотреть расписание занятий ТУСУР?", False),
    ],
)
def test_faq_similarity_routes_typical_user_phrases(
    question: str, faq_question: str, meets_threshold: bool
) -> None:
    score = service.faq_similarity(question, faq_question)

    if meets_threshold:
        assert score >= settings.FAQ_SIMILARITY_THRESHOLD
    else:
        assert score < settings.FAQ_SIMILARITY_THRESHOLD


def test_chunk_text_returns_short_text_as_single_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHUNK_SIZE", 100)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP", 10)

    assert service.chunk_text("short source text") == ["short source text"]


def test_chunk_text_splits_source_with_configured_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHUNK_SIZE", 10)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP", 2)

    chunks = service.chunk_text("0123456789abcdef")

    assert chunks == ["0123456789", "89abcdef"]


def test_merge_hybrid_results_combines_same_chunk_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HYBRID_SEMANTIC_WEIGHT", 0.7)
    monkeypatch.setattr(settings, "HYBRID_LEXICAL_WEIGHT", 0.3)
    monkeypatch.setattr(settings, "HYBRID_CANDIDATES_LIMIT", 10)
    source_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    semantic = _result(source_id=source_id, chunk_id=chunk_id, score=0.8)
    lexical = _result(source_id=source_id, chunk_id=chunk_id, score=0.6)

    merged = service._merge_hybrid_results(
        semantic_results=[semantic],
        lexical_results=[lexical],
    )

    assert len(merged) == 1
    assert merged[0].chunk_id == chunk_id
    assert merged[0].score == pytest.approx(0.74)


def test_merge_hybrid_results_preserves_semantic_only_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HYBRID_CANDIDATES_LIMIT", 10)
    semantic = _result(score=0.95)

    merged = service._merge_hybrid_results(
        semantic_results=[semantic],
        lexical_results=[],
    )

    assert len(merged) == 1
    assert merged[0].score == pytest.approx(0.95)


def test_merge_hybrid_results_preserves_lexical_only_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HYBRID_CANDIDATES_LIMIT", 10)
    lexical = _result(score=0.67)

    merged = service._merge_hybrid_results(
        semantic_results=[],
        lexical_results=[lexical],
    )

    assert len(merged) == 1
    assert merged[0].score == pytest.approx(0.67)


def test_rerank_results_uses_lexical_similarity_test_double(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RERANK_WEIGHT", 0.5)
    monkeypatch.setattr(settings, "RETRIEVAL_TOP_K", 2)
    weak_semantic_strong_lexical = _result(snippet="оплата договора", score=0.5)
    strong_semantic_weak_lexical = _result(snippet="расписание занятий", score=0.7)

    def fake_lexical_similarity(_question: str, snippet: str) -> float:
        return 1.0 if "оплата" in snippet else 0.0

    with patch(
        "app.services.support_service._lexical_similarity",
        side_effect=fake_lexical_similarity,
    ):
        reranked = service.rerank_results(
            "как оплатить договор",
            [strong_semantic_weak_lexical, weak_semantic_strong_lexical],
        )

    assert reranked[0].snippet == "оплата договора"
    assert reranked[0].score == pytest.approx(0.75)


def test_generate_answer_falls_back_to_ollama_test_double() -> None:
    with (
        patch(
            "app.services.support_service._generate_with_google",
            side_effect=RuntimeError("google unavailable"),
        ) as google_mock,
        patch(
            "app.services.support_service._generate_with_lmstudio",
            side_effect=RuntimeError("lmstudio unavailable"),
        ),
        patch(
            "app.services.support_service._generate_with_ollama",
            return_value="Ответ из резервной модели",
        ) as ollama_mock,
    ):
        answer, fallback_used = service.generate_answer(
            "Где получить справку?",
            [_result(snippet="Справка доступна в личном кабинете.", score=0.93)],
        )

    assert answer == "Ответ из резервной модели"
    assert fallback_used is True
    google_mock.assert_called_once()
    ollama_mock.assert_called_once()


def test_generate_answer_prefers_lmstudio_over_ollama() -> None:
    """Если ключа Google нет, ответ пишет LM Studio, а Ollama не трогается."""

    with (
        patch(
            "app.services.support_service._generate_with_google",
            side_effect=RuntimeError("google unavailable"),
        ),
        patch(
            "app.services.support_service._generate_with_lmstudio",
            return_value="Ответ от локальной модели",
        ) as lmstudio_mock,
        patch(
            "app.services.support_service._generate_with_ollama",
            return_value="Ответ из резервной модели",
        ) as ollama_mock,
    ):
        answer, fallback_used = service.generate_answer(
            "Где получить справку?",
            [_result(snippet="Справка доступна в личном кабинете.", score=0.93)],
        )

    assert answer == "Ответ от локальной модели"
    assert fallback_used is True
    lmstudio_mock.assert_called_once()
    ollama_mock.assert_not_called()

def test_sanitize_answer_links_keeps_only_source_links() -> None:
    """В ответе остаются только ссылки из найденных источников."""
    allowed = "https://help.tusur.ru/knowledgebase.php?article=135"
    results = [
        _result(snippet="Инструкция по справке.", score=0.9, source_ref=allowed)
    ]
    text = (
        "Смотри [инструкцию](https://help.tusur.ru/knowledgebase.php?article=135) "
        "и ещё [сайт](http://evil.example/fake)."
    )

    cleaned = service.sanitize_answer_links(text, results)

    assert f"[инструкцию]({allowed})" in cleaned
    assert "evil.example" not in cleaned
    assert "сайт" in cleaned


def test_sanitize_answer_links_removes_links_without_sources() -> None:
    results = [_result(snippet="Файл устава.", score=0.9, source_ref="Ustav_2018.pdf")]

    cleaned = service.sanitize_answer_links(
        "Подробнее: https://example.org/x и [тут](https://example.org/y).", results
    )

    assert "example.org" not in cleaned

def test_ensure_answer_links_appends_source_link() -> None:
    """Если модель не вставила ссылку, в конце ответа появляется «Подробнее»."""
    url = "https://help.tusur.ru/knowledgebase.php?article=135"
    results = [_result(snippet="Инструкция.", score=0.9, source_ref=url)]

    linked = service.ensure_answer_links("Готовый ответ без ссылок.", results)

    assert "Подробнее" in linked
    assert f"[Support source]({url})" in linked


def test_ensure_answer_links_keeps_existing_link() -> None:
    url = "https://help.tusur.ru/knowledgebase.php?article=135"
    results = [_result(snippet="Инструкция.", score=0.9, source_ref=url)]
    answer = f"Смотри [инструкцию]({url})."

    assert service.ensure_answer_links(answer, results) == answer
