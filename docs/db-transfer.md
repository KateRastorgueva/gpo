# Перенос БД проекта на другую машину (для Руслана)

Документ можно целиком отдать ИИ-агенту. Агент считает задачу сделанной, когда
проходит проверка из шага 5.

## Как устроена БД

- **СУБД:** PostgreSQL 18, контейнер `db` в `compose.yml`.
- **Где лежат данные:** в Docker-томе `app-db-data` (внутри контейнера
  `/var/lib/postgresql/data/pgdata`). Тома живут в виртуальной машине Docker,
  а не в папке проекта. Удаление контейнера данные не трогает, а команда
  `docker compose down -v` или удаление тома стирает всё.
- **Как бэкенд подключается:** адрес собирается из переменных `.env`
  (`backend/app/core/config.py`, `SQLALCHEMY_DATABASE_URI`):
  `postgresql+psycopg://POSTGRES_USER:POSTGRES_PASSWORD@POSTGRES_SERVER:POSTGRES_PORT/POSTGRES_DB`.
  Внутри Docker-сети сервер называется `db`, снаружи БД доступна на
  `localhost:5432` (порт открыт в `compose.override.yml`).
- **Схема:** создаётся миграциями Alembic (`backend/app/alembic/versions`). Контейнер
  `prestart` при каждом запуске делает `alembic upgrade head` и создаёт первого
  суперпользователя из `FIRST_SUPERUSER*`.
- **Что внутри:** 16 таблиц, схема в `docs/db-schema.drawio`. Главное: база знаний
  (`knowledge_source`, `knowledge_chunk`, ...), обращения (`request_journal`,
  `answer_journal`, `support_ticket`, ...), пользователи и роли.
- **Что в БД НЕ лежит:** сами PDF-документы в Gemini File Search (они в облаке Google,
  хранилище `GEMINI_FILE_SEARCH_STORE`) и векторы старого поиска (Qdrant, том `qdrant-data`).

## Два способа переноса

**А. Только схема и справочники, без истории (рекомендуется для нового стенда).**
Схема создаётся миграциями сама, база знаний заливается заново из «tusur docs».
Ничего переносить не нужно:

```bash
cp .env.example .env        # заполнить ключи и пароли
docker compose up -d db prestart backend
```

**Б. С данными (дамп и восстановление).** Нужен, если важны текущие FAQ, источники,
пользователи и история обращений.

## Ограничения (нарушать нельзя)

1. Не коммитить `.env`, дампы и пароли. Дамп содержит хеши паролей и тексты обращений:
   передавать его мимо git, в личных сообщениях или на флешке.
2. Не использовать `docker compose down -v` и не удалять том `app-db-data` на машине-источнике.
3. Не править миграции Alembic задним числом и не менять схему вручную в psql.
4. Запускать стек только из корня проекта (с `compose.override.yml`).
5. Версия PostgreSQL на обеих машинах должна совпадать (18), иначе дамп может не восстановиться.

## Шаги (способ Б)

### 1. На машине-источнике: снять дамп

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > gpo2501.dump
```

`-Fc` — сжатый формат, восстанавливается через `pg_restore`.

### 2. Передать файл `gpo2501.dump` Руслану

Мимо репозитория. Размер порядка 10–50 МБ.

### 3. На новой машине: подготовить пустую БД

```bash
git clone <репозиторий> && cd gpo2501
cp .env.example .env        # заполнить: пароли, SECRET_KEY, GOOGLE_API_KEY
docker compose up -d db
```

Подождать статус `healthy` (`docker compose ps`). Миграции пока не запускать.

### 4. Восстановить данные

```bash
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < gpo2501.dump
docker compose up -d prestart backend frontend
```

`prestart` увидит, что схема уже на последней миграции, и ничего не сломает.
Если `pg_restore` выдал ошибки про уже существующие объекты при `--clean`, это
нормально для свежей БД; ошибки про отсутствующие таблицы не нормальны, их нужно разбирать.

### 5. Приёмка (обязательна)

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
select (select count(*) from knowledge_source) as sources,
       (select count(*) from knowledge_chunk) as chunks,
       (select count(*) from app_user) as users,
       (select count(*) from request_journal) as requests,
       (select version_num from alembic_version) as migration;"'
curl http://localhost:8000/api/v1/utils/health-check/
```

Числа должны совпасть с источником (запустить тот же запрос там и сравнить), health-check
отвечает `true`, на http://localhost:5173 открывается вход под суперпользователем и
чат отвечает на вопрос «Где смотреть расписание занятий ТУСУР?».

### 6. После переноса

- В новом `.env` задать `RAG_PROVIDER` и `GEMINI_FILE_SEARCH_STORE` (хранилище в Google
  общее, заливать документы заново не нужно, если используется тот же ключ/проект).
  Иначе: `python scripts/gemini_file_search.py create` и `upload "tusur docs"`.
- Для режима `legacy` после восстановления выполнить полную пересборку векторов
  (Управление → База знаний → «Полная пересборка»): Qdrant при переносе не копируется.

## Альтернатива: общая БД без переноса

Пока команда работает вместе, можно не переносить данные, а смотреть в одну БД.
Для этого на машине-источнике `POSTGRES_PORT` уже открыт, и Руслан в своём `.env`
ставит `POSTGRES_SERVER=<ip источника>`. Минусы: нужна одна сеть/VPN, пароль БД
уходит наружу, и при выключенном ноутбуке всё недоступно. Для демо не рекомендуется.
