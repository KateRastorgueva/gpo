# План реализации схемы БД (support desk)

Статус: Draft v0.3 (уточнена механика журнала: hot/cold-разделение запросов)
Дата: 2026-04-02
Основание: диаграмма БД (13 сущностей) + ответы владельца по открытым вопросам.

Документ описывает переход от текущей схемы к целевой: решения, целевая модель, разрывы,
миграции, изменения в коде, фазы работ, риски и оставшиеся вопросы.

История версий: v0.1 — первичный план; v0.2 — слияние FAQ с БЗ, RBAC без `is_superuser`,
независимый корпус документов, переоткрытие тикетов, переименования в отдельной миграции,
исправлены противоречия A6/M4-M5, добавлен `support_request.updated_at`, уточнён wildcard
в разрешениях, проработана фильтрация в Qdrant, снят UNIQUE у тикетов.
v0.3 — журнал запросов переопределён как архив всех запросов (hot/cold-разделение ради
производительности на растущей БД), добавлен §0.3 с разбором FK-ловушки и выбором механики.

## Статус реализации

| Миграция | Что | Статус |
|---|---|---|
| M0 `8f4c1a2b7d90` | переименование таблиц в snake_case | ✅ применено, проверен round-trip |
| M1 `c5a9e3d1b746` | роли, `role_id`/`phone`, бэкфилл + RBAC в коде | ✅ применено, проверено |
| M2 `a7c4e1b93d52` | жизненный цикл запроса + горячая очередь `active_request` | ✅ применено, проверен round-trip |
| M9 `e6b2f8a41c73` | слияние FAQ в базу знаний (`source_type='faq'`), `faqentry` удалена | ✅ применено, проверен round-trip, UUID сохранены |
| M3 `f2d5a8c14b60` | таксономия: `knowledge_category`, `tag`, `knowledge_tag`, `knowledge_source.category_id` | ✅ применено, проверен round-trip |
| M4 `b8e4c7d29a51` | `knowledge_doc` + `doc_tag`, обобщение `knowledge_chunk` (CHECK на владельца), payload и payload-индексы Qdrant (D4) | ✅ применено, round-trip + проверка payload/фильтров на живом Qdrant |
| M5 `d4a1f7c83e26` | `knowledge_archive` (снапшоты версий), мягкое удаление источника, ретенция версий | ✅ применено, проверен round-trip |
| M6 `c9f3b1e64d07` | журнал ответов как шаги (1:N), `is_final`, `response_time_ms`, FK на знание/чанк | ✅ применено, round-trip + проверка защиты отката |
| M7 `e2b7d5a91f38` | тикеты: назначение агента, решение, переоткрытие, частичный уникальный индекс | ✅ применено, round-trip + проверка защиты отката |
| M8 `f5c8a2d64b19` | отзывы (один на запрос, CHECK 1..5) + метрики средней оценки | ✅ применено, проверен round-trip |
| M10 `a1e9c4f72b58` | удаление `is_superuser` (в API — производное поле) | ✅ применено, проверен round-trip |

Проверки на момент завершения: `ruff` — чисто; `mypy` (strict) — 11 ошибок (было 17:
шесть baseline-ошибок устранены попутно, новых нет); backend-тесты — **111 passed** на
отдельной базе `app_test`; покрытие 80%.

Фаза 7 (документация) закрыта: обновлены `CURRENT_VERSION.md`, `TD.md`, `LINKS.md`,
`docs/backend-architecture.md`, `docs/testing.md`, `AGENT_HANDOFF.md`.

UI под новые возможности сделан (после починки фронтенд-тулкина): `/admin-support` — восемь
вкладок (метрики, очередь и журнал, тикеты, база знаний с архивом версий, документы,
категории и тэги, поиск с фильтрами, частые вопросы), `/support` — ответ со шагами обработки
и оценкой 1–5. Управление пользователями переведено на выбор роли (`GET /users/roles`),
потому что после M10 прежний чекбокс «Is superuser?» молча игнорировался.

Доступы в UI строятся по правам роли: `/users/me` отдаёт `permissions`, и от них зависят
ссылки сайдбара, состав вкладок и доступные действия (оператор видит обращения и метрики,
знания — только на чтение; управление пользователями только у `user:manage`). Права задаются
ролью, индивидуальных исключений для пользователя схема не содержит.

Осталось за пределами плана: гейт покрытия CI (80% против 90%),
ужесточение `app_user.role_id` до NOT NULL, индивидуальные права пользователя.
Таблица `item` удалена (решение владельца, миграция `9e7c2b41d805`).

---

## 0. Scope, решения владельца и допущения

В scope: персистентный слой (SQLModel + Alembic), сервисная логика, API-контракты,
необходимый UI, тесты, документация. Telegram — вне scope (`AGENTS.md`).

### 0.1 Решения владельца (зафиксированы, не обсуждаются)

