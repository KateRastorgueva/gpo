"""Сервисный слой обработки обращений технической поддержки.

Модуль реализует маршрут обработки пользовательского вопроса по схеме
``FAQ -> RAG -> Operator``. В нем находятся функции поиска FAQ-ответов,
извлечения релевантных фрагментов базы знаний, генерации ответа через LLM,
эскалации обращения оператору и обслуживания административных сценариев.
"""

import hashlib
import math
import re
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.models import (
    DecisionMetrics,
    FaqEntry,
    FaqEntryCreate,
    FaqEntryUpdate,
    KnowledgeChunk,
    KnowledgeSource,
    MyQueueEntry,
    OperatorQueue,
    OperatorQueueEntry,
    OperatorReply,
    SourceAttribution,
    SupportAnswer,
    SupportAskRequest,
    SupportAskResponse,
    SupportHistoryEntry,
    SupportMetricsPublic,
    SupportRequest,
)


CRITICAL_KEYWORDS = (
    "срок",
    "дедлайн",
    "оплата",
    "платеж",
    "приказ",
    "регламент",
    "договор",
    "юрид",
    "штраф",
)

FAQ_STOPWORDS = {
    # Russian stopwords for intent-oriented FAQ matching
    "а",
    "без",
    "более",
    "бы",
    "в",
    "вам",
    "вас",
    "все",
    "где",
    "да",
    "для",
    "до",
    "его",
    "ее",
    "же",
    "за",
    "и",
    "из",
    "или",
    "как",
    "какой",
    "какая",
    "какие",
    "когда",
    "кто",
    "ли",
    "мне",
    "можно",
    "на",
    "надо",
    "не",
    "но",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "что",
    "чтобы",
    "это",
    # Domain-generic words that don't define FAQ intent
    "тусур",
    "университет",
    "университета",
    "официальный",
    "официальная",
    "официальные",
    # English stopwords used in existing tests/examples
    "a",
    "an",
    "and",
    "for",
    "from",
    "get",
    "how",
    "i",
    "in",
    "is",
    "me",
    "on",
    "or",
    "the",
    "to",
    "we",
    "where",
}

FAQ_KEYWORD_SYNONYMS = {
    # Schedule
    "пара": "расписание",
    "пары": "расписание",
    "пар": "расписание",
    "занятие": "расписание",
    "занятия": "расписание",
    "занятий": "расписание",
    "расписании": "расписание",
    "расписание": "расписание",
    "timetable": "расписание",
    "schedule": "расписание",
    "classes": "расписание",
    # Admissions / contacts
    "абитуриент": "поступление",
    "абитуриентам": "поступление",
    "поступление": "поступление",
    "поступления": "поступление",
    "поступлению": "поступление",
    "приемная": "поступление",
    "приемной": "поступление",
    "приемную": "поступление",
    "комиссия": "поступление",
    "комиссии": "поступление",
    "admission": "поступление",
    "enrollment": "поступление",
    "apply": "поступление",
    "applicant": "поступление",
    "контакт": "контакты",
    "контакты": "контакты",
    "почта": "контакты",
    "телефон": "контакты",
    "писать": "контакты",
    "написать": "контакты",
    "write": "контакты",
    "email": "контакты",
    "phone": "контакты",
    "contact": "контакты",
    "contacts": "контакты",
    # Scholarship / support
    "стипендия": "стипендия",
    "стипендии": "стипендия",
    "грант": "стипендия",
    "гранты": "стипендия",
    "поддержка": "стипендия",
    "поддержки": "стипендия",
    "scholarship": "стипендия",
    # Paid education / payment
    "оплата": "оплата",
    "оплаты": "оплата",
    "оплатить": "оплата",
    "платное": "оплата",
    "платных": "оплата",
    "стоимость": "оплата",
    "договор": "оплата",
    "договоров": "оплата",
    "payment": "оплата",
    "tuition": "оплата",
    # Programs / education
    "образование": "программы",
    "образовании": "программы",
    "образовательная": "программы",
    "образовательные": "программы",
    "образовательных": "программы",
    "программа": "программы",
    "программы": "программы",
    "program": "программы",
    "programs": "программы",
}

_embedding_model: Any | None = None
_embedding_backend: str | None = None


@dataclass
class RetrievalResult:
    """Результат поиска одного релевантного фрагмента базы знаний.

    Атрибуты содержат идентификаторы источника и фрагмента, человекочитаемое
    название источника, ссылку на него, текст найденного фрагмента и оценку
    релевантности.
    """

    source_id: uuid.UUID
    source_title: str
    source_ref: str | None
    chunk_id: uuid.UUID | None
    snippet: str
    score: float


def normalize_text(value: str) -> str:
    """Нормализует строку для сравнения, поиска и вычисления сходства."""

    lowered = value.lower().strip()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^\w\sа-яА-ЯёЁ-]", "", lowered)
    return lowered.strip()


def _token_set(value: str) -> set[str]:
    """Преобразует нормализованный текст в множество непустых токенов."""

    normalized = normalize_text(value)
    if not normalized:
        return set()
    return {token for token in normalized.split(" ") if token}


_RU_SUFFIXES = (
    "иями", "ями", "ами", "ией", "иям", "иях", "его", "ому", "ими", "ыми",
    "ого", "ему", "ая", "яя", "ое", "ее", "ые", "ие", "ий", "ый", "ой", "ей",
    "ия", "ие", "ии", "ов", "ев", "ин", "ын", "ах", "ях", "ам", "ям", "ом", "ем",
    "ы", "и", "а", "я", "о", "е", "у", "ю", "ь",
)


def russian_stem(word: str) -> str:
    """Возвращает грубую основу русского слова отсечением типовых окончаний."""

    if len(word) <= 3:
        return word
    for suffix in _RU_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _lexical_tokens(value: str) -> list[str]:
    """Токены с лёгким русским стеммингом для лексического поиска."""

    return [russian_stem(token) for token in _token_set(value)]


def _canonical_faq_token(token: str) -> str:
    """Возвращает каноническую форму FAQ-токена с учетом словаря синонимов."""

    return FAQ_KEYWORD_SYNONYMS.get(token, token)


def _faq_keyword_set(value: str) -> set[str]:
    """Выделяет значимые ключевые слова для intent-oriented FAQ-сравнения."""

    tokens = _token_set(value)
    keywords: set[str] = set()
    for token in tokens:
        canonical = _canonical_faq_token(token)
        if len(canonical) < 3:
            continue
        if canonical in FAQ_STOPWORDS:
            continue
        keywords.add(canonical)
    return keywords


