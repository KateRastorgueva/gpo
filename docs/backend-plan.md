# Backend — план улучшений

> Актуально на: 2026-04-29

Список конкретных доработок бэкенда для корректной работы всех сценариев.
Задачи сгруппированы по приоритету.

---

## Статус выполнения

### ✅ Сделано (Этап 1, ветка `feat/import-gpo-data`)

**Блок 1.1 — OperatorReply: модель + endpoint + my-queue:**
- Модель `OperatorReply` (`queue_id` FK CASCADE, `operator_id` NOT NULL FK на `user.id`, `reply_text`, `created_at`) и relationship `OperatorQueue.reply` → `backend/app/models.py`.
- Схемы `OperatorReplyCreate`, `MyQueueEntry`, `MyQueuePublic`; в `OperatorQueueEntry` добавлены `reply_text`/`reply_created_at` → `backend/app/models.py`.
- Сервис `reply_to_queue_item()` (создаёт reply, ставит `OperatorQueue.status=resolved`, `SupportRequest.status=operator_replied`, отдаёт 409 при повторном ответе) и `list_my_queue()` → `backend/app/services/support_service.py`.
- `list_operator_queue()` теперь джойнит `OperatorReply` и возвращает текст ответа.
- Эндпоинт `PATCH /api/v1/admin/operator-queue/{queue_id}` (использует `current_user.id` как `operator_id`) → `backend/app/api/routes/admin_support.py`.
- Эндпоинт `GET /api/v1/support/my-queue` → `backend/app/api/routes/support.py`.
- Alembic-миграция `b7a4f1c2e9d0_add_operator_reply.py` (ревизит `1a31ce608336`).

**Блок 1.2 — Статус `operator_replied`:**
- Выставляется в `reply_to_queue_item()`.
- В `SupportHistoryEntry` добавлено поле `status: str`, заполняется в `list_support_history()`.

**Фронтенд (этапа 1):**
- Типы и методы `replyOperatorQueueItem`, `getMyQueue` в `frontend/src/services/supportApi.ts`.
- Форма ответа оператора в карточке очереди → `frontend/src/routes/_layout/admin-support.tsx`.
- Страница «Мои обращения» → `frontend/src/routes/_layout/my-requests.tsx`.

### ⏳ Осталось

- Блок 2.1 — BackgroundTasks для индексирования.
- Блок 2.2 — SQL-агрегаты в метриках.
- Блок 2.3 — пагинация и фильтрация очереди оператора.
- Блок 3.1 — умный chunking по границам предложений.
- Блок 3.2 — семантический FAQ-матчинг.
- Блок 3.3 — контекст диалога в LLM-промпте.
- Блок 4.1 — rate limiting на `/support/ask`.
- Блок 4.2 — дедупликация источников по `content_hash`.

Рекомендованная следующая пара (по плану ревью): **4.2 + 2.1** одним PR.

---

## Блок 1: Незавершённые бизнес-сценарии (🔴 Критично)

### 1.1 Цикл «Оператор → Пользователь»

**Проблема:** Оператор не может ответить на обращение. В `OperatorQueue` есть статус `open`, но нет endpoint'а для ответа и нет модели для хранения текста ответа.

**Что реализовать:**

1. `backend/app/models.py`
   - Новая модель `OperatorReply` (таблица): поля `id`, `queue_id` (FK → `operatorqueue.id`, CASCADE), `reply_text`, `operator_id` (FK → `user.id`, nullable), `created_at`
   - Добавить `reply: OperatorReply` relationship в `OperatorQueue`
   - Новая схема `OperatorReplyCreate` (входной Pydantic-объект: только `reply_text`)
   - Обновить `OperatorQueueEntry` — добавить поля `reply_text: str | None` и `reply_created_at: datetime | None`
   - Новые схемы `MyQueueEntry` и `MyQueuePublic` — для пользовательского просмотра своих обращений

