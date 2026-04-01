# AGENT HANDOFF — Web MVP (без Telegram)

Дата обновления: 2026-04-02

## 1) Цель следующей сессии

Довести web-MVP техподдержки до стабильной демонстрации по сценарию:

- `FAQ -> RAG -> Operator`
- воспроизводимо в UI и API
- с прозрачными полями `mode`, `confidence`, `sources`, `fallback_used`

Исключение: Telegram не трогаем.

## 2) Текущее состояние (AS-IS)

Уже готово:

- Backend и UI маршрутизация `FAQ -> RAG -> Operator`.
- Страницы: `/support`, `/admin-support`.
- Админ API: FAQ CRUD, загрузка источников, reindex, очередь оператора.
- Qdrant подключен и используется для retrieval.
- Google AI Studio — основной LLM, Ollama — fallback.

Не закрыто полностью:

- Нет полного UI-цикла «оператор ответил пользователю».
- Качество RAG зависит от полноты источников и корректной переиндексации.
- Нужен регулярный smoke/regression после изменения FAQ/источников/порогов.

Что считать done на ближайший шаг:

- стабильные ответы по 3 режимам в UI;
- predictable поведение порогов;
- seed-данные загружаются и переиндексируются без ошибок;
- тесты support проходят.

## 3) Приоритетный план (без Telegram)

P0:

1. Проверить, что стек и ключи работают (`docker`, `.env`, Google API).
2. Загрузить seed-источники и FAQ.
3. Выполнить reindex.
4. Прогнать smoke на 3 режима в UI и API.
5. Прогнать backend support tests.

P1:

1. Уточнить пороги/правила FAQ vs RAG для переформулированных вопросов.
2. Добавить/почистить FAQ и источники TUSUR по фактическим кейсам.
3. Расширить e2e проверки для support UI.

## 4) Операционный чеклист (команды)

### 4.1 Запуск

```bash
docker compose up -d
docker compose ps
```

Проверить URL:

- <http://localhost:5173>
- <http://localhost:8000/docs>
- <http://localhost:5173/support>
- <http://localhost:5173/admin-support>

### 4.2 Логин

- superuser: `admin@example.com` (пароль из `.env`, по умолчанию часто `changethis` в локалке).
- при проблемах с auth проверить `/api/v1/users/me` и валидность токена.

### 4.3 Импорт источников + FAQ

```powershell
powershell -ExecutionPolicy Bypass -File scripts/import-tusur-sources.ps1
```

Seed-файл:

- `scripts/tusur_sources_seed_v1.json`

### 4.4 Reindex

Reindex обычно запускается скриптом импорта. При необходимости отдельно:

```http
POST /api/v1/admin/sources/reindex
```

### 4.5 Smoke-вопросы на 3 режима

FAQ-ожидание:

- «где посмотреть расписание занятий»

RAG-ожидание:

- вопрос по факту из загруженного источника (должны быть `sources` и `mode=rag`)

Operator-ожидание:

- редкий/критичный вопрос без достаточного основания (ожидаем `mode=operator`)

Проверять поля ответа:

- `mode`
- `confidence`
- `sources`
- `escalated`
- `fallback_used`

## 5) Где искать информацию

Ключевые файлы:

- `backend/app/services/support_service.py`
- `backend/app/core/config.py`
- `backend/app/api/routes/support.py`
- `backend/app/api/routes/admin_support.py`
- `frontend/src/routes/_layout/support.tsx`
- `scripts/import-tusur-sources.ps1`
- `scripts/tusur_sources_seed_v1.json`
- `LINKS.md`

Быстрые команды поиска:

```bash
rg -n "support|faq|rag|operator|reindex|qdrant|google|ollama" backend frontend scripts
rg --files | rg "README|CURRENT_VERSION|LINKS|TD|TUSUR|support"
```

## 6) SKILLS/MCP Playbook

Когда использовать skills:

- `playwright`: UI smoke/regression, проверка маршрутов, воспроизведение багов в браузере.
- `pdf`: извлечение/проверка содержания PDF-ТЗ и документов.
- `openai-docs`: только для задач по OpenAI API/моделям/официальным практикам.

Когда использовать MCP:

- MCP GitHub: PR, комментарии, ревью, статус CI.
- Для локальной диагностики/запуска/тестов в этом проекте приоритет у shell-команд.

Правило:

- сначала подтвердить факты из репозитория и логов;
- потом подключать skill/MCP точечно под задачу.

## 7) Безопасность и ограничения

- Не записывать API-ключи и секреты в markdown, коммиты, issue/PR.
- Все ключи хранить только в `.env` локально.
- Не публиковать токены в логах и примерах команд.
- Telegram в этой ветке работ не включать.

## 8) Шаблон первого ответа агента в новом чате

Использовать как старт:

1. Подтверждаю цель: web-only MVP `FAQ -> RAG -> Operator`, Telegram вне scope.
2. Сначала проверяю фактическое состояние: `docker compose ps`, health-check, доступность `/support` и `/admin-support`.
3. Затем валидирую данные: импорт seed, reindex, smoke-вопросы по 3 режимам.
4. После этого даю короткий отчет:
   - что работает;
   - что сломано;
   - точный следующий шаг с командами.

Ожидаемые артефакты отчета:

- список проверенных URL/endpoint’ов;
- примеры ответов по `faq`, `rag`, `operator`;
- статус тестов (`test_support.py` и e2e при необходимости);
- конкретный список blockers (если есть).