| # | Решение | Следствие для плана |
|---|---|---|
| V1 | **FAQ — это и есть база знаний** | `faqentry` сливается в `knowledge_source`; FAQ-ступень маршрутизации работает по записям БЗ; отдельной FAQ-таблицы и `/admin/faq` не остаётся |
| V2 | **Набор ролей фиксированный, `is_superuser` не используем** | RBAC на таблице `role`; колонка `is_superuser` удаляется (M10) |
| V3 | **«Журнал запросов» — архив ВСЕХ запросов** (расчёт на рост БД, чтобы запросы оставались быстрыми); «активные запросы» — то, что висит в очереди | Две таблицы: `request_journal` (все запросы, источник правды) + `active_request` (горячее рабочее множество очереди). Механика и обоснование — §0.3 |
| V4 | **БЗ доков — независимая таблица с отдельной индексацией** | `knowledge_doc` без FK на знание; свои чанки и свой путь индексации |
| V5 | **В архиве БЗ хранятся старые данные (снапшоты)** | `knowledge_archive` с полным снапшотом контента |
| V6 | **Архив БЗ уничтожается при удалении источника** | `knowledge_archive.knowledge_id` → `ON DELETE CASCADE` |
| V7 | **Отзыв один на запрос** | `UNIQUE(request_id)` в `support_feedback` |
| V8 | **Тикет должен уметь переоткрываться** | 1:N тикетов на запрос + частичный уникальный индекс «один активный тикет» |
| V9 | **Переименование делаем** | Отдельная первая миграция M0, дальше везде финальные имена |

Допущения (мои, при несогласии — править до старта):

- **A1.** Набор ролей — `admin`, `operator`, `user` с матрицей разрешений (§2.1). Вы написали
  «набор такой», не перечислив его; здесь взята матрица из v0.1. Если набор другой — сказать,
  меняется только seed и матрица, структура не затрагивается.
- **A2.** Схема разделения запросов — по §0.3: журнал (`request_journal`) как источник правды
  и `active_request` как горячее множество очереди. Это единственный вариант «двух таблиц»,
  при котором не рвётся ссылочная целостность; отвергнутые альтернативы разобраны там же.
- **A3.** `knowledge_chunk` остаётся: на неё ссылаются payload-и Qdrant (`chunk_id`, `source_id`).
- **A4.** Поля `mode`, `confidence`, `fallback_used`, `escalated`, `session_id` в запросе
  сохраняются: на них держатся маршрутизация, объяснимость ответа и метрики.
- **A5.** Существующие UUID не меняются (payload в Qdrant хранит UUID строками).
- **A6.** `item` — наследство шаблона; в целевой модели отсутствует. Решение принято:
  таблица и её API удалены (миграция `9e7c2b41d805`, §11 вопрос 1 закрыт).
- **A7.** `hashed_password` остаётся, хотя в диаграмме не показан: без него нет аутентификации.

### 0.2 Противоречие, требующее вашего подтверждения

В вашем сообщении два взаимоисключающих указания по архиву:

- решение **V6**: «Архив БЗ уничтожается при удалении источника»;
- замечание ревью: «CASCADE противоречит смыслу архива, нужно SET NULL / nullable без FK /
  отдельное хранилище снапшотов».

В плане я следую вашему явному решению (**V6, CASCADE**), но добавляю компенсацию:
**основной путь удаления в UI — мягкое удаление** (`is_active = false` + `status = 'deleted'`),
при котором источник исчезает из активной базы, но архив остаётся. Жёсткое удаление
(`DELETE /admin/sources/{id}?hard=true`) сохраняет текущее поведение и уничтожает архив вместе
с источником — это должно быть явно написано в подтверждении в UI. Если мягкое удаление
не нужно — убираем его из фазы 3, но тогда потеря истории при случайном удалении необратима.

### 0.3 Механика hot/cold-разделения запросов (V3)

Задача: «активные запросы» (очередь) должны отвечаться быстро независимо от того, что
«журнал запросов» растёт неограниченно.

**FK-ловушка, из-за которой наивные «две таблицы с переносом строк» не работают.**
Если запрос физически переезжает из `active_request` в `request_journal` (INSERT + DELETE),
то дочерние таблицы (`answer_journal`, `support_ticket`, `support_feedback`) оказываются
в безвыходном положении:

- FK на **активную** таблицу → при переносе строка удаляется, и `ON DELETE CASCADE` уничтожит
  журнал ответов и тикет вместе с ней. Это тихая потеря данных.
- FK на **журнальную** таблицу → тоже нельзя: тикет создаётся в момент эскалации, когда запрос
  ещё активен, то есть родительской строки в журнале ещё нет.
- Совсем без FK → теряется ссылочная целостность и каскады.

Вариант с партиционированием одной таблицы по `status`/`created_at` тоже не спасает:
в PostgreSQL уникальный ключ партиционированной таблицы обязан включать ключ партиционирования,
а значит PK станет составным `(id, status)`, и все FK детей придётся делать составными.

**Принятая механика (A2): журнал — источник правды, «активные» — горячее множество.**

```text
request_journal   (растёт: все запросы, включая активные)   ← PK id, сюда смотрят все FK
      ▲
      │ 1:1 (request_id, PK/FK, CASCADE)
active_request    (маленькая: только то, что сейчас в очереди)

answer_journal / support_ticket / support_feedback → FK на request_journal.id (никогда не рвётся)
```

- Постановка в очередь = `INSERT INTO active_request`; ответ/эскалация = работа с журналом;
  завершение = `DELETE FROM active_request`. **Строки между таблицами не переносятся**,
  поэтому FK и каскады остаются корректными навсегда.
- Скорость очереди: запрос идёт по `active_request` (маленькая, всегда в кеше) — при
  денормализации текста вопроса вообще без join. Журнал — большая таблица с индексами
  `(user_id, created_at DESC)`, `(created_at DESC)`, `(status)`; при дальнейшем росте
  партиционируется по месяцам без изменения остальной схемы.
- Формулировка V3 «журнал — архив всех существующих запросов» выполняется буквально:
  в `request_journal` попадает каждый запрос с момента создания.
- Цена: текст вопроса и `user_id` дублируются в `active_request` (денормализация ради скорости).
  Это осознанный размен, а не случайное дублирование.