def _faq_keyword_similarity(left: str, right: str) -> float:
    """Вычисляет сходство двух FAQ-фраз по пересечению ключевых слов."""

    left_keywords = _faq_keyword_set(left)
    right_keywords = _faq_keyword_set(right)
    if not left_keywords or not right_keywords:
        return 0.0

    intersection = len(left_keywords.intersection(right_keywords))
    if intersection == 0:
        return 0.0

    query_coverage = intersection / len(left_keywords)
    faq_coverage = intersection / len(right_keywords)
    f1 = (
        (2 * query_coverage * faq_coverage) / (query_coverage + faq_coverage)
        if (query_coverage + faq_coverage) > 0
        else 0.0
    )

    # If all user intent keywords are covered by FAQ, strongly boost score.
    if query_coverage == 1.0:
        f1 = max(f1, 0.95)
    return f1


def faq_similarity(left: str, right: str) -> float:
    """Вычисляет итоговую оценку похожести вопроса пользователя и FAQ."""

    left_n = normalize_text(left)
    right_n = normalize_text(right)
    if not left_n or not right_n:
        return 0.0
    seq = SequenceMatcher(None, left_n, right_n).ratio()
    left_tokens = _token_set(left_n)
    right_tokens = _token_set(right_n)
    if not left_tokens or not right_tokens:
        return seq
    intersection = len(left_tokens.intersection(right_tokens))
    union = len(left_tokens.union(right_tokens))
    jaccard = intersection / union if union else 0.0
    lexical_score = (seq * 0.7) + (jaccard * 0.3)
    keyword_score = _faq_keyword_similarity(left_n, right_n)
    return round(min(1.0, max(lexical_score, keyword_score)), 4)