2. `backend/app/services/support_service.py`
   - Функция `reply_to_queue_item(session, queue_item, reply_text, operator_id)`:
     - Создать `OperatorReply`
     - Обновить `OperatorQueue.status → "resolved"`
     - Обновить `SupportRequest.status → "operator_replied"`
   - Функция `list_my_queue(session, user_id)` — возвращает список `MyQueueEntry` для конкретного пользователя (его эскалированные запросы + статус + ответ оператора если есть)

3. `backend/app/api/routes/admin_support.py`
   - `PATCH /api/v1/admin/operator-queue/{queue_id}` — принять `OperatorReplyCreate`, вызвать `reply_to_queue_item()`, вернуть обновлённый `OperatorQueueEntry`

4. `backend/app/api/routes/support.py`
   - `GET /api/v1/support/my-queue` — для авторизованного пользователя, вернуть `MyQueuePublic`

5. Alembic-миграция: новая таблица `operatorreply`

---

### 1.2 Статус обращения — `operator_replied`

**Проблема:** `SupportRequest.status` принимает только `completed` / `escalated`, нет статуса «оператор ответил».

**Что реализовать:**

- В `reply_to_queue_item()` (см. 1.1): при создании `OperatorReply` выставлять `SupportRequest.status = "operator_replied"`
- `SupportHistoryEntry` — добавить поле `status: str` чтобы пользователь видел статус в истории

---

## Блок 2: Производительность и надёжность (🟠 Важно)

### 2.1 Асинхронное индексирование источников

**Проблема:** `index_source()` вызывается синхронно в HTTP-хендлере. Загрузка большого PDF блокирует воркер на 10–30 сек.

**Что реализовать:**

- `backend/app/api/routes/admin_support.py`
  - `POST /admin/sources/upload` и `POST /admin/sources/upload-json` — вернуть `202 Accepted` сразу, индексирование запустить через `BackgroundTasks` FastAPI
  - `GET /admin/sources/{source_id}` — новый endpoint для проверки статуса индексирования (`pending/indexed/failed`)
- `KnowledgeSource.status` уже есть — достаточно сохранить источник со статусом `pending` и вернуть его, а `index_source()` запустить фоном

---

### 2.2 SQL-агрегаты в метриках