Отвергнуто: перенос строк между таблицами (ломает FK), партиционирование по статусу
(составные PK/FK), отказ от FK (потеря целостности).

---

## 1. AS-IS (проверено по коду)

Head миграции: `3f2d3d2d6e45`. Цепочка линейна:
`e2412789c190` → `9c0a54914c78` → `d98dd8ec85a3` → `1a31ce608336` → `fe56fa70289e` → `3f2d3d2d6e45`.

| Таблица | Ключевые поля | Что важно для плана |
|---|---|---|
| `user` | email, hashed_password, is_active, **is_superuser**, full_name, created_at | нет phone и роли; имя таблицы — зарезервированное слово |
| `item` | title, description, owner_id | наследство шаблона (A6) — удалено |
| `faqentry` | question, answer, is_active, normalized_question | по V1 сливается в БЗ и удаляется |
| `knowledgesource` | title, source_type, source_ref, is_active, content, status, last_indexed_at, created_at, updated_at | `source_type` различает faq/pdf/txt/url/manual — пригодится после слияния |
| `knowledgechunk` | source_id, chunk_index, content, vector_id (unique) | потребуется обобщение под доки (V4) |
| `supportrequest` | user_id (nullable), session_id, channel, question, mode, confidence, fallback_used, escalated, status, created_at | нет `updated_at`, нет разметки жизненного цикла (V3) |
| `supportanswer` | request_id, answer, sources_json, created_at | **`request_id` UNIQUE → 1:1** |
| `operatorqueue` | request_id, reason, status, created_at, updated_at | **`request_id` UNIQUE → 1:1** |

Проверенные факты по коду:

- RBAC отсутствует: единственная проверка — `is_superuser` в `backend/app/api/deps.py:53`,
  `get_current_active_superuser` защищает весь `/api/v1/admin/*`.
- Логики категорий/тэгов/документов/архива/отзывов нет (поиск по `role|permission|category|tag`
  даёт только `route.tags`, HTML-теги и `ENVIRONMENT`).
- Нет `PATCH /admin/sources/{id}`; `CURRENT_VERSION.md:19` заявляет `GET/POST/DELETE /admin/sources`,
  хотя существует только `/sources/upload` и `/sources/upload-json` — расхождение документации.
- Нет ни одного эндпоинта смены статуса тикета: `operatorqueue` только читается, статусы
  `in_progress`/`closed` недостижимы из UI, «ответ оператора» не закрыт (`TD.md:60`).
- Данные заводятся не миграциями: `scripts/import-tusur-sources.ps1` + `tusur_sources_seed_v1.json`;
  `initial_data.py` создаёт только первого суперпользователя (`backend/app/core/db.py:31`).
- `backend/tests/conftest.py:24-39` чистит таблицы рабочей БД — блокирующий риск для миграций (R1).

---

## 2. TO-BE: целевая модель

Имена таблиц — финальные (snake_case), применяются миграцией M0. Жирным — то, чего нет
в диаграмме, но что обязательно для работы системы.

### 2.1 Доступ

```python
class Role(SQLModel, table=True):
    __tablename__ = "role"
    id: uuid.UUID                 # PK
    name: str                     # unique, index, max 50: admin | operator | user
    permissions: list[str]        # JSON; для admin: ["*"] — wildcard
    created_at: datetime
```

```python
class User(...):                  # таблица app_user
    __tablename__ = "app_user"
    role_id: uuid.UUID | None     # FK role.id, index; nullable — см. примечание ниже
    phone: str | None             # max 32
    # email (unique), hashed_password, is_active, full_name, created_at — без изменений
    # is_superuser — удаляется в M10
```

Каталог разрешений (`backend/app/core/permissions.py`):

```python
WILDCARD = "*"
KNOWLEDGE_READ   = "knowledge:read"
KNOWLEDGE_WRITE  = "knowledge:write"
FAQ_WRITE        = "knowledge:write"   # FAQ = БЗ (V1), отдельного права нет
TICKET_READ      = "ticket:read"
TICKET_RESOLVE   = "ticket:resolve"
METRICS_READ     = "metrics:read"
USER_MANAGE      = "user:manage"
TAXONOMY_WRITE   = "taxonomy:write"    # категории и тэги
```

Матрица: `admin` → `["*"]`; `operator` → `knowledge:read`, `ticket:read`, `ticket:resolve`,
`metrics:read`; `user` → `[]`.

Проверка прав (**исправление замечания ревью по D2**):

```python
def has_permission(user: User, permission: str) -> bool:
    role = user.role
    if role is None:
        return False
    return WILDCARD in role.permissions or permission in role.permissions
```

`require_permission("*")` больше нигде не используется: для «любого права» вызывается
`require_permission(...)` с конкретным правом, а wildcard раскрывается внутри `has_permission`.
Явного `admin:all` не вводим — один механизм вместо двух.

### 2.2 База знаний (FAQ + документы)

```python
class KnowledgeSource:            # таблица knowledge_source — "База знаний акт."
    id: uuid.UUID                 # PK
    title: str                    # max 255, "Заголовок"
    normalized_title: str         # max 255, index — для FAQ-ступени (V1)
    content: str                  # "Содержание"
    source_type: str              # max 20: faq | manual | url | pdf | txt  (V1: faq здесь)
    source_ref: str | None        # max 1024
    is_active: bool               # "Используется" (D3)
    status: str                   # pending | indexed | failed | deleted
    category_id: uuid.UUID | None # FK knowledge_category.id ON DELETE SET NULL, index
    last_indexed_at: datetime | None
    created_at, updated_at
```