def _lexical_similarity(left: str, right: str) -> float:
    """Считает F1-подобную лексическую близость двух текстов по токенам."""

    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens.intersection(right_tokens))
    if intersection == 0:
        return 0.0
    precision = intersection / len(right_tokens)
    recall = intersection / len(left_tokens)
    return round(
        (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0,
        4,
    )


def _compute_idf(texts: Iterable[str]) -> dict[str, float]:
    """Считает IDF-веса терминов по коллекции документов."""

    doc_freq: Counter[str] = Counter()
    doc_count = 0
    for text in texts:
        doc_count += 1
        for token in set(_lexical_tokens(text)):
            doc_freq[token] += 1
    return {
        token: math.log((doc_count + 1) / (count + 1)) + 1.0
        for token, count in doc_freq.items()
    }


def _tfidf_vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    """Возвращает TF-IDF вектор текста, нормированный по частоте терминов."""

    term_freq: Counter[str] = Counter(_lexical_tokens(text))
    total = sum(term_freq.values()) or 1
    return {
        token: (count / total) * idf.get(token, 1.0)
        for token, count in term_freq.items()
    }


def _tfidf_cosine(left: dict[str, float], right: dict[str, float]) -> float:
    """Косинусное сходство двух разреженных TF-IDF векторов."""

    if not left or not right:
        return 0.0
    numerator = sum(weight * right.get(token, 0.0) for token, weight in left.items())
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _clamp_score(value: float) -> float:
    """Ограничивает числовую оценку диапазоном от 0.0 до 1.0."""

    return max(0.0, min(1.0, value))


def is_critical_question(question: str) -> bool:
    """Проверяет, содержит ли вопрос признаки критичного обращения."""

    normalized = normalize_text(question)
    return any(keyword in normalized for keyword in CRITICAL_KEYWORDS)


def _get_sentence_transformer() -> Any | None:
    """Лениво загружает локальную модель SentenceTransformer для embeddings."""

    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return _embedding_model
    except Exception:
        return None


def get_embedding_backend() -> str:
    """Выбирает backend embeddings один раз на процесс.

    Индекс и запросы должны строиться в одном векторном пространстве, поэтому
    backend не переключается от вызова к вызову: при сбое выбранного backend
    embed_texts падает, а не подменяет вектор другим.
    """

    global _embedding_backend
    if _embedding_backend is not None:
        return _embedding_backend
    configured = settings.EMBEDDING_BACKEND.strip().lower()
    if configured == "auto":
        if _get_sentence_transformer() is not None:
            configured = "sentence-transformers"
        elif settings.GOOGLE_API_KEY and settings.GOOGLE_EMBEDDING_MODEL.strip():
            configured = "google"
        else:
            configured = "hashed"
    if configured not in {"sentence-transformers", "google", "hashed"}:
        raise ValueError(f"Unknown EMBEDDING_BACKEND: {settings.EMBEDDING_BACKEND}")
    if configured == "sentence-transformers" and _get_sentence_transformer() is None:
        raise RuntimeError(
            f"sentence-transformers model {settings.EMBEDDING_MODEL_NAME} is not available"
        )
    _embedding_backend = configured
    return configured


def get_embedding_model_id() -> str:
    """Возвращает идентификатор векторного пространства для payload и проверок."""

    backend = get_embedding_backend()
    if backend == "sentence-transformers":
        name = settings.EMBEDDING_MODEL_NAME
    elif backend == "google":
        name = settings.GOOGLE_EMBEDDING_MODEL.strip()
    else:
        name = "char3gram-md5-v1"
    return f"{backend}:{name}:{settings.EMBEDDING_DIM}"


def _hashed_embedding(text: str, size: int = 384) -> list[float]:
    """Строит резервный embedding через char-n-gram feature hashing.

    Прежний вариант на SHA-256 давал случайные векторы без смысловой близости,
    из-за чего семантический поиск без sentence-transformers/Google был шумом.
    Feature hashing по символьным n-граммам сохраняет близость текстов, похожих
    по словам и их написанию, без внешних моделей.
    """

    gram_size = 3
    grams: Counter[str] = Counter()
    for token in re.findall(r"[a-zа-яё0-9]+", text.lower()):
        token = f"#{token}#"
        for index in range(len(token) - gram_size + 1):
            grams[token[index : index + gram_size]] += 1

    vector = [0.0] * size
    for gram, count in grams.items():
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % size
        vector[bucket] += float(count)

    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def _resize_vector(vector: list[float], size: int) -> list[float]:
    """Приводит embedding-вектор к требуемой размерности."""

    if len(vector) == size:
        return vector
    if len(vector) > size:
        return vector[:size]
    return vector + ([0.0] * (size - len(vector)))


def _embed_with_google(text: str) -> list[float] | None:
    """Получает embedding текста через Google API, если ключ настроен."""

    if not settings.GOOGLE_API_KEY:
        return None
    embedding_model = settings.GOOGLE_EMBEDDING_MODEL.strip()
    if not embedding_model:
        return None
    if not embedding_model.startswith("models/"):
        embedding_model = f"models/{embedding_model}"
    url = f"{settings.GOOGLE_API_URL}/{embedding_model}:embedContent"
    payload = {
        "model": embedding_model,
        "content": {"parts": [{"text": text}]},
    }
    headers = {"X-goog-api-key": settings.GOOGLE_API_KEY}
    try:
        with httpx.Client(timeout=settings.QDRANT_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            values = body.get("embedding", {}).get("values", [])
            if isinstance(values, list) and values:
                return [float(v) for v in values]
    except Exception:
        return None
    return None


def embed_text(text: str) -> list[float]:
    """Создает embedding для одного текста выбранным backend embeddings."""

    return embed_texts([text])[0]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Создает embeddings для набора текстов выбранным backend без подмены."""

    text_list = list(texts)
    if not text_list:
        return []
    backend = get_embedding_backend()
    if backend == "sentence-transformers":
        model = _get_sentence_transformer()
        raw = model.encode(text_list)  # type: ignore[union-attr]
        vectors = [[float(v) for v in vector] for vector in raw]
    elif backend == "google":
        vectors = []
        for text in text_list:
            google_vector = _embed_with_google(text)
            if google_vector is None:
                raise RuntimeError("Google embedding request failed")
            vectors.append(google_vector)
    else:
        vectors = [_hashed_embedding(text) for text in text_list]
    return [_resize_vector(vector, settings.EMBEDDING_DIM) for vector in vectors]


def _qdrant_base_url() -> str:
    """Формирует базовый URL Qdrant с учетом настроек host и port."""

    host = settings.QDRANT_HOST.strip()
    if host.startswith(("http://", "https://")):
        parsed = urlparse(host)
        if parsed.port is not None:
            return host.rstrip("/")
        return f"{host.rstrip('/')}:{settings.QDRANT_PORT}"
    return f"http://{host}:{settings.QDRANT_PORT}"


def _qdrant_headers() -> dict[str, str]:
    """Возвращает HTTP-заголовки для запросов к Qdrant."""

    headers: dict[str, str] = {}
    if settings.QDRANT_API_KEY:
        headers["api-key"] = settings.QDRANT_API_KEY
    return headers


def _qdrant_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    allowed_statuses: set[int] | None = None,
) -> httpx.Response:
    """Выполняет HTTP-запрос к Qdrant и проверяет статус ответа."""

    url = f"{_qdrant_base_url()}{path}"
    with httpx.Client(timeout=settings.QDRANT_TIMEOUT_SECONDS) as client:
        response = client.request(
            method=method, url=url, headers=_qdrant_headers(), json=payload
        )
    if allowed_statuses and response.status_code in allowed_statuses:
        return response
    response.raise_for_status()
    return response


def ensure_qdrant_collection(vector_size: int) -> None:
    """Создает коллекцию Qdrant для embeddings, если она еще не существует."""

    collection_path = f"/collections/{settings.QDRANT_COLLECTION_NAME}"
    response = _qdrant_request("GET", collection_path, allowed_statuses={404})
    if response.status_code != 404:
        vectors_config = (
            response.json().get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
        )
        existing_size = vectors_config.get("size") if isinstance(vectors_config, dict) else None
        if existing_size is not None and existing_size != vector_size:
            raise RuntimeError(
                f"Qdrant collection has vector size {existing_size}, current embedding "
                f"backend produces {vector_size}. Run a full reindex."
            )
        return
    _qdrant_request(
        "PUT",
        collection_path,
        payload={"vectors": {"size": vector_size, "distance": "Cosine"}},
    )


def reset_qdrant_collection() -> None:
    """Удаляет коллекцию Qdrant, игнорируя ее отсутствие."""

    collection_path = f"/collections/{settings.QDRANT_COLLECTION_NAME}"
    _qdrant_request("DELETE", collection_path, allowed_statuses={404})


def _scroll_qdrant_points(limit: int = 256) -> list[dict[str, Any]]:
    """Постранично получает payload всех точек из коллекции Qdrant."""

    collection_path = f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/scroll"
    points: list[dict[str, Any]] = []
    offset: Any | None = None
    while True:
        payload: dict[str, Any] = {
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            payload["offset"] = offset
        response = _qdrant_request(
            "POST", collection_path, payload=payload, allowed_statuses={404}
        )
        if response.status_code == 404:
            return []
        result = response.json().get("result") or {}
        batch = result.get("points") or []
        points.extend(batch)
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return points


def _delete_qdrant_points(point_ids: list[Any]) -> None:
    """Удаляет из Qdrant точки с указанными идентификаторами."""

    if not point_ids:
        return
    _qdrant_request(
        "POST",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/delete",
        payload={"points": point_ids},
        allowed_statuses={404},
    )


def remove_orphan_vectors(session: Session) -> int:
    """Удаляет векторы Qdrant без активного источника или связанного chunk."""

    points = _scroll_qdrant_points()
    if not points:
        return 0

    valid_source_ids = {
        str(source_id)
        for source_id in session.exec(
            select(KnowledgeSource.id).where(KnowledgeSource.is_active == True)  # noqa: E712
        ).all()
    }
    valid_chunk_ids = {str(chunk_id) for chunk_id in session.exec(select(KnowledgeChunk.id)).all()}

    orphan_ids: list[Any] = []
    for point in points:
        payload = point.get("payload") or {}
        source_id = str(payload.get("source_id") or "")
        chunk_id = str(payload.get("chunk_id") or "")
        source_exists = bool(source_id and source_id in valid_source_ids)
        chunk_exists = bool(chunk_id and chunk_id in valid_chunk_ids)
        if not source_exists or not chunk_exists:
            orphan_ids.append(point.get("id"))

    if orphan_ids:
        _delete_qdrant_points(orphan_ids)
    return len(orphan_ids)


def chunk_text(text: str) -> list[str]:
    """Разбивает текст источника на перекрывающиеся фрагменты для индексации."""

    stripped = text.strip()
    if not stripped:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(stripped):
        end = min(len(stripped), start + settings.CHUNK_SIZE)
        chunk = stripped[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(stripped):
            break
        start = max(0, end - settings.CHUNK_OVERLAP)
    return chunks


def find_faq_match(session: Session, question: str) -> tuple[FaqEntry | None, float]:
    """Ищет лучший активный FAQ-ответ для вопроса пользователя."""

    faqs = session.exec(select(FaqEntry).where(FaqEntry.is_active == True)).all()  # noqa: E712
    if not faqs:
        return None, 0.0
    best_score = 0.0
    best_faq: FaqEntry | None = None
    for faq in faqs:
        score = faq_similarity(question, faq.normalized_question or faq.question)
        if score > best_score:
            best_score = score
            best_faq = faq
    return best_faq, best_score


def _parse_uuid(value: Any) -> uuid.UUID | None:
    """Преобразует произвольное значение в UUID или возвращает None."""

    try:
        if value is None:
            return None
        return uuid.UUID(str(value))
    except Exception:
        return None


def _to_source_attributions(results: list[RetrievalResult]) -> list[SourceAttribution]:
    """Преобразует результаты retrieval в публичные описания источников."""

    return [
        SourceAttribution(
            source_id=result.source_id,
            source_title=result.source_title,
            source_ref=result.source_ref,
            chunk_id=result.chunk_id,
            snippet=result.snippet,
            score=result.score,
        )
        for result in results
    ]


def _serialize_sources(sources: list[SourceAttribution]) -> list[dict[str, Any]]:
    """Сериализует источники ответа в JSON-совместимый список словарей."""

    serialized: list[dict[str, Any]] = []
    for source in sources:
        serialized.append(
            {
                "source_id": str(source.source_id),
                "source_title": source.source_title,
                "source_ref": source.source_ref,
                "chunk_id": str(source.chunk_id) if source.chunk_id else None,
                "snippet": source.snippet,
                "score": source.score,
            }
        )
    return serialized


def retrieve_semantic_chunks(question: str, limit: int | None = None) -> list[RetrievalResult]:
    """Получает кандидаты базы знаний через семантический поиск Qdrant."""

    final_limit = limit or settings.HYBRID_CANDIDATES_LIMIT
    query_vector = embed_text(question)
    ensure_qdrant_collection(len(query_vector))
    response = _qdrant_request(
        "POST",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/search",
        payload={
            "vector": query_vector,
            "limit": final_limit,
            "with_payload": True,
            "filter": {
                "must": [
                    {"key": "embedding_model", "match": {"value": get_embedding_model_id()}}
                ]
            },
        },
        allowed_statuses={404},
    )
    if response.status_code == 404:
        return []
    points = response.json().get("result") or []
    results: list[RetrievalResult] = []
    for point in points:
        payload = point.get("payload") or {}
        source_id = _parse_uuid(payload.get("source_id"))
        if source_id is None:
            continue
        results.append(
            RetrievalResult(
                source_id=source_id,
                source_title=str(payload.get("source_title") or "Источник"),
                source_ref=payload.get("source_ref"),
                chunk_id=_parse_uuid(payload.get("chunk_id")),
                snippet=str(payload.get("chunk_text") or ""),
                score=float(point.get("score") or 0.0),
            )
        )
    return results


def retrieve_lexical_chunks(session: Session, question: str) -> list[RetrievalResult]:
    """Получает кандидаты базы знаний через взвешенный лексический поиск (TF-IDF)."""

    statement = (
        select(KnowledgeChunk, KnowledgeSource)
        .join(KnowledgeSource, KnowledgeChunk.source_id == KnowledgeSource.id)
        .where(KnowledgeSource.is_active == True)  # noqa: E712
    )
    rows = session.exec(statement).all()
    if not rows:
        return []

    idf = _compute_idf([chunk.content for chunk, _source in rows])
    query_vector = _tfidf_vector(question, idf)
    if not query_vector:
        return []

    lexical_results: list[RetrievalResult] = []
    for chunk, source in rows:
        chunk_score = _tfidf_cosine(query_vector, _tfidf_vector(chunk.content, idf))
        title_score = _tfidf_cosine(query_vector, _tfidf_vector(source.title, idf))
        score = max(chunk_score, title_score)
        if score <= 0:
            continue
        lexical_results.append(
            RetrievalResult(
                source_id=source.id,
                source_title=source.title,
                source_ref=source.source_ref,
                chunk_id=chunk.id,
                snippet=chunk.content,
                score=score,
            )
        )
    lexical_results.sort(key=lambda item: item.score, reverse=True)
    return lexical_results[: settings.HYBRID_CANDIDATES_LIMIT]


def _result_key(item: RetrievalResult) -> str:
    """Формирует стабильный ключ для объединения retrieval-результатов."""

    if item.chunk_id is not None:
        return f"chunk:{item.chunk_id}"
    return f"source:{item.source_id}:{hash(item.snippet)}"


def _merge_hybrid_results(
    semantic_results: list[RetrievalResult],
    lexical_results: list[RetrievalResult],
) -> list[RetrievalResult]:
    """Объединяет семантические и лексические результаты в общий рейтинг."""

    semantic_by_key = {_result_key(item): item for item in semantic_results}
    lexical_by_key = {_result_key(item): item for item in lexical_results}
    keys = set(semantic_by_key).union(lexical_by_key)
    if not keys:
        return []

    merged: list[RetrievalResult] = []
    for key in keys:
        semantic_item = semantic_by_key.get(key)
        lexical_item = lexical_by_key.get(key)
        base = semantic_item or lexical_item
        if base is None:
            continue

        sem_score_raw = semantic_item.score if semantic_item else 0.0
        lex_score_raw = lexical_item.score if lexical_item else 0.0

        weighted_sum = 0.0
        active_weight = 0.0
        if semantic_item is not None:
            weighted_sum += settings.HYBRID_SEMANTIC_WEIGHT * sem_score_raw
            active_weight += settings.HYBRID_SEMANTIC_WEIGHT
        if lexical_item is not None:
            weighted_sum += settings.HYBRID_LEXICAL_WEIGHT * lex_score_raw
            active_weight += settings.HYBRID_LEXICAL_WEIGHT

        combined = _clamp_score(weighted_sum / active_weight) if active_weight > 0 else 0.0
        merged.append(
            RetrievalResult(
                source_id=base.source_id,
                source_title=base.source_title,
                source_ref=base.source_ref,
                chunk_id=base.chunk_id,
                snippet=base.snippet,
                score=combined,
            )
        )

    merged.sort(key=lambda item: item.score, reverse=True)
    return merged[: settings.HYBRID_CANDIDATES_LIMIT]


def rerank_results(question: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """Повторно ранжирует найденные фрагменты с учетом лексического совпадения."""

    if not results:
        return []
    normalized_question = normalize_text(question)
    reranked: list[RetrievalResult] = []
    for item in results:
        lexical_score = _lexical_similarity(normalized_question, item.snippet)
        # Rerank should boost lexical agreement without suppressing strong semantic matches.
        score = _clamp_score(
            item.score + (settings.RERANK_WEIGHT * max(0.0, lexical_score - item.score))
        )
        reranked.append(
            RetrievalResult(
                source_id=item.source_id,
                source_title=item.source_title,
                source_ref=item.source_ref,
                chunk_id=item.chunk_id,
                snippet=item.snippet,
                score=score,
            )
        )
    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked[: settings.RETRIEVAL_TOP_K]


def retrieve_relevant_chunks(*, session: Session, question: str) -> list[RetrievalResult]:
    """Возвращает итоговый набор релевантных фрагментов для RAG-ответа."""

    semantic = retrieve_semantic_chunks(question)
    lexical = retrieve_lexical_chunks(session, question)
    merged = _merge_hybrid_results(semantic, lexical)
    return rerank_results(question, merged)


_NEGATION_WORDS = ("не", "нельзя", "нет")


def _has_negation(text: str) -> bool:
    """Проверяет наличие маркеров отрицания в тексте по токенам."""

    for token in _token_set(text):
        if token in _NEGATION_WORDS:
            return True
        if token.startswith(("запрещ", "отмен", "неверн", "отсутств")):
            return True
    return False


def has_conflicting_sources(results: list[RetrievalResult]) -> bool:
    """Определяет явный содержательный конфликт между найденными источниками.

    Консервативная эвристика: конфликт фиксируется, только если два
    высокорейтинговых фрагмента из разных источников говорят об одном и том же
    (значительное пересечение значимых терминов), но противоположны по
    полярности (один отрицает, другой утверждает). Близкие оценки согласующихся
    источников конфликтом не считаются, чтобы не блокировать многокорпусный RAG.
    """

    _top_threshold, chunk_threshold, _min_relevant = routing_thresholds()
    strong = [item for item in results if item.score >= chunk_threshold]
    if len(strong) < 2:
        return False

    first, second = strong[0], strong[1]
    if first.source_id == second.source_id:
        return False

    first_terms = set(_lexical_tokens(first.snippet))
    second_terms = set(_lexical_tokens(second.snippet))
    if not first_terms or not second_terms:
        return False
    overlap = len(first_terms.intersection(second_terms)) / min(
        len(first_terms), len(second_terms)
    )
    if overlap < 0.3:
        return False

    return _has_negation(first.snippet) != _has_negation(second.snippet)


def _build_prompt(question: str, results: list[RetrievalResult]) -> str:
    """Формирует prompt для LLM на основе вопроса и найденных источников."""

    contexts: list[str] = []
    for idx, result in enumerate(results, start=1):
        source_ref = result.source_ref or "без ссылки"
        contexts.append(
            f"[{idx}] Источник: {result.source_title} ({source_ref})\n"
            f"Фрагмент: {result.snippet}"
        )
    context_block = "\n\n".join(contexts)
    return (
        "Ты ассистент техподдержки университета. Отвечай только на основе контекста.\n"
        "Если контекста недостаточно, скажи, что ответа нет.\n"
        "Ответ должен быть кратким и практичным.\n\n"
        f"Вопрос пользователя:\n{question}\n\n"
        f"Подтверждающий контекст:\n{context_block}\n\n"
        "Сформируй ответ на русском языке."
    )


def _generate_with_google(prompt: str) -> str:
    """Генерирует ответ через Google Generative Language API."""

    if not settings.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not configured")
    url = f"{settings.GOOGLE_API_URL}/models/{settings.GOOGLE_MODEL}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"X-goog-api-key": settings.GOOGLE_API_KEY}
    with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Google API returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError("Google API returned empty content")
    text = parts[0].get("text", "").strip()
    if not text:
        raise RuntimeError("Google API returned empty text")
    return text


def _generate_with_ollama(prompt: str) -> str:
    """Генерирует ответ через локальный или удаленный Ollama API."""

    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()
    text = str(body.get("response", "")).strip()
    if not text:
        raise RuntimeError("Ollama returned empty text")
    return text


def generate_answer(question: str, results: list[RetrievalResult]) -> tuple[str, bool]:
    """Генерирует RAG-ответ и возвращает признак использования fallback."""

    prompt = _build_prompt(question, results)
    try:
        return _generate_with_google(prompt), False
    except Exception:
        return _generate_with_ollama(prompt), True


def _create_queue_item(session: Session, request_id: uuid.UUID, reason: str) -> None:
    """Создает открытую запись в очереди оператора для обращения."""

    queue_item = OperatorQueue(request_id=request_id, reason=reason, status="open")
    session.add(queue_item)


def _record_support_result(
    *,
    session: Session,
    user_id: uuid.UUID | None,
    payload: SupportAskRequest,
    session_id: str,
    mode: str,
    confidence: float,
    fallback_used: bool,
    escalated: bool,
    answer_text: str,
    sources: list[SourceAttribution],
    escalation_reason: str | None,
    route_reason: str,
    decision_metrics: DecisionMetrics,
) -> SupportAskResponse:
    """Сохраняет запрос, ответ, источники и при необходимости очередь оператора."""

    request = SupportRequest(
        user_id=user_id,
        session_id=session_id,
        channel=payload.channel,
        question=payload.question,
        mode=mode,  # type: ignore[arg-type]
        confidence=confidence,
        fallback_used=fallback_used,
        escalated=escalated,
        status="escalated" if escalated else "completed",
    )
    session.add(request)
    session.flush()

    answer = SupportAnswer(
        request_id=request.id,
        answer=answer_text,
        sources_json=_serialize_sources(sources),
    )
    session.add(answer)

    if escalated:
        _create_queue_item(
            session, request.id, escalation_reason or "insufficient-confidence"
        )

    session.commit()
    return SupportAskResponse(
        request_id=request.id,
        session_id=session_id,
        mode=mode,  # type: ignore[arg-type]
        answer=answer_text,
        sources=sources,
        confidence=confidence,
        escalated=escalated,
        fallback_used=fallback_used,
        route_reason=route_reason,
        decision_metrics=decision_metrics,
    )


def routing_thresholds() -> tuple[float, float, int]:
    """Возвращает пороги маршрутизации RAG для текущего backend embeddings."""

    if get_embedding_backend() == "hashed":
        return (
            settings.RAG_TOP_SCORE_THRESHOLD_HASHED,
            settings.RAG_RELEVANT_CHUNK_THRESHOLD_HASHED,
            settings.RAG_MIN_RELEVANT_CHUNKS_HASHED,
        )
    return (
        settings.RAG_TOP_SCORE_THRESHOLD,
        settings.RAG_RELEVANT_CHUNK_THRESHOLD,
        settings.RAG_MIN_RELEVANT_CHUNKS,
    )


def run_support_pipeline(
    *, session: Session, user_id: uuid.UUID | None, payload: SupportAskRequest
) -> SupportAskResponse:
    """Выполняет полный pipeline обработки обращения: FAQ, RAG или Operator."""

    session_id = payload.session_id or str(uuid.uuid4())
    faq_match, faq_score = find_faq_match(session, payload.question)
    critical = is_critical_question(payload.question)

    if faq_match and faq_score >= settings.FAQ_SIMILARITY_THRESHOLD:
        faq_source = SourceAttribution(
            source_id=faq_match.id,
            source_title="FAQ",
            source_ref=f"faq:{faq_match.id}",
            chunk_id=None,
            snippet=faq_match.question,
            score=faq_score,
        )
        decision_metrics = DecisionMetrics(
            top_score=0.0,
            relevant_chunks=0,
            faq_score=_clamp_score(faq_score),
            conflict=False,
            critical=critical,
        )
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            mode="faq",
            confidence=min(1.0, faq_score),
            fallback_used=False,
            escalated=False,
            answer_text=faq_match.answer,
            sources=[faq_source],
            escalation_reason=None,
            route_reason="faq_hit",
            decision_metrics=decision_metrics,
        )

    try:
        retrieved = retrieve_relevant_chunks(session=session, question=payload.question)
    except Exception:
        decision_metrics = DecisionMetrics(
            top_score=0.0,
            relevant_chunks=0,
            faq_score=_clamp_score(faq_score),
            conflict=False,
            critical=critical,
        )
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            mode="operator",
            confidence=0.0,
            fallback_used=False,
            escalated=True,
            answer_text="Поиск по базе знаний временно недоступен. Обращение передано оператору.",
            sources=[],
            escalation_reason="retrieval-failure",
            route_reason="retrieval_failure",
            decision_metrics=decision_metrics,
        )

    top_threshold, chunk_threshold, min_relevant = routing_thresholds()
    top_score = retrieved[0].score if retrieved else 0.0
    relevant_chunk_count = sum(1 for item in retrieved if item.score >= chunk_threshold)
    has_context = relevant_chunk_count >= min_relevant and top_score >= top_threshold
    conflict = has_conflicting_sources(retrieved)
    decision_metrics = DecisionMetrics(
        top_score=_clamp_score(top_score),
        relevant_chunks=relevant_chunk_count,
        faq_score=_clamp_score(faq_score),
        conflict=conflict,
        critical=critical,
    )

    if not has_context or conflict:
        reason = "conflicting-sources" if conflict else "insufficient-context"
        route_reason = "conflict" if conflict else "insufficient_context"
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            mode="operator",
            confidence=min(1.0, top_score),
            fallback_used=False,
            escalated=True,
            answer_text="Автоматический ответ недоступен. Обращение передано оператору.",
            sources=_to_source_attributions(retrieved),
            escalation_reason=reason,
            route_reason=route_reason,
            decision_metrics=decision_metrics,
        )

    confidence = min(1.0, top_score)
    if critical and confidence < settings.CRITICAL_CONFIDENCE_THRESHOLD:
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            mode="operator",
            confidence=confidence,
            fallback_used=False,
            escalated=True,
            answer_text="Для этого вопроса требуется проверка оператором. Обращение передано.",
            sources=_to_source_attributions(retrieved),
            escalation_reason="low-confidence-critical",
            route_reason="critical_low_confidence",
            decision_metrics=decision_metrics,
        )

    try:
        answer_text, fallback_used = generate_answer(payload.question, retrieved)
    except Exception:
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            mode="operator",
            confidence=confidence,
            fallback_used=True,
            escalated=True,
            answer_text="Не удалось сформировать надежный ответ автоматически. Обращение передано оператору.",
            sources=_to_source_attributions(retrieved),
            escalation_reason="llm-failure",
            route_reason="llm_failure",
            decision_metrics=decision_metrics,
        )

    if not answer_text.strip():
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            mode="operator",
            confidence=confidence,
            fallback_used=fallback_used,
            escalated=True,
            answer_text="Ответ получился пустым. Обращение передано оператору.",
            sources=_to_source_attributions(retrieved),
            escalation_reason="empty-answer",
            route_reason="empty_answer",
            decision_metrics=decision_metrics,
        )

    if (
        not critical
        and settings.LOW_CONFIDENCE_MIN <= confidence <= settings.LOW_CONFIDENCE_MAX
    ):
        answer_text = (
            f"{answer_text}\n\nТребуется проверка актуальности по указанным источникам."
        )

    return _record_support_result(
        session=session,
        user_id=user_id,
        payload=payload,
        session_id=session_id,
        mode="rag",
        confidence=confidence,
        fallback_used=fallback_used,
        escalated=False,
        answer_text=answer_text,
        sources=_to_source_attributions(retrieved),
        escalation_reason=None,
        route_reason="rag_answer",
        decision_metrics=decision_metrics,
    )


def list_support_history(
    *, session: Session, user_id: uuid.UUID, session_id: str | None = None, limit: int = 50
) -> list[SupportHistoryEntry]:
    """Возвращает историю обращений пользователя вместе с ответами и источниками."""

    statement = select(SupportRequest).where(SupportRequest.user_id == user_id)
    if session_id:
        statement = statement.where(SupportRequest.session_id == session_id)
    statement = statement.order_by(col(SupportRequest.created_at).desc()).limit(limit)
    requests = session.exec(statement).all()
    if not requests:
        return []

    answer_map: dict[uuid.UUID, SupportAnswer] = {}
    request_ids = [request.id for request in requests]
    answers = session.exec(
        select(SupportAnswer).where(SupportAnswer.request_id.in_(request_ids))
    ).all()
    for answer in answers:
        answer_map[answer.request_id] = answer

    queue_reply_map: dict[uuid.UUID, OperatorReply] = {}
    queue_items = session.exec(
        select(OperatorQueue).where(OperatorQueue.request_id.in_(request_ids))
    ).all()
    queue_ids = [item.id for item in queue_items]
    if queue_ids:
        replies = session.exec(
            select(OperatorReply).where(OperatorReply.queue_id.in_(queue_ids))
        ).all()
        reply_by_queue_id = {reply.queue_id: reply for reply in replies}
        for queue_item in queue_items:
            reply = reply_by_queue_id.get(queue_item.id)
            if reply:
                queue_reply_map[queue_item.request_id] = reply

    history: list[SupportHistoryEntry] = []
    for request in requests:
        answer = answer_map.get(request.id)
        operator_reply = queue_reply_map.get(request.id)
        sources = []
        if answer and answer.sources_json:
            for item in answer.sources_json:
                source_id = _parse_uuid(item.get("source_id"))
                if source_id is None:
                    continue
                sources.append(
                    SourceAttribution(
                        source_id=source_id,
                        source_title=str(item.get("source_title", "Источник")),
                        source_ref=item.get("source_ref"),
                        chunk_id=_parse_uuid(item.get("chunk_id")),
                        snippet=item.get("snippet"),
                        score=item.get("score"),
                    )
                )
        history.append(
            SupportHistoryEntry(
                request_id=request.id,
                question=request.question,
                mode=request.mode,
                answer=answer.answer if answer else "",
                sources=sources,
                confidence=request.confidence,
                escalated=request.escalated,
                fallback_used=request.fallback_used,
                status=request.status,
                created_at=request.created_at,
                operator_reply_text=operator_reply.reply_text if operator_reply else None,
                operator_reply_created_at=operator_reply.created_at if operator_reply else None,
            )
        )
    return history


def create_faq_entry(session: Session, faq_in: FaqEntryCreate) -> FaqEntry:
    """Создает FAQ-запись и сохраняет нормализованную форму вопроса."""

    sanitized_question = _ensure_utf8_text(faq_in.question)
    sanitized_answer = _ensure_utf8_text(faq_in.answer)
    faq = FaqEntry(
        question=sanitized_question,
        answer=sanitized_answer,
        is_active=faq_in.is_active,
        normalized_question=normalize_text(sanitized_question),
    )
    session.add(faq)
    session.commit()
    session.refresh(faq)
    return faq


def update_faq_entry(session: Session, faq: FaqEntry, faq_in: FaqEntryUpdate) -> FaqEntry:
    """Обновляет FAQ-запись и пересчитывает нормализованный вопрос."""

    data = faq_in.model_dump(exclude_unset=True)
    if "question" in data and data["question"]:
        data["question"] = _ensure_utf8_text(data["question"])
    if "answer" in data and data["answer"]:
        data["answer"] = _ensure_utf8_text(data["answer"])
    if "question" in data and data["question"]:
        data["normalized_question"] = normalize_text(data["question"])
    data["updated_at"] = datetime.now(timezone.utc)
    faq.sqlmodel_update(data)
    session.add(faq)
    session.commit()
    session.refresh(faq)
    return faq


# Меньше этого числа символов на страницу считаем, что текстового слоя нет (скан).
_PDF_MIN_CHARS_PER_PAGE = 20


def _extract_text_from_pdf(data: bytes) -> str:
    """Извлекает текстовый слой PDF через pypdf, страницы разделяет пустой строкой."""

    import io

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not data.startswith(b"%PDF"):
        raise ValueError("File is not a PDF document")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise ValueError(f"PDF could not be parsed: {exc}") from exc
    text = _ensure_utf8_text("\n\n".join(page.strip() for page in pages))
    if len(text) < _PDF_MIN_CHARS_PER_PAGE * max(1, len(pages)):
        raise ValueError(
            "PDF has no text layer (looks like a scan). OCR is not supported yet."
        )
    return text


def _extract_text_from_html(html: bytes, content_type: str | None = None) -> str:
    """Извлекает основной текст HTML без навигации, колонтитулов и скриптов."""

    from bs4 import BeautifulSoup

    from_encoding = None
    if content_type and "charset=" in content_type.lower():
        from_encoding = content_type.lower().split("charset=")[-1].split(";")[0].strip()
    # BeautifulSoup сам определяет кодировку по meta или содержимому, если ее нет в заголовке.
    soup = BeautifulSoup(html, "html.parser", from_encoding=from_encoding)
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    return _ensure_utf8_text(root.get_text(separator="\n", strip=True))


def _extract_text_from_url(url: str) -> str:
    """Загружает страницу по URL (с редиректами) и извлекает из нее текст."""

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    with httpx.Client(
        timeout=settings.URL_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": settings.URL_FETCH_USER_AGENT},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        body = response.content
    if len(body) > max_bytes:
        raise ValueError(f"Page is larger than {settings.MAX_UPLOAD_SIZE_MB} MB")
    content_type = response.headers.get("content-type", "")
    if "application/pdf" in content_type or body.startswith(b"%PDF"):
        return _extract_text_from_pdf(body)
    return _extract_text_from_html(body, content_type)


def _decode_utf8_text_bytes(data: bytes) -> str:
    """Декодирует байты текстового источника как UTF-8 с учетом BOM."""

    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Text source must be UTF-8 encoded") from exc


def _ensure_utf8_text(value: str) -> str:
    """Возвращает строку, безопасно приведенную к UTF-8 и очищенную по краям.

    NUL-символы удаляются: PostgreSQL не хранит их в text-полях.
    """

    value = value.replace("\x00", "")
    return value.encode("utf-8", errors="replace").decode("utf-8", errors="replace").strip()


def resolve_source_content(
    *,
    filename: str | None,
    file_bytes: bytes | None,
    source_url: str | None,
    manual_content: str | None,
) -> tuple[str, str, str | None]:
    """Определяет тип источника знаний и возвращает извлеченный текст."""

    if manual_content and manual_content.strip():
        source_ref = _ensure_utf8_text(source_url) if source_url else None
        return _ensure_utf8_text(manual_content), "manual", source_ref
    if source_url:
        text = _extract_text_from_url(source_url)
        return text, "url", _ensure_utf8_text(source_url)
    if file_bytes is None or not filename:
        raise ValueError("No source content provided")
    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        text = _extract_text_from_pdf(file_bytes)
        return text, "pdf", _ensure_utf8_text(filename)
    if lower_name.endswith((".html", ".htm")):
        text = _extract_text_from_html(file_bytes)
        return text, "html", _ensure_utf8_text(filename)
    if lower_name.endswith(".txt") or lower_name.endswith(".md"):
        text = _decode_utf8_text_bytes(file_bytes)
        return _ensure_utf8_text(text), "txt", _ensure_utf8_text(filename)
    raise ValueError("Unsupported file type. Use pdf/txt/md/html or URL/manual content.")


def remove_source_vectors(source_id: uuid.UUID) -> None:
    """Удаляет из Qdrant все векторы, связанные с указанным источником."""

    _qdrant_request(
        "POST",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/delete",
        payload={
            "filter": {
                "must": [
                    {"key": "source_id", "match": {"value": str(source_id)}},
                ]
            }
        },
        allowed_statuses={404},
    )


def _upsert_points(points: list[dict[str, Any]]) -> None:
    """Записывает или обновляет набор точек в коллекции Qdrant."""

    _qdrant_request(
        "PUT",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points?wait=true",
        payload={"points": points},
    )


def index_source(session: Session, source: KnowledgeSource) -> int:
    """Индексирует источник знаний в базе данных и векторном хранилище."""

    source.title = _ensure_utf8_text(source.title)
    source.content = _ensure_utf8_text(source.content)
    if source.source_ref:
        source.source_ref = _ensure_utf8_text(source.source_ref)

    chunks = chunk_text(source.content)
    if not chunks:
        raise ValueError("Source content is empty after processing")

    vectors = embed_texts(chunks)
    if not vectors:
        raise ValueError("Failed to create embeddings")
    ensure_qdrant_collection(len(vectors[0]))
    embedding_model = get_embedding_model_id()

    # Старые векторы удаляются только после записи новых и commit: при сбое
    # посередине остаются лишние точки (их чистит remove_orphan_vectors),
    # а не чанки без векторов.
    old_vector_ids = list(
        session.exec(
            select(KnowledgeChunk.vector_id).where(KnowledgeChunk.source_id == source.id)
        ).all()
    )
    session.exec(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
    session.flush()

    points: list[dict[str, Any]] = []
    new_chunks: list[KnowledgeChunk] = []
    for index, (chunk_text_value, vector) in enumerate(zip(chunks, vectors, strict=True)):
        vector_id = uuid.uuid4().hex
        chunk_obj = KnowledgeChunk(
            source_id=source.id,
            chunk_index=index,
            content=chunk_text_value,
            vector_id=vector_id,
        )
        new_chunks.append(chunk_obj)
        points.append(
            {
                "id": vector_id,
                "vector": vector,
                "payload": {
                    "source_id": str(source.id),
                    "source_title": source.title,
                    "source_ref": source.source_ref,
                    "chunk_text": chunk_text_value,
                    "chunk_index": index,
                    "embedding_model": embedding_model,
                },
            }
        )

    for chunk in new_chunks:
        session.add(chunk)
    session.flush()

    for chunk, point in zip(new_chunks, points, strict=True):
        point["payload"]["chunk_id"] = str(chunk.id)

    _upsert_points(points)
    source.status = "indexed"
    source.last_indexed_at = datetime.now(timezone.utc)
    source.updated_at = datetime.now(timezone.utc)
    session.add(source)
    session.commit()
    try:
        _delete_qdrant_points(old_vector_ids)
    except Exception:
        pass  # remove_orphan_vectors дочистит при следующей переиндексации
    return len(new_chunks)


def reindex_sources(
    session: Session,
    source_ids: list[uuid.UUID] | None = None,
    *,
    full_rebuild: bool = False,
    purge_orphans: bool = True,
) -> tuple[int, int]:
    """Переиндексирует активные источники и возвращает статистику обработки."""

    if full_rebuild:
        source_ids = None

    statement = select(KnowledgeSource).where(KnowledgeSource.is_active == True)  # noqa: E712
    if source_ids:
        statement = statement.where(KnowledgeSource.id.in_(source_ids))
    sources = session.exec(statement).all()
    if full_rebuild:
        reset_qdrant_collection()
        session.exec(delete(KnowledgeChunk))
        session.commit()

    count = 0
    for source in sources:
        try:
            index_source(session, source)
            count += 1
        except Exception:
            session.rollback()
            source_db = session.get(KnowledgeSource, source.id)
            if source_db:
                source_db.status = "failed"
                source_db.updated_at = datetime.now(timezone.utc)
                session.add(source_db)
                session.commit()
    orphan_vectors_removed = remove_orphan_vectors(session) if purge_orphans else 0
    return count, orphan_vectors_removed


def list_operator_queue(session: Session) -> list[OperatorQueueEntry]:
    """Возвращает очередь операторских обращений с данными запросов и ответов."""

    queue_items = session.exec(
        select(OperatorQueue).order_by(col(OperatorQueue.created_at).desc())
    ).all()
    if not queue_items:
        return []
    request_ids = [item.request_id for item in queue_items]
    queue_ids = [item.id for item in queue_items]
    requests = session.exec(
        select(SupportRequest).where(SupportRequest.id.in_(request_ids))
    ).all()
    request_map = {request.id: request for request in requests}
    replies = session.exec(
        select(OperatorReply).where(OperatorReply.queue_id.in_(queue_ids))
    ).all()
    reply_map = {reply.queue_id: reply for reply in replies}
    response: list[OperatorQueueEntry] = []
    for item in queue_items:
        request = request_map.get(item.request_id)
        if not request:
            continue
        reply = reply_map.get(item.id)
        response.append(
            OperatorQueueEntry(
                queue_id=item.id,
                request_id=item.request_id,
                reason=item.reason,
                status=item.status,
                question=request.question,
                created_at=item.created_at,
                reply_text=reply.reply_text if reply else None,
                reply_created_at=reply.created_at if reply else None,
            )
        )
    return response


def reply_to_queue_item(
    session: Session,
    queue_item: OperatorQueue,
    reply_text: str,
    operator_id: uuid.UUID,
) -> OperatorQueueEntry:
    """Сохраняет ответ оператора и переводит обращение в resolved-состояние."""

    sanitized = _ensure_utf8_text(reply_text)
    existing = session.exec(
        select(OperatorReply).where(OperatorReply.queue_id == queue_item.id)
    ).first()
    if existing is not None:
        raise ValueError("Queue item already has a reply")

    reply = OperatorReply(
        queue_id=queue_item.id,
        operator_id=operator_id,
        reply_text=sanitized,
    )
    session.add(reply)

    queue_item.status = "resolved"
    queue_item.updated_at = datetime.now(timezone.utc)
    session.add(queue_item)

    request = session.get(SupportRequest, queue_item.request_id)
    if request is not None:
        request.status = "operator_replied"
        session.add(request)

    session.commit()
    session.refresh(reply)
    session.refresh(queue_item)
    question = request.question if request is not None else ""
    return OperatorQueueEntry(
        queue_id=queue_item.id,
        request_id=queue_item.request_id,
        reason=queue_item.reason,
        status=queue_item.status,
        question=question,
        created_at=queue_item.created_at,
        reply_text=reply.reply_text,
        reply_created_at=reply.created_at,
    )


def list_my_queue(session: Session, user_id: uuid.UUID) -> list[MyQueueEntry]:
    """Возвращает пользовательские обращения, переданные оператору."""

    statement = (
        select(SupportRequest)
        .where(SupportRequest.user_id == user_id)
        .where(SupportRequest.escalated == True)  # noqa: E712
        .order_by(col(SupportRequest.created_at).desc())
    )
    requests = session.exec(statement).all()
    if not requests:
        return []
    request_ids = [request.id for request in requests]
    queue_items = session.exec(
        select(OperatorQueue).where(OperatorQueue.request_id.in_(request_ids))
    ).all()
    queue_map = {item.request_id: item for item in queue_items}
    queue_ids = [item.id for item in queue_items]
    replies = (
        session.exec(
            select(OperatorReply).where(OperatorReply.queue_id.in_(queue_ids))
        ).all()
        if queue_ids
        else []
    )
    reply_map = {reply.queue_id: reply for reply in replies}

    response: list[MyQueueEntry] = []
    for request in requests:
        queue_item = queue_map.get(request.id)
        if queue_item is None:
            continue
        reply = reply_map.get(queue_item.id)
        response.append(
            MyQueueEntry(
                queue_id=queue_item.id,
                request_id=request.id,
                question=request.question,
                reason=queue_item.reason,
                status=queue_item.status,
                created_at=queue_item.created_at,
                reply_text=reply.reply_text if reply else None,
                reply_created_at=reply.created_at if reply else None,
            )
        )
    return response


def get_support_metrics(session: Session) -> SupportMetricsPublic:
    """Рассчитывает агрегированные метрики работы службы поддержки."""

    requests = session.exec(select(SupportRequest)).all()
    total = len(requests)
    if total == 0:
        return SupportMetricsPublic()

    faq_count = sum(1 for item in requests if item.mode == "faq")
    rag_count = sum(1 for item in requests if item.mode == "rag")
    operator_count = sum(1 for item in requests if item.mode == "operator")
    average_confidence = sum(item.confidence for item in requests) / total

    answers = session.exec(select(SupportAnswer)).all()
    answer_count = len(answers)
    empty_sources_count = sum(
        1 for answer in answers if not answer.sources_json or len(answer.sources_json) == 0
    )
    empty_sources_share = (empty_sources_count / answer_count) if answer_count else 0.0

    return SupportMetricsPublic(
        total_requests=total,
        faq_share=_clamp_score(faq_count / total),
        rag_share=_clamp_score(rag_count / total),
        operator_share=_clamp_score(operator_count / total),
        average_confidence=_clamp_score(average_confidence),
        empty_sources_share=_clamp_score(empty_sources_share),
    )
