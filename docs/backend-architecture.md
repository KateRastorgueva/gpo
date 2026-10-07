# Backend Architecture

Ниже упрощенная карта backend, чтобы новичок быстро понимал, где и что искать.

## 1. Слои

```text
HTTP request
  -> app/api/routes/*
  -> app/services/*
  -> app/models.py + app/core/db.py
  -> DB / Qdrant / внешние LLM
  -> response schema (app/models.py)
```

## 2. Основные директории

- `backend/app/api/`  
  Точки входа HTTP API, зависимости, маршруты.
- `backend/app/services/`  
  Бизнес-логика (pipeline, retrieval, индексация и т.д.).
- `backend/app/core/`  
  Конфиг, подключение БД, security-утилиты.
- `backend/app/alembic/`  
  Миграции БД.
- `backend/tests/`  
  API/CRUD/script тесты.

## 3. Важный текущий домен

Support-поток (`FAQ -> RAG -> Operator`) сейчас концентрирован в:

- `backend/app/services/support_service.py`
- `backend/app/api/routes/support.py`
- `backend/app/api/routes/admin_support.py`

## 4. Права доступа

- Каталог прав и матрица ролей: `backend/app/core/permissions.py`.
- Проверка в роутерах: `Depends(require_permission(...))` из `backend/app/api/deps.py`
  (например `knowledge:read`, `knowledge:write`, `taxonomy:write`, `ticket:read`,
  `ticket:resolve`, `metrics:read`, `user:manage`).
- Роли: `admin` (wildcard `*`), `operator`, `user`; сидируются миграцией
  `c5a9e3d1b746_roles_and_permissions`.
- `is_superuser` в БД больше нет (миграция `a1e9c4f72b58`): это производное поле API
  (wildcard у роли), оставленное для совместимости фронтенда.

## 5. Модель данных поддержки

- `request_journal` — все запросы (источник правды) + `active_request` — горячая очередь.
  Строки между ними не переносятся: постановка = INSERT, завершение = DELETE.
- `answer_journal` — шаги обработки запроса (1:N): `faq`, `rag`, `operator`, `human`.
- `knowledge_source`/`knowledge_doc`/`knowledge_chunk` — база знаний: FAQ (`source_type='faq'`),
  документы (независимый корпус) и общие чанки (`source_id` xor `doc_id`).
- `knowledge_category`, `tag`, `knowledge_tag`, `doc_tag` — таксономия.
- `knowledge_archive` — снапшоты предыдущих версий знания.
- `support_ticket` — тикеты с назначением, решением и переоткрытием (новый тикет).
- `support_feedback` — отзывы (один на запрос).

План и статус внедрения: `../docs/db-schema-implementation-plan.md`.

## 6. Как читать код новичку

1. Начать с route-файла нужного endpoint.
2. Найти вызов service-функции.
3. Пройти до схемы ответа в `models.py`.
4. Открыть соответствующий тест в `backend/tests/api/routes/`.
