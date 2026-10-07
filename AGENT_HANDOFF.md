# AGENT HANDOFF - Web MVP

Актуально на: 2026-04-02
Режим проекта: web-only, Telegram вне scope.

## Start Here

1. Правила работы агента (primary policy): `AGENTS.md`.
2. Быстрый вход в новую сессию: `docs/agent-session-checklist.md`.
3. Карта документации: `docs/README.md`.

## Цель следующей сессии

Целевая схема БД внедрена (миграции M0–M10), UI доведён до рабочего состояния.
Открытые кандидаты:

1. **Гейт покрытия CI**: покрытие backend-тестами 80% против `--fail-under=90`,
   workflow `test-backend` красный. Либо поднимать покрытие, либо осознанно снижать порог.
2. **Решение по таблице `item`** (наследство шаблона): удалять или оставлять.
3. Ужесточить `app_user.role_id` до NOT NULL после аудита путей создания пользователя
   (сейчас nullable, отсутствие роли = «нет прав»).
4. Контент: наполнить базу знаний FAQ-записями и источниками, разложить по категориям/тэгам.

## Frontend: что сделано и как проверять

- Тулкинч работает: `bun install` из корня (bun-workspace, `frontend` — воркспейс),
  `bun run build`, `bunx playwright test`.
- **Доступы по ролям**: `GET /users/me` отдаёт `permissions` и `role_name`; UI строит
  интерфейс по ним (`frontend/src/lib/permissions.ts` + `hooks/usePermissions.ts`).
  Сайдбар, состав вкладок `/admin-support` и кнопки действий зависят от прав:
  - `user` — Dashboard/Items/Support, админские маршруты редиректят на `/`;
  - `operator` — плюс метрики, очередь/журнал и тикеты (assign/resolve/reopen), знания
    только на чтение;
  - `admin` ("*") — плюс управление пользователями и запись в базу знаний.
- Новые страницы/разделы: `/support` (ответ, шаги обработки, оценка 1–5 + комментарий),
  `/admin-support` (до 8 вкладок: метрики, очередь и журнал, тикеты, база знаний,
  документы, категории и тэги, поиск, частые вопросы).
- Слой API поддержки — `frontend/src/services/supportApi.ts` (типизированные вызовы всех
  новых эндпоинтов, `ApiError` со статусом). Сгенерированный клиент `src/client` обновлён
  (`bun run generate-client`), в нём появились `UsersService.readRoles` и типы ролей.
- Управление пользователями в `/admin` переведено на выбор роли (`GET /users/roles`,
  `role_id` в create/update) вместо флага «Is superuser?» — это была реальная регрессия
  после M10, её поймал e2e `admin.spec.ts`.
- e2e-проверки: `frontend/tests/support-smoke.spec.ts` (рендер страниц, все вкладки,
  поиск по базе знаний, цикл создания/удаления категории), `frontend/tests/roles.spec.ts`
  (доступы operator и user) и `frontend/tests/support-workflow.spec.ts`
  (выдача роли в админке; ответ оператора на эскалированный вопрос — целиком через UI).
  Для сценариев сброса пароля нужен `docker compose up -d mailcatcher`.
- **Грабли №1 (ловились как «нет разделения по ролям, оператор не может отвечать»):
  контейнер `frontend` отдаёт статическую сборку из образа.** Старый образ был собран
  ~5 месяцев назад, и на 5173 показывался UI без ролей, тикетов и отзывов. Лечится
  `docker compose build frontend` (или `up -d --build frontend`) после правок фронта;
  для живой разработки — `bun run dev` при остановленном контейнере `frontend`.
- **Грабли №2 (найденный баг валидации):** в прод-бандле zod показывает обобщённое
  «Invalid input» вместо «Invalid email address». Исправлено явными сообщениями в схемах
  (`z.email({ message: ... })` в login/signup/recover-password).
- Если Playwright обновился, доставить браузер: `cd frontend && bunx playwright install chromium`.
- Грабли окружения: если в Docker параллельно поднят **старый стек** проекта `gpo2501`
  (прежнее имя каталога), он занимает порты 5432/6333/8000/5173 и `up` падает с
  «port is already allocated»; останавливать его: `docker stop gpo2501-db-1 ...`
  (или `docker compose -p gpo2501 down`). Застрявший `prestart` с ошибкой
  «failed to resolve host 'db'» лечится `docker compose down --remove-orphans` и повторным `up`.

## Состояние схемы БД

- План и статус: `docs/db-schema-implementation-plan.md` (все миграции помечены как выполненные).
- Применены и проверены round-trip'ом (`upgrade → downgrade → upgrade`) на реальной БД:

