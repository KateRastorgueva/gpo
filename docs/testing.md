# Testing

Короткий guide для новичка: что запускать и в каком порядке.

## 1. Backend (основное)

Полный прогон backend-тестов:

```bash
docker compose run --rm --no-deps \
  -v ./backend/tests:/app/backend/tests \
  backend bash scripts/tests-start.sh
```

Скрипт сам переключает прогон на отдельную базу `app_test` (создаёт её при необходимости
и прогоняет миграции), потому что сессионная фикстура `db` очищает таблицы.

**Почему нужен `-v .../tests`:** образ backend собирается без каталога `tests`
(см. `backend/Dockerfile`), поэтому `docker compose exec backend bash scripts/tests-start.sh`
упадёт с `file or directory not found: tests/`. Каталог появляется в контейнере только если
запущен `docker compose watch` (он синхронизирует `./backend` в `/app/backend`) — тогда
команду с `exec` можно использовать как раньше.

**Важно:** прямой запуск `pytest` использует базу из `POSTGRES_DB` и по умолчанию
отказывается работать, если имя базы не заканчивается на `_test` — так рабочая база
с наполненными FAQ и источниками не будет очищена. Осознанный прогон против рабочей
базы возможен только через `ALLOW_DESTRUCTIVE_TESTS=1`:

```bash
# откажется работать (защита от очистки рабочей базы)
docker compose run --rm ... backend pytest tests/api/routes/test_support.py
# корректно
docker compose run --rm -v ./backend/tests:/app/backend/tests \
  -e POSTGRES_DB=app_test backend pytest tests/api/routes/test_support.py
```

В CI тесты запускаются на раннере через `uv run bash scripts/tests-start.sh`
(`.github/workflows/test-backend.yml`), там же применяется гейт покрытия.

## 2. Frontend e2e (smoke)

Из корня репозитория (bun-workspace, `frontend` — воркспейс):

```bash
bun install                 # ставит зависимости воркспейса в ./node_modules
cd frontend
bunx playwright test                       # весь e2e-набор
bunx playwright test tests/support-smoke.spec.ts   # только разделы поддержки
bun run build                              # tsc + vite build
```

Что нужно для прогона:

- backend и db запущены (`docker compose up -d db qdrant backend`);
- для сценариев сброса пароля — `docker compose up -d mailcatcher`;
- Playwright сам поднимает dev-сервер (`webServer` в `playwright.config.ts`,
  `reuseExistingServer: true`). Если порт 5173 уже занят контейнером `frontend`,
  тесты пойдут против **собранной** сборки — это тоже валидная проверка, но образ
  должен быть пересобран после правок: `docker compose build frontend`.

Важно про Docker-фронтенд: контейнер `frontend` отдаёт статическую сборку из образа
(nginx), а не исходники. После любых правок в `frontend/` нужно
`docker compose up -d --build frontend`, иначе на 5173 останется старая версия UI.
Для живой разработки удобнее `bun run dev` (но тогда остановите контейнер `frontend`,
чтобы не занимать порт).

Если Playwright обновился и браузер не найден (`Executable doesn't exist at
...ms-playwright\chromium_headless_shell-<version>`), нужно доставить браузер:

```bash
cd frontend && bunx playwright install chromium
```

Проверка стиля фронтенда (biome с автофиксом, как в CI):

```bash
bun run lint          # из корня: biome check --write ./ в frontend
bunx biome check src  # только диагностика, без правок
```

Примечание: часть существующих файлов хранится с CRLF, поэтому `biome check` без `--write`
показывает по ним форматные замечания — это baseline, а не результат правок.

Примечание про сообщения валидации: задавайте текст явно
(`z.email({ message: "Invalid email address" })`). При сборке прод-бандла дефолтные
сообщения zod отличаются от dev-сервера (в проде показывалось обобщённое «Invalid input»),
и тесты, завязанные на текст, расходятся между окружениями.

## 3. Рекомендуемый порядок перед PR

1. Точечные backend-тесты по измененной зоне.
2. Полный backend-тест прогон.
3. `bun run build` + `bunx biome check` по измененным файлам.
4. E2E smoke для критичных пользовательских сценариев.