```python
class KnowledgeCategory:          # "Категории"
    __tablename__ = "knowledge_category"
    id, name (unique, max 120), created_at

class Tag:                        # "Тэг"
    __tablename__ = "tag"
    id, name (unique, index, max 80), created_at

class KnowledgeTag:               # "Тэг-знание" (составной PK)
    __tablename__ = "knowledge_tag"
    knowledge_id: FK knowledge_source.id CASCADE   # PK
    tag_id:       FK tag.id CASCADE                # PK

class KnowledgeDoc:               # "БЗ доков" — независимый корпус (V4)
    __tablename__ = "knowledge_doc"
    id: uuid.UUID                 # PK
    title: str                    # max 255
    url: str                      # max 1024, "Ссылка на док"
    status: str                   # pending | indexed | failed
    last_indexed_at: datetime | None
    created_at, updated_at
    # FK на knowledge_source НЕТ — по V4 это независимая сущность

class DocTag:                     # "Тэг-док" (составной PK)
    __tablename__ = "doc_tag"
    doc_id: FK knowledge_doc.id CASCADE            # PK
    tag_id: FK tag.id CASCADE                      # PK
```

Чанки — одна таблица на два корпуса (обоснование в D9):

```python
class KnowledgeChunk:             # таблица knowledge_chunk
    id: uuid.UUID                 # PK
    source_id: uuid.UUID | None   # FK knowledge_source.id CASCADE
    doc_id: uuid.UUID | None      # FK knowledge_doc.id CASCADE    ← новое
    chunk_index: int
    content: str
    vector_id: str                # unique
    created_at
    # CHECK (num_nonnulls(source_id, doc_id) = 1)  — чанк принадлежит ровно одному корпусу
```

### 2.3 Архив

```python
class KnowledgeArchive:           # "Архив БЗ"
    __tablename__ = "knowledge_archive"
    id: uuid.UUID
    knowledge_id: uuid.UUID       # FK knowledge_source.id ON DELETE CASCADE (V6), index
    version: int                  # unique(knowledge_id, version)
    title: str                    # снапшот
    content: str                  # снапшот (V5)
    category_id: uuid.UUID | None
    tags_json: list[str]          # снапшот тэгов на момент версии
    source_type: str
    archived_at: datetime
    archived_by: uuid.UUID | None # FK app_user.id — кто изменил/удалил
```

### 2.4 Обращения, журнал, тикеты, отзывы

```python
class RequestJournalEntry:        # таблица request_journal — "Журнал запросов" (V3, §0.3)
    id: uuid.UUID                 # PK — единый id запроса на всю его жизнь
    user_id: uuid.UUID | None     # FK app_user.id, index
    session_id: str
    channel: str                  # "Источник запроса"
    question: str                 # "Текст запроса" (снапшот для архива)
    mode, confidence, fallback_used, escalated        # A4
    status: str                   # queued | in_progress | answered | closed
    created_at, updated_at        # ← updated_at добавлен (M2)
    answered_at: datetime | None  # ← момент финального ответа
    closed_at: datetime | None
    # индексы: (user_id, created_at DESC), (created_at DESC), (status)
    # ВАЖНО: здесь лежит КАЖДЫЙ запрос, включая активные — это источник правды

class ActiveRequest:              # таблица active_request — "Активные запросы" (§0.3)
    request_id: uuid.UUID         # PK, FK request_journal.id ON DELETE CASCADE
    user_id: uuid.UUID | None     # денормализация ради скорости очереди
    question: str                 # денормализация ради скорости очереди
    channel: str
    priority: int = 0             # порядок разбора
    assigned_to: uuid.UUID | None # FK app_user.id — кто взял в работу
    queued_at: datetime
    updated_at: datetime | None
    # индексы: (priority, queued_at), (assigned_to)
    # Строки между request_journal и active_request НЕ переносятся:
    # постановка в очередь = INSERT, завершение = DELETE.
```

```python
class AnswerJournalEntry:         # таблица answer_journal — "Журнал запросов"
    id: uuid.UUID
    request_id: uuid.UUID         # FK request_journal.id CASCADE, index — БЕЗ UNIQUE (1:N)
    step: str                     # max 20: faq | rag | operator | human
    step_index: int               # unique(request_id, step_index)
    performed_by: uuid.UUID | None      # FK app_user.id — "ID выполнявшего"
    knowledge_id: uuid.UUID | None      # FK knowledge_source.id ON DELETE SET NULL — "ID БЗ"
    knowledge_chunk_id: uuid.UUID | None # FK knowledge_chunk.id ON DELETE SET NULL
    answer: str                   # max 8000 — "Текст ответа"
    sources_json: JSON
    is_final: bool                # "Завершено на данном шаге"
    response_time_ms: int | None  # "Время ответа"
    created_at
```

```python
class SupportTicket:              # таблица support_ticket — "Тикеты поддержки"
    id: uuid.UUID
    request_id: uuid.UUID         # FK request_journal.id CASCADE, index — БЕЗ UNIQUE (V8)
    assigned_to: uuid.UUID | None # FK app_user.id — "ID агента"
    status: str                   # open | in_progress | resolved | closed
    reason: str                   # max 500 (сохраняется из operatorqueue)
    resolution: str | None        # max 4000 — "Итоговое решение"
    reopened_from_id: uuid.UUID | None  # self-FK: из какого тикета переоткрыт
    created_at, updated_at, resolved_at
    # частичный уникальный индекс: UNIQUE(request_id) WHERE status IN ('open','in_progress')
```

