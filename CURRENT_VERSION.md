# Текущая версия проекта (Web MVP)

Дата фиксации: 2026-04-02  
Статус: рабочая web-версия, целевая схема БД внедрена (миграции M0–M10), Telegram вне релиза.

## 1. Ключевой результат

Реализован контур поддержки `FAQ -> RAG -> Operator` в UI и API, поверх целевой схемы БД:
FAQ стал частью базы знаний, запросы живут по жизненному циклу (журнал + горячая очередь),
тикеты умеют переоткрываться, у знаний появились таксономия, отдельный корпус документов
и архив версий.

## 2. Что реализовано

### Пользовательский API

- `POST /api/v1/support/ask` — маршрутизация и запись шага в журнал.
- `GET /api/v1/support/history` — история сессии; поле `answer` (финальный шаг) сохранено,
  добавлено `steps` со всеми шагами обработки.
- `POST /api/v1/support/feedback` — отзыв на свой запрос (один отзыв на запрос).

### Admin API

- База знаний: `GET/POST /api/v1/admin/sources`, `POST /sources/upload`, `POST /sources/upload-json`,
  `PATCH /sources/{id}` (заголовок, категория, активность, тэги), `DELETE /sources/{id}` (жёсткое),
  `POST /sources/{id}/deactivate` (мягкое удаление), `GET /sources/{id}/archive` (история версий),
  `POST /sources/reindex`.
- FAQ-фасад (совместимость): `GET/POST/PATCH/DELETE /api/v1/admin/faq` — те же схемы, хранилищем
  служит `knowledge_source` с `source_type='faq'`.
- Таксономия: `GET/POST/PATCH/DELETE /api/v1/admin/categories`, `GET/POST/DELETE /api/v1/admin/tags`.
- Документы (независимый корпус): `GET/POST /api/v1/admin/docs`, `PATCH/DELETE /api/v1/admin/docs/{id}`,
  `POST /api/v1/admin/docs/reindex`.
- Поиск с фильтрами: `POST /api/v1/admin/knowledge/search` (корпус, категория, тэги).
- Обращения: `GET /api/v1/admin/requests/active` (горячая очередь),
  `GET /api/v1/admin/requests/journal?status=...` (журнал всех запросов).
- Тикеты: `GET /api/v1/admin/operator-queue`,
  `POST /api/v1/admin/tickets/{id}/assign|resolve|reopen`.
- Пользователи и роли: `GET /api/v1/users/roles` (справочник ролей),
  `POST /api/v1/users/`, `PATCH /api/v1/users/{id}` принимают `role_id`.
- Метрики: `GET /api/v1/admin/metrics` (включая `feedback_count`, `average_rating`).

Логика маршрутизации (не менялась по существу):

- `FAQ`: similarity-порог `FAQ_SIMILARITY_THRESHOLD=0.90`, сравнение по заголовку записи БЗ.
- `RAG`: нужен достаточный контекст (`>=2` релевантных чанка и `top_score >= 0.72`).
- `Operator`: недостаток оснований, конфликт источников, критичный вопрос при низкой уверенности.
- Объяснимость: `route_reason` и `decision_metrics`.

### Права доступа (RBAC)

- Роли: `admin` (wildcard), `operator` (`knowledge:read`, `ticket:read`,
  `ticket:resolve`, `metrics:read`), `user` (без админских прав).
- Проверки в коде: `require_permission(...)` (`backend/app/api/deps.py`),
  каталог прав — `backend/app/core/permissions.py`.
- `GET /api/v1/users/me` отдаёт `role_name` и `permissions` (может содержать `*`),
  поэтому UI строит интерфейс по фактическим правам, а не по флагу.
- Колонки `is_superuser` в БД нет (миграция M10); поле `is_superuser` осталось в ответе
  как производное (wildcard у роли).
- Что видно по ролям во фронтенде:
  - `user`: разделы Dashboard, Items, Support; админские маршруты редиректят на `/`.
  - `operator`: плюс «Support Admin» с вкладками метрик, обращений и тикетов (может
    назначать и решать), знания — только чтение.
  - `admin`: плюс управление пользователями и запись в базу знаний (источники, документы,
    категории, тэги, FAQ).

### RAG / LLM

- Embeddings: `sentence-transformers` (если доступен), иначе Google (`gemini-embedding-001`),
  иначе hash-embedding.
- Vector storage: Qdrant (`knowledge_chunks`); payload содержит `owner_type`, `source_id`/`doc_id`,
  `category_id`, `tag_ids`, `chunk_id`; создаются payload-индексы для фильтрации.
- Поиск: гибридный (семантический + лексический) + повторное ранжирование; фильтры по корпусу,
  категории и тэгам применяются в Qdrant до top-k.
- LLM: primary Google AI Studio (`gemini-flash-latest`), fallback Ollama (`llama3.1:8b`).

### Frontend

- `/support`: вопрос и ответ, режим и уверенность, причина маршрута, источники,
  метрики решения, история обращений со шагами обработки и оценкой ответа
  (1–5 звёзд + комментарий, один отзыв на запрос).
- `/admin-support`: восемь вкладок — метрики, очередь и журнал запросов, тикеты
  (взять себе / ответить и решить / переоткрыть), база знаний (загрузка, метаданные,
  категория и тэги, история версий, скрытие и удаление, reindex), документы,
  категории и тэги, поиск по базе знаний с фильтрами, частые вопросы.
