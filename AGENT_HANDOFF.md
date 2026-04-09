# AGENT HANDOFF - Web MVP

Актуально на: 2026-04-02
Режим проекта: web-only, Telegram вне scope.

## Start Here

1. Правила работы агента (primary policy): `AGENTS.md`.
2. Быстрый вход в новую сессию: `docs/agent-session-checklist.md`.
3. Карта документации: `docs/README.md`.

## Цель следующей сессии

Подтвердить стабильную демонстрацию `FAQ -> RAG -> Operator` в UI и API с прозрачными полями ответа (`mode`, `confidence`, `sources`, `fallback_used`).

## Текущий статус

- Реализован рабочий pipeline `faq/rag/operator`.
- Доступны web-экраны: `/support`, `/admin-support`.
- Есть импорт seed-данных и reindex источников.
- Остается закрыть полный пользовательский цикл ответа оператора в UI.

## Быстрые ссылки

- `README.md`
- `CURRENT_VERSION.md`
- `TD.md`
- `LINKS.md`
- `backend/app/services/support_service.py`
- `backend/app/api/routes/support.py`
- `backend/app/api/routes/admin_support.py`
- `frontend/src/routes/_layout/support.tsx`

## Минимальный Smoke-Check

1. Проверить контейнеры: `docker compose ps`.
2. Проверить доступность UI: `/support`, `/admin-support`.
3. Проверить три маршрута в support:
- FAQ кейс -> `mode=faq`
- RAG кейс -> `mode=rag` + `sources`
- Сложный кейс -> `mode=operator`

## Важно

Любые правила и ограничения по процессу разработки берутся только из `AGENTS.md`.