```python
class SupportFeedback:            # "Отзывы"
    __tablename__ = "support_feedback"
    id: uuid.UUID
    request_id: uuid.UUID         # FK request_journal.id CASCADE, UNIQUE (V7), index
    user_id: uuid.UUID | None     # FK app_user.id
    rating: int                   # CHECK 1..5
    comment: str | None           # max 2000
    submitted_at: datetime
```

---

## 3. Ключевые технические решения

**D1. Журнал ответов — 1:N, и это центральное изменение.**
`supportanswer.request_id` сейчас UNIQUE, то есть на запрос физически пишется один ответ.
Журнал требует шагов (БЗ → ИИ → агент) и ответа оператора после эскалации. Решение: снять UNIQUE,
добавить `step` + `step_index` и `UNIQUE(request_id, step_index)`.
`_record_support_result` (`backend/app/services/support_service.py:795-849`) начинает писать
список записей. Контракт `GET /support/history` **не ломаем**: поле `answer` (финальный шаг)
остаётся, добавляется `steps: list[...]`.

**D2. RBAC вместо `is_superuser`, без двойного источника правды.**
По V2 `is_superuser` не используется как механизм доступа. Колонка перестаёт читаться кодом
в фазе 1 и физически удаляется в M10. Wildcard `"*"` — единственный способ выдать «всё»
(см. §2.1), это закрывает замечание ревью о несогласованности `require_permission("admin")`.

**D3. `is_active` источника = «Используется».** Второй флаг не заводим.

**D4. Фильтрация по категориям и тэгам — на стороне Qdrant, а не post-filter.**
Это прямое исправление замечания ревью. При индексации в payload точки добавляются
`owner_type` (`source` | `doc`), `category_id`, `tag_ids`; в коллекции создаются payload-индексы:

```
PUT /collections/{collection}/index   {"field_name": "owner_type",  "field_schema": "keyword"}
PUT /collections/{collection}/index   {"field_name": "category_id", "field_schema": "keyword"}
PUT /collections/{collection}/index   {"field_name": "tag_ids",     "field_schema": "keyword"}
```

Поиск выполняется с `filter` (must: owner_type; must: category_id; must: tag_ids match any),
то есть отбор идёт **до** top-k, recall не страдает. Смена категории или набора тэгов
**не требует переэмбеддинга**: payload обновляется точечно

```
POST /collections/{collection}/points/payload
{"payload": {"tag_ids": [...]}, "filter": {"must": [{"key": "source_id", "match": {"value": "<uuid>"}}]}}
```

Переиндексация нужна только при смене текста, чанкинга или модели эмбеддингов.
Лексический поиск фильтруется join'ом на `knowledge_tag`/`doc_tag` как обычно.

**D5. Архив пишется сервисом, а не триггером БД.**
Снапшот создаётся в сервисных функциях обновления/удаления (`archive_knowledge(...)`) — это
тестируемо и не требует прав на триггеры. Снапшот пишется только по факту update/delete,
с ограничением размера и ретенцией по числу версий (R4).

**D6. Переименования — отдельной первой миграцией M0.**
Это устраняет противоречие v0.1 (A6 против M4/M5). Порядок: сначала механические переименования
без изменения структуры, затем всё остальное уже на финальных именах.
Список: `knowledgesource` → `knowledge_source`, `knowledgechunk` → `knowledge_chunk`,
`supportrequest` → `support_request`, `supportanswer` → `answer_journal`,
`operatorqueue` → `support_ticket`, `user` → `app_user` (зарезервированное слово в PostgreSQL).
Индексы и constraint'ы переименовываются явно (`ALTER INDEX ... RENAME TO ...`), потому что
PostgreSQL при `ALTER TABLE RENAME` имена индексов не меняет.

**D7. Одна миграция — один логический блок** (§4), каждая с `downgrade()`.

**D8. FAQ = БЗ (V1): как именно.**
`faqentry` сливается в `knowledge_source` со `source_type = 'faq'`:
`question → title` (+ `normalized_title`), `answer → content`, `is_active`/`created_at`/`updated_at`
переносятся как есть. Ступень FAQ в маршрутизации (`find_faq_match`) начинает искать по
`knowledge_source.normalized_title` среди записей с `source_type = 'faq'`;
`FAQ_SIMILARITY_THRESHOLD = 0.90` сохраняется. Следствия: `/admin/faq*` уходит (заменяется
CRUD по БЗ), в UI вкладка FAQ становится «База знаний», тесты `test_support.py` и
`test_support_reference_60.py` переписываются на новую сущность.

**Уточнение по реализации (принято после проверки фазы 1):** чтобы M9 не ломала API и UI сразу,
`/admin/faq*` сохраняется как **фасад** над `knowledge_source` (`source_type='faq'`): сигнатуры
`FaqEntryCreate`/`FaqEntryPublic` и функции `create_faq_entry`/`update_faq_entry`/`find_faq_match`
остаются, меняется только хранилище. Тогда текущий админский UI и тесты продолжают работать,
а перенос UI на knowledge CRUD (с категориями и тэгами) делается в фазе 6 без спешки.
Это осознанное отклонение от «breaking change» из v0.2 и зафиксировано здесь.
Отдельно: слияние не лечит известную слабость эвристики (`_faq_keyword_similarity` даёт 0.95
при полном покрытии ключевых слов, `support_service.py:252-253`), из-за чего короткие запросы
дают ложные попадания. Рекомендую поправить в той же фазе, но это отдельная задача.

