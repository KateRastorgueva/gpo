# Текущая версия проекта (Web MVP)

Дата фиксации: 2026-04-02  
Статус: рабочая web-версия, Telegram вне релиза.

## 1. Ключевой результат

В проекте реализован рабочий контур поддержки:
`FAQ -> RAG -> Operator` в UI и API.

## 2. Что реализовано

### Backend

- `POST /api/v1/support/ask`
- `GET /api/v1/support/history`
- Admin API:
- `GET/POST/PATCH/DELETE /api/v1/admin/faq`
- `GET/POST/DELETE /api/v1/admin/sources`
- `POST /api/v1/admin/sources/reindex`
- `GET /api/v1/admin/operator-queue`

Логика маршрутизации:

- `FAQ`: similarity-порог `FAQ_SIMILARITY_THRESHOLD=0.90`.
- `RAG`: нужен достаточный контекст (`>=2` релевантных чанка и `top_score >= 0.72`).
- `Operator`: когда оснований недостаточно, при конфликте источников или для критичных вопросов при низкой уверенности.

### RAG / LLM

- Embeddings:
- `sentence-transformers` (если доступен локально)
- fallback на Google embeddings (`gemini-embedding-001`)
- резервный hash-embedding
- Vector storage: Qdrant (`knowledge_chunks`)
- LLM:
- primary: Google AI Studio (`gemini-flash-latest`)
- fallback: Ollama (`llama3.1:8b`)

### Frontend

- Пользовательская страница: `/support`.
- Админская страница: `/admin-support`.
- В UI видны поля `mode`, `confidence`, `fallback_used`, `sources`.
- Есть история сессии и очередь оператора.

### Данные и миграции

- Добавлены сущности:
- `faqentry`
- `knowledgesource`
- `knowledgechunk`
- `supportrequest`
- `supportanswer`
- `operatorqueue`
- Добавлена Alembic-миграция под RAG/support слой.

### Инфраструктура

- В `compose.yml` добавлен сервис `qdrant`.
- Поддержаны переменные окружения для Google/Ollama/Qdrant.
- Telegram вынесен в профиль `telegram` и не участвует в web-флоу.

## 3. Что подтверждено проверками

- Поддержка работает в 3 режимах (`faq`, `rag`, `operator`) при заполненных данных.
- API login суперпользователя и базовые auth-сценарии работают.
- Есть автотесты для support API (`backend/tests/api/routes/test_support.py`).
- Есть e2e тесты для UI-auth и базового UX (`frontend/tests/*.spec.ts`).

## 4. Ограничения на сейчас

- Если FAQ пустой, запросы уходят в RAG/Operator.
- Нет полного workflow ответа оператора пользователю в UI.
- Качество RAG критично зависит от качества и полноты источников.

## 5. Что нужно для стабильной демо-версии

1. Заполнить FAQ (рекомендуемо 10-30 пар вопрос/ответ).
2. Загрузить источники (рекомендуемо 20+ страниц/документов).
3. Выполнить reindex.
4. Проверить 3 smoke-сценария: `faq`, `rag`, `operator`.
