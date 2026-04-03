import hashlib
import re
import uuid
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
    OperatorQueue,
    OperatorQueueEntry,
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


@dataclass
class RetrievalResult:
    source_id: uuid.UUID
    source_title: str
    source_ref: str | None
    chunk_id: uuid.UUID | None
    snippet: str
    score: float


def normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^\w\sа-яА-ЯёЁ-]", "", lowered)
    return lowered.strip()


def _token_set(value: str) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()
    return {token for token in normalized.split(" ") if token}


def _canonical_faq_token(token: str) -> str:
    return FAQ_KEYWORD_SYNONYMS.get(token, token)


def _faq_keyword_set(value: str) -> set[str]:
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


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def is_critical_question(question: str) -> bool:
    normalized = normalize_text(question)
    return any(keyword in normalized for keyword in CRITICAL_KEYWORDS)


def _get_sentence_transformer() -> Any | None:
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return _embedding_model
    except Exception:
        return None


def _hashed_embedding(text: str, size: int = 384) -> list[float]:
    text_bytes = text.encode("utf-8", errors="ignore")
    digest = hashlib.sha256(text_bytes).digest()
    output: list[float] = []
    idx = 0
    while len(output) < size:
        byte_val = digest[idx % len(digest)]
        output.append((byte_val / 127.5) - 1.0)
        idx += 1
    return output


def _resize_vector(vector: list[float], size: int) -> list[float]:
    if len(vector) == size:
        return vector
    if len(vector) > size:
        return vector[:size]
    return vector + ([0.0] * (size - len(vector)))


def _embed_with_google(text: str) -> list[float] | None:
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
    model = _get_sentence_transformer()
    if model is not None:
        vector = model.encode(text)  # type: ignore[no-untyped-call]
        return _resize_vector([float(v) for v in vector], settings.EMBEDDING_DIM)
    google_vector = _embed_with_google(text)
    if google_vector is not None:
        return _resize_vector(google_vector, settings.EMBEDDING_DIM)
    return _resize_vector(_hashed_embedding(text), settings.EMBEDDING_DIM)


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    model = _get_sentence_transformer()
    text_list = list(texts)
    if model is not None and text_list:
        vectors = model.encode(text_list)  # type: ignore[no-untyped-call]
        return [[float(v) for v in vector] for vector in vectors]
    return [embed_text(text) for text in text_list]


def _qdrant_base_url() -> str:
    host = settings.QDRANT_HOST.strip()
    if host.startswith(("http://", "https://")):
        parsed = urlparse(host)
        if parsed.port is not None:
            return host.rstrip("/")
        return f"{host.rstrip('/')}:{settings.QDRANT_PORT}"
    return f"http://{host}:{settings.QDRANT_PORT}"


def _qdrant_headers() -> dict[str, str]:
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
    collection_path = f"/collections/{settings.QDRANT_COLLECTION_NAME}"
    response = _qdrant_request("GET", collection_path, allowed_statuses={404})
    if response.status_code != 404:
        return
    _qdrant_request(
        "PUT",
        collection_path,
        payload={"vectors": {"size": vector_size, "distance": "Cosine"}},
    )


def reset_qdrant_collection() -> None:
    collection_path = f"/collections/{settings.QDRANT_COLLECTION_NAME}"
    _qdrant_request("DELETE", collection_path, allowed_statuses={404})


def _scroll_qdrant_points(limit: int = 256) -> list[dict[str, Any]]:
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
    if not point_ids:
        return
    _qdrant_request(
        "POST",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points/delete",
        payload={"points": point_ids},
        allowed_statuses={404},
    )


def remove_orphan_vectors(session: Session) -> int:
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
    try:
        if value is None:
            return None
        return uuid.UUID(str(value))
    except Exception:
        return None


def _to_source_attributions(results: list[RetrievalResult]) -> list[SourceAttribution]:
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
    statement = (
        select(KnowledgeChunk, KnowledgeSource)
        .join(KnowledgeSource, KnowledgeChunk.source_id == KnowledgeSource.id)
        .where(KnowledgeSource.is_active == True)  # noqa: E712
    )
    rows = session.exec(statement).all()
    question_normalized = normalize_text(question)
    lexical_results: list[RetrievalResult] = []
    for chunk, source in rows:
        chunk_score = _lexical_similarity(question_normalized, chunk.content)
        title_score = _lexical_similarity(question_normalized, source.title)
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
    if item.chunk_id is not None:
        return f"chunk:{item.chunk_id}"
    return f"source:{item.source_id}:{hash(item.snippet)}"


def _merge_hybrid_results(
    semantic_results: list[RetrievalResult],
    lexical_results: list[RetrievalResult],
) -> list[RetrievalResult]:
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
    semantic = retrieve_semantic_chunks(question)
    lexical = retrieve_lexical_chunks(session, question)
    merged = _merge_hybrid_results(semantic, lexical)
    return rerank_results(question, merged)


