# Техподдержка Университета — Web MVP

Рабочий web-проект техподдержки университета с маршрутизацией запросов `FAQ -> RAG -> Operator`.

Текущий фокус релиза: только веб. Telegram-бот временно исключен из релизного контура.

## Что это и цель версии

Система принимает вопрос пользователя, определяет режим обработки и возвращает:

- `mode=faq` — шаблонный ответ из FAQ.
- `mode=rag` — ответ по базе знаний с источниками.
- `mode=operator` — эскалация в очередь оператора.

Цель v0.1-draft: стабильный рабочий MVP в UI и API, где видны режим ответа, confidence и источники.

## Что уже реализовано

- Backend pipeline: `FAQ -> RAG -> Operator` с порогами маршрутизации.
- API поддержки:
- `POST /api/v1/support/ask`
- `GET /api/v1/support/history`
- API админки поддержки:
- `GET/POST/PATCH/DELETE /api/v1/admin/faq`
- `GET/POST/DELETE /api/v1/admin/sources`
- `POST /api/v1/admin/sources/reindex`
- `GET /api/v1/admin/operator-queue`
- UI пользователя: `/support`.
- UI админа: `/admin-support`.
- Retrieval: Qdrant.
- LLM orchestration:
- primary: Google AI Studio (`gemini-flash-latest`)
- fallback: Ollama (`llama3.1:8b`)

## Быстрый запуск (локально)

1. Проверьте, что заполнен `.env` (минимум: БД, superuser, `GOOGLE_API_KEY`).
2. Поднимите стек:

```bash
docker compose up -d
```

3. Откройте:
- UI: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>
- Support UI: <http://localhost:5173/support>
- Admin Support UI: <http://localhost:5173/admin-support>

## Загрузка стартовых данных (TUSUR seed)

Импорт источников и FAQ из seed-файла:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/import-tusur-sources.ps1
```

- seed: `scripts/tusur_sources_seed_v1.json`
- скрипт выполняет загрузку источников, импорт FAQ и reindex (если не отключено флагами).

## Как быстро проверить 3 режима

В UI (`/support`):

1. FAQ-кейс: задайте типовой вопрос из FAQ (или близкую формулировку) и проверьте `mode=faq`.
2. RAG-кейс: задайте вопрос по контенту загруженных источников и проверьте `mode=rag` + `sources`.
3. Operator-кейс: задайте редкий/критичный вопрос без достаточного основания и проверьте `mode=operator`.

Через API:

```json
POST /api/v1/support/ask
{
  "question": "Где посмотреть расписание занятий?",
  "session_id": "demo-session-1",
  "channel": "web"
}
```

Проверьте поля ответа: `mode`, `confidence`, `sources`, `escalated`, `fallback_used`.

## Тесты

Где находятся:

- backend: `backend/tests/api/routes/test_support.py`
- frontend e2e: `frontend/tests/*.spec.ts`

Как запускать:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

Точечно backend support:

```bash
docker compose exec backend pytest tests/api/routes/test_support.py
```

Frontend e2e (из корня):

```bash
bun run test
```

## Архитектура (кратко)

- Frontend: React + Vite (`frontend/`).
- Backend: FastAPI + SQLModel (`backend/`).
- DB: PostgreSQL.
- Vector DB: Qdrant.
- Ingestion/Indexing: загрузка источников, чанкинг, embeddings, индексация.
- LLM слой: Google API как основной, Ollama как fallback.

## Ограничения текущей версии

- Релизный контур: только web (Telegram отключен по продуктному решению).
- Очередь оператора реализована, но нет полного UI-цикла «оператор ответил пользователю».
- Качество ответов RAG сильно зависит от полноты и актуальности загруженных источников.

## SKILLS/MCP (кратко)

- Для UI-проверок и регрессии: skill `playwright`.
- Для задач по PDF/ТЗ: skill `pdf`.
- Для задач именно по OpenAI-продуктам: skill `openai-docs`.
- MCP GitHub: для PR/комментариев/ревью.
- Локальная диагностика и запуск — через shell-команды в репозитории.

Подробный operational playbook для следующей сессии в файле `AGENT_HANDOFF.md`.

## Документация и ссылки

- [TD.md](TD.md)
- [CURRENT_VERSION.md](CURRENT_VERSION.md)
- [LINKS.md](LINKS.md)
- [TUSUR_TYPICAL_QUESTIONS.md](TUSUR_TYPICAL_QUESTIONS.md)
- [development.md](development.md)
- [deployment.md](deployment.md)
- [SECURITY.md](SECURITY.md)
- [release-notes.md](release-notes.md)
- [ТЗ_Техподдержка_университета.docx](ТЗ_Техподдержка_университета.docx)

## Что добавить далее

- Troubleshooting-гайд по типовым проблемам (`env`, stale token, reindex, пустой FAQ).
- Env-матрицу (какие переменные обязательны, какие опциональны, значения по умолчанию).
- Runbook инцидентов (Google API недоступен, Qdrant недоступен, деградация retrieval).
- Release checklist (pre-release smoke, regression, миграции, rollback-план).
