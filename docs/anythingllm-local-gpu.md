# AnythingLLM на машине с GPU (RTX 4070, 12 ГБ VRAM)

Зачем: на ноутбуке без GPU AnythingLLM работает с маленькой моделью эмбеддингов
`multilingual-e5-small`, и поиск почти не различает документы (оценки 0.84–0.86
у всех кусков, сканы проигрывают). На GPU можно взять сильную модель и
не зависеть от квот Google.

## 1. Модели через Ollama

```bash
ollama pull bge-m3          # эмбеддинги, ~1.2 ГБ, 100+ языков, контекст 8192
ollama pull qwen2.5:14b     # ответы, ~9 ГБ в Q4, влезает в 12 ГБ VRAM (опционально)
```

Вместо Ollama подойдёт LM Studio: в AnythingLLM выбрать провайдер `lmstudio`
и указать `http://host.docker.internal:1234/v1`.

## 2. Переменные для сервиса `anythingllm` в `compose.override.yml`

```yaml
      - EMBEDDING_ENGINE=ollama
      - EMBEDDING_BASE_PATH=http://host.docker.internal:11434
      - EMBEDDING_MODEL_PREF=bge-m3:latest
      - EMBEDDING_MODEL_MAX_CHUNK_LENGTH=8192
      # если ответы тоже локально, без Google:
      - LLM_PROVIDER=ollama
      - OLLAMA_BASE_PATH=http://host.docker.internal:11434
      - OLLAMA_MODEL_PREF=qwen2.5:14b
      - OLLAMA_MODEL_TOKEN_LIMIT=8192
```

`TARGET_OCR_LANG=rus,eng` оставить: без него сканы распознаются английским OCR.

## 3. Запуск и проверка

```bash
docker compose --profile anythingllm up -d --no-deps anythingllm
# API-ключ: Settings -> Developer API в http://localhost:3001
export ANYTHINGLLM_API_KEY=...
python scripts/anythingllm.py upload "tusur docs" --max-pages 2000
python scripts/anythingllm.py eval --out anythingllm-gpu.json
```

После смены модели эмбеддингов документы нужно переиндексировать: векторы
разных моделей несовместимы.

Ориентир для сравнения (2026-10-14, ноутбук без GPU, 17 эталонных вопросов):
Gemini File Search 15/17 (сканы 3/3), AnythingLLM + e5-small 14/17 (сканы 0/3).