- `/admin`: управление пользователями через выбор роли (админка получает список ролей
  с `GET /users/roles`), вместо прежнего флага «Is superuser?».
- Интерфейс строится по правам: ссылки в сайдбаре, доступные вкладки и кнопки действий
  зависят от `permissions` из `/users/me` (оператор не видит формы редактирования знаний,
  обычный пользователь не видит админских разделов).
- e2e-покрытие: `frontend/tests/support-smoke.spec.ts` (страницы и вкладки поддержки,
  поиск, цикл создания/удаления категории), `frontend/tests/roles.spec.ts` (доступы ролей
  operator и user) и `frontend/tests/support-workflow.spec.ts` (роль выдаётся в админке
  и работает; оператор отвечает на эскалированный вопрос, пользователь видит ответ).
- В Docker контейнер `frontend` отдаёт статическую сборку: после правок фронтенда нужен
  `docker compose up -d --build frontend`, иначе на 5173 останется прежняя версия UI.

### Данные и миграции

Актуальный состав таблиц (16 + `alembic_version`):

| Таблица | Назначение |
|---|---|
| `app_user`, `role` | пользователи и RBAC-роли (`role_id`, `phone`) |
| `request_journal` | ВСЕ запросы — источник правды (жизненный цикл + журнал) |
| `active_request` | горячая очередь (только то, что висит в очереди) |
| `answer_journal` | шаги обработки запроса (1:N): `faq`/`rag`/`operator`/`human` |
| `support_ticket` | тикеты: назначение, решение, переоткрытие (частичный уникальный индекс) |
| `support_feedback` | отзывы (один на запрос, оценка 1..5) |
| `knowledge_source` | база знаний и FAQ (`source_type='faq'`), категория, статус |
| `knowledge_category`, `tag`, `knowledge_tag` | таксономия знаний |
| `knowledge_doc`, `doc_tag` | независимый корпус документов |
| `knowledge_chunk` | чанки обоих корпусов (`source_id` xor `doc_id`) |
| `knowledge_archive` | снапшоты предыдущих версий знания |
| `item` | наследство шаблона, вне домена поддержки |

Цепочка миграций: `e2412789c190` → … → `3f2d3d2d6e45` → `8f4c1a2b7d90` (M0) →
`c5a9e3d1b746` (M1) → `a7c4e1b93d52` (M2) → `e6b2f8a41c73` (M9) → `f2d5a8c14b60` (M3) →
`b8e4c7d29a51` (M4) → `d4a1f7c83e26` (M5) → `c9f3b1e64d07` (M6) → `e2b7d5a91f38` (M7) →
`f5c8a2d64b19` (M8) → `a1e9c4f72b58` (M10). План и статус — `docs/db-schema-implementation-plan.md`.

### Инфраструктура

- `compose.yml`: db, qdrant, adminer, prestart, backend, frontend, telegram (профиль).
- Переменные окружения для Google/Ollama/Qdrant; ретенция архива — `KNOWLEDGE_ARCHIVE_MAX_VERSIONS`.
- Тесты изолированы: `scripts/tests-start.sh` работает на отдельной базе `app_test`.
- Telegram вынесен в профиль `telegram` и в web-флоу не участвует.

## 3. Что подтверждено проверками

- Backend-тесты: **116 passed** на отдельной базе `app_test`.
- Frontend: `tsc` + `vite build` без ошибок, `biome check` по новым файлам чисто.
- Playwright e2e: **71 passed** (включая smoke новых разделов поддержки, доступы ролей
  operator/user, выдачу роли в админке и полный цикл «эскалация → ответ оператора →
  ответ виден пользователю», а также цикл создания/удаления категории через реальный API).
- Для каждой миграции проверен round-trip `upgrade → downgrade → upgrade` на реальной БД;
  для M6/M7 проверены и защитные отказы `downgrade` при наличии нескольких шагов/тикетов.
- Индексация и фильтры Qdrant проверены на живом Qdrant (payload и payload-индексы).
- `ruff` — чисто; `mypy` (strict) — 11 ошибок, все вне добавленного кода.
- Покрытие backend-тестами: 80% (гейт CI `--fail-under=90` при этом не проходит — см. §4).

## 4. Ограничения на сейчас

- Если FAQ пустой, запросы уходят в RAG/Operator.
- Качество RAG критично зависит от качества и полноты источников; документы индексируются
  по ссылке, поэтому недоступный URL даёт `status='failed'`.
- Покрытие backend-тестами 80% при гейте 90% в CI: workflow `test-backend` красный.
- `app_user.role_id` остаётся nullable (пользователей создают и в обход `crud.create_user`);
  пользователь без роли не имеет прав.
- Права задаются только на уровне роли: индивидуальных исключений для конкретного
  пользователя в схеме нет (нужно — потребуется отдельная таблица/поле).
- Таблица `item` (наследство шаблона) не удалена: решение за владельцем.
- Локальная пересборка e2e-браузеров: если Playwright обновился, нужен
  `bunx playwright install chromium` (см. `docs/testing.md`).

## 5. Что нужно для стабильной демо-версии

1. Заполнить базу знаний: FAQ-записи (`source_type='faq'`) и источники (рекомендуемо 20+).
2. Разложить знания по категориям и тэгам, загрузить документы.
3. Выполнить reindex (`POST /api/v1/admin/sources/reindex`), при необходимости `full_rebuild`.
4. Проверить 3 smoke-сценария: `faq`, `rag`, `operator`, а также ответ оператора и переоткрытие.
