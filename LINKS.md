# Ссылки проекта (Web MVP)

Обновлено: 2026-04-02

Ниже собраны рабочие ссылки для запуска, проверки и демо.  
Список ориентирован на текущий web-релиз (без Telegram).

## 1) Веб-интерфейс (пользователь)

- http://localhost:5173/
- http://localhost:5173/login
- http://localhost:5173/signup
- http://localhost:5173/recover-password
- http://localhost:5173/support

## 2) Веб-интерфейс (админ)

- http://localhost:5173/admin
- http://localhost:5173/admin-support

## 3) Backend и API

- http://localhost:8000/docs
- http://localhost:8000/redoc
- http://localhost:8000/api/v1/openapi.json
- http://localhost:8000/api/v1/utils/health-check/

Поддержка (основные endpoints):

- `POST` http://localhost:8000/api/v1/support/ask
- `GET` http://localhost:8000/api/v1/support/history
- `GET` http://localhost:8000/api/v1/admin/faq
- `POST` http://localhost:8000/api/v1/admin/faq
- `PATCH` http://localhost:8000/api/v1/admin/faq/{faq_id}
- `DELETE` http://localhost:8000/api/v1/admin/faq/{faq_id}
- `GET` http://localhost:8000/api/v1/admin/sources
- `POST` http://localhost:8000/api/v1/admin/sources/upload
- `DELETE` http://localhost:8000/api/v1/admin/sources/{source_id}
- `POST` http://localhost:8000/api/v1/admin/sources/reindex
- `GET` http://localhost:8000/api/v1/admin/operator-queue

## 4) Локальные сервисы Docker

- http://localhost:6333 (Qdrant API)
- http://localhost:1080 (MailCatcher UI)
- http://localhost:8080 (Adminer)

## 5) LLM/Embeddings провайдеры

- https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent
- https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent
- http://localhost:11434/api/generate (Ollama fallback)

## 6) Источники знаний TUSUR (RAG seed)

- https://tusur.ru/ru
- https://tusur.ru/ru/studentam
- https://abiturient.tusur.ru/ru
- https://abiturient.tusur.ru/ru/kontakty
- https://timetable.tusur.ru/
- https://tusur.ru/sveden/common
- https://tusur.ru/sveden/education
- https://tusur.ru/sveden/grants
- https://tusur.ru/sveden/paid_edu

