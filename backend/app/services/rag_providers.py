"""Внешние RAG-движки, подключаемые вместо собственного поиска.

Переключатель ``RAG_PROVIDER`` выбирает, кто отвечает после промаха FAQ:

* ``legacy`` — собственный поиск Postgres + Qdrant (``support_service``);
* ``gemini_file_search`` — Google Gemini File Search (хранилище в облаке Google);
* ``anythingllm`` — self-hosted AnythingLLM (workspace в режиме ``query``).

Маршрут ``FAQ -> RAG -> Operator``, БД и фронт от выбора движка не зависят:
провайдер возвращает текст ответа, список источников и признак того,
что ответ опирается на документы. Решение об эскалации принимает
``support_service.run_support_pipeline``.
"""

import uuid
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

NO_ANSWER_MARKER = "НЕТ_ОТВЕТА"

SYSTEM_PROMPT = (
    "Ты ассистент техподдержки университета ТУСУР. Отвечай только на основе "
    "найденных документов, кратко и по делу, на русском языке. Указывай, из какого "
    "документа взят ответ. Если в документах нет ответа на вопрос, ответь ровно "
    f"одним словом {NO_ANSWER_MARKER} и ничего больше."
)

RETRYABLE_STATUS = {404, 429, 500, 503, 504}

# Ответ AnythingLLM в режиме query, когда в workspace нет подходящих фрагментов.
ANYTHINGLLM_REFUSAL_PREFIX = "There is no relevant information"


@dataclass
class ProviderSource:
    title: str
    snippet: str | None = None
    ref: str | None = None
    page: int | None = None
    score: float | None = None

    @property
    def source_id(self) -> uuid.UUID:
        # Документы живут во внешнем хранилище, поэтому id детерминированно
        # выводится из названия: одинаковый файл даёт одинаковый id в истории.
        return uuid.uuid5(uuid.NAMESPACE_URL, f"rag-provider:{self.title}")


@dataclass
class ProviderAnswer:
    provider: str
    answer: str
    grounded: bool
    confidence: float
    sources: list[ProviderSource] = field(default_factory=list)


def is_external_provider_enabled() -> bool:
    return settings.RAG_PROVIDER in {"gemini_file_search", "anythingllm"}


def ask_provider(question: str) -> ProviderAnswer:
    """Отправляет вопрос во внешний движок, выбранный ``RAG_PROVIDER``."""

    if settings.RAG_PROVIDER == "gemini_file_search":
        return ask_gemini_file_search(question)
    if settings.RAG_PROVIDER == "anythingllm":
        return ask_anythingllm(question)
    raise RuntimeError(f"Unknown external RAG_PROVIDER: {settings.RAG_PROVIDER}")


# Модель иногда пишет маркер латиницей вперемешку с кириллицей: «НЕТ_OTBETА».
_HOMOGLYPHS = str.maketrans("ABEKMHOPCTXY", "АВЕКМНОРСТХУ")


def _is_no_answer(text: str) -> bool:
    return not text.strip() or NO_ANSWER_MARKER in text.upper().translate(_HOMOGLYPHS)


def ask_gemini_file_search(question: str) -> ProviderAnswer:
    api_key = settings.gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if not settings.GEMINI_FILE_SEARCH_STORE:
        raise RuntimeError("GEMINI_FILE_SEARCH_STORE is not configured")

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "tools": [
            {
                "fileSearch": {
                    "fileSearchStoreNames": [settings.GEMINI_FILE_SEARCH_STORE],
                    "topK": settings.GEMINI_FILE_SEARCH_TOP_K,
                }
            }
        ],
        "generationConfig": {"temperature": 0.1},
    }
    # Список моделей через запятую: при перегрузке (503/429) или снятой с
    # поддержки модели (404) пробуем следующую, а не сразу зовём оператора.
    models = [
        m.strip() for m in settings.GEMINI_FILE_SEARCH_MODEL.split(",") if m.strip()
    ]
    with httpx.Client(timeout=settings.RAG_PROVIDER_TIMEOUT_SECONDS) as client:
        for index, model in enumerate(models):
            url = f"{settings.GOOGLE_API_URL}/models/{model}:generateContent"
            response = client.post(
                url, headers={"X-goog-api-key": api_key}, json=payload
            )
            if response.status_code in RETRYABLE_STATUS and index < len(models) - 1:
                continue
            response.raise_for_status()
            body = response.json()
            break
    return parse_gemini_response(body)


