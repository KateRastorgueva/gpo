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
- `GET /api/v1/support/history`
- `GET/POST/PATCH/DELETE /api/v1/admin/faq`
- `GET/POST/DELETE /api/v1/admin/sources`
- `POST /api/v1/admin/sources/reindex`
- `GET /api/v1/admin/operator-queue`

## 3. Локальные сервисы Docker

- Qdrant API: <http://localhost:6333>
- MailCatcher UI: <http://localhost:1080>
- Adminer: <http://localhost:8080>
- Traefik (local): <http://localhost:8090>

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
