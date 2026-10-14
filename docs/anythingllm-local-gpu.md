# Задание: локальный RAG на AnythingLLM без Google (GPU-машина)

Документ написан так, чтобы его можно было отдать ИИ-агенту целиком.
Агент выполняет шаги по порядку и считает работу сделанной только тогда,
когда приёмочный скрипт из шага 6 завершился с кодом 0.

## Контекст

- Проект: веб-техподдержка ТУСУР, маршрут `FAQ -> RAG -> оператор`.
- RAG-движок выбирается переменной `RAG_PROVIDER` в `.env`:
  `legacy` | `gemini_file_search` | `anythingllm`. Адаптер уже написан:
  `backend/app/services/rag_providers.py`, функция `ask_anythingllm`.
- AnythingLLM поднимается отдельным сервисом `anythingllm` в
  `compose.override.yml` (профиль `anythingllm`).
- Сейчас там эмбеддинги `MintplexLabs/multilingual-e5-small` на CPU и ответы
  через Gemini. Проблема: поиск почти не различает документы (оценки 0.84–0.86
  у всех кусков), вопросы по сканам не находятся. Цель: сильные локальные
  модели и полный отказ от Google.
- Железо: RTX 4070, 12 ГБ VRAM.

## Ограничения (нарушать нельзя)

1. Не менять схему БД, миграции, фронтенд и `backend/app/services/support_service.py`.
2. Не трогать адаптер `rag_providers.py`, если приёмка проходит без этого.
   Если менять, то тесты `backend/tests/services/test_rag_providers.py` должны проходить.
3. Не коммитить `.env`, ключи и токены. В коммит добавлять файлы только точечно
   (`git add <путь>`), не `git add .`.
4. Работать в отдельной ветке от `master`, например `feat/anythingllm-local`.
   В `master` напрямую не пушить.
5. Запускать стек только с `compose.override.yml` (то есть просто
   `docker compose ...` из корня), одиночный `compose.yml` не использовать.
6. Не придумывать параметры AnythingLLM. Использовать только переменные из этого
   документа; если чего-то не хватает, проверить по исходникам в контейнере
   (`/app/server/utils/helpers/updateENV.js`), а не угадывать.
7. Не удалять volume `anythingllm-storage` и данные БД без явного согласия команды.

## Шаги

### 1. Модели в Ollama

```bash
ollama pull bge-m3
ollama pull qwen2.5:14b
ollama list   # обе модели должны быть в списке
```

Проверка, что эмбеддинги работают:

```bash
curl http://localhost:11434/api/embed -d '{"model":"bge-m3","input":"проверка"}'
```

Ответ должен содержать `embeddings` с вектором длины 1024.

### 2. Настройки сервиса `anythingllm` в `compose.override.yml`

Заменить блок переменных `LLM_*`, `GEMINI_*`, `EMBEDDING_*` на:

```yaml
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_PATH=http://host.docker.internal:11434
      - OLLAMA_MODEL_PREF=qwen2.5:14b
      - OLLAMA_MODEL_TOKEN_LIMIT=8192
      - EMBEDDING_ENGINE=ollama
      - EMBEDDING_BASE_PATH=http://host.docker.internal:11434
      - EMBEDDING_MODEL_PREF=bge-m3:latest
      - EMBEDDING_MODEL_MAX_CHUNK_LENGTH=8192
```

Оставить как есть: `STORAGE_DIR`, `VECTOR_DB=lancedb`, `DISABLE_TELEMETRY`,
`TARGET_OCR_LANG=rus,eng` (без него сканы распознаются английским OCR и
превращаются в мусор).

Если вместо Ollama используется LM Studio: `LLM_PROVIDER=lmstudio`,
`LMSTUDIO_BASE_PATH=http://host.docker.internal:1234/v1`, `EMBEDDING_ENGINE=lmstudio`,
`EMBEDDING_BASE_PATH=http://host.docker.internal:1234/v1`.

### 3. Запуск только AnythingLLM

```bash
docker compose --profile anythingllm up -d --no-deps anythingllm
curl http://localhost:3001/api/ping        # {"online":true}
```

Если в volume остались настройки со старой моделью, после запуска проверить
`GET /api/v1/system` (шаг 6 сделает это сам). Настройки из переменных окружения
имеют приоритет.

### 4. API-ключ

Открыть http://localhost:3001 -> Settings -> Developer API -> Generate.
Ключ передавать только через переменную окружения `ANYTHINGLLM_API_KEY`,
в файлы и коммиты не писать.

### 5. Переиндексация

Векторы разных моделей несовместимы, поэтому старые документы нужно убрать из
workspace и загрузить заново:

```bash
python scripts/anythingllm.py reset     # пересоздать workspace без старых векторов
python scripts/anythingllm.py upload "tusur docs" --max-pages 2000
```

На GPU это минуты. Скрипт печатает по строке на файл; `status` должен быть `ok`.

### 6. Приёмка (обязательна)

```bash
python scripts/check_anythingllm_local.py
```

Скрипт проверяет: локальные эмбеддинги `bge-m3`, локальная LLM, русский OCR,
не меньше 16 документов в workspace, эталонные вопросы >= 15/17, вопросы по
сканам >= 2/3, вопросы не по теме уходят в отказ. Код выхода 0 = готово.

Затем проверка через само приложение:

```bash
# в .env: RAG_PROVIDER=anythingllm, ANYTHINGLLM_API_KEY=<ключ>,
#         ANYTHINGLLM_BASE_URL=http://anythingllm:3001
docker compose --profile anythingllm up -d
python scripts/check_anythingllm_local.py --app
```

### 7. Отчёт

В PR в `master` приложить вывод шага 6 целиком, таблицу сравнения с базовой
линией ниже и время индексации. Если какая-то проверка не прошла, так и
написать, с выводом, а не подгонять пороги в скрипте.

## Базовая линия (2026-10-14, ноутбук без GPU)

| | Эталонные вопросы | Сканы | Время ответа |
|---|---|---|---|
| Gemini File Search | 15/17 | 3/3 | 8–40 с |
| AnythingLLM + e5-small + Gemini | 14/17 | 0/3 | 1–7 с |
