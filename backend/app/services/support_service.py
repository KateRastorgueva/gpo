"""Сервисный слой обработки обращений технической поддержки.

Модуль реализует маршрут обработки пользовательского вопроса по схеме
``FAQ -> RAG -> Operator``. В нем находятся функции поиска FAQ-ответов,
извлечения релевантных фрагментов базы знаний, генерации ответа через LLM,
эскалации обращения оператору и обслуживания административных сценариев.
"""

import hashlib
import math
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import and_, or_, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, col, delete, func, select

from app.core import event_log
from app.core.config import settings
from app.models import (
    ActiveRequest,
    ActiveRequestPublic,
    DecisionMetrics,
    DocTag,
    FaqEntryCreate,
    FaqEntryPublic,
    FaqEntryUpdate,
    JournalRequestPublic,
    KnowledgeArchive,
    KnowledgeArchivePublic,
    KnowledgeCategory,
    KnowledgeCategoryCreate,
    KnowledgeCategoryPublic,
    KnowledgeCategoryUpdate,
    KnowledgeChunk,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPublic,
    KnowledgeDocUpdate,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSource,
    KnowledgeSourcePublic,
    KnowledgeSourceUpdate,
    KnowledgeTag,
    MyQueueEntry,
    SourceAttribution,
    SupportAnswer,
    SupportAskRequest,
    SupportAskResponse,
    SupportFeedback,
    SupportFeedbackCreate,
    SupportFeedbackPublic,
    SupportHistoryEntry,
    SupportHistoryStep,
    SupportMetricsPublic,
    SupportRequest,
    SupportTicket,
    SupportTicketPublic,
    Tag,
    TagCreate,
    TagPublic,
    User,
)
from app.services import rag_providers
from app.services.app_config import live_settings

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

# FAQ — это записи базы знаний с этим типом источника (решение V1: FAQ = БЗ).
FAQ_SOURCE_TYPE = "faq"


class SupportConflictError(Exception):
    """Конфликт состояния: нарушение уникальности имени категории или тэга."""


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
    "иями",
    "ями",
    "ами",
    "ией",
    "иям",
    "иях",
    "его",
    "ому",
    "ими",
    "ыми",
    "ого",
    "ему",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ий",
    "ый",
    "ой",
    "ей",
    "ия",
    "ие",
    "ии",
    "ов",
    "ев",
    "ин",
    "ын",
    "ах",
    "ях",
    "ам",
    "ям",
    "ом",
    "ем",
    "ы",
    "и",
    "а",
    "я",
    "о",
    "е",
    "у",
    "ю",
    "ь",
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
        (2 * precision * recall) / (precision + recall)
        if (precision + recall)
        else 0.0,
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
        from sentence_transformers import (  # type: ignore[import-not-found]
            SentenceTransformer,
        )

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
        elif live_settings.GOOGLE_API_KEY and settings.GOOGLE_EMBEDDING_MODEL.strip():
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

    if not live_settings.GOOGLE_API_KEY:
        return None
    embedding_model = settings.GOOGLE_EMBEDDING_MODEL.strip()
    if not embedding_model:
        return None
    if not embedding_model.startswith("models/"):
        embedding_model = f"models/{embedding_model}"
    url = f"{live_settings.GOOGLE_API_URL}/{embedding_model}:embedContent"
    payload = {
        "model": embedding_model,
        "content": {"parts": [{"text": text}]},
    }
    headers = {"X-goog-api-key": live_settings.GOOGLE_API_KEY}
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
            response.json()
            .get("result", {})
            .get("config", {})
            .get("params", {})
            .get("vectors", {})
        )
        existing_size = (
            vectors_config.get("size") if isinstance(vectors_config, dict) else None
        )
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


# Поля payload, по которым фильтруем (D4). Индексы создаются один раз на коллекцию
# и нужны, чтобы фильтр не превращался в полный перебор.
PAYLOAD_INDEX_FIELDS = (
    "owner_type",
    "source_id",
    "doc_id",
    "category_id",
    "tag_ids",
)

OWNER_TYPE_SOURCE = "source"
OWNER_TYPE_DOC = "doc"


def ensure_qdrant_payload_indexes() -> None:
    """Идемпотентно создаёт payload-индексы для фильтров поиска."""
    index_path = f"/collections/{settings.QDRANT_COLLECTION_NAME}/index"
    for field_name in PAYLOAD_INDEX_FIELDS:
        _qdrant_request(
            "PUT",
            index_path,
            payload={"field_name": field_name, "field_schema": "keyword"},
            allowed_statuses={400, 404, 409},
        )


def build_qdrant_filter(
    *,
    owner_types: list[str] | None = None,
    category_ids: list[uuid.UUID] | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any] | None:
    """Собрать `filter` для Qdrant. None — фильтровать нечего."""
    must: list[dict[str, Any]] = []
    if owner_types:
        must.append({"key": "owner_type", "match": {"any": list(owner_types)}})
    if category_ids:
        must.append(
            {"key": "category_id", "match": {"any": [str(i) for i in category_ids]}}
        )
    if tag_ids:
        must.append({"key": "tag_ids", "match": {"any": [str(i) for i in tag_ids]}})
    return {"must": must} if must else None


def _owner_from_payload(
    payload: dict[str, Any],
) -> tuple[uuid.UUID, str, str | None] | None:
    """Определить владельца чанка по payload: источник БЗ или документ."""
    owner_type = str(payload.get("owner_type") or OWNER_TYPE_SOURCE)
    if owner_type == OWNER_TYPE_DOC:
        owner_id = _parse_uuid(payload.get("doc_id"))
        if owner_id is None:
            return None
        return (
            owner_id,
            str(payload.get("doc_title") or "Документ"),
            payload.get("doc_url"),
        )
    owner_id = _parse_uuid(payload.get("source_id"))
    if owner_id is None:
        return None
    return (
        owner_id,
        str(payload.get("source_title") or "Источник"),
        payload.get("source_ref"),
    )


def _lexical_owner_condition(owner_types: list[str] | None) -> ColumnElement[bool]:
    """Условие «чанк относится к активному источнику и/или к документу»."""
    active_source = and_(
        col(KnowledgeChunk.source_id).is_not(None),
        col(KnowledgeSource.is_active).is_(True),
    )
    doc_chunk = col(KnowledgeChunk.doc_id).is_not(None)
    if owner_types == [OWNER_TYPE_SOURCE]:
        return active_source
    if owner_types == [OWNER_TYPE_DOC]:
        return doc_chunk
    return or_(active_source, doc_chunk)


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
    """Удалить векторы, у которых нет живого владельца или чанка.

    Владельцем может быть источник БЗ (только активный) или документ: у чанков документов
    поля `source_id` нет, поэтому проверка идёт по `owner_type`.
    """
    points = _scroll_qdrant_points()
    if not points:
        return 0

    valid_source_ids = {
        str(source_id)
        for source_id in session.exec(
            select(KnowledgeSource.id).where(KnowledgeSource.is_active == True)  # noqa: E712
        ).all()
    }
    valid_doc_ids = {
        str(doc_id) for doc_id in session.exec(select(KnowledgeDoc.id)).all()
    }
    valid_chunk_ids = {
        str(chunk_id) for chunk_id in session.exec(select(KnowledgeChunk.id)).all()
    }

    orphan_ids: list[Any] = []
    for point in points:
        payload = point.get("payload") or {}
        owner_type = str(payload.get("owner_type") or OWNER_TYPE_SOURCE)
        if owner_type == OWNER_TYPE_DOC:
            owner_id = str(payload.get("doc_id") or "")
            owner_exists = bool(owner_id and owner_id in valid_doc_ids)
        else:
            owner_id = str(payload.get("source_id") or "")
            owner_exists = bool(owner_id and owner_id in valid_source_ids)
        chunk_id = str(payload.get("chunk_id") or "")
        chunk_exists = bool(chunk_id and chunk_id in valid_chunk_ids)
        if not owner_exists or not chunk_exists:
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


def find_faq_match(
    session: Session, question: str
) -> tuple[KnowledgeSource | None, float]:
    """FAQ-ступень маршрутизации: FAQ — это записи базы знаний с `source_type='faq'` (V1).

    `faq_similarity` нормализует обе строки сама, поэтому хранимый
    `normalized_question` из прежней таблицы `faqentry` не нужен.
    """
    faqs = session.exec(
        select(KnowledgeSource).where(
            KnowledgeSource.is_active == True,  # noqa: E712
            KnowledgeSource.source_type == FAQ_SOURCE_TYPE,
        )
    ).all()
    if not faqs:
        return None, 0.0
    best_score = 0.0
    best_faq: KnowledgeSource | None = None
    for faq in faqs:
        score = faq_similarity(question, faq.title)
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


