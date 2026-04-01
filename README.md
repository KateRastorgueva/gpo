# Техподдержка Университета — Web MVP

Актуально на: 2026-04-02

Проект реализует web-версию техподдержки с маршрутизацией запроса:
`FAQ -> RAG -> Operator`.

Текущий фокус: только web. Telegram-бот исключен из ближайшего релиза.

## 1. Что уже есть

- Backend pipeline с режимами `faq`, `rag`, `operator`.
- UI пользователя: `/support`.
- UI админа: `/admin-support`.
- FAQ CRUD, загрузка источников, reindex, очередь оператора.
- Векторный поиск через Qdrant.
- LLM orchestration:
- primary: Google AI Studio (`gemini-flash-latest`)
- fallback: Ollama (`llama3.1:8b`)

## 2. Быстрый запуск

1. Заполните `.env` (минимум: БД, superuser, `GOOGLE_API_KEY`).
2. Поднимите проект:

```bash
docker compose up -d
```

3. Откройте:
- UI: <http://localhost:5173>
- Support: <http://localhost:5173/support>
- Admin Support: <http://localhost:5173/admin-support>
- API docs: <http://localhost:8000/docs>

## 3. Загрузка стартовых данных

```powershell
powershell -ExecutionPolicy Bypass -File scripts/import-tusur-sources.ps1
```

- Seed-файл: `scripts/tusur_sources_seed_v1.json`
- Скрипт импортирует источники, FAQ и запускает reindex (если не отключать флагами).

## 4. Как проверить логику FAQ / RAG / Operator

В UI `/support`:

1. FAQ-кейс: типовой вопрос из FAQ или близкий перефраз, ожидается `mode=faq`.
2. RAG-кейс: вопрос по загруженным источникам, ожидается `mode=rag` и `sources`.
3. Operator-кейс: редкий/критичный вопрос без достаточного основания, ожидается `mode=operator`.

В API `POST /api/v1/support/ask` проверяйте поля:
`mode`, `confidence`, `sources`, `escalated`, `fallback_used`.

## 5. Тесты

- Backend support: `backend/tests/api/routes/test_support.py`
- Frontend e2e: `frontend/tests/*.spec.ts`

Запуск:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

Точечно backend:

```bash
docker compose exec backend pytest tests/api/routes/test_support.py
```

Frontend e2e:

```bash
bun run test
```

## 6. Краткая архитектура

- Frontend: React + Vite (`frontend/`)
- Backend: FastAPI + SQLModel (`backend/`)
- DB: PostgreSQL
- Vector DB: Qdrant
- RAG: ingestion/chunking/embedding/retrieval
- LLM: Google API + fallback Ollama

## 7. Ограничения текущей версии

- Telegram не входит в релизный контур.
- Нет полного UI-цикла «оператор ответил пользователю».
- Качество RAG зависит от полноты и актуальности источников.

## 8. Документы проекта

- [CURRENT_VERSION.md](CURRENT_VERSION.md) — зафиксированное текущее состояние.
- [TD.md](TD.md) — техническая документация и gap-анализ.
- [LINKS.md](LINKS.md) — рабочие URL и endpoint-ы.
- [AGENT_HANDOFF.md](AGENT_HANDOFF.md) — файл для следующей сессии агента.
- [TUSUR_TYPICAL_QUESTIONS.md](TUSUR_TYPICAL_QUESTIONS.md) — типовые вопросы для FAQ/RAG.
- [development.md](development.md), [deployment.md](deployment.md), [SECURITY.md](SECURITY.md), [release-notes.md](release-notes.md).
- [ТЗ_Техподдержка_университета.docx](ТЗ_Техподдержка_университета.docx).

## 9. SKILLS / MCP (коротко)

- `playwright`: UI smoke/regression.
- `pdf`: задачи по PDF/ТЗ.
- `openai-docs`: только когда вопрос про OpenAI-платформу.
- MCP GitHub: PR/ревью/комментарии.
- Локальная проверка и диагностика проекта: через shell.
