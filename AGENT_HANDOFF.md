# AGENT HANDOFF — Web MVP

Актуально на: 2026-04-02  
Режим проекта: web-only, Telegram вне scope.

## 1. Цель следующей сессии

Подтвердить стабильную демонстрацию `FAQ -> RAG -> Operator` в UI и API, с прозрачным ответом (`mode`, `confidence`, `sources`, `fallback_used`).

## 2. Источники правды

Порядок чтения:

1. `README.md` — быстрый вход и запуск.
2. `CURRENT_VERSION.md` — что считается реализованным сейчас.
3. `TD.md` — gap и ближайший путь до стабилизации.
4. `LINKS.md` — URL и endpoint-ы.

Кодовые точки:

- `backend/app/services/support_service.py`
- `backend/app/api/routes/support.py`
- `backend/app/api/routes/admin_support.py`
- `backend/app/core/config.py`
- `frontend/src/routes/_layout/support.tsx`

## 3. Что уже готово

- Рабочий pipeline `faq/rag/operator`.
- Web UI: `/support`, `/admin-support`.
- Seed-импорт источников и FAQ.
- Reindex для обновления retrieval.
- Очередь эскалации оператора.

## 4. Что еще не закрыто

- Нет полного цикла ответа оператора обратно пользователю в UI.
- Нужна регулярная чистка/пополнение FAQ и источников.
- Нужен формальный troubleshooting/release checklist.

## 5. Операционный чеклист (быстрая валидация)

Запуск:

```bash
docker compose up -d
docker compose ps
```

Импорт:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/import-tusur-sources.ps1
```

Smoke:

1. FAQ-вопрос -> `mode=faq`
2. Вопрос по источникам -> `mode=rag` + `sources`
3. Редкий/критичный вопрос -> `mode=operator`

Проверяемые поля:

- `mode`
- `confidence`
- `sources`
- `escalated`
- `fallback_used`

## 6. SKILLS / MCP playbook

- `playwright`: UI smoke/regression.
- `pdf`: извлечение и сверка содержания ТЗ/PDF.
- `openai-docs`: только при задачах по OpenAI API/моделям.
- MCP GitHub: PR/ревью/комментарии.
- Локальная диагностика и запуск проекта: shell.

## 7. Безопасность

- Секреты не хранить в markdown и коммитах.
- Ключи только в `.env`.
- Не публиковать токены в логах и примерах.

## 8. Шаблон первого ответа в новом чате

1. Подтверждаю цель: web-only MVP, Telegram вне scope.
2. Проверяю факт запуска и доступность `/support` и `/admin-support`.
3. Валидирую данные: импорт seed + reindex.
4. Даю короткий отчет: что работает, что сломано, следующий шаг.