def parse_gemini_response(body: dict) -> ProviderAnswer:  # type: ignore[type-arg]
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    answer = "".join(str(part.get("text", "")) for part in parts).strip()

    metadata = candidate.get("groundingMetadata") or {}
    chunks = metadata.get("groundingChunks") or []
    supports = metadata.get("groundingSupports") or []

    sources: list[ProviderSource] = []
    seen: set[tuple[str, str | None]] = set()
    for chunk in chunks:
        context = chunk.get("retrievedContext") or {}
        title = str(context.get("title") or "Документ")
        snippet = context.get("text")
        key = (title, (snippet or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        page = context.get("pageNumber")
        sources.append(
            ProviderSource(
                title=title,
                snippet=(snippet or "")[:400] or None,
                ref=f"gemini-file-search: {title}" + (f", стр. {page}" if page else ""),
                page=int(page) if page else None,
            )
        )

    # Уверенность = доля текста ответа, подтверждённая фрагментами документов.
    supported = 0
    for support in supports:
        segment = support.get("segment") or {}
        start = int(segment.get("startIndex") or 0)
        end = int(segment.get("endIndex") or 0)
        supported += max(0, end - start)
    answer_len = len(answer.encode("utf-8")) or 1
    coverage = min(1.0, supported / answer_len)

    grounded = bool(sources) and not _is_no_answer(answer)
    confidence = coverage if grounded else 0.0
    return ProviderAnswer(
        provider="gemini_file_search",
        answer=answer,
        grounded=grounded,
        confidence=round(confidence, 4),
        sources=sources,
    )


def ask_anythingllm(question: str) -> ProviderAnswer:
    if not settings.ANYTHINGLLM_API_KEY:
        raise RuntimeError("ANYTHINGLLM_API_KEY is not configured")
    url = (
        f"{settings.ANYTHINGLLM_BASE_URL.rstrip('/')}/api/v1/workspace/"
        f"{settings.ANYTHINGLLM_WORKSPACE}/chat"
    )
    headers = {"Authorization": f"Bearer {settings.ANYTHINGLLM_API_KEY}"}
    payload = {"message": question, "mode": "query"}
    with httpx.Client(timeout=settings.RAG_PROVIDER_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
    return parse_anythingllm_response(body)


def parse_anythingllm_response(body: dict) -> ProviderAnswer:  # type: ignore[type-arg]
    if body.get("error"):
        raise RuntimeError(f"AnythingLLM error: {body['error']}")
    answer = str(body.get("textResponse") or "").strip()
    sources: list[ProviderSource] = []
    scores: list[float] = []
    for item in body.get("sources") or []:
        title = str(item.get("title") or "Документ")
        score = item.get("score")
        if isinstance(score, int | float):
            scores.append(float(score))
        sources.append(
            ProviderSource(
                title=title,
                snippet=(str(item.get("text") or item.get("chunk") or ""))[:400]
                or None,
                ref=f"anythingllm: {title}",
                score=float(score) if isinstance(score, int | float) else None,
            )
        )
    refused = answer.startswith(ANYTHINGLLM_REFUSAL_PREFIX)
    grounded = bool(sources) and not refused and not _is_no_answer(answer)
    confidence = max(scores) if scores else (1.0 if grounded else 0.0)
    return ProviderAnswer(
        provider="anythingllm",
        answer=answer,
        grounded=grounded,
        confidence=round(min(1.0, confidence), 4) if grounded else 0.0,
        sources=sources,
    )