**D9. Документы индексируются независимо, но чанки живут в одной таблице.**
`knowledge_doc` не связан с `knowledge_source` (V4). Отдельная индексация = свой путь
`index_doc()` / `reindex_docs()` и свой `owner_type` в payload. Чанки при этом остаются в
`knowledge_chunk` с двумя nullable FK и CHECK `num_nonnulls(source_id, doc_id) = 1`, потому что:
(1) одна логика чанкинга/эмбеддингов/очистки сирот (`remove_orphan_vectors` уже сверяет
`chunk_id` с этой таблицей); (2) `chunk_id` уникален глобально, а значит гибридный merge
(`_merge_hybrid_results`) продолжает работать без изменений.

**D10. Hot/cold-разделение запросов: `request_journal` — источник правды, `active_request` — очередь.**
Механика и разбор FK-ловушки — §0.3. Строки между таблицами не переносятся, поэтому каскады
и ссылочная целостность сохраняются; очередь читается из маленькой `active_request`,
журнал растёт отдельно и при необходимости партиционируется по месяцам.

---

## 4. Миграции

Правила: обязательный `downgrade()`, бэкфилл внутри миграции, новые FK — сначала nullable,
`NOT NULL` — только при доказуемо полном бэкфилле, разрушительные шаги — с пометкой в docstring.

| № | Имя | Содержание | Бэкфилл |
|---|---|---|---|
| **M0** | `rename_legacy_tables` | rename 6 таблиц (D6) + rename индексов: `supportrequest` → `request_journal` (финальное имя сразу, см. D10) | нет (механика) |
| **M1** | `roles_and_permissions` | create `role`; ALTER `app_user`: `+phone`, `+role_id` (FK, index) | seed `admin`/`operator`/`user`; `is_superuser=true → admin`, иначе `user`; проверка `count(role_id IS NULL) = 0`; затем `SET NOT NULL` |
| **M2** | `request_lifecycle` | ALTER `request_journal`: `+updated_at`, `+answered_at`, `+closed_at`; индексы `(user_id, created_at DESC)`, `(created_at DESC)`, `(status)`; CREATE `active_request` (PK/FK на журнал, денормализация `user_id`/`question`/`channel`, `priority`, `assigned_to`) | `status='answered'`, `answered_at` из `answer_journal.created_at` для запросов с ответом; остальные → `queued`; заполнить `active_request` для незавершённых |
| **M3** | `knowledge_taxonomy` | create `knowledge_category`, `tag`, `knowledge_tag`; ALTER `knowledge_source`: `+category_id` | опционально: категория «Без категории» и привязка существующих источников |
| **M4** | `knowledge_docs_and_chunks` | create `knowledge_doc`, `doc_tag`; ALTER `knowledge_chunk`: `source_id` → nullable, `+doc_id`, CHECK `num_nonnulls(source_id, doc_id) = 1`, index на `doc_id` | нет |
| **M5** | `knowledge_archive` | create `knowledge_archive` + `unique(knowledge_id, version)` + index | нет |
| **M6** | `answer_journal_steps` | ALTER `answer_journal`: DROP UNIQUE(`request_id`); ADD `step`, `step_index`, `performed_by`, `knowledge_id`, `knowledge_chunk_id`, `is_final`, `response_time_ms`; `unique(request_id, step_index)` | `step = support_request.mode`, `step_index = 0`, `is_final = true` |
| **M7** | `ticket_workflow` | ALTER `support_ticket`: DROP UNIQUE(`request_id`); ADD `assigned_to`, `resolution`, `reopened_from_id`, `resolved_at`; index(`status`); частичный unique `(request_id) WHERE status IN ('open','in_progress')` | нет |
| **M8** | `support_feedback` | create `support_feedback` + `unique(request_id)` + CHECK `rating BETWEEN 1 AND 5` | нет |
| **M9** | `faq_merge_into_knowledge` | INSERT из `faqentry` в `knowledge_source` (`source_type='faq'`, `status='pending'`); DROP TABLE `faqentry` | перенос 1:1 **с сохранением UUID** (исторические `sources_json` продолжают резолвиться). Колонка `normalized_title` не добавляется: `faq_similarity` нормализует строки сама |
| **M10** | `drop_superuser_flag` | ALTER `app_user`: DROP COLUMN `is_superuser` | выполняется только после того, как код перестал её читать (фаза 7) |
| **M11** | *(опционально)* `embeddings_metadata` | таблица-инвариант векторного пространства: provider, model, dim, created_at | текущие настройки из `settings` |

Порядок применения: M0 → M1 → M2 → M9 (FAQ) → M3 → M4 → M5 → M6 → M7 → M8 → M10.

M9 стоит раньше таксономии, потому что после слияния `knowledge_source` становится единственной
точкой входа для FAQ, категорий и тэгов — иначе `retrieval` и админку придётся править дважды.

Проверка каждой миграции:

