# Ссылки проекта (Web MVP)

Актуально на: 2026-04-02

## 1. Web UI

- Главная: <http://localhost:5173/>
- Логин: <http://localhost:5173/login>
- Регистрация: <http://localhost:5173/signup>
- Восстановление пароля: <http://localhost:5173/recover-password>
- Поддержка: <http://localhost:5173/support>
- Админка: <http://localhost:5173/admin>
- Админка поддержки: <http://localhost:5173/admin-support>

## 2. Backend и API

- Swagger: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI JSON: <http://localhost:8000/api/v1/openapi.json>
- Health-check: <http://localhost:8000/api/v1/utils/health-check/>

Ключевые endpoint-ы поддержки:

- `POST /api/v1/support/ask`
- `GET /api/v1/support/history` (поле `steps` — шаги обработки)
- `POST /api/v1/support/feedback`
- `GET/POST/PATCH/DELETE /api/v1/admin/faq` (фасад над базой знаний)
- `GET/POST /api/v1/admin/sources`
- `PATCH/DELETE /api/v1/admin/sources/{id}`
- `POST /api/v1/admin/sources/{id}/deactivate` (мягкое удаление)
- `GET /api/v1/admin/sources/{id}/archive` (история версий)
- `POST /api/v1/admin/sources/upload`, `POST /api/v1/admin/sources/upload-json`
- `POST /api/v1/admin/sources/reindex`
- `GET/POST/PATCH/DELETE /api/v1/admin/categories`
- `GET/POST/DELETE /api/v1/admin/tags`
- `GET/POST /api/v1/admin/docs`, `PATCH/DELETE /api/v1/admin/docs/{id}`, `POST /api/v1/admin/docs/reindex`
- `POST /api/v1/admin/knowledge/search` (фильтры: корпус, категория, тэги)
- `GET /api/v1/admin/requests/active`, `GET /api/v1/admin/requests/journal`
- `GET /api/v1/admin/operator-queue`
- `POST /api/v1/admin/tickets/{id}/assign`, `/resolve`, `/reopen`
- `GET /api/v1/admin/metrics`
- `GET /api/v1/users/roles` (справочник ролей для админки)
- `GET /api/v1/admin/intent/status`, `PUT /api/v1/admin/intent/engine` `{engine}` — состояние и переключение движка классификатора тем
- `GET /api/v1/admin/rag/documents?engine=gemini|anythingllm`, `DELETE` с `{engine, ref}` — список и удаление документов движка

## 3. Локальные сервисы Docker

По умолчанию поднимаются только `db`, `prestart`, `backend`, `frontend`, `proxy`.
Остальное — по профилям.

- Traefik (local): <http://localhost:8090>
- Qdrant API: <http://localhost:6333> — `--profile qdrant`
- MailCatcher UI: <http://localhost:1080> — `--profile mail`
- Adminer: <http://localhost:8080> — `--profile tools`

## 4. Внешние LLM/Embeddings endpoint-ы

- Google generation:  
  <https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent>
- Google embeddings:  
  <https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent>
- Ollama fallback:  
  <http://localhost:11434/api/generate>

## 5. Seed-источники TUSUR

- <https://tusur.ru/ru>
- <https://tusur.ru/ru/studentam>
- <https://abiturient.tusur.ru/ru>
- <https://abiturient.tusur.ru/ru/kontakty>
- <https://timetable.tusur.ru/>
- <https://tusur.ru/sveden/common>
- <https://tusur.ru/sveden/education>
- <https://tusur.ru/sveden/grants>
- <https://tusur.ru/sveden/paid_edu>

## 6. Внутренние документы

- [README.md](README.md)
- [CURRENT_VERSION.md](CURRENT_VERSION.md)
- [TD.md](TD.md)
- [AGENT_HANDOFF.md](AGENT_HANDOFF.md)
- [TUSUR_TYPICAL_QUESTIONS.md](TUSUR_TYPICAL_QUESTIONS.md)