def retrieve_semantic_chunks(
    question: str,
    limit: int | None = None,
    *,
    owner_types: list[str] | None = None,
    category_ids: list[uuid.UUID] | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> list[RetrievalResult]:
    """Векторный поиск.

    Фильтры (D4) уходят в Qdrant как `filter`, то есть отбор выполняется ДО top-k —
    recall не страдает от post-filtering.
    """
    final_limit = limit or settings.HYBRID_CANDIDATES_LIMIT
    query_vector = embed_text(question)
    ensure_qdrant_collection(len(query_vector))
    payload: dict[str, Any] = {
        "vector": query_vector,
        "limit": final_limit,
        "with_payload": True,
    }
    qdrant_filter = build_qdrant_filter(
        owner_types=owner_types, category_ids=category_ids, tag_ids=tag_ids
    ) or {"must": []}
    # Векторы другой модели эмбеддингов несопоставимы с текущим запросом (P0).
    qdrant_filter["must"].append(
        {"key": "embedding_model", "match": {"value": get_embedding_model_id()}}
    )
    payload["filter"] = qdrant_filter
    response = _qdrant_request(
        "POST",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/search",
        payload=payload,
        allowed_statuses={404},
    )
    if response.status_code == 404:
        return []
    points = response.json().get("result") or []
    results: list[RetrievalResult] = []
    for point in points:
        payload_data = point.get("payload") or {}
        owner = _owner_from_payload(payload_data)
        if owner is None:
            continue
        owner_id, owner_title, owner_ref = owner
        results.append(
            RetrievalResult(
                source_id=owner_id,
                source_title=owner_title,
                source_ref=owner_ref,
                chunk_id=_parse_uuid(payload_data.get("chunk_id")),
                snippet=str(payload_data.get("chunk_text") or ""),
                score=float(point.get("score") or 0.0),
            )
        )
    return results


def _lexical_rows(
    session: Session,
    *,
    owner_types: list[str] | None = None,
    category_ids: list[uuid.UUID] | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> list[tuple[KnowledgeChunk, uuid.UUID, str, str | None]]:
    """Чанки обоих корпусов (источники БЗ и документы) с фильтрами D4 и данными владельца."""
    statement = (
        select(KnowledgeChunk, KnowledgeSource, KnowledgeDoc)
        .outerjoin(
            KnowledgeSource, col(KnowledgeChunk.source_id) == col(KnowledgeSource.id)
        )
        .outerjoin(KnowledgeDoc, col(KnowledgeChunk.doc_id) == col(KnowledgeDoc.id))
        # Полный текст источника тут не нужен, а на больших PDF он съедает память.
        .options(defer(KnowledgeSource.content))  # type: ignore[arg-type]
    )
    statement = statement.where(_lexical_owner_condition(owner_types))
    if category_ids:
        statement = statement.where(
            col(KnowledgeSource.category_id).in_(list(category_ids))
        )
    if tag_ids:
        source_ids = session.exec(
            select(KnowledgeTag.knowledge_id).where(
                col(KnowledgeTag.tag_id).in_(list(tag_ids))
            )
        ).all()
        doc_ids = session.exec(
            select(DocTag.doc_id).where(col(DocTag.tag_id).in_(list(tag_ids)))
        ).all()
        statement = statement.where(
            or_(
                col(KnowledgeChunk.source_id).in_(list(source_ids)),
                col(KnowledgeChunk.doc_id).in_(list(doc_ids)),
            )
        )

    rows: list[tuple[KnowledgeChunk, uuid.UUID, str, str | None]] = []
    for chunk, source, doc in session.exec(statement).all():
        if source is not None:
            rows.append((chunk, source.id, source.title, source.source_ref))
        elif doc is not None:
            rows.append((chunk, doc.id, doc.title, doc.url))
    return rows


def retrieve_lexical_chunks(
    session: Session,
    question: str,
    *,
    owner_types: list[str] | None = None,
    category_ids: list[uuid.UUID] | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> list[RetrievalResult]:
    """Взвешенный лексический поиск (TF-IDF) по обоим корпусам."""
    rows = _lexical_rows(
        session, owner_types=owner_types, category_ids=category_ids, tag_ids=tag_ids
    )
    if not rows:
        return []

    idf = _compute_idf([chunk.content for chunk, *_owner in rows])
    query_vector = _tfidf_vector(question, idf)
    if not query_vector:
        return []

    lexical_results: list[RetrievalResult] = []
    for chunk, owner_id, owner_title, owner_ref in rows:
        chunk_score = _tfidf_cosine(query_vector, _tfidf_vector(chunk.content, idf))
        title_score = _tfidf_cosine(query_vector, _tfidf_vector(owner_title, idf))
        score = max(chunk_score, title_score)
        if score <= 0:
            continue
        lexical_results.append(
            RetrievalResult(
                source_id=owner_id,
                source_title=owner_title,
                source_ref=owner_ref,
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

        combined = (
            _clamp_score(weighted_sum / active_weight) if active_weight > 0 else 0.0
        )
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


def rerank_results(
    question: str, results: list[RetrievalResult]
) -> list[RetrievalResult]:
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
    return reranked[: live_settings.RETRIEVAL_TOP_K]


RAG_EXTRA_STOPWORDS = frozenset(
    "какой какая какие каких какого сколько можно нужно будет если есть быть где когда кто чей чем через время".split()
)
BM25_K1 = 1.4
BM25_B = 0.75
RRF_K = 60


def _bm25_tokens(value: str) -> list[str]:
    """Токены для BM25: без стоп-слов, со стеммингом."""

    return [
        russian_stem(token)
        for token in _token_set(value)
        if len(token) > 1
        and token not in FAQ_STOPWORDS
        and token not in RAG_EXTRA_STOPWORDS
    ]


def retrieve_lexical_bm25(
    session: Session,
    question: str,
    *,
    owner_types: list[str] | None = None,
    category_ids: list[uuid.UUID] | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> tuple[list[RetrievalResult], dict[uuid.UUID, float]]:
    """BM25 по всем активным чанкам.

    Возвращает кандидатов, отсортированных по BM25, и покрытие запроса для каждого
    чанка: долю idf-массы слов запроса, найденных в чанке (0..1). Слова, которых нет
    в корпусе, считаются максимально информативными и снижают покрытие.
    """

    rows = _lexical_rows(
        session, owner_types=owner_types, category_ids=category_ids, tag_ids=tag_ids
    )
    query_terms = set(_bm25_tokens(question))
    if not rows or not query_terms:
        return [], {}

    docs = [
        Counter(_bm25_tokens(f"{title} {chunk.content}"))
        for chunk, _id, title, _ref in rows
    ]
    total_docs = len(docs)
    avg_len = sum(sum(doc.values()) for doc in docs) / total_docs or 1.0
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        doc_freq.update(doc.keys())

    def idf(term: str) -> float:
        n = doc_freq.get(term, 0)
        return math.log(1 + (total_docs - n + 0.5) / (n + 0.5))

    unknown_idf = math.log(1 + total_docs)
    total_mass = (
        sum(idf(t) if doc_freq.get(t) else unknown_idf for t in query_terms) or 1.0
    )

    scored: list[
        tuple[float, float, tuple[KnowledgeChunk, uuid.UUID, str, str | None]]
    ] = []
    for row, doc in zip(rows, docs, strict=True):
        length = sum(doc.values())
        bm25 = 0.0
        matched_mass = 0.0
        for term in query_terms:
            freq = doc.get(term, 0)
            if not freq:
                continue
            weight = idf(term)
            matched_mass += weight
            bm25 += (
                weight
                * freq
                * (BM25_K1 + 1)
                / (freq + BM25_K1 * (1 - BM25_B + BM25_B * length / avg_len))
            )
        if bm25 > 0:
            scored.append((bm25, matched_mass / total_mass, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    coverage = {row[0].id: cov for _bm, cov, row in scored}
    results = [
        RetrievalResult(
            source_id=owner_id,
            source_title=owner_title,
            source_ref=owner_ref,
            chunk_id=chunk.id,
            snippet=chunk.content,
            score=_clamp_score(cov),
        )
        for _bm, cov, (chunk, owner_id, owner_title, owner_ref) in scored[
            : settings.HYBRID_CANDIDATES_LIMIT
        ]
    ]
    return results, coverage


def _rrf_merge(
    semantic_results: list[RetrievalResult],
    lexical_results: list[RetrievalResult],
    coverage: dict[uuid.UUID, float],
) -> list[RetrievalResult]:
    """Объединяет списки по рангам (RRF), не смешивая несопоставимые шкалы оценок.

    Порядок задаёт RRF. Оценка для маршрутизации: покрытие запроса чанком при hashed-эмбеддингах
    (их косинусы почти не различают тему), иначе прежняя взвешенная смесь.
    """

    rrf: dict[str, float] = {}
    items: dict[str, RetrievalResult] = {}
    for results in (semantic_results, lexical_results):
        for rank, item in enumerate(results):
            key = _result_key(item)
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
            items.setdefault(key, item)
    blended = {
        _result_key(i): i.score
        for i in _merge_hybrid_results(semantic_results, lexical_results)
    }
    hashed = get_embedding_backend() == "hashed"
    merged: list[RetrievalResult] = []
    for key in sorted(rrf, key=lambda k: rrf[k], reverse=True):
        base = items[key]
        score = (
            coverage.get(base.chunk_id, 0.0)
            if hashed and base.chunk_id
            else blended.get(key, base.score)
        )
        merged.append(
            RetrievalResult(
                source_id=base.source_id,
                source_title=base.source_title,
                source_ref=base.source_ref,
                chunk_id=base.chunk_id,
                snippet=base.snippet,
                score=_clamp_score(score),
            )
        )
    return merged[: live_settings.RETRIEVAL_TOP_K]


_NEGATION_WORDS = ("не", "нельзя", "нет")


def _has_negation(text: str) -> bool:
    """Проверяет наличие маркеров отрицания в тексте по токенам."""

    for token in _token_set(text):
        if token in _NEGATION_WORDS:
            return True
        if token.startswith(("запрещ", "отмен", "неверн", "отсутств")):
            return True
    return False


def retrieve_relevant_chunks(
    *,
    session: Session,
    question: str,
    owner_types: list[str] | None = None,
    category_ids: list[uuid.UUID] | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> list[RetrievalResult]:
    semantic = retrieve_semantic_chunks(
        question,
        owner_types=owner_types,
        category_ids=category_ids,
        tag_ids=tag_ids,
    )
    lexical, coverage = retrieve_lexical_bm25(
        session,
        question,
        owner_types=owner_types,
        category_ids=category_ids,
        tag_ids=tag_ids,
    )
    return _rrf_merge(semantic, lexical, coverage)


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

    api_key = live_settings.gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    url = f"{live_settings.GOOGLE_API_URL}/models/{live_settings.GOOGLE_MODEL}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"X-goog-api-key": api_key}
    with httpx.Client(timeout=live_settings.OLLAMA_TIMEOUT_SECONDS) as client:
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

    url = f"{live_settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": live_settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    with httpx.Client(timeout=live_settings.OLLAMA_TIMEOUT_SECONDS) as client:
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
    queue_item = SupportTicket(request_id=request_id, reason=reason, status="open")
    session.add(queue_item)


def _open_active_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    user_id: uuid.UUID | None,
    question: str,
    channel: str,
    queued_at: datetime,
) -> None:
    """Поставить запрос в горячую очередь.

    `request_journal` остаётся источником правды: здесь только рабочее множество очереди,
    поэтому строка не «переезжает», а добавляется и позже удаляется.
    """
    session.add(
        ActiveRequest(
            request_id=request_id,
            user_id=user_id,
            question=question,
            channel=channel,
            priority=0,
            queued_at=queued_at,
            updated_at=queued_at,
        )
    )


def close_active_request(session: Session, request_id: uuid.UUID) -> bool:
    """Убрать запрос из очереди (он остаётся в журнале). Возвращает True, если строка была."""
    active = session.get(ActiveRequest, request_id)
    if active is None:
        return False
    session.delete(active)
    return True


def _next_step_index(session: Session, request_id: uuid.UUID) -> int:
    """Номер шага обработки внутри запроса (0 — первый)."""
    current = session.exec(
        select(func.max(SupportAnswer.step_index)).where(
            col(SupportAnswer.request_id) == request_id
        )
    ).one()
    return 0 if current is None else int(current) + 1


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


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
    response_time_ms: int | None = None,
    provider: str | None = None,
    error: str | None = None,
) -> SupportAskResponse:
    """Сохраняет запрос, ответ, источники и при необходимости очередь оператора."""

    recorded_at = datetime.now(timezone.utc)
    request = SupportRequest(
        user_id=user_id,
        session_id=session_id,
        channel=payload.channel,
        question=payload.question,
        mode=mode,  # type: ignore[arg-type]
        confidence=confidence,
        fallback_used=fallback_used,
        escalated=escalated,
        # Эскалация оставляет запрос в очереди (queued), иначе он сразу отвечен.
        status="queued" if escalated else "answered",
        updated_at=recorded_at,
        answered_at=None if escalated else recorded_at,
    )
    session.add(request)
    session.flush()

    # Журнал: одна запись на шаг обработки (M6). Шаг совпадает с режимом,
    # автозапись не финальна при эскалации — запрос ещё ждёт оператора.
    # Ссылки на знание и чанк подтверждаем по БД: id из payload Qdrant может быть
    # устаревшим (осиротевший вектор), а FK-нарушение сорвало бы запись всего запроса.
    knowledge_id: uuid.UUID | None = None
    knowledge_chunk_id: uuid.UUID | None = None
    if sources:
        first_source = sources[0]
        if session.get(KnowledgeSource, first_source.source_id) is not None:
            knowledge_id = first_source.source_id
        if first_source.chunk_id is not None and (
            session.get(KnowledgeChunk, first_source.chunk_id) is not None
        ):
            knowledge_chunk_id = first_source.chunk_id

    answer = SupportAnswer(
        request_id=request.id,
        step=mode,
        step_index=_next_step_index(session, request.id),
        performed_by=None,
        knowledge_id=knowledge_id,
        knowledge_chunk_id=knowledge_chunk_id,
        answer=answer_text,
        sources_json=_serialize_sources(sources),
        is_final=not escalated,
        response_time_ms=response_time_ms,
    )
    session.add(answer)

    if escalated:
        _create_queue_item(
            session, request.id, escalation_reason or "insufficient-confidence"
        )
        _open_active_request(
            session,
            request_id=request.id,
            user_id=user_id,
            question=payload.question,
            channel=payload.channel,
            queued_at=recorded_at,
        )

    session.commit()
    event_log.log_event(
        "support.ask",
        request_id=str(request.id),
        user_id=str(user_id) if user_id else None,
        session_id=session_id,
        channel=payload.channel,
        question=payload.question if settings.EVENT_LOG_QUESTIONS else None,
        question_len=len(payload.question),
        mode=mode,
        provider="faq" if mode == "faq" else (provider or "legacy"),
        route_reason=route_reason,
        escalated=escalated,
        escalation_reason=escalation_reason,
        confidence=round(confidence, 4),
        fallback_used=fallback_used,
        response_time_ms=response_time_ms,
        answer_len=len(answer_text),
        sources=[item.source_title for item in sources[:5]],
        top_score=round(decision_metrics.top_score, 4),
        faq_score=round(decision_metrics.faq_score, 4),
        relevant_chunks=decision_metrics.relevant_chunks,
        critical=decision_metrics.critical,
        conflict=decision_metrics.conflict,
        error=error,
    )
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
        live_settings.RAG_TOP_SCORE_THRESHOLD,
        live_settings.RAG_RELEVANT_CHUNK_THRESHOLD,
        live_settings.RAG_MIN_RELEVANT_CHUNKS,
    )


def _run_external_rag(
    *,
    session: Session,
    user_id: uuid.UUID | None,
    payload: SupportAskRequest,
    session_id: str,
    faq_score: float,
    critical: bool,
    started: float,
    provider: str,
) -> SupportAskResponse:
    """Шаг RAG через внешний движок (Gemini File Search или AnythingLLM)."""

    def _record(**kwargs: Any) -> SupportAskResponse:
        return _record_support_result(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            response_time_ms=_elapsed_ms(started),
            provider=provider,
            **kwargs,
        )

    try:
        result = rag_providers.ask_provider(payload.question, provider)
    except Exception as exc:
        event_log.log_event(
            "rag.provider_error",
            provider=provider,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=_elapsed_ms(started),
        )
        return _record(
            error=f"{type(exc).__name__}: {exc}",
            mode="operator",
            confidence=0.0,
            fallback_used=False,
            escalated=True,
            answer_text="Поиск по базе знаний временно недоступен. Обращение передано оператору.",
            sources=[],
            escalation_reason="retrieval-failure",
            route_reason="retrieval_failure",
            decision_metrics=DecisionMetrics(
                top_score=0.0,
                relevant_chunks=0,
                faq_score=_clamp_score(faq_score),
                conflict=False,
                critical=critical,
            ),
        )

    sources = [
        SourceAttribution(
            source_id=item.source_id,
            source_title=item.title,
            source_ref=item.ref,
            chunk_id=None,
            snippet=item.snippet,
            score=item.score,
        )
        for item in result.sources[: live_settings.RETRIEVAL_TOP_K]
    ]
    confidence = _clamp_score(result.confidence)
    decision_metrics = DecisionMetrics(
        top_score=confidence,
        relevant_chunks=len(result.sources),
        faq_score=_clamp_score(faq_score),
        conflict=False,
        critical=critical,
    )

    if not result.grounded:
        return _record(
            mode="operator",
            confidence=confidence,
            fallback_used=False,
            escalated=True,
            answer_text="Автоматический ответ недоступен. Обращение передано оператору.",
            sources=sources,
            escalation_reason="insufficient-context",
            route_reason="insufficient_context",
            decision_metrics=decision_metrics,
        )

    if critical and confidence < live_settings.CRITICAL_CONFIDENCE_THRESHOLD:
        return _record(
            mode="operator",
            confidence=confidence,
            fallback_used=False,
            escalated=True,
            answer_text="Для этого вопроса требуется проверка оператором. Обращение передано.",
            sources=sources,
            escalation_reason="low-confidence-critical",
            route_reason="critical_low_confidence",
            decision_metrics=decision_metrics,
        )

    answer_text = result.answer
    if (
        not critical
        and live_settings.LOW_CONFIDENCE_MIN
        <= confidence
        <= live_settings.LOW_CONFIDENCE_MAX
    ):
        answer_text = (
            f"{answer_text}\n\nТребуется проверка актуальности по указанным источникам."
        )
    return _record(
        mode="rag",
        confidence=confidence,
        fallback_used=False,
        escalated=False,
        answer_text=answer_text,
        sources=sources,
        escalation_reason=None,
        route_reason="rag_answer",
        decision_metrics=decision_metrics,
    )


def run_support_pipeline(
    *, session: Session, user_id: uuid.UUID | None, payload: SupportAskRequest
) -> SupportAskResponse:
    """Выполняет полный pipeline обработки обращения: FAQ, RAG или Operator."""

    started = time.perf_counter()
    session_id = payload.session_id or str(uuid.uuid4())
    faq_match, faq_score = find_faq_match(session, payload.question)
    critical = is_critical_question(payload.question)

    if faq_match and faq_score >= live_settings.FAQ_SIMILARITY_THRESHOLD:
        faq_source = SourceAttribution(
            source_id=faq_match.id,
            source_title="FAQ",
            source_ref=f"faq:{faq_match.id}",
            chunk_id=None,
            snippet=faq_match.title,
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
            answer_text=faq_match.content,
            sources=[faq_source],
            escalation_reason=None,
            route_reason="faq_hit",
            decision_metrics=decision_metrics,
            response_time_ms=_elapsed_ms(started),
        )

    # Движок переключается админом на лету, поэтому читается на каждый запрос.
    provider = rag_providers.get_active_provider(session)
    if rag_providers.is_external_provider_enabled(provider):
        return _run_external_rag(
            session=session,
            user_id=user_id,
            payload=payload,
            session_id=session_id,
            faq_score=faq_score,
            critical=critical,
            started=started,
            provider=provider,
        )

    try:
        retrieved = retrieve_relevant_chunks(session=session, question=payload.question)
    except Exception as exc:
        event_log.log_event(
            "rag.retrieval_error",
            provider="legacy",
            error=f"{type(exc).__name__}: {exc}",
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
            mode="operator",
            confidence=0.0,
            fallback_used=False,
            escalated=True,
            answer_text="Поиск по базе знаний временно недоступен. Обращение передано оператору.",
            sources=[],
            escalation_reason="retrieval-failure",
            route_reason="retrieval_failure",
            decision_metrics=decision_metrics,
            response_time_ms=_elapsed_ms(started),
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
            response_time_ms=_elapsed_ms(started),
        )

    confidence = min(1.0, top_score)
    if critical and confidence < live_settings.CRITICAL_CONFIDENCE_THRESHOLD:
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
            response_time_ms=_elapsed_ms(started),
        )

    try:
        answer_text, fallback_used = generate_answer(payload.question, retrieved)
    except Exception as exc:
        event_log.log_event(
            "rag.llm_error", provider="legacy", error=f"{type(exc).__name__}: {exc}"
        )
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
            response_time_ms=_elapsed_ms(started),
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
            response_time_ms=_elapsed_ms(started),
        )

    if (
        not critical
        and live_settings.LOW_CONFIDENCE_MIN
        <= confidence
        <= live_settings.LOW_CONFIDENCE_MAX
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
        response_time_ms=_elapsed_ms(started),
    )


def _sources_from_json(items: list[dict[str, Any]] | None) -> list[SourceAttribution]:
    sources: list[SourceAttribution] = []
    for item in items or []:
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
    return sources


def list_support_history(
    *,
    session: Session,
    user_id: uuid.UUID,
    session_id: str | None = None,
    limit: int = 50,
) -> list[SupportHistoryEntry]:
    """Возвращает историю обращений пользователя вместе с ответами и источниками."""

    statement = select(SupportRequest).where(SupportRequest.user_id == user_id)
    if session_id:
        statement = statement.where(SupportRequest.session_id == session_id)
    statement = statement.order_by(col(SupportRequest.created_at).desc()).limit(limit)
    requests = session.exec(statement).all()
    if not requests:
        return []

    request_ids = [request.id for request in requests]
    entries = session.exec(
        select(SupportAnswer)
        .where(col(SupportAnswer.request_id).in_(request_ids))
        .order_by(col(SupportAnswer.step_index))
    ).all()
    steps_map: dict[uuid.UUID, list[SupportAnswer]] = {}
    for entry in entries:
        steps_map.setdefault(entry.request_id, []).append(entry)

    history: list[SupportHistoryEntry] = []
    for request in requests:
        request_entries = steps_map.get(request.id, [])
        # Поле `answer` сохраняет прежний контракт: это финальный шаг (или последний, если
        # финального ещё нет — например, запрос ждёт оператора).
        final_entry = next(
            (entry for entry in reversed(request_entries) if entry.is_final),
            request_entries[-1] if request_entries else None,
        )
        steps = [
            SupportHistoryStep(
                step=entry.step,
                step_index=entry.step_index,
                answer=entry.answer,
                is_final=entry.is_final,
                performed_by=entry.performed_by,
                knowledge_id=entry.knowledge_id,
                knowledge_chunk_id=entry.knowledge_chunk_id,
                response_time_ms=entry.response_time_ms,
                sources=_sources_from_json(entry.sources_json),
                created_at=entry.created_at,
            )
            for entry in request_entries
        ]
        history.append(
            SupportHistoryEntry(
                request_id=request.id,
                question=request.question,
                mode=request.mode,
                answer=final_entry.answer if final_entry else "",
                sources=_sources_from_json(
                    final_entry.sources_json if final_entry else None
                ),
                confidence=request.confidence,
                escalated=request.escalated,
                fallback_used=request.fallback_used,
                status=request.status,
                created_at=request.created_at,
                session_id=request.session_id,
                steps=steps,
            )
        )
    return history


def _to_faq_public(source: KnowledgeSource) -> FaqEntryPublic:
    """Фасад: запись базы знаний в форме прежней FAQ-сущности (title -> question, content -> answer)."""
    return FaqEntryPublic(
        id=source.id,
        question=source.title,
        answer=source.content,
        is_active=source.is_active,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def get_faq_entry(session: Session, faq_id: uuid.UUID) -> KnowledgeSource | None:
    """Найти FAQ-запись (запись БЗ с типом faq). Возвращает None, если это не FAQ."""
    source = session.get(KnowledgeSource, faq_id)
    if source is None or source.source_type != FAQ_SOURCE_TYPE:
        return None
    return source


def list_faq_entries(
    session: Session, *, skip: int = 0, limit: int = 100
) -> tuple[list[FaqEntryPublic], int]:
    count = session.exec(
        select(func.count())
        .select_from(KnowledgeSource)
        .where(KnowledgeSource.source_type == FAQ_SOURCE_TYPE)
    ).one()
    statement = (
        select(KnowledgeSource)
        .where(KnowledgeSource.source_type == FAQ_SOURCE_TYPE)
        .order_by(col(KnowledgeSource.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    rows = session.exec(statement).all()
    return [_to_faq_public(row) for row in rows], count


def create_faq_entry(session: Session, faq_in: FaqEntryCreate) -> FaqEntryPublic:
    source = KnowledgeSource(
        title=_ensure_utf8_text(faq_in.question),
        content=_ensure_utf8_text(faq_in.answer),
        source_type=FAQ_SOURCE_TYPE,
        source_ref=None,
        is_active=faq_in.is_active,
        status="pending",
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return _to_faq_public(source)


def update_faq_entry(
    session: Session, faq: KnowledgeSource, faq_in: FaqEntryUpdate
) -> FaqEntryPublic:
    data = faq_in.model_dump(exclude_unset=True)
    updates: dict[str, Any] = {}
    if data.get("question"):
        updates["title"] = _ensure_utf8_text(data["question"])
    if data.get("answer"):
        updates["content"] = _ensure_utf8_text(data["answer"])
    if data.get("is_active") is not None:
        updates["is_active"] = data["is_active"]
    updates["updated_at"] = datetime.now(timezone.utc)
    faq.sqlmodel_update(updates)
    session.add(faq)
    session.commit()
    session.refresh(faq)
    return _to_faq_public(faq)


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
    for tag in soup(
        ["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]
    ):
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
    return (
        value.encode("utf-8", errors="replace")
        .decode("utf-8", errors="replace")
        .strip()
    )


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
    raise ValueError(
        "Unsupported file type. Use pdf/txt/md/html or URL/manual content."
    )


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


def remove_doc_vectors(doc_id: uuid.UUID) -> None:
    _qdrant_request(
        "POST",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/delete",
        payload={
            "filter": {
                "must": [
                    {"key": "doc_id", "match": {"value": str(doc_id)}},
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


def _reindex_owner_chunks(
    session: Session,
    *,
    content: str,
    payload_base: dict[str, Any],
    make_chunk: Callable[[int, str, str], KnowledgeChunk],
    chunk_owner_condition: ColumnElement[bool],
    delete_vectors: Callable[[], None],
) -> int:
    """Общий путь индексации для обоих корпусов (источник БЗ и документ, решение D9)."""
    chunks = chunk_text(content)
    if not chunks:
        raise ValueError("Content is empty after processing")

    vectors = embed_texts(chunks)
    if not vectors:
        raise ValueError("Failed to create embeddings")
    ensure_qdrant_collection(len(vectors[0]))
    ensure_qdrant_payload_indexes()
    embedding_model = get_embedding_model_id()

    delete_vectors()
    session.exec(delete(KnowledgeChunk).where(chunk_owner_condition))
    session.flush()

    points: list[dict[str, Any]] = []
    new_chunks: list[KnowledgeChunk] = []
    for index, (chunk_text_value, vector) in enumerate(
        zip(chunks, vectors, strict=True)
    ):
        vector_id = uuid.uuid4().hex
        new_chunks.append(make_chunk(index, chunk_text_value, vector_id))
        points.append(
            {
                "id": vector_id,
                "vector": vector,
                "payload": {
                    **payload_base,
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
    return len(new_chunks)


def index_source(session: Session, source: KnowledgeSource) -> int:
    source.title = _ensure_utf8_text(source.title)
    source.content = _ensure_utf8_text(source.content)
    if source.source_ref:
        source.source_ref = _ensure_utf8_text(source.source_ref)

    count = _reindex_owner_chunks(
        session,
        content=source.content,
        payload_base={
            "owner_type": OWNER_TYPE_SOURCE,
            "source_id": str(source.id),
            "source_title": source.title,
            "source_ref": source.source_ref,
            "category_id": str(source.category_id) if source.category_id else None,
            "tag_ids": _source_tag_ids(session, source.id),
        },
        make_chunk=lambda index, text, vector_id: KnowledgeChunk(
            source_id=source.id,
            chunk_index=index,
            content=text,
            vector_id=vector_id,
        ),
        chunk_owner_condition=col(KnowledgeChunk.source_id) == source.id,
        delete_vectors=lambda: remove_source_vectors(source.id),
    )
    source.status = "indexed"
    source.last_indexed_at = datetime.now(timezone.utc)
    source.updated_at = datetime.now(timezone.utc)
    session.add(source)
    session.commit()
    return count


def index_doc(session: Session, doc: KnowledgeDoc) -> int:
    """Индексация документа: содержимое забирается по ссылке."""
    doc.title = _ensure_utf8_text(doc.title)
    doc.url = _ensure_utf8_text(doc.url)
    content = _extract_text_from_url(doc.url)

    count = _reindex_owner_chunks(
        session,
        content=content,
        payload_base={
            "owner_type": OWNER_TYPE_DOC,
            "doc_id": str(doc.id),
            "doc_title": doc.title,
            "doc_url": doc.url,
            "tag_ids": _doc_tag_ids(session, doc.id),
        },
        make_chunk=lambda index, text, vector_id: KnowledgeChunk(
            doc_id=doc.id,
            chunk_index=index,
            content=text,
            vector_id=vector_id,
        ),
        chunk_owner_condition=col(KnowledgeChunk.doc_id) == doc.id,
        delete_vectors=lambda: remove_doc_vectors(doc.id),
    )
    doc.status = "indexed"
    doc.last_indexed_at = datetime.now(timezone.utc)
    doc.updated_at = datetime.now(timezone.utc)
    session.add(doc)
    session.commit()
    return count


def reindex_knowledge(
    session: Session,
    *,
    source_ids: list[uuid.UUID] | None = None,
    doc_ids: list[uuid.UUID] | None = None,
    include_sources: bool = True,
    include_docs: bool = True,
    full_rebuild: bool = False,
    purge_orphans: bool = True,
) -> tuple[int, int, int]:
    """Переиндексация корпусов базы знаний.

    Возвращает `(источников, документов, удалённых сиротских векторов)`.
    `full_rebuild` пересоздаёт коллекцию Qdrant, поэтому требует переиндексации обоих корпусов:
    иначе векторы второго корпуса были бы потеряны.
    """
    if full_rebuild:
        if not (include_sources and include_docs):
            raise ValueError(
                "full_rebuild requires reindexing both corpora (sources and docs)"
            )
        source_ids = None
        doc_ids = None

    sources: list[KnowledgeSource] = []
    if include_sources:
        source_statement = select(KnowledgeSource).where(
            col(KnowledgeSource.is_active).is_(True)
        )
        if source_ids:
            source_statement = source_statement.where(
                col(KnowledgeSource.id).in_(source_ids)
            )
        sources = list(session.exec(source_statement).all())

    docs: list[KnowledgeDoc] = []
    if include_docs:
        doc_statement = select(KnowledgeDoc)
        if doc_ids:
            doc_statement = doc_statement.where(col(KnowledgeDoc.id).in_(doc_ids))
        docs = list(session.exec(doc_statement).all())

    if full_rebuild:
        reset_qdrant_collection()
        session.exec(delete(KnowledgeChunk))
        session.commit()

    source_count = 0
    for source in sources:
        try:
            index_source(session, source)
            source_count += 1
        except Exception:
            session.rollback()
            source_db = session.get(KnowledgeSource, source.id)
            if source_db:
                source_db.status = "failed"
                source_db.updated_at = datetime.now(timezone.utc)
                session.add(source_db)
                session.commit()

    doc_count = 0
    for doc in docs:
        try:
            index_doc(session, doc)
            doc_count += 1
        except Exception:
            session.rollback()
            doc_db = session.get(KnowledgeDoc, doc.id)
            if doc_db:
                doc_db.status = "failed"
                doc_db.updated_at = datetime.now(timezone.utc)
                session.add(doc_db)
                session.commit()

    orphan_vectors_removed = remove_orphan_vectors(session) if purge_orphans else 0
    return source_count, doc_count, orphan_vectors_removed


def _to_category_public(category: KnowledgeCategory) -> KnowledgeCategoryPublic:
    return KnowledgeCategoryPublic(
        id=category.id, name=category.name, created_at=category.created_at
    )


def _to_tag_public(tag: Tag) -> TagPublic:
    return TagPublic(id=tag.id, name=tag.name, created_at=tag.created_at)


def _normalize_tag_name(value: str) -> str:
    """Тэги приводятся к нижнему регистру: уникальность имени в БД регистрозависимая."""
    return _ensure_utf8_text(value).lower()


def list_categories(
    session: Session, *, skip: int = 0, limit: int = 100
) -> tuple[list[KnowledgeCategoryPublic], int]:
    total = session.exec(select(func.count()).select_from(KnowledgeCategory)).one()
    rows = session.exec(
        select(KnowledgeCategory)
        .order_by(col(KnowledgeCategory.name))
        .offset(skip)
        .limit(limit)
    ).all()
    return [_to_category_public(row) for row in rows], total


def create_category(
    session: Session, category_in: KnowledgeCategoryCreate
) -> KnowledgeCategoryPublic:
    name = _ensure_utf8_text(category_in.name)
    existing = session.exec(
        select(KnowledgeCategory).where(
            func.lower(KnowledgeCategory.name) == name.lower()
        )
    ).first()
    if existing is not None:
        raise SupportConflictError(f"Category {name!r} already exists")

    category = KnowledgeCategory(name=name)
    session.add(category)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SupportConflictError(f"Category {name!r} already exists") from exc
    session.refresh(category)
    return _to_category_public(category)


def get_category(session: Session, category_id: uuid.UUID) -> KnowledgeCategory | None:
    return session.get(KnowledgeCategory, category_id)


def update_category(
    session: Session, category: KnowledgeCategory, category_in: KnowledgeCategoryUpdate
) -> KnowledgeCategoryPublic:
    if category_in.name is not None:
        name = _ensure_utf8_text(category_in.name)
        existing = session.exec(
            select(KnowledgeCategory).where(
                func.lower(KnowledgeCategory.name) == name.lower(),
                KnowledgeCategory.id != category.id,
            )
        ).first()
        if existing is not None:
            raise SupportConflictError(f"Category {name!r} already exists")
        category.name = name
        session.add(category)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise SupportConflictError(f"Category {name!r} already exists") from exc
        session.refresh(category)
    return _to_category_public(category)


def delete_category(session: Session, category_id: uuid.UUID) -> bool:
    """Удалить категорию. Источники остаются: FK выставлен в ON DELETE SET NULL."""
    category = session.get(KnowledgeCategory, category_id)
    if category is None:
        return False
    session.exec(
        delete(KnowledgeCategory).where(col(KnowledgeCategory.id) == category_id)
    )
    session.commit()
    return True


def list_tags(
    session: Session, *, skip: int = 0, limit: int = 200
) -> tuple[list[TagPublic], int]:
    total = session.exec(select(func.count()).select_from(Tag)).one()
    rows = session.exec(
        select(Tag).order_by(col(Tag.name)).offset(skip).limit(limit)
    ).all()
    return [_to_tag_public(row) for row in rows], total


def create_tag(session: Session, tag_in: TagCreate) -> TagPublic:
    name = _normalize_tag_name(tag_in.name)
    if not name:
        raise ValueError("Tag name must not be empty")

    tag = Tag(name=name)
    session.add(tag)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SupportConflictError(f"Tag {name!r} already exists") from exc
    session.refresh(tag)
    return _to_tag_public(tag)


def delete_tag(session: Session, tag_id: uuid.UUID) -> bool:
    tag = session.get(Tag, tag_id)
    if tag is None:
        return False
    session.exec(delete(Tag).where(col(Tag.id) == tag_id))
    session.commit()
    return True


def list_source_tags(
    session: Session, source_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Тэги для набора источников одним запросом (без N+1)."""
    if not source_ids:
        return {}
    rows = session.exec(
        select(KnowledgeTag.knowledge_id, Tag.name)
        .join(Tag, col(KnowledgeTag.tag_id) == col(Tag.id))
        .where(col(KnowledgeTag.knowledge_id).in_(source_ids))
        .order_by(col(Tag.name))
    ).all()
    result: dict[uuid.UUID, list[str]] = {}
    for knowledge_id, name in rows:
        result.setdefault(knowledge_id, []).append(name)
    return result


def list_doc_tags(
    session: Session, doc_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Тэги документов одним запросом (без N+1)."""
    if not doc_ids:
        return {}
    rows = session.exec(
        select(DocTag.doc_id, Tag.name)
        .join(Tag, col(DocTag.tag_id) == col(Tag.id))
        .where(col(DocTag.doc_id).in_(doc_ids))
        .order_by(col(Tag.name))
    ).all()
    result: dict[uuid.UUID, list[str]] = {}
    for doc_id, name in rows:
        result.setdefault(doc_id, []).append(name)
    return result


def _source_tag_ids(session: Session, source_id: uuid.UUID) -> list[str]:
    rows = session.exec(
        select(KnowledgeTag.tag_id).where(col(KnowledgeTag.knowledge_id) == source_id)
    ).all()
    return [str(tag_id) for tag_id in rows]


def _doc_tag_ids(session: Session, doc_id: uuid.UUID) -> list[str]:
    rows = session.exec(select(DocTag.tag_id).where(col(DocTag.doc_id) == doc_id)).all()
    return [str(tag_id) for tag_id in rows]


def _replace_tags(
    session: Session,
    *,
    names: list[str],
    delete_links: Callable[[], Any],
    make_link: Callable[[uuid.UUID], Any],
) -> None:
    """Общая замена набора тэгов для источника и документа."""
    delete_links()
    seen: set[str] = set()
    for raw in names:
        name = _normalize_tag_name(raw)
        if not name or name in seen:
            continue
        seen.add(name)
        tag = session.exec(select(Tag).where(Tag.name == name)).first()
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        session.add(make_link(tag.id))


def _replace_source_tags(
    session: Session, source: KnowledgeSource, names: list[str]
) -> None:
    _replace_tags(
        session,
        names=names,
        delete_links=lambda: session.exec(
            delete(KnowledgeTag).where(col(KnowledgeTag.knowledge_id) == source.id)
        ),
        make_link=lambda tag_id: KnowledgeTag(knowledge_id=source.id, tag_id=tag_id),
    )


def _replace_doc_tags(session: Session, doc: KnowledgeDoc, names: list[str]) -> None:
    _replace_tags(
        session,
        names=names,
        delete_links=lambda: session.exec(
            delete(DocTag).where(col(DocTag.doc_id) == doc.id)
        ),
        make_link=lambda tag_id: DocTag(doc_id=doc.id, tag_id=tag_id),
    )


def _to_source_public(
    source: KnowledgeSource, *, category_name: str | None, tags: list[str]
) -> KnowledgeSourcePublic:
    return KnowledgeSourcePublic(
        id=source.id,
        title=source.title,
        source_type=source.source_type,
        source_ref=source.source_ref,
        is_active=source.is_active,
        status=source.status,
        category_id=source.category_id,
        category_name=category_name,
        tags=tags,
        last_indexed_at=source.last_indexed_at,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _category_names(
    session: Session, sources: list[KnowledgeSource]
) -> dict[uuid.UUID, str]:
    ids = {source.category_id for source in sources if source.category_id}
    if not ids:
        return {}
    rows = session.exec(
        select(KnowledgeCategory).where(col(KnowledgeCategory.id).in_(list(ids)))
    ).all()
    return {row.id: row.name for row in rows}


def get_source_public(
    session: Session, source: KnowledgeSource
) -> KnowledgeSourcePublic:
    tags = list_source_tags(session, [source.id]).get(source.id, [])
    category_name = None
    if source.category_id:
        category = session.get(KnowledgeCategory, source.category_id)
        category_name = category.name if category else None
    return _to_source_public(source, category_name=category_name, tags=tags)


def list_sources(
    session: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    source_type: str | None = None,
    exclude_type: str | None = None,
) -> tuple[list[KnowledgeSourcePublic], int]:
    conditions: list[ColumnElement[bool]] = []
    if search and search.strip():
        conditions.append(col(KnowledgeSource.title).ilike(f"%{search.strip()}%"))
    if source_type:
        conditions.append(col(KnowledgeSource.source_type) == source_type)
    if exclude_type:
        conditions.append(col(KnowledgeSource.source_type) != exclude_type)
    where = and_(true(), *conditions)
    total = session.exec(
        select(func.count()).select_from(KnowledgeSource).where(where)
    ).one()
    rows = session.exec(
        select(KnowledgeSource)
        .where(where)
        # Полный текст для списка не нужен, а на больших PDF это мегабайты.
        .options(defer(KnowledgeSource.content))  # type: ignore[arg-type]
        .order_by(col(KnowledgeSource.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    tags_map = list_source_tags(session, [row.id for row in rows])
    names = _category_names(session, list(rows))
    data = [
        _to_source_public(
            row,
            category_name=names.get(row.category_id) if row.category_id else None,
            tags=tags_map.get(row.id, []),
        )
        for row in rows
    ]
    return data, total


def _to_archive_public(archive: KnowledgeArchive) -> KnowledgeArchivePublic:
    return KnowledgeArchivePublic(
        id=archive.id,
        knowledge_id=archive.knowledge_id,
        version=archive.version,
        title=archive.title,
        content=archive.content,
        category_id=archive.category_id,
        tags=list(archive.tags_json or []),
        source_type=archive.source_type,
        archived_at=archive.archived_at,
        archived_by=archive.archived_by,
    )


def _next_archive_version(session: Session, knowledge_id: uuid.UUID) -> int:
    current = session.exec(
        select(func.max(KnowledgeArchive.version)).where(
            col(KnowledgeArchive.knowledge_id) == knowledge_id
        )
    ).one()
    return int(current or 0) + 1


def _prune_archive(session: Session, knowledge_id: uuid.UUID) -> int:
    """Ретенция: оставляем только последние N версий (риск R4 плана)."""
    keep = max(1, settings.KNOWLEDGE_ARCHIVE_MAX_VERSIONS)
    versions = session.exec(
        select(KnowledgeArchive.id)
        .where(col(KnowledgeArchive.knowledge_id) == knowledge_id)
        .order_by(col(KnowledgeArchive.version).desc())
    ).all()
    stale = list(versions)[keep:]
    if stale:
        session.exec(
            delete(KnowledgeArchive).where(col(KnowledgeArchive.id).in_(stale))
        )
    return len(stale)


def archive_knowledge(
    session: Session,
    source: KnowledgeSource,
    *,
    archived_by: uuid.UUID | None = None,
) -> KnowledgeArchive:
    """Сохранить снапшот ТЕКУЩЕГО состояния знания (вызывается перед изменением)."""
    archive = KnowledgeArchive(
        knowledge_id=source.id,
        version=_next_archive_version(session, source.id),
        title=source.title,
        content=source.content,
        category_id=source.category_id,
        tags_json=list_source_tags(session, [source.id]).get(source.id, []),
        source_type=source.source_type,
        archived_at=datetime.now(timezone.utc),
        archived_by=archived_by,
    )
    session.add(archive)
    session.flush()
    _prune_archive(session, source.id)
    return archive


def list_knowledge_archive(
    session: Session, knowledge_id: uuid.UUID
) -> tuple[list[KnowledgeArchivePublic], int]:
    """История версий знания, свежие сверху."""
    rows = session.exec(
        select(KnowledgeArchive)
        .where(col(KnowledgeArchive.knowledge_id) == knowledge_id)
        .order_by(col(KnowledgeArchive.version).desc())
    ).all()
    return [_to_archive_public(row) for row in rows], len(rows)


def deactivate_source(
    session: Session,
    source: KnowledgeSource,
    *,
    archived_by: uuid.UUID | None = None,
) -> KnowledgeSourcePublic:
    """Мягкое удаление: снапшот в архив + `is_active=False`, строка источника сохраняется.

    В отличие от жёсткого удаления (которое по решению V6 уничтожает и архив), здесь история
    остаётся, а источник пропадает из поиска.
    """
    archive_knowledge(session, source, archived_by=archived_by)
    source.is_active = False
    source.status = "deleted"
    source.updated_at = datetime.now(timezone.utc)
    session.add(source)
    session.commit()
    session.refresh(source)
    return get_source_public(session, source)


def update_source_metadata(
    session: Session,
    source: KnowledgeSource,
    source_in: KnowledgeSourceUpdate,
    *,
    archived_by: uuid.UUID | None = None,
) -> KnowledgeSourcePublic:
    """Обновить метаданные источника: заголовок, категорию, активность и набор тэгов.

    Перед изменением сохраняется снапшот предыдущей версии (D5).
    """
    data = source_in.model_dump(exclude_unset=True)
    archive_knowledge(session, source, archived_by=archived_by)

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if data.get("title"):
        updates["title"] = _ensure_utf8_text(data["title"])
    if data.get("is_active") is not None:
        updates["is_active"] = data["is_active"]
    if "category_id" in data:
        category_id = data["category_id"]
        if (
            category_id is not None
            and session.get(KnowledgeCategory, category_id) is None
        ):
            raise ValueError("Knowledge category not found")
        updates["category_id"] = category_id
    source.sqlmodel_update(updates)

    if data.get("tags") is not None:
        _replace_source_tags(session, source, data["tags"])

    session.add(source)
    session.commit()
    session.refresh(source)
    return get_source_public(session, source)


def _to_doc_public(doc: KnowledgeDoc, *, tags: list[str]) -> KnowledgeDocPublic:
    return KnowledgeDocPublic(
        id=doc.id,
        title=doc.title,
        url=doc.url,
        status=doc.status,
        tags=tags,
        last_indexed_at=doc.last_indexed_at,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def get_doc(session: Session, doc_id: uuid.UUID) -> KnowledgeDoc | None:
    return session.get(KnowledgeDoc, doc_id)


def get_doc_public(session: Session, doc: KnowledgeDoc) -> KnowledgeDocPublic:
    return _to_doc_public(doc, tags=list_doc_tags(session, [doc.id]).get(doc.id, []))


def list_docs(
    session: Session, *, skip: int = 0, limit: int = 100
) -> tuple[list[KnowledgeDocPublic], int]:
    total = session.exec(select(func.count()).select_from(KnowledgeDoc)).one()
    rows = session.exec(
        select(KnowledgeDoc)
        .order_by(col(KnowledgeDoc.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    tags_map = list_doc_tags(session, [row.id for row in rows])
    return [_to_doc_public(row, tags=tags_map.get(row.id, [])) for row in rows], total


def create_doc(session: Session, doc_in: KnowledgeDocCreate) -> KnowledgeDoc:
    doc = KnowledgeDoc(
        title=_ensure_utf8_text(doc_in.title),
        url=_ensure_utf8_text(doc_in.url),
        status="pending",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    if doc_in.tags:
        _replace_doc_tags(session, doc, doc_in.tags)
        session.commit()
        session.refresh(doc)
    return doc


def update_doc_metadata(
    session: Session, doc: KnowledgeDoc, doc_in: KnowledgeDocUpdate
) -> KnowledgeDocPublic:
    data = doc_in.model_dump(exclude_unset=True)
    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if data.get("title"):
        updates["title"] = _ensure_utf8_text(data["title"])
    if data.get("url"):
        updates["url"] = _ensure_utf8_text(data["url"])
    doc.sqlmodel_update(updates)

    if data.get("tags") is not None:
        _replace_doc_tags(session, doc, data["tags"])

    session.add(doc)
    session.commit()
    session.refresh(doc)
    return get_doc_public(session, doc)


def delete_doc(session: Session, doc_id: uuid.UUID) -> bool:
    doc = session.get(KnowledgeDoc, doc_id)
    if doc is None:
        return False
    try:
        remove_doc_vectors(doc_id)
    except Exception:
        # Документ мог не индексироваться: удаление не должно блокироваться.
        pass
    session.exec(delete(KnowledgeDoc).where(col(KnowledgeDoc.id) == doc_id))
    session.commit()
    return True


def search_knowledge(
    session: Session, payload: KnowledgeSearchRequest
) -> list[KnowledgeSearchHit]:
    """Поиск по базе знаний с фильтрами (проверка D4 в админке)."""
    results = retrieve_relevant_chunks(
        session=session,
        question=payload.question,
        owner_types=list(payload.owner_types) if payload.owner_types else None,
        category_ids=payload.category_ids,
        tag_ids=payload.tag_ids,
    )
    return [
        KnowledgeSearchHit(
            source_id=item.source_id,
            source_title=item.source_title,
            source_ref=item.source_ref,
            chunk_id=item.chunk_id,
            snippet=item.snippet,
            score=item.score,
        )
        for item in results[: payload.limit]
    ]


def _to_ticket_public(ticket: SupportTicket, question: str) -> SupportTicketPublic:
    return SupportTicketPublic(
        ticket_id=ticket.id,
        request_id=ticket.request_id,
        reason=ticket.reason,
        status=ticket.status,
        question=question,
        assigned_to=ticket.assigned_to,
        resolution=ticket.resolution,
        reopened_from_id=ticket.reopened_from_id,
        created_at=ticket.created_at,
        resolved_at=ticket.resolved_at,
    )


def get_ticket(session: Session, ticket_id: uuid.UUID) -> SupportTicket | None:
    return session.get(SupportTicket, ticket_id)


def _request_for_ticket(session: Session, ticket: SupportTicket) -> SupportRequest:
    request = session.get(SupportRequest, ticket.request_id)
    if request is None:
        raise SupportConflictError("Request for this ticket no longer exists")
    return request


def _has_active_ticket(session: Session, request_id: uuid.UUID) -> bool:
    active = session.exec(
        select(SupportTicket).where(
            col(SupportTicket.request_id) == request_id,
            col(SupportTicket.status).in_(["open", "in_progress"]),
        )
    ).first()
    return active is not None


def assign_ticket(
    session: Session,
    ticket: SupportTicket,
    *,
    assigned_to: uuid.UUID | None,
) -> SupportTicketPublic:
    """Назначить агента и перевести открытый тикет в работу."""
    if ticket.status not in ("open", "in_progress"):
        raise SupportConflictError("Only an open ticket can be assigned")
    if assigned_to is not None and session.get(User, assigned_to) is None:
        raise ValueError("Assigned user not found")

    ticket.assigned_to = assigned_to
    if assigned_to is not None and ticket.status == "open":
        ticket.status = "in_progress"
    ticket.updated_at = datetime.now(timezone.utc)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return _to_ticket_public(ticket, _request_for_ticket(session, ticket).question)


def resolve_ticket(
    session: Session,
    ticket: SupportTicket,
    *,
    resolution: str,
    actor_id: uuid.UUID | None,
) -> SupportTicketPublic:
    """Ответ оператора: итоговое решение, запись в журнал как шаг `human`, запрос отвечен."""
    if ticket.status not in ("open", "in_progress"):
        raise SupportConflictError("Only an open or in-progress ticket can be resolved")

    request = _request_for_ticket(session, ticket)
    now = datetime.now(timezone.utc)

    ticket.resolution = _ensure_utf8_text(resolution)
    ticket.status = "resolved"
    ticket.resolved_at = now
    ticket.updated_at = now
    if ticket.assigned_to is None:
        ticket.assigned_to = actor_id
    session.add(ticket)

    session.add(
        SupportAnswer(
            request_id=request.id,
            step="human",
            step_index=_next_step_index(session, request.id),
            performed_by=actor_id,
            answer=ticket.resolution,
            sources_json=[],
            is_final=True,
        )
    )

    request.status = "answered"
    request.answered_at = request.answered_at or now
    request.updated_at = now
    session.add(request)
    # Запрос больше не висит в очереди: выход из горячей таблицы = DELETE
    close_active_request(session, request.id)

    session.commit()
    session.refresh(ticket)
    return _to_ticket_public(ticket, request.question)


def reopen_ticket(
    session: Session,
    ticket: SupportTicket,
    *,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> SupportTicketPublic:
    """Переоткрытие: создаётся НОВЫЙ тикет со ссылкой на прежний, запрос возвращается в очередь."""
    if ticket.status not in ("resolved", "closed"):
        raise SupportConflictError("Only a resolved ticket can be reopened")

    request = _request_for_ticket(session, ticket)
    if _has_active_ticket(session, request.id):
        raise SupportConflictError("This request already has an active ticket")

    now = datetime.now(timezone.utc)
    new_ticket = SupportTicket(
        request_id=request.id,
        reason=_ensure_utf8_text(reason) if reason else f"Переоткрыт: {ticket.reason}",
        status="open",
        assigned_to=actor_id,
        reopened_from_id=ticket.id,
        updated_at=now,
    )
    session.add(new_ticket)
    session.flush()

    request.status = "queued"
    request.answered_at = None
    request.updated_at = now
    session.add(request)

    if session.get(ActiveRequest, request.id) is None:
        _open_active_request(
            session,
            request_id=request.id,
            user_id=request.user_id,
            question=request.question,
            channel=request.channel,
            queued_at=now,
        )

    session.commit()
    session.refresh(new_ticket)
    return _to_ticket_public(new_ticket, request.question)


def create_feedback(
    session: Session, *, user_id: uuid.UUID | None, payload: SupportFeedbackCreate
) -> SupportFeedbackPublic:
    """Отзыв пользователя на свой запрос: один на запрос (V7)."""
    request = session.get(SupportRequest, payload.request_id)
    # Чужие запросы не раскрываем: отвечаем так же, как на несуществующий
    if request is None or (request.user_id is not None and request.user_id != user_id):
        raise ValueError("Request not found")

    existing = session.exec(
        select(SupportFeedback).where(
            col(SupportFeedback.request_id) == payload.request_id
        )
    ).first()
    if existing is not None:
        raise SupportConflictError("Feedback for this request already exists")

    feedback = SupportFeedback(
        request_id=payload.request_id,
        user_id=user_id,
        rating=payload.rating,
        comment=_ensure_utf8_text(payload.comment) if payload.comment else None,
    )
    session.add(feedback)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SupportConflictError("Feedback for this request already exists") from exc
    session.refresh(feedback)
    return SupportFeedbackPublic(
        id=feedback.id,
        request_id=feedback.request_id,
        user_id=feedback.user_id,
        rating=feedback.rating,
        comment=feedback.comment,
        submitted_at=feedback.submitted_at,
    )


def list_operator_queue(session: Session) -> list[SupportTicketPublic]:
    tickets = session.exec(
        select(SupportTicket).order_by(col(SupportTicket.created_at).desc())
    ).all()
    if not tickets:
        return []
    request_ids = [ticket.request_id for ticket in tickets]
    requests = session.exec(
        select(SupportRequest).where(col(SupportRequest.id).in_(request_ids))
    ).all()
    request_map = {request.id: request for request in requests}
    response: list[SupportTicketPublic] = []
    for ticket in tickets:
        request = request_map.get(ticket.request_id)
        if not request:
            continue
        response.append(_to_ticket_public(ticket, request.question))
    return response


def list_my_queue(session: Session, user_id: uuid.UUID) -> list[MyQueueEntry]:
    """Обращения пользователя, переданные оператору: последний тикет и решение по нему."""

    requests = session.exec(
        select(SupportRequest)
        .where(SupportRequest.user_id == user_id)
        .where(SupportRequest.escalated == True)  # noqa: E712
        .order_by(col(SupportRequest.created_at).desc())
    ).all()
    if not requests:
        return []
    request_ids = [request.id for request in requests]
    tickets = session.exec(
        select(SupportTicket)
        .where(col(SupportTicket.request_id).in_(request_ids))
        .order_by(col(SupportTicket.created_at))
    ).all()
    # После переоткрытия у запроса несколько тикетов: актуален последний
    ticket_map = {ticket.request_id: ticket for ticket in tickets}

    response: list[MyQueueEntry] = []
    for request in requests:
        ticket = ticket_map.get(request.id)
        if ticket is None:
            continue
        response.append(
            MyQueueEntry(
                queue_id=ticket.id,
                request_id=request.id,
                question=request.question,
                reason=ticket.reason,
                status=ticket.status,
                created_at=ticket.created_at,
                reply_text=ticket.resolution,
                reply_created_at=ticket.resolved_at,
            )
        )
    return response


def list_active_requests(
    session: Session, *, skip: int = 0, limit: int = 100
) -> tuple[list[ActiveRequestPublic], int]:
    """Очередь: читается из горячей `active_request`, без join к растущему журналу."""
    total = session.exec(select(func.count()).select_from(ActiveRequest)).one()
    statement = (
        select(ActiveRequest)
        .order_by(col(ActiveRequest.priority), col(ActiveRequest.queued_at))
        .offset(skip)
        .limit(limit)
    )
    rows = session.exec(statement).all()
    data = [
        ActiveRequestPublic(
            request_id=row.request_id,
            user_id=row.user_id,
            question=row.question,
            channel=row.channel,
            priority=row.priority,
            assigned_to=row.assigned_to,
            queued_at=row.queued_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return data, total


def list_journal_requests(
    session: Session,
    *,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[JournalRequestPublic], int]:
    """Журнал: все запросы (это источник правды), свежие сверху."""
    count_statement = select(func.count()).select_from(SupportRequest)
    statement = select(SupportRequest)
    if status:
        count_statement = count_statement.where(SupportRequest.status == status)
        statement = statement.where(SupportRequest.status == status)

    total = session.exec(count_statement).one()
    rows = session.exec(
        statement.order_by(col(SupportRequest.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    data = [
        JournalRequestPublic(
            request_id=row.id,
            user_id=row.user_id,
            question=row.question,
            channel=row.channel,
            mode=row.mode,
            status=row.status,
            confidence=row.confidence,
            escalated=row.escalated,
            created_at=row.created_at,
            answered_at=row.answered_at,
            closed_at=row.closed_at,
        )
        for row in rows
    ]
    return data, total


def get_support_metrics(session: Session) -> SupportMetricsPublic:
    """Рассчитывает агрегированные метрики работы службы поддержки."""

    requests = session.exec(select(SupportRequest)).all()
    total = len(requests)

    feedback_rows = session.exec(select(SupportFeedback)).all()
    feedback_count = len(feedback_rows)
    average_rating = (
        sum(row.rating for row in feedback_rows) / feedback_count
        if feedback_count
        else 0.0
    )

    if total == 0:
        return SupportMetricsPublic(
            feedback_count=feedback_count,
            average_rating=round(average_rating, 2),
        )

    faq_count = sum(1 for item in requests if item.mode == "faq")
    rag_count = sum(1 for item in requests if item.mode == "rag")
    operator_count = sum(1 for item in requests if item.mode == "operator")
    average_confidence = sum(item.confidence for item in requests) / total

    answers = session.exec(select(SupportAnswer)).all()
    answer_count = len(answers)
    empty_sources_count = sum(
        1
        for answer in answers
        if not answer.sources_json or len(answer.sources_json) == 0
    )
    empty_sources_share = (empty_sources_count / answer_count) if answer_count else 0.0

    return SupportMetricsPublic(
        total_requests=total,
        faq_share=_clamp_score(faq_count / total),
        rag_share=_clamp_score(rag_count / total),
        operator_share=_clamp_score(operator_count / total),
        average_confidence=_clamp_score(average_confidence),
        empty_sources_share=_clamp_score(empty_sources_share),
        feedback_count=feedback_count,
        average_rating=round(average_rating, 2),
    )
