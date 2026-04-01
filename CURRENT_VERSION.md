# Текущая Рабочая Версия (Web MVP)

Дата фиксации: 2026-04-02  
Статус: рабочая версия для Web (Telegram в релиз не входит)

## 1) Что реализовано

### 1.1 Backend: поддержка FAQ -> RAG -> Operator

- Добавлены API-роуты поддержки:
  - `POST /api/v1/support/ask`
  - `GET /api/v1/support/history`
- Добавлены admin-роуты:
  - `GET/POST/PATCH/DELETE /api/v1/admin/faq`
  - `GET/POST/DELETE /api/v1/admin/sources`
  - `POST /api/v1/admin/sources/reindex`
  - `GET /api/v1/admin/operator-queue`
- Реализован pipeline:
  - `FAQ`: матч по похожести текста (порог `FAQ_SIMILARITY_THRESHOLD=0.90`)
  - `RAG`: нужен достаточный контекст (`>=2` релевантных чанка и `top_score >= 0.72`)
  - `Operator`: если контекста мало/конфликт источников/критичный вопрос при низкой уверенности
- Для `FAQ` добавлен intent-матчинг по ключевым словам/синонимам (перефразированные запросы и запросы в формате ключевых слов теперь лучше попадают в FAQ до RAG).
- Реализованы правила критичных тем (сроки, оплаты, приказы/регламенты и др.).
- Добавлена логика предупреждения при низкой уверенности для некритичных вопросов.
- Добавлено логирование запросов/ответов/источников/эскалации в БД.

### 1.2 LLM + Retrieval

- Primary LLM: Google AI Studio (`gemini-flash-latest`).
- Fallback LLM: Ollama (`llama3.1:8b`) при ошибке Google.
- Embeddings:
  - `sentence-transformers` (если доступен локально),
  - иначе Google embeddings (`gemini-embedding-001`),
  - резервный fallback — hash embedding.
- Vector storage: Qdrant (`knowledge_chunks`).
- Ingestion:
  - загрузка `pdf/txt/md/url/manual`,
  - чанкинг (`CHUNK_SIZE=1000`, `CHUNK_OVERLAP=150`),
  - индексирование и переиндексация.

### 1.3 Модель данных и миграции

- Добавлены таблицы:
  - `faqentry`
  - `knowledgesource`
  - `knowledgechunk`
  - `supportrequest`
  - `supportanswer`
  - `operatorqueue`
- Добавлена Alembic-миграция для схемы поддержки/RAG.

### 1.4 Frontend (UI)

- Страница пользователя: `/support`
  - ввод вопроса,
  - ответ,
  - `mode` (`faq|rag|operator`),
  - `confidence`,
  - `fallback_used`,
  - список `sources`,
  - история сессии.
- Страница админа: `/admin-support`
  - FAQ CRUD,
  - загрузка источников,
  - `Reindex`,
  - очередь оператора.
- Пункты меню добавлены в Sidebar:
  - `Support`,
  - `Support Admin` (для superuser).

### 1.5 Исправление авторизации в UI (критичный фикс)

- Раньше роуты считали пользователя авторизованным только по наличию токена в `localStorage`.
- Теперь добавлена проверка валидности сессии через `/users/me`:
  - невалидный/протухший токен автоматически очищается,
  - снова доступны `/login`, `/signup`, `/recover-password`, `/reset-password`,
  - защищенные роуты корректно редиректят на `/login` при невалидной сессии.

### 1.6 Инфраструктура и окружение

- В Docker Compose добавлен сервис `qdrant`.
- Backend/prestart получают переменные для Google/Ollama/Qdrant.
- Для локальной проверки включены `mailcatcher` и `playwright` в override.
- Telegram-бот вынесен в профиль `telegram` и в текущий web-флоу не входит.

### 1.7 Скрипты и материалы

- Скрипт импорта seed-источников TUSUR:
  - `scripts/import-tusur-sources.ps1`
  - теперь импортирует и `FAQ` в БД из `sample_questions` (единый seed для FAQ+RAG).
- Seed источников:
  - `scripts/tusur_sources_seed_v1.json`
- Примеры UI-сценариев:
  - `scripts/tusur_ui_examples.md`
- Файл со ссылками проекта:
  - `LINKS.md`

## 2) Что проверено

- Прогон E2E для auth-части:
  - `tests/login.spec.ts` + `tests/sign-up.spec.ts`,
  - результат: `21 passed`.
- Прогон backend-тестов support:
  - `tests/api/routes/test_support.py`,
  - результат: `13 passed`.
- Добавлены и проверены кейсы на невалидный токен:
  - доступ к `/login` и `/signup` не блокируется,
  - stale token очищается.
- Добавлены и проверены FAQ-кейсы на перефраз/ключевые слова (типичный вопрос ТУСУР):
  - `расписание тусур пары` корректно уходит в `mode=faq` при наличии FAQ-записи.
- Проверен API-логин суперпользователя (`admin@example.com / changethis`) — работает.
- Проверены ручные вызовы `/support/ask` — ответы и эскалация отрабатывают.

## 3) Известные ограничения текущей версии

- Если FAQ пустой, `mode=faq` не сработает (система идет в RAG/Operator).
- В UI пока нет функционала "оператор отвечает пользователю" (есть только очередь эскалаций).
- Для стабильного `mode=rag` нужна заполненная и релевантная база источников.
- Часть тестовых/seed-данных содержит проблемы с кодировкой текста; это влияет на читабельность контента.

## 4) Что нужно для стабильной демо-работы

1. Заполнить FAQ минимум 10-30 реальных пар вопрос/ответ.
2. Загрузить источники (20+ документов/страниц) и выполнить `Reindex`.
3. Проверить 3 сценария:
   - FAQ-вопрос (должен дать `mode=faq`),
   - вопрос по источникам (`mode=rag`),
   - редкий/критичный вопрос (`mode=operator`).

## 5) Измененные файлы (по модулям)

### Backend

- `backend/app/api/main.py`
- `backend/app/api/routes/support.py`
- `backend/app/api/routes/admin_support.py`
- `backend/app/models.py`
- `backend/app/services/support_service.py`
- `backend/app/core/config.py`
- `backend/app/alembic/versions/3f2d3d2d6e45_add_support_rag_models.py`
- `backend/tests/api/routes/test_support.py`
- `backend/tests/conftest.py`
- `backend/Dockerfile`

### Frontend

- `frontend/src/routes/_layout/support.tsx`
- `frontend/src/routes/_layout/admin-support.tsx`
- `frontend/src/services/supportApi.ts`
- `frontend/src/components/Sidebar/AppSidebar.tsx`
- `frontend/src/hooks/useAuth.ts`
- `frontend/src/routes/_layout.tsx`
- `frontend/src/routes/login.tsx`
- `frontend/src/routes/signup.tsx`
- `frontend/src/routes/recover-password.tsx`
- `frontend/src/routes/reset-password.tsx`
- `frontend/src/routeTree.gen.ts`
- `frontend/tests/login.spec.ts`
- `frontend/tests/sign-up.spec.ts`

### Infra / Docs / Scripts

- `compose.yml`
- `compose.override.yml`
- `.env` (локальные параметры, без коммита секретов)
- `scripts/import-tusur-sources.ps1`
- `scripts/tusur_sources_seed_v1.json`
- `scripts/tusur_ui_examples.md`
- `TUSUR_TYPICAL_QUESTIONS.md`
- `LINKS.md`
- `TD.md`