```bash
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Обратимость: M0–M3, M5, M7, M8, M9, M10 откатываются без потери данных (M9 — с потерей строк
FAQ, восстановимых только из бэкапа; M10 — с потерей флага). **M6 и M7 необратимы по данным,
если после них у запроса появилось больше одной записи журнала или больше одного тикета**:
`DROP UNIQUE` назад не восстанавливается без удаления лишних строк. Это фиксируется в docstring
обеих миграций и требует `pg_dump` перед применением.

---

## 5. Изменения в backend

**`backend/app/models.py`** — новые: `Role`, `KnowledgeCategory`, `Tag`, `KnowledgeTag`,
`KnowledgeDoc`, `DocTag`, `KnowledgeArchive`, `AnswerJournalEntry` (вместо `SupportAnswer`),
`SupportTicket` (вместо `OperatorQueue`), `SupportFeedback`; правки: `User` (+`phone`, +`role_id`, −`is_superuser`), `KnowledgeSource` (+`category_id`,
+`normalized_title`), `SupportRequest` → `RequestJournalEntry` (+`updated_at`, `answered_at`,
`closed_at`), новый `ActiveRequest` (§0.3), `KnowledgeChunk` (+`doc_id`); `FaqEntry` удаляется.
Публичные схемы: `RolePublic`, `KnowledgeCategoryPublic`, `TagPublic`, `DocPublic`,
`FeedbackCreate/Public`, `TicketPublic`; `SupportHistoryEntry` (+`steps`, `answer` сохранён).

**`backend/app/core/permissions.py`** (новый) — каталог разрешений, `has_permission`, матрица ролей.

**`backend/app/core/db.py`** — идемпотентный seed ролей; создание первого пользователя сразу
с ролью `admin` (сейчас `is_superuser=True`, `db.py:31`).

**`backend/app/api/deps.py`** — `require_permission(permission)` как фабрика зависимостей;
`get_current_active_superuser` удаляется вместе с `is_superuser`.

**`backend/app/services/support_service.py`**
- `find_faq_match` → поиск по `knowledge_source` (`source_type='faq'`, `normalized_title`) (D8);
- `_record_support_result` → запись журнала шагами, `knowledge_id` из top-1 источника,
  `response_time_ms` через `time.perf_counter()`, `step_index`, обновление
  `support_request.status`/`answered_at`/`updated_at`;
- `retrieve_*` → Qdrant `filter` по `owner_type`/`category_id`/`tag_ids` (D4) + общий поиск
  по двум корпусам (source и doc) с merge по `chunk_id`;
- `reindex_sources`/`delete_source` → `archive_knowledge(...)` перед изменением (D5),
  мягкое удаление по умолчанию (см. §0.2);
- новые: `index_doc`/`reindex_docs` (V4), CRUD категорий/тэгов/документов,
  `sync_chunk_payload_tags` (обновление payload без переэмбеддинга),
  `create_ticket`/`assign_ticket`/`resolve_ticket`/`reopen_ticket` (V8),
  `create_feedback`, метрики качества (средний рейтинг, доля отзывов, p50/p95 ответа).

**`backend/app/api/routes/`**
- `admin_support.py`: `+ /admin/categories`, `+ /admin/tags`, `+ /admin/docs` (CRUD),
  `+ PATCH /admin/sources/{id}` (отсутствует), `+ POST /admin/sources/{id}/archive` (мягкое удаление),
  `+ PATCH /admin/tickets/{id}` (assign/resolve/reopen), `+ GET /admin/requests` (активные/журнал
  с фильтром по статусу), расширение `/admin/metrics`; `/admin/faq*` удаляются (D8);
- `support.py`: `+ POST /support/feedback`; `/support/history` — аддитивно (+`steps`).

**Совместимость API.** Поля `answer`, `mode`, `confidence`, `sources`, `fallback_used`,
`decision_metrics` сохраняются. Явные breaking changes: удаление `/admin/faq*` (замена на БЗ)
и появление `steps`. Фиксируются в `CURRENT_VERSION.md` и в описании релиза (`AGENTS.md` §8).

---

## 6. Frontend

- `/support`: отзыв после ответа (1–5 + комментарий, один на запрос), отображение шагов журнала,
  обработка ошибок/пустых состояний (сейчас их нет).
- `/admin-support`: вкладки «База знаний» (вместо FAQ), «Категории», «Тэги», «Документы»,
  «Тикеты» (назначение агента, статусы, переоткрытие), «Активные / Журнал».
  Подключить существующие, но неиспользуемые методы (редактирование FAQ, удаление источника).
- `frontend/src/services/supportApi.ts`: типы и вызовы под новые эндпоинты; устранить
  расхождение с `src/client` (дублирующий ручной слой) — отдельным решением.

---

## 7. Тесты и eval loop (`AGENTS.md` §7)

- **Миграции**: CI-шаг `upgrade head → downgrade -1 → upgrade head` на чистой БД (сейчас нет).
- **Бэкфилл**: после M1 нет пользователей без роли; после M2 нет запросов без статуса;
  после M6 `count(answer_journal) = count(support_request)`; после M9 нет строк с `source_type='faq'`
  без `normalized_title`.
- **API**: тесты на каждый новый эндпоинт; **обязательно** `403` для `/admin/*` пользователем
  без прав и успешный доступ для `operator` (сейчас таких тестов нет).
- **Сервисные**: журнал пишет несколько шагов; архив создаётся при update/delete; фильтр по
  категории/тэгу меняет выдачу; переоткрытие тикета создаёт новую запись, а активный тикет
  остаётся один (частичный индекс); повторный отзыв на запрос отклоняется.
- **E2E**: `/support` — вопрос → ответ → отзыв; `/admin-support` — БЗ/категория/тэг/тикет.
- **Smoke**: `docker compose ps`, три режима `POST /support/ask`, `GET /admin/metrics`.

Регрессия, которую нельзя допустить: `test_support.py` и `test_support_reference_60.py` должны
остаться зелёными (с переписанным способом создания FAQ-записей) — маршрутизация не должна
измениться от смены схемы.

---

## 8. Фазы работ

| Фаза | Содержание | DoD | Оценка |
|---|---|---|---|
| **0. Подготовка** | изоляция тестовой БД (R1), фиксация §0.2 и A1/A2, baseline-прогон | `pytest` не трогает dev-данные; решения записаны | 0.5 дня |
| **1. Переименования + RBAC** | M0, M1, `permissions.py`, `require_permission`, seed ролей, код перестаёт читать `is_superuser` | переименования без потери данных; `403` по ролям; тесты 403 зелёные | 1.5 дня |
| **2. FAQ → БЗ + жизненный цикл запроса** | M2, M9, hot/cold-разделение (§0.3), `find_faq_match` по БЗ, замена `/admin/faq*` | FAQ-маршрут работает по БЗ; reference-60 зелёные; очередь читается из `active_request`; журнал содержит все запросы | 2.5 дня |
| **3. Таксономия, документы, архив** | M3, M4, M5, payload-индексы Qdrant (D4), `index_doc`, архивация, мягкое удаление | фильтр по категории/тэгу работает через Qdrant; доки индексируются отдельно; снапшот виден | 2.5 дня |
| **4. Журнал** | M6, `AnswerJournalEntry`, шаги в `_record_support_result`, `/support/history` +steps, UI шагов | в БД видны шаги `faq/rag/operator`; история не сломана | 2 дня |
| **5. Тикеты** | M7, assign/resolve/reopen, UI оператора | оператор берёт тикет, отвечает, переоткрывает; активный тикет один | 1.5 дня |
| **6. Отзывы** | M8, `POST /support/feedback`, UI, метрики качества | один отзыв на запрос; средний рейтинг в админке | 1 день |
| **7. Стабилизация** | M10 (drop `is_superuser`), документация, решение по `item` | документы соответствуют коду; тесты и smoke зелёные | 1 день |

Итого ~12 дней одного исполнителя. Фазы 3 и 4 частично параллелятся (разные файлы);
1 → 2 → 3 → 4 последовательны из-за зависимостей миграций.

---

## 9. Риски и откат

| ID | Риск | Влияние | Митигация |
|---|---|---|---|
| R1 | Тесты и миграции идут против рабочей БД (`conftest.py:24-39`) | потеря БЗ, требующая повторного наполнения и reindex | **Фаза 0 обязательна**: отдельная тестовая БД, guard по имени БД, `pg_dump` перед M0/M2/M6/M7/M9 |
| R2 | Журнал 1:N ломает `/support/history` | сломанный UI истории | аддитивная схема (`answer` + `steps`) |
| R3 | M9 (слияние FAQ) затрагивает работающую ступень маршрутизации | регресс FAQ, ложные/пропущенные попадания | reference-60 как гейт; слияние — отдельная фаза с бэкапом; эвристику `_faq_keyword_similarity` чинить здесь же |
| R4 | Снапшоты архива раздувают БД | рост объёма, медленные бэкапы | снапшот только при update/delete, лимит размера, ретенция по числу версий |
| R5 | Категории/тэги не подключены к поиску | мёртвые справочники | D4 обязателен в фазе 3 + тест «фильтр меняет выдачу» |
| R6 | Рассинхрон Qdrant и БД после M3/M4/M9 | поиск отдаёт удалённое/пропускает новое | reindex после каждой структурной миграции; payload-индексы создаются до первого фильтрованного поиска |
| R7 | `DROP UNIQUE` в M6/M7 необратим | потеря истории шагов/тикетов при откате | пометка в docstring + `pg_dump` перед применением |
| R8 | Жёсткое удаление источника уничтожает архив (V6) | безвозвратная потеря истории | мягкое удаление по умолчанию (§0.2), явное подтверждение для `hard=true` |

---

## 10. Документация к обновлению

`CURRENT_VERSION.md` (состав таблиц и эндпоинтов, breaking changes: `/admin/faq*` → БЗ),
`TD.md` (закрытие gap «ответ оператора»), `docs/backend-architecture.md` (слои + RBAC),
`LINKS.md` (новые эндпоинты), `AGENT_HANDOFF.md`, `docs/db-schema-implementation-plan.md` (этот файл).
Отдельно: исправить `CURRENT_VERSION.md:19` (несуществующий `POST /admin/sources`).

---

## 11. Оставшиеся открытые вопросы

1. ~~**`item`**: удаляем таблицу и её API или оставляем демо-раздел шаблона?~~
   Закрыт: таблица, CRUD и API удалены (миграция `9e7c2b41d805`).
2. **Подтверждение §0.2**: мягкое удаление источника как основной путь — оставляем?
3. **§0.3**: подтвердить, что «журнал = источник правды, `active_request` = горячая очередь»
   соответствует вашему замыслу. Это единственный вариант двух таблиц без потери целостности;
   если представлялось иначе (запрос физически переезжает в журнал) — обсудить до M2, потому что
   перенос строк ломает FK детей.
4. **A1**: подтвердить набор ролей и матрицу разрешений (§2.1) — если набор другой, назовите его.
5. **M11** (`embeddings_metadata`): нужен ли инвариант «провайдер/модель/размерность» в БД,
   учитывая, что сейчас смена модели эмбеддингов не инвалидирует индекс и не диагностируется?

---

## 12. Первые три шага

1. Изолировать тестовую БД и зафиксировать §0.2 + A1/A2 — без этого миграции и `downgrade` опасны (R1).
2. **M0** (переименования) — дешёвая механическая миграция, после неё весь план читается
   на финальных именах и противоречие A6/M4-M5 исчезает.
3. **M6** (журнал, 1:N) проверить на копии данных как можно раньше: от него зависят история,
   шаги, трассируемость источников и весь UX оператора.