def has_conflicting_sources(results: list[RetrievalResult]) -> bool:
    if len(results) < 2:
        return False
    first, second = results[0], results[1]
    close_scores = abs(first.score - second.score) <= 0.03
    different_sources = first.source_id != second.source_id
    return close_scores and different_sources


def _build_prompt(question: str, results: list[RetrievalResult]) -> str:
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
    prompt = _build_prompt(question, results)
    try:
        return _generate_with_google(prompt), False
    except Exception:
        return _generate_with_ollama(prompt), True


def _create_queue_item(session: Session, request_id: uuid.UUID, reason: str) -> None:
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


def run_support_pipeline(
    *, session: Session, user_id: uuid.UUID | None, payload: SupportAskRequest
) -> SupportAskResponse:
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

    top_score = retrieved[0].score if retrieved else 0.0
    relevant_chunk_count = sum(
        1 for item in retrieved if item.score >= settings.RAG_RELEVANT_CHUNK_THRESHOLD
    )
    has_context = (
        relevant_chunk_count >= 2 and top_score >= settings.RAG_TOP_SCORE_THRESHOLD
    )
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

    history: list[SupportHistoryEntry] = []
    for request in requests:
        answer = answer_map.get(request.id)
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
                created_at=request.created_at,
            )
        )
    return history


def create_faq_entry(session: Session, faq_in: FaqEntryCreate) -> FaqEntry:
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


def _extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        fallback_parts = re.findall(rb"\(([^()]*)\)", data)
        if fallback_parts:
            merged = " ".join(
                part.decode("utf-8", errors="ignore")
                .replace("\\n", " ")
                .replace("\\r", " ")
                .replace("\\t", " ")
                for part in fallback_parts
            )
            merged = re.sub(r"\s+", " ", merged).strip()
            if merged:
                return merged
        raise ValueError(
            "PDF parsing dependency is missing. Install `pypdf` for reliable PDF ingestion."
        ) from exc

    import io

    reader = PdfReader(io.BytesIO(data))
    text_parts: list[str] = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return _ensure_utf8_text("\n".join(text_parts))


def _extract_text_from_url(url: str) -> str:
    with httpx.Client(timeout=settings.QDRANT_TIMEOUT_SECONDS) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text_without_tags = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text_without_tags).strip()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return _ensure_utf8_text(soup.get_text(separator=" ", strip=True))


def _decode_utf8_text_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Text source must be UTF-8 encoded") from exc


def _ensure_utf8_text(value: str) -> str:
    return value.encode("utf-8", errors="replace").decode("utf-8", errors="replace").strip()


def resolve_source_content(
    *,
    filename: str | None,
    file_bytes: bytes | None,
    source_url: str | None,
    manual_content: str | None,
) -> tuple[str, str, str | None]:
    if manual_content and manual_content.strip():
        return _ensure_utf8_text(manual_content), "manual", None
    if source_url:
        text = _extract_text_from_url(source_url)
        return text, "url", _ensure_utf8_text(source_url)
    if file_bytes is None or not filename:
        raise ValueError("No source content provided")
    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        text = _extract_text_from_pdf(file_bytes)
        return text, "pdf", _ensure_utf8_text(filename)
    if lower_name.endswith(".txt") or lower_name.endswith(".md"):
        text = _decode_utf8_text_bytes(file_bytes)
        return _ensure_utf8_text(text), "txt", _ensure_utf8_text(filename)
    raise ValueError("Unsupported file type. Use pdf/txt/md or URL/manual content.")


def remove_source_vectors(source_id: uuid.UUID) -> None:
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
    _qdrant_request(
        "PUT",
        f"/collections/{settings.QDRANT_COLLECTION_NAME}/points?wait=true",
        payload={"points": points},
    )


def index_source(session: Session, source: KnowledgeSource) -> int:
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

    remove_source_vectors(source.id)

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
    return len(new_chunks)


def reindex_sources(
    session: Session,
    source_ids: list[uuid.UUID] | None = None,
    *,
    full_rebuild: bool = False,
    purge_orphans: bool = True,
) -> tuple[int, int]:
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
    queue_items = session.exec(
        select(OperatorQueue).order_by(col(OperatorQueue.created_at).desc())
    ).all()
    if not queue_items:
        return []
    request_ids = [item.request_id for item in queue_items]
    requests = session.exec(
        select(SupportRequest).where(SupportRequest.id.in_(request_ids))
    ).all()
    request_map = {request.id: request for request in requests}
    response: list[OperatorQueueEntry] = []
    for item in queue_items:
        request = request_map.get(item.request_id)
        if not request:
            continue
        response.append(
            OperatorQueueEntry(
                queue_id=item.id,
                request_id=item.request_id,
                reason=item.reason,
                status=item.status,
                question=request.question,
                created_at=item.created_at,
            )
        )
    return response


def get_support_metrics(session: Session) -> SupportMetricsPublic:
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
