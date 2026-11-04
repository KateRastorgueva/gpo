"""Внешние RAG-движки, подключаемые вместо собственного поиска.

Кто отвечает после промаха FAQ, выбирает админ в «Управлении» (таблица
``app_setting``); пока выбора нет, действует ``RAG_PROVIDER`` из окружения:

* ``legacy`` — собственный поиск Postgres + Qdrant (``support_service``);
* ``gemini_file_search`` — Google Gemini File Search (хранилище в облаке Google);
* ``anythingllm`` — self-hosted AnythingLLM (workspace в режиме ``query``).

Маршрут ``FAQ -> RAG -> Operator``, БД и фронт от выбора движка не зависят:
провайдер возвращает текст ответа, список источников и признак того,
что ответ опирается на документы. Решение об эскалации принимает
``support_service.run_support_pipeline``.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlmodel import Session

from app.core.config import settings
from app.models import AppSetting, EngineDocument, get_datetime_utc
from app.services import app_config
from app.services.app_config import live_settings

EXTERNAL_PROVIDERS = {"gemini_file_search", "anythingllm"}
PROVIDER_LABELS = {
    "gemini_file_search": "Облако — Gemini File Search",
    "anythingllm": "Локально — AnythingLLM",
    "legacy": "Встроенный поиск + генерация ответа (LLM)",
    "search_only": "Только поиск, без генерации (лёгкий)",
}
# Не ходят во внешний сервис: встроенный поиск по базе знаний в Postgres.
BUILTIN_PROVIDERS = {"legacy", "search_only"}
PROVIDER_SETTING_KEY = "rag_provider"

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
    # Полный текст фрагмента (для проверки ответа); в историю не пишется.
    text: str | None = None

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


def get_active_provider(session: Session) -> str:
    """Движок, выбранный админом; без выбора — ``RAG_PROVIDER`` из окружения."""
    row = session.get(AppSetting, PROVIDER_SETTING_KEY)
    if row and row.value in PROVIDER_LABELS:
        return row.value
    return settings.RAG_PROVIDER


def set_active_provider(session: Session, provider: str) -> None:
    if provider not in PROVIDER_LABELS:
        raise ValueError(f"Unknown RAG provider: {provider}")
    row = session.get(AppSetting, PROVIDER_SETTING_KEY) or AppSetting(
        key=PROVIDER_SETTING_KEY, value=provider
    )
    row.value = provider
    row.updated_at = get_datetime_utc()
    session.add(row)
    session.commit()
    app_config.invalidate_cache()


def is_provider_configured(provider: str) -> bool:
    if provider == "gemini_file_search":
        return bool(
            live_settings.gemini_api_key and live_settings.GEMINI_FILE_SEARCH_STORE
        )
    if provider == "anythingllm":
        return bool(live_settings.ANYTHINGLLM_API_KEY)
    return provider in BUILTIN_PROVIDERS


def is_external_provider_enabled(provider: str | None = None) -> bool:
    return (provider or live_settings.RAG_PROVIDER) in EXTERNAL_PROVIDERS


def ask_provider(question: str, provider: str | None = None) -> ProviderAnswer:
    """Отправляет вопрос во внешний движок (по умолчанию — ``RAG_PROVIDER``)."""

    provider = provider or live_settings.RAG_PROVIDER
    if provider == "gemini_file_search":
        return ask_gemini_file_search(question)
    if provider == "anythingllm":
        return ask_anythingllm(question)
    raise RuntimeError(f"Unknown external RAG_PROVIDER: {provider}")


# Модель иногда пишет маркер латиницей вперемешку с кириллицей: «НЕТ_OTBETА».
_HOMOGLYPHS = str.maketrans("ABEKMHOPCTXY", "АВЕКМНОРСТХУ")


def _is_no_answer(text: str) -> bool:
    return not text.strip() or NO_ANSWER_MARKER in text.upper().translate(_HOMOGLYPHS)


# --------------------------- проверка источников ответа ---------------------------

_METADATA_RE = re.compile(
    r"<document_metadata>.*?</document_metadata>\s*", re.DOTALL | re.IGNORECASE
)
# Название файла в тексте ответа: «..., из документа Pravila_02.11.2017_(1) (1).pdf».
_DOC_NAME_RE = re.compile(
    r"[\w.()\-]+(?: [\w.()\-]+){0,6}?\.(?:pdf|docx?|rtf|txt)\b", re.IGNORECASE
)
_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d  ]*(?:[.,]\d+)?")
UNVERIFIED_DOC_PENALTY = 0.5
UNVERIFIED_NUMBERS_PENALTY = 0.7


def strip_document_metadata(text: str | None) -> str:
    """Убирает служебный блок ``<document_metadata>`` AnythingLLM из фрагмента."""

    return _METADATA_RE.sub("", text or "").strip()


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def verify_answer_sources(result: ProviderAnswer) -> ProviderAnswer:
    """Сверяет ответ модели с найденными фрагментами.

    * документ, названный в ответе, но отсутствующий среди источников, помечается
      как неподтверждённый, уверенность снижается;
    * числа (2+ цифры) из ответа, которых нет в тексте фрагментов, помечаются
      как непроверенные, уверенность снижается.
    """

    if not result.grounded or not result.sources:
        return result
    titles = {_norm_name(s.title) for s in result.sources}
    corpus = " ".join(s.text or s.snippet or "" for s in result.sources)
    corpus_digits_text = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", corpus)
    answer = result.answer
    notes: list[str] = []

    for match in _DOC_NAME_RE.finditer(answer):
        name = match.group(0).strip()
        norm = _norm_name(name)
        if any(norm == t or norm in t or t in norm for t in titles):
            continue
        answer = answer.replace(name, f"«{name}» (источник не подтверждён)")
        result.confidence = round(result.confidence * UNVERIFIED_DOC_PENALTY, 4)
        notes.append(f"документ «{name}» не найден среди использованных фрагментов")
        break  # одного штрафа за ответ достаточно

    # Числа из названий файлов (даты в имени) не проверяем.
    plain = _DOC_NAME_RE.sub(" ", result.answer)
    plain = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", plain)
    unverified: list[str] = []
    for match in _NUMBER_RE.finditer(plain):
        raw = match.group(0).strip()
        if len(_digits(raw)) < 2 or raw in unverified:
            continue
        if (
            raw not in corpus_digits_text
            and raw.replace(",", ".") not in corpus_digits_text
        ):
            unverified.append(raw)
    if unverified:
        result.confidence = round(result.confidence * UNVERIFIED_NUMBERS_PENALTY, 4)
        notes.append("числа " + ", ".join(unverified[:5]) + " не найдены во фрагментах")

    if notes:
        answer += (
            "\n\n⚠ Не удалось подтвердить по найденным фрагментам: "
            + "; ".join(notes)
            + ". Проверьте информацию в первоисточнике."
        )
    result.answer = answer
    return result


def ask_gemini_file_search(question: str) -> ProviderAnswer:
    api_key = live_settings.gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if not live_settings.GEMINI_FILE_SEARCH_STORE:
        raise RuntimeError("GEMINI_FILE_SEARCH_STORE is not configured")

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "tools": [
            {
                "fileSearch": {
                    "fileSearchStoreNames": [live_settings.GEMINI_FILE_SEARCH_STORE],
                    "topK": live_settings.GEMINI_FILE_SEARCH_TOP_K,
                }
            }
        ],
        "generationConfig": {"temperature": 0.1},
    }
    # Список моделей через запятую: при перегрузке (503/429) или снятой с
    # поддержки модели (404) пробуем следующую, а не сразу зовём оператора.
    models = [
        m.strip()
        for m in live_settings.GEMINI_FILE_SEARCH_MODEL.split(",")
        if m.strip()
    ]
    with httpx.Client(timeout=live_settings.RAG_PROVIDER_TIMEOUT_SECONDS) as client:
        for index, model in enumerate(models):
            url = f"{live_settings.GOOGLE_API_URL}/models/{model}:generateContent"
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
        snippet = strip_document_metadata(context.get("text"))
        key = (title, (snippet or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        page = context.get("pageNumber")
        sources.append(
            ProviderSource(
                title=title,
                snippet=(snippet or "")[:400] or None,
                text=snippet or None,
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
    return verify_answer_sources(
        ProviderAnswer(
            provider="gemini_file_search",
            answer=answer,
            grounded=grounded,
            confidence=round(confidence, 4),
            sources=sources,
        )
    )


def ask_anythingllm(question: str) -> ProviderAnswer:
    if not live_settings.ANYTHINGLLM_API_KEY:
        raise RuntimeError("ANYTHINGLLM_API_KEY is not configured")
    url = (
        f"{live_settings.ANYTHINGLLM_BASE_URL.rstrip('/')}/api/v1/workspace/"
        f"{live_settings.ANYTHINGLLM_WORKSPACE}/chat"
    )
    headers = {"Authorization": f"Bearer {live_settings.ANYTHINGLLM_API_KEY}"}
    payload = {"message": question, "mode": "query"}
    with httpx.Client(timeout=live_settings.RAG_PROVIDER_TIMEOUT_SECONDS) as client:
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
        text = strip_document_metadata(str(item.get("text") or item.get("chunk") or ""))
        sources.append(
            ProviderSource(
                title=title,
                snippet=text[:400] or None,
                text=text or None,
                ref=f"anythingllm: {title}",
                score=float(score) if isinstance(score, int | float) else None,
            )
        )
    refused = answer.startswith(ANYTHINGLLM_REFUSAL_PREFIX)
    grounded = bool(sources) and not refused and not _is_no_answer(answer)
    confidence = max(scores) if scores else (1.0 if grounded else 0.0)
    return verify_answer_sources(
        ProviderAnswer(
            provider="anythingllm",
            answer=answer,
            grounded=grounded,
            confidence=round(min(1.0, confidence), 4) if grounded else 0.0,
            sources=sources,
        )
    )


# ------------------------- загрузка документов в движки -------------------------
#
# Используются админской пакетной загрузкой (``rag_ingest``). Функции загрузки
# возвращают статус файла: ``ok`` — загружен и проиндексирован, ``already`` —
# документ с таким именем уже есть, ``no-text`` — AnythingLLM не извлёк текст
# (скан без текстового слоя: сам AnythingLLM OCR не делает, Gemini — делает).

GEMINI_OPERATION_TIMEOUT_SECONDS = 600
GEMINI_POLL_SECONDS = 3.0


def _gemini_upload_base() -> str:
    # https://host/v1beta -> https://host/upload/v1beta
    url = httpx.URL(live_settings.GOOGLE_API_URL)
    return f"{url.scheme}://{url.netloc.decode()}/upload{url.path.rstrip('/')}"


def _require_gemini() -> tuple[str, str]:
    api_key = live_settings.gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if not live_settings.GEMINI_FILE_SEARCH_STORE:
        raise RuntimeError("GEMINI_FILE_SEARCH_STORE is not configured")
    return api_key, live_settings.GEMINI_FILE_SEARCH_STORE


def list_gemini_documents(client: httpx.Client | None = None) -> list[EngineDocument]:
    api_key, store = _require_gemini()
    own = client is None
    client = client or httpx.Client(timeout=60)
    docs: list[EngineDocument] = []
    try:
        token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 20}
            if token:
                params["pageToken"] = token
            response = client.get(
                f"{live_settings.GOOGLE_API_URL}/{store}/documents",
                headers={"X-goog-api-key": api_key},
                params=params,
            )
            response.raise_for_status()
            body = response.json()
            for doc in body.get("documents") or []:
                size = doc.get("sizeBytes")
                state = str(doc.get("state") or "").removeprefix("STATE_")
                docs.append(
                    EngineDocument(
                        name=str(doc.get("displayName") or doc.get("name") or ""),
                        state=state or None,
                        size_bytes=int(size) if size is not None else None,
                    )
                )
            token = body.get("nextPageToken")
            if not token:
                return docs
    finally:
        if own:
            client.close()


def upload_gemini_document(
    filename: str,
    data: bytes,
    mime_type: str,
    *,
    existing: set[str] | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Resumable-загрузка в File Search store — тот же протокол, что у SDK google-genai."""
    api_key, store = _require_gemini()
    own = client is None
    client = client or httpx.Client(timeout=live_settings.RAG_PROVIDER_TIMEOUT_SECONDS)
    try:
        if existing is None:
            existing = {d.name for d in list_gemini_documents(client)}
        if filename in existing:
            return "already"
        start = client.post(
            f"{_gemini_upload_base()}/{store}:uploadToFileSearchStore",
            headers={
                "X-goog-api-key": api_key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)),
                "X-Goog-Upload-Header-Content-Type": mime_type,
            },
            json={"displayName": filename, "mimeType": mime_type},
        )
        start.raise_for_status()
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise RuntimeError("Gemini did not return an upload URL")
        finish = client.post(
            upload_url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            },
            content=data,
        )
        finish.raise_for_status()
        operation = finish.json()
        # Индексация (в т.ч. OCR сканов) идёт асинхронно: ждём завершения операции.
        deadline = time.monotonic() + GEMINI_OPERATION_TIMEOUT_SECONDS
        while not operation.get("done"):
            if time.monotonic() > deadline:
                raise RuntimeError("Gemini indexing timed out")
            time.sleep(GEMINI_POLL_SECONDS)
            poll = client.get(
                f"{live_settings.GOOGLE_API_URL}/{operation['name']}",
                headers={"X-goog-api-key": api_key},
            )
            poll.raise_for_status()
            operation = poll.json()
        if operation.get("error"):
            message = operation["error"].get("message")
            raise RuntimeError(f"Gemini indexing failed: {message}")
        existing.add(filename)
        return "ok"
    finally:
        if own:
            client.close()


