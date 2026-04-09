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

## 4. Как читать код новичку

1. Начать с route-файла нужного endpoint.
2. Найти вызов service-функции.
3. Пройти до схемы ответа в `models.py`.
4. Открыть соответствующий тест в `backend/tests/api/routes/`.