| Ревизия | Что |
|---|---|
| `8f4c1a2b7d90` (M0) | переименование таблиц в snake_case + индексов |
| `c5a9e3d1b746` (M1) | роли `admin`/`operator`/`user`, `role_id`, `phone`, бэкфилл из `is_superuser` |
| `a7c4e1b93d52` (M2) | жизненный цикл `request_journal` + горячая очередь `active_request` |
| `e6b2f8a41c73` (M9) | слияние FAQ в базу знаний (`source_type='faq'`), `faqentry` удалена |
| `f2d5a8c14b60` (M3) | таксономия: категории, тэги, `knowledge_tag` |
| `b8e4c7d29a51` (M4) | документы (`knowledge_doc`, `doc_tag`), обобщение чанков, payload Qdrant |
| `d4a1f7c83e26` (M5) | архив версий знания + мягкое удаление источника |
| `c9f3b1e64d07` (M6) | журнал ответов как шаги (1:N), финальность, время ответа |
| `e2b7d5a91f38` (M7) | тикеты: назначение, решение, переоткрытие (частичный уникальный индекс) |
| `f5c8a2d64b19` (M8) | отзывы (один на запрос, оценка 1..5) |
| `a1e9c4f72b58` (M10) | удаление колонки `is_superuser` |

- Обратимость: M6 и M7 при откате падают с явной ошибкой, если у запроса уже есть несколько
  шагов или тикетов (UNIQUE не восстановить без потери истории) — это осознанное поведение.
- API-совместимость: `/admin/faq*` работает как фасад над базой знаний, поле `answer` в
  истории сохранено (добавлено `steps`), `is_superuser` отдаётся как производное поле
  (wildcard у роли).
- Роли: `GET /users/roles` + `role_id` в create/update пользователя. В админке флаг
  «Is superuser?» заменён выбором роли (иначе чекбокс молча игнорировался после M10).

## Проверки

- Backend-тесты: **116 passed** на отдельной базе `app_test`
  (`docker compose run --rm --no-deps -v ./backend/tests:/app/backend/tests backend bash scripts/tests-start.sh`).
- Playwright e2e: **71 passed** (`cd frontend && bunx playwright test`); backend, db и
  mailcatcher должны быть запущены. Если контейнер `frontend` поднят, прогон идёт против
  собранной сборки — сначала `docker compose build frontend`.
- `ruff` — чисто; `mypy` (strict) — 11 ошибок, все вне добавленного кода.
- Покрытие backend-тестами: 80%.
- Frontend: `tsc -p tsconfig.build.json` и `vite build` — без ошибок; `biome check` по
  новым/изменённым файлам — чисто.
- Индексация и фильтры Qdrant проверены на живом Qdrant: payload (`owner_type`, `category_id`,
  `tag_ids`, `doc_id`, `chunk_id`) и payload-индексы, фильтры по тэгу/категории/корпусу.

## Известные проблемы процесса

- Гейт покрытия backend-тестами в CI (`--fail-under=90`) не проходит (80%).
- `docker compose exec backend ... pytest` не работает без `docker compose watch`: образ не
  содержит каталог `tests` (рабочая команда — в `docs/testing.md`).
- Backend-тесты запускаются только после пересборки образа (`docker compose up -d --build
  backend`), иначе исполняется старый код.
- `biome check` без `--write` показывает форматные замечания по существующим файлам с CRLF —
  это baseline, а не результат правок.
- E2E-прогон изменяет рабочую базу разработки (создаёт пользователей/items, правит профиль
  суперюзера) — это поведение существующего набора тестов.
- В Docker остаются volumes от прежнего имени проекта (`gpo2501_*`) — кандидаты на очистку.

## Быстрые ссылки

- `README.md`
- `CURRENT_VERSION.md`
- `docs/db-schema-implementation-plan.md`
- `TD.md`
- `LINKS.md`
- `backend/app/services/support_service.py`
- `backend/app/core/permissions.py`
- `backend/app/api/routes/support.py`
- `backend/app/api/routes/admin_support.py`
- `frontend/src/routes/_layout/support.tsx`

## Минимальный Smoke-Check

1. Проверить контейнеры: `docker compose ps`.
2. Проверить доступность UI: `/support`, `/admin-support`, `/admin`.
3. Проверить три маршрута в support:
   - FAQ кейс -> `mode=faq`
   - RAG кейс -> `mode=rag` + `sources`
   - Сложный кейс -> `mode=operator`
4. Проверить цикл оператора: `POST /api/v1/admin/tickets/{id}/resolve` -> запрос уходит из
   `/admin/requests/active`, в истории появляется шаг `human`; кнопка «Переоткрыть» возвращает
   запрос в очередь.
5. Проверить отзыв: `POST /api/v1/support/feedback` -> `GET /api/v1/admin/metrics`
   (`feedback_count`, `average_rating`).
6. Проверить роли: создать пользователя в `/admin` с ролью `admin` -> в таблице появится
   бейдж `admin`; войти оператором -> в сайдбаре есть «Support Admin», нет «Admin»,
   в базе знаний нет форм редактирования; обычным пользователем -> админские URL
   редиректят на `/`.
7. Автоматически: `cd frontend && bunx playwright test` (включая `support-smoke.spec.ts`
   и `roles.spec.ts`).

## Важно

Любые правила и ограничения по процессу разработки берутся только из `AGENTS.md`.