**Проблема:** `get_support_metrics()` в [support_service.py:1346](../backend/app/services/support_service.py#L1346) делает `select(SupportRequest).all()` — загружает всю таблицу в память Python.

**Что реализовать:**

- `backend/app/services/support_service.py` — переписать `get_support_metrics()`:
  ```sql
  SELECT
    COUNT(*) AS total,
    AVG(confidence) AS avg_confidence,
    SUM(CASE WHEN mode='faq' THEN 1 ELSE 0 END)::float / COUNT(*) AS faq_share,
    SUM(CASE WHEN mode='rag' THEN 1 ELSE 0 END)::float / COUNT(*) AS rag_share,
    SUM(CASE WHEN mode='operator' THEN 1 ELSE 0 END)::float / COUNT(*) AS operator_share
  FROM supportrequest
  ```
  Аналогично для `empty_sources_share` — через SQL COUNT по `SupportAnswer`.

---

### 2.3 Пагинация и фильтрация очереди оператора

**Проблема:** `list_operator_queue()` возвращает все элементы без пагинации и без фильтрации по статусу.

**Что реализовать:**

- `backend/app/services/support_service.py` — добавить параметры `skip: int`, `limit: int`, `status: str | None` в `list_operator_queue()`
- `backend/app/api/routes/admin_support.py` — `GET /admin/operator-queue` принимает query-параметры `skip`, `limit`, `status`
- `OperatorQueuePublic` — поле `count` теперь отдельным SQL COUNT (не `len(data)`)

---

## Блок 3: Качество RAG-пайплайна (🟡 Улучшение)

### 3.1 Умный chunking по границам предложений

**Проблема:** `chunk_text()` в [support_service.py:496](../backend/app/services/support_service.py#L496) режет текст ровно по `CHUNK_SIZE=1000` символов — контекст разрывается на полуслове.

**Что реализовать:**

- `backend/app/services/support_service.py` — переписать `chunk_text()`:
  - Искать ближайшую границу предложения (`\n`, `. `, `? `, `! `) внутри окна `[CHUNK_SIZE - 200, CHUNK_SIZE]`
  - Если граница не найдена — резать по пробелу
  - Жёсткий лимит остаётся как fallback

---

### 3.2 Семантический FAQ-матчинг

**Проблема:** `find_faq_match()` использует только текстовое/лексическое сходство. Перефразированные вопросы не попадают в FAQ.

**Что реализовать:**

- `backend/app/services/support_service.py`
  - При `create_faq_entry()` и `update_faq_entry()` — индексировать embedding FAQ-вопроса в Qdrant (отдельная коллекция `faq_embeddings` или payload-тег `type=faq` в существующей коллекции)
  - Добавить `find_faq_match_semantic(question)` — семантический поиск по FAQ в Qdrant
  - В `run_support_pipeline()` — запускать семантический FAQ-поиск параллельно с лексическим, брать максимум из двух скоров
- `backend/app/api/routes/admin_support.py`
  - При `DELETE /admin/faq/{id}` — удалять вектор из Qdrant
  - При `PATCH /admin/faq/{id}` — переиндексировать вектор

---

### 3.3 Контекст диалога в LLM-промпте

**Проблема:** Каждый вопрос обрабатывается изолированно, хотя `session_id` сохраняется в БД.

**Что реализовать:**

- `backend/app/services/support_service.py`
  - Изменить сигнатуру `_build_prompt(question, results, history=None)` — принимать историю диалога
  - В `run_support_pipeline()` — перед вызовом `generate_answer()` загружать последние 3 пары вопрос/ответ из истории сессии через `list_support_history()`
  - В промпте добавить блок:
    ```
    История диалога (последние сообщения):
    Пользователь: ...
    Ассистент: ...
    ```

---

## Блок 4: Безопасность (🟢 Желательно)

### 4.1 Rate limiting на `/support/ask`

**Проблема:** Нет ограничения частоты. Залогиненный пользователь может спамить LLM-вызовами.

**Что реализовать:**

- Подключить `slowapi` (`pip install slowapi`)
- `backend/app/main.py` — инициализировать Limiter, добавить handler для 429
- `backend/app/api/routes/support.py` — декоратор `@limiter.limit("20/minute")` на `ask_support_question`

---

### 4.2 Дедупликация источников

**Проблема:** Один URL или файл можно загрузить дважды — дублирование чанков в Qdrant.

**Что реализовать:**

- `backend/app/models.py` — добавить поле `content_hash: str | None` (SHA-256) в `KnowledgeSource`
- `backend/app/services/support_service.py` — функция `compute_content_hash(content: str) -> str`
- `backend/app/api/routes/admin_support.py` — перед созданием источника проверять хэш, возвращать `409 Conflict` если уже существует
- Alembic-миграция: добавить колонку `content_hash`

---

## Итоговая таблица задач

| # | Задача | Приоритет | Файлы |
|---|--------|-----------|-------|
| 1.1 | OperatorReply: модель + endpoint + my-queue | 🔴 | `models.py`, `support_service.py`, `admin_support.py`, `support.py` + миграция |
| 1.2 | Статус `operator_replied` | 🔴 | `models.py`, `support_service.py` |
| 2.1 | BackgroundTasks для индексирования | 🟠 | `admin_support.py` |
| 2.2 | SQL-агрегаты в метриках | 🟠 | `support_service.py` |
| 2.3 | Пагинация + фильтр очереди | 🟠 | `admin_support.py`, `support_service.py` |
| 3.1 | Умный chunking | 🟡 | `support_service.py` |
| 3.2 | Семантический FAQ | 🟡 | `support_service.py`, `admin_support.py` |
| 3.3 | Контекст диалога в промпте | 🟡 | `support_service.py` |
| 4.1 | Rate limiting | 🟢 | `main.py`, `support.py` |
| 4.2 | Дедупликация источников | 🟢 | `models.py`, `admin_support.py` + миграция |
