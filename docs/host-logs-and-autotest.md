# Журнал хоста и автотест

## Что пишется в журнал

Backend пишет события в `/app/logs/events-YYYY-MM-DD.jsonl` (одна JSON-строка на
событие, дата по UTC). Папка — docker-том `app-logs`, поэтому журнал переживает
пересборку контейнера. Файлы старше `EVENT_LOG_RETENTION_DAYS` (30 дней) удаляются
при старте backend.

| Событие | Когда | Главные поля |
|---|---|---|
| `http.request` | каждый запрос к `/api/v1` (кроме health-check) | `route`, `method`, `status`, `duration_ms`, `request_id` |
| `http.error` | необработанное исключение в запросе | `path`, `error` |
| `support.ask` | ответ на вопрос в чате | `mode` (faq/rag/operator), `provider`, `route_reason`, `confidence`, `response_time_ms`, `sources`, `question` |
| `rag.provider_error` | облачный/локальный движок упал или не ответил | `provider`, `error`, `elapsed_ms` |
| `rag.retrieval_error`, `rag.llm_error` | ошибки старого поиска | `error` |
| `ingest.file` | файл из пакетной загрузки ушёл в движки | `filename`, `bytes`, `status`, `engines`, `error`, `wait_ms` |
| `app.startup` | старт воркера backend | `rag_provider_env` |

Пароли, токены и тексты ответов в журнал не пишутся. Текст вопроса пишется (первые
500 символов), отключается `EVENT_LOG_QUESTIONS=false`. Весь журнал выключается
`EVENT_LOG_ENABLED=false`.

Каждый ответ API несёт заголовок `X-Request-ID`: по нему ошибку из браузера можно
найти в журнале.

## Как смотреть

Нужна роль с правом `metrics:read` (админ):

- `GET /api/v1/admin/logs/events?hours=24&event=support.` — последние события;
- `GET /api/v1/admin/logs/summary?hours=24` — сводка: статусы, p50/p95, медленные
  маршруты, режимы ответов, доля эскалаций, ошибки;
- `GET /api/v1/admin/logs/files/2026-11-04` — файл журнала за день целиком.

На самом хосте: `docker compose exec backend tail -f /app/logs/events-$(date -u +%F).jsonl`.

## Автотест хоста

`scripts/host_autotest.py` — один скрипт без сторонних пакетов. Он проверяет фронт,
health-check, вход админа, выбранный движок, задаёт вопросы из
`scripts/host_autotest.json`, проверяет историю и метрики, а затем забирает журнал
хоста за время прогона.

```bash
python scripts/host_autotest.py                 # хост из HOST_URL или командный по умолчанию
python scripts/host_autotest.py --push          # плюс коммит отчёта в ветку host-reports
python scripts/host_autotest.py --skip-questions  # без расхода квоты движка
python scripts/host_autotest.py --full-day --push # приложить весь журнал за сегодня
```

Логин и пароль берутся из `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` (окружение или
`.env` в корне). Отчёт: `reports/host/<время>/report.md`, `results.json`,
`events.jsonl`, `summary.json` (локальная папка `reports/` в git не попадает).

С `--push` отчёт коммитится в отдельную ветку `host-reports` через временный
`git worktree`: текущая ветка и незакоммиченные файлы не трогаются, `master` не
засоряется. Код выхода 0, если все проверки прошли, иначе 1.

Вопросы автотеста идут в чат админа с `session_id` вида `autotest-<время>`, так их
легко отличить от настоящих обращений. Каждый вопрос тратит квоту облачного движка,
поэтому сценариев немного; список правится в `scripts/host_autotest.json`
(`expect_mode`: faq | rag | operator | any, `expect_source` — часть имени файла).