def _anythingllm_client() -> httpx.Client:
    if not live_settings.ANYTHINGLLM_API_KEY:
        raise RuntimeError("ANYTHINGLLM_API_KEY is not configured")
    return httpx.Client(
        base_url=f"{live_settings.ANYTHINGLLM_BASE_URL.rstrip('/')}/api/v1",
        headers={"Authorization": f"Bearer {live_settings.ANYTHINGLLM_API_KEY}"},
        timeout=900,
    )


def _anythingllm_title(document: dict[str, Any]) -> str:
    metadata = document.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    if isinstance(metadata, dict) and metadata.get("title"):
        return str(metadata["title"])
    return str(document.get("filename") or document.get("docpath") or "")


def _anythingllm_engine_document(document: dict[str, Any]) -> EngineDocument:
    metadata = document.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    words = metadata.get("wordCount") if isinstance(metadata, dict) else None
    # Документ из workspace уже проиндексирован: AnythingLLM отдаёт только такие.
    return EngineDocument(
        name=_anythingllm_title(document),
        state="В индексе",
        word_count=int(words) if isinstance(words, int | float) else None,
    )


def list_anythingllm_documents(
    client: httpx.Client | None = None,
) -> list[EngineDocument]:
    own = client is None
    client = client or _anythingllm_client()
    try:
        response = client.get(f"/workspace/{live_settings.ANYTHINGLLM_WORKSPACE}")
        response.raise_for_status()
        workspace = response.json().get("workspace") or []
        if isinstance(workspace, dict):
            workspace = [workspace]
        return [
            _anythingllm_engine_document(document)
            for ws in workspace
            for document in ws.get("documents") or []
        ]
    finally:
        if own:
            client.close()


def upload_anythingllm_document(
    filename: str,
    data: bytes,
    mime_type: str,
    *,
    existing: set[str] | None = None,
    client: httpx.Client | None = None,
) -> str:
    own = client is None
    client = client or _anythingllm_client()
    try:
        if existing is None:
            existing = {d.name for d in list_anythingllm_documents(client)}
        if filename in existing:
            return "already"
        response = client.post(
            "/document/upload", files={"file": (filename, data, mime_type)}
        )
        response.raise_for_status()
        documents = response.json().get("documents") or []
        locations = [d["location"] for d in documents if d.get("location")]
        words = sum(int(d.get("wordCount") or 0) for d in documents)
        if not locations or words == 0:
            return "no-text"
        client.post(
            f"/workspace/{live_settings.ANYTHINGLLM_WORKSPACE}/update-embeddings",
            json={"adds": locations, "deletes": []},
        ).raise_for_status()
        existing.add(filename)
        return "ok"
    finally:
        if own:
            client.close()
